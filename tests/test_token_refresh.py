"""Installing a new Schwab token from a Slack upload.

This is the sharpest tool in the set: it replaces the credential the live
trading system runs on. The failure that matters is not "it didn't work" — it
is installing a *dead* token, which looks fine until the overseer goes blind at
the next market open.

So the file is validated before anyone is asked to approve anything, and the
approval prompt shows the expiry rather than the secret.
"""
import json
import time

import pytest

from bot import authz
from bot.approval import ApprovalStore
from bot.reqctx import current_channel, current_client, current_files, current_thread_ts, current_user
from bot.tools import overseer

ADMIN = "U02DQJ9KKFZ"
STRANGER = "U999NOTALLOWED"
WEEK = 7 * 86400


def a_token(offset_s=0, refresh=True):
    tok = {"access_token": "a" * 76}
    if refresh:
        tok["refresh_token"] = "r" * 140
    return {"creation_timestamp": time.time() + offset_s, "token": tok}


def an_upload(name="schwab_token.json", size=808, filetype="json"):
    return {
        "name": name,
        "size": size,
        "filetype": filetype,
        "url_private_download": "https://files.slack.com/fake",
    }


class FakePoster:
    def __init__(self):
        self.posts = []

    async def chat_postMessage(self, **kw):
        self.posts.append(kw)
        return {"ts": "1.1"}


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setattr(authz.settings, "overseer_admin_ids", ADMIN)
    monkeypatch.setattr(overseer, "store", ApprovalStore(ttl_s=300))
    poster = FakePoster()
    tokens = [
        current_user.set(ADMIN),
        current_client.set(poster),
        current_channel.set("C1"),
        current_thread_ts.set("1.0"),
        current_files.set([]),
    ]
    yield poster
    for t in reversed(tokens):
        t.var.reset(t)


def _serve(monkeypatch, payload):
    async def fake_download(url):
        return payload if isinstance(payload, str) else json.dumps(payload)

    monkeypatch.setattr(overseer, "_download_slack_file", fake_download)


# --- validation ------------------------------------------------------------

def test_validate_accepts_a_fresh_token():
    ok, why, ttl = overseer._validate_token(a_token())
    assert ok and ttl > 167


def test_validate_rejects_an_expired_token():
    ok, why, _ = overseer._validate_token(a_token(-8 * 86400))
    assert not ok and "expired" in why


def test_validate_rejects_a_token_with_no_refresh_token():
    ok, why, _ = overseer._validate_token(a_token(refresh=False))
    assert not ok and "refresh_token" in why


def test_validate_rejects_something_that_is_not_a_token_file():
    ok, why, _ = overseer._validate_token({"hello": "world"})
    assert not ok and "creation_timestamp" in why


# --- the tool --------------------------------------------------------------

async def test_refuses_a_stranger(ctx, monkeypatch):
    _serve(monkeypatch, a_token())
    current_files.set([an_upload()])
    token = current_user.set(STRANGER)
    try:
        with pytest.raises(authz.NotAuthorized):
            await overseer.overseer_refresh_token()
    finally:
        current_user.reset(token)
    assert ctx.posts == []


async def test_asks_for_a_file_when_none_is_attached(ctx):
    out = await overseer.overseer_refresh_token()
    assert "upload" in out.lower() or "attach" in out.lower()
    assert ctx.posts == []


async def test_a_dead_token_is_refused_before_any_approval(ctx, monkeypatch):
    """The important one. Installing an expired token would look like success
    and take the overseer down at the next open, so it must never even reach
    the approve button."""
    _serve(monkeypatch, a_token(-8 * 86400))
    current_files.set([an_upload()])

    out = await overseer.overseer_refresh_token()

    assert "refusing" in out.lower()
    assert "expired" in out.lower()
    assert ctx.posts == [], "no approval prompt for a credential we know is dead"
    assert len(overseer.store) == 0


async def test_a_token_without_refresh_token_is_refused(ctx, monkeypatch):
    _serve(monkeypatch, a_token(refresh=False))
    current_files.set([an_upload()])
    out = await overseer.overseer_refresh_token()
    assert "refusing" in out.lower()
    assert ctx.posts == []


