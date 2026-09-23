"""The overseer tools themselves.

Two properties matter more than the happy path:

1. An unauthorised caller produces NO side effect — not a refused subprocess,
   not a posted button, nothing. The check runs before anything else.
2. `overseer_restart` never restarts anything by itself. It only asks. The
   execution lives behind the Slack button handler, where the clicker's
   identity is signed by Slack.
"""
import pytest

from bot import authz
from bot.approval import ApprovalStore
from bot.reqctx import current_channel, current_client, current_thread_ts, current_user
from bot.tools import overseer, toolbox_for

ADMIN = "U02DQJ9KKFZ"
STRANGER = "U999NOTALLOWED"


class FakePoster:
    def __init__(self):
        self.posts = []

    async def chat_postMessage(self, **kw):
        self.posts.append(kw)
        return {"ts": "1.1"}


@pytest.fixture
def ran(monkeypatch):
    """Capture subprocess invocations instead of running them."""
    calls = []

    def fake_run(argv, timeout=None):
        calls.append(list(argv))
        return True, "FAKE OUTPUT"

    monkeypatch.setattr(overseer, "_run", fake_run)
    return calls


@pytest.fixture(autouse=True)
def _ctx(monkeypatch):
    monkeypatch.setattr(authz.settings, "overseer_admin_ids", ADMIN)
    monkeypatch.setattr(overseer, "store", ApprovalStore(ttl_s=300))
    poster = FakePoster()
    tokens = [
        current_client.set(poster),
        current_channel.set("C1"),
        current_thread_ts.set("1.0"),
    ]
    yield poster
    for t in reversed(tokens):
        t.var.reset(t)


# --- authorisation ---------------------------------------------------------

async def test_status_refuses_a_stranger_without_running_anything(ran):
    token = current_user.set(STRANGER)
    try:
        with pytest.raises(authz.NotAuthorized):
            await overseer.overseer_status()
    finally:
        current_user.reset(token)
    assert ran == [], "no subprocess may run for an unauthorised caller"


async def test_restart_refuses_a_stranger_without_posting_a_button(ran, _ctx):
    token = current_user.set(STRANGER)
    try:
        with pytest.raises(authz.NotAuthorized):
            await overseer.overseer_restart()
    finally:
        current_user.reset(token)
    assert _ctx.posts == [], "an unauthorised caller must not even get a prompt"
    assert ran == []


async def test_tools_refuse_when_there_is_no_caller(ran):
    """Outside a Slack request there is no identity, so everything refuses."""
    with pytest.raises(authz.NotAuthorized):
        await overseer.overseer_status()
    assert ran == []


# --- status ----------------------------------------------------------------

async def test_status_runs_the_reconciling_status_tool(ran):
    token = current_user.set(ADMIN)
    try:
        out = await overseer.overseer_status()
    finally:
        current_user.reset(token)
    assert "FAKE OUTPUT" in out
    assert len(ran) == 1
    assert ran[0][-1].endswith("overseer_status.py"), ran[0]


# --- restart ---------------------------------------------------------------

async def test_restart_only_requests_approval(ran, _ctx):
    """The tool must not bounce live trading infrastructure on its own."""
    token = current_user.set(ADMIN)
    try:
        out = await overseer.overseer_restart()
    finally:
        current_user.reset(token)

    assert ran == [], "restart must not execute before a human approves"
    assert len(_ctx.posts) == 1, "an approval prompt should be posted"
    assert "blocks" in _ctx.posts[0]
    assert "approval" in out.lower()


async def test_restart_registers_a_pending_action_for_the_button(ran, _ctx):
    token = current_user.set(ADMIN)
    try:
        await overseer.overseer_restart()
    finally:
        current_user.reset(token)
    assert len(overseer.store) == 1


# --- which tools the model is even shown -----------------------------------

def test_a_stranger_is_not_offered_the_overseer_tools():
    """Defence in depth: the code gate is the real control, but a non-admin's
    model should never see these tools at all, so injected text has nothing to
    aim at."""
    names = {s["function"]["name"] for s in toolbox_for(STRANGER).schemas}
    assert "overseer_status" not in names
    assert "overseer_restart" not in names


def test_an_admin_is_offered_the_overseer_tools():
    names = {s["function"]["name"] for s in toolbox_for(ADMIN).schemas}
    assert {"overseer_status", "overseer_restart"} <= names


def test_no_trading_tool_is_ever_exposed():
    """Lifecycle only, mirroring the Drive control channel. A bug here should
    be able to bounce the scanner, never move money."""
    names = {s["function"]["name"] for s in toolbox_for(ADMIN).schemas}
    for forbidden in ("place_order", "close_position", "cancel_order", "sell_put"):
        assert forbidden not in names
