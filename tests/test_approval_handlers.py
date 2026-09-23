"""The Slack button handlers — the last line of defence.

Everything upstream (allowlist, hidden tools, approval prompt) can be argued
with. This cannot: the clicker's id arrives in a Slack-signed interaction
payload, and the restart only ever runs from here. So these tests are about
what must NOT happen — a stranger's click, a stale button, a double-click.
"""
import pytest

from bot import app as botapp
from bot import authz
from bot.approval import ApprovalStore

ADMIN = "U02DQJ9KKFZ"
STRANGER = "U999NOTALLOWED"


class FakeClient:
    def __init__(self):
        self.updates = []

    async def chat_update(self, **kw):
        self.updates.append(kw)
        return {"ok": True}


def _body(action_id: str, clicker: str):
    return {
        "user": {"id": clicker},
        "channel": {"id": "C1"},
        "message": {"ts": "1.1", "thread_ts": "1.0"},
        "actions": [{"value": action_id}],
    }


async def _noop_ack():
    return None


@pytest.fixture
def wired(monkeypatch):
    """Isolated store + a recording executor in place of the real restart."""
    monkeypatch.setattr(authz.settings, "overseer_admin_ids", ADMIN)
    store = ApprovalStore(ttl_s=300)
    monkeypatch.setattr(botapp, "store", store)

    ran = []

    def fake_restart(pending=None):
        ran.append(True)
        return True, "Overseer restarted."

    monkeypatch.setattr(botapp, "EXECUTORS", {"restart": fake_restart})
    return store, ran, FakeClient()


async def test_a_strangers_click_executes_nothing(wired):
    store, ran, client = wired
    pending = store.register("restart", requested_by=ADMIN, channel="C1", thread_ts="1.0")

    await botapp.on_approve(_noop_ack, _body(pending.id, STRANGER), client)

    assert ran == [], "an unauthorised click must never restart anything"
    assert "not authorised" in client.updates[0]["text"]
    assert store.take(pending.id) is not None, "the request should survive a bad click"


async def test_an_admin_click_executes_once(wired):
    store, ran, client = wired
    pending = store.register("restart", requested_by=ADMIN, channel="C1", thread_ts="1.0")

    await botapp.on_approve(_noop_ack, _body(pending.id, ADMIN), client)

    assert ran == [True]
    assert "approved by" in client.updates[0]["text"]


async def test_double_click_executes_only_once(wired):
    """Slack redelivers interactions; a person can double-tap. Restarting live
    trading infrastructure twice is not acceptable."""
    store, ran, client = wired
    pending = store.register("restart", requested_by=ADMIN, channel="C1", thread_ts="1.0")

    await botapp.on_approve(_noop_ack, _body(pending.id, ADMIN), client)
    await botapp.on_approve(_noop_ack, _body(pending.id, ADMIN), client)

    assert ran == [True]
    assert "expired or was already handled" in client.updates[1]["text"]


async def test_expired_button_executes_nothing(wired, monkeypatch):
    _, ran, client = wired
    clock = [1000.0]
    store = ApprovalStore(ttl_s=300, now=lambda: clock[0])
    monkeypatch.setattr(botapp, "store", store)
    pending = store.register("restart", requested_by=ADMIN, channel="C1", thread_ts="1.0")
    clock[0] += 301

    await botapp.on_approve(_noop_ack, _body(pending.id, ADMIN), client)

    assert ran == []
    assert "expired" in client.updates[0]["text"]


async def test_unknown_action_id_executes_nothing(wired):
    _, ran, client = wired
    await botapp.on_approve(_noop_ack, _body("deadbeef", ADMIN), client)
    assert ran == []


async def test_reject_consumes_the_request_without_executing(wired):
    store, ran, client = wired
    pending = store.register("restart", requested_by=ADMIN, channel="C1", thread_ts="1.0")

    await botapp.on_reject(_noop_ack, _body(pending.id, ADMIN), client)

    assert ran == []
    assert "rejected by" in client.updates[0]["text"]
    assert store.take(pending.id) is None, "a rejected request must not remain approvable"


async def test_a_stranger_cannot_reject_either(wired):
    store, ran, client = wired
    pending = store.register("restart", requested_by=ADMIN, channel="C1", thread_ts="1.0")

    await botapp.on_reject(_noop_ack, _body(pending.id, STRANGER), client)

    assert "not authorised" in client.updates[0]["text"]
    assert store.take(pending.id) is not None


# --- audit trail -----------------------------------------------------------

def _audit(caplog):
    return [r.message for r in caplog.records if "AUDIT" in r.message]


async def test_an_approval_is_recorded_with_who_what_and_outcome(wired, caplog):
    """Reconstructing 'who restarted live trading, when' should not require
    correlating process start times against Slack message timestamps — which is
    exactly what it took on 2026-09-23, because only DENIED clicks were logged.
    """
    store, _, client = wired
    pending = store.register("restart", requested_by=ADMIN, channel="C1", thread_ts="1.0")

    with caplog.at_level("INFO"):
        await botapp.on_approve(_noop_ack, _body(pending.id, ADMIN), client)

    line = _audit(caplog)
    assert line, "an executed action must leave an audit line"
    assert ADMIN in line[0]
    assert "restart" in line[0]
    assert "approved" in line[0]
    assert "ok=True" in line[0]


async def test_a_failed_execution_is_recorded_as_such(wired, caplog, monkeypatch):
    store, _, client = wired
    monkeypatch.setattr(
        botapp, "EXECUTORS", {"restart": lambda pending=None: (False, "launchctl blew up")}
    )
    pending = store.register("restart", requested_by=ADMIN, channel="C1", thread_ts="1.0")

    with caplog.at_level("INFO"):
        await botapp.on_approve(_noop_ack, _body(pending.id, ADMIN), client)

    assert "ok=False" in _audit(caplog)[0]


async def test_a_rejection_is_recorded_too(wired, caplog):
    store, _, client = wired
    pending = store.register("restart", requested_by=ADMIN, channel="C1", thread_ts="1.0")

    with caplog.at_level("INFO"):
        await botapp.on_reject(_noop_ack, _body(pending.id, ADMIN), client)

    line = _audit(caplog)
    assert line and "rejected" in line[0] and ADMIN in line[0]


async def test_the_requester_is_recorded_alongside_the_approver(wired, caplog):
    """They can differ — one admin asks, another approves. Both belong in the
    record."""
    store, _, client = wired
    pending = store.register("restart", requested_by="U_REQUESTER", channel="C1", thread_ts="1.0")

    with caplog.at_level("INFO"):
        await botapp.on_approve(_noop_ack, _body(pending.id, ADMIN), client)

    assert "U_REQUESTER" in _audit(caplog)[0]