async def test_non_json_attachment_is_rejected(ctx, monkeypatch):
    _serve(monkeypatch, "this is not json")
    current_files.set([an_upload()])
    out = await overseer.overseer_refresh_token()
    assert "not valid json" in out.lower()
    assert ctx.posts == []


async def test_an_oversized_file_is_never_downloaded(ctx, monkeypatch):
    downloaded = []

    async def tripwire(url):
        downloaded.append(url)
        return "{}"

    monkeypatch.setattr(overseer, "_download_slack_file", tripwire)
    current_files.set([an_upload(size=10_000_000)])

    out = await overseer.overseer_refresh_token()

    assert "too large" in out.lower()
    assert downloaded == []


async def test_a_good_token_posts_an_approval_carrying_the_payload(ctx, monkeypatch):
    _serve(monkeypatch, a_token())
    current_files.set([an_upload()])

    out = await overseer.overseer_refresh_token()

    assert "approval" in out.lower()
    assert len(ctx.posts) == 1
    assert len(overseer.store) == 1


async def test_the_approval_prompt_never_shows_the_secret(ctx, monkeypatch):
    """The prompt is posted in a Slack channel. It should carry the expiry, not
    the credential."""
    tok = a_token()
    _serve(monkeypatch, tok)
    current_files.set([an_upload()])

    await overseer.overseer_refresh_token()

    posted = str(ctx.posts[0])
    assert tok["token"]["refresh_token"] not in posted
    assert tok["token"]["access_token"] not in posted


# --- execution -------------------------------------------------------------

def test_execute_installs_archives_and_restarts(monkeypatch, tmp_path):
    dst = tmp_path / "schwab_token.json"
    dst.write_text(json.dumps({"creation_timestamp": 0, "token": {"refresh_token": "OLD"}}))
    monkeypatch.setattr(overseer.settings, "overseer_token_path", dst)
    restarted = []
    monkeypatch.setattr(
        overseer, "execute_restart",
        lambda pending=None: (restarted.append(True), (True, "Overseer restarted."))[1],
    )

    new = a_token()
    pending = ApprovalStore(ttl_s=300).register(
        "refresh_token", requested_by=ADMIN, channel="C1", thread_ts="1.0",
        payload={"token": new, "expires": "2026-09-29 18:18", "ttl_h": 167.0},
    )

    ok, msg = overseer.execute_refresh_token(pending)

    assert ok, msg
    assert json.loads(dst.read_text())["token"]["refresh_token"] == new["token"]["refresh_token"]
    assert list(tmp_path.glob("*.revoked-*")), "the outgoing token must be archived"
    assert dst.stat().st_mode & 0o777 == 0o600, "a credential must not be world-readable"
    assert restarted == [True]


def test_execute_reports_a_failed_restart_without_claiming_success(monkeypatch, tmp_path):
    dst = tmp_path / "schwab_token.json"
    monkeypatch.setattr(overseer.settings, "overseer_token_path", dst)
    monkeypatch.setattr(overseer, "execute_restart", lambda pending=None: (False, "launchctl blew up"))

    pending = ApprovalStore(ttl_s=300).register(
        "refresh_token", requested_by=ADMIN, channel="C1", thread_ts="1.0",
        payload={"token": a_token(), "expires": "x", "ttl_h": 167.0},
    )
    ok, msg = overseer.execute_refresh_token(pending)

    assert not ok
    assert "restart failed" in msg


def test_execute_without_a_payload_fails_loudly(monkeypatch, tmp_path):
    """A bot restart drops pending actions. Better to ask for a re-upload than
    to write nothing and report success."""
    monkeypatch.setattr(overseer.settings, "overseer_token_path", tmp_path / "t.json")
    pending = ApprovalStore(ttl_s=300).register(
        "refresh_token", requested_by=ADMIN, channel="C1", thread_ts="1.0"
    )
    ok, msg = overseer.execute_refresh_token(pending)
    assert not ok and "re-upload" in msg
