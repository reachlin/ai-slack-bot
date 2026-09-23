"""Tools for operating the gold-finger Schwab overseer.

Scope is deliberately *lifecycle only* — report and restart. There is no order
placement, position closing or cancelling, mirroring the same decision made for
the Drive control channel: a bug in this path should be able to bounce the
scanner, never move money.

The overseer runs on this same host, so these call it directly rather than
going through the Google Drive channel. That channel exists because the user's
*other* machine has no access here; routing a local call through it would add a
90-second poll plus macOS FileProvider hazards (EDEADLK, and a kernel-level
open() hang) for nothing.

Every tool calls `require_admin()` as its first statement. That check reads the
caller from the signed Slack payload, never from anything the model can write.
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from ..approval import approval_blocks, store
from ..authz import require_admin
from ..config import settings
from ..reqctx import current_channel, current_client, current_files, current_thread_ts
from .base import Tool

log = logging.getLogger(__name__)


def _run(argv: list[str], timeout: float | None = None) -> tuple[bool, str]:
    """Run a command with a hard timeout, returning (ok, combined output)."""
    try:
        p = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout or settings.overseer_timeout_s,
            cwd=str(settings.goldfinger_repo),
        )
        return p.returncode == 0, ((p.stdout or "") + (p.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout or settings.overseer_timeout_s}s"
    except Exception as exc:  # noqa: BLE001 - surfaced to the model as text
        return False, f"{type(exc).__name__}: {exc}"


def _overseer_target() -> str:
    return f"gui/{os.getuid()}/{settings.overseer_label}"


PLIST_DST = Path("~/Library/LaunchAgents").expanduser() / "com.goldfinger.overseer.plist"


async def _request_approval(action: str, summary: str, payload: dict | None = None) -> str:
    """Post an approve/reject prompt for a lifecycle action and return.

    Nothing is executed here on purpose: the click carries a Slack-signed
    identity, so that — not a model reading thread text — is the authorisation
    that actually gates live trading.
    """
    user_id = require_admin()
    channel = current_channel.get()
    thread_ts = current_thread_ts.get()
    client = current_client.get()
    if not (channel and client):
        return "Error: no Slack context to post an approval prompt into."

    pending = store.register(
        action,
        requested_by=user_id,
        channel=channel,
        thread_ts=thread_ts or "",
        payload=payload,
    )
    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Approval needed: {action} the overseer",
        blocks=approval_blocks(pending, summary),
    )
    return (
        f"Approval requested for *{action}* — I posted Approve/Reject buttons in "
        "this thread. It runs only after you approve."
    )


# --- report ---------------------------------------------------------------

async def overseer_status() -> str:
    require_admin()
    status_tool = str(settings.goldfinger_repo / "schwab" / "overseer_status.py")
    ok, out = await asyncio.to_thread(
        _run, [str(settings.overseer_python), status_tool]
    )
    if not ok:
        return f"Status check failed:\n{out}"
    return f"```\n{out}\n```"


OVERSEER_STATUS = Tool(
    name="overseer_status",
    description=(
        "Report the live status of the gold-finger Schwab overseer: process health, "
        "cash and committed collateral, every open option position, resting GTC "
        "cover orders, and recent state-change events. Reconciled against the live "
        "brokerage account. Read-only."
    ),
    parameters={"type": "object", "properties": {}},
    fn=overseer_status,
    admin_only=True,
)


# --- restart (approval-gated) ---------------------------------------------

async def overseer_restart() -> str:
    """Ask for approval to restart. Never restarts by itself."""
    return await _request_approval(
        "restart",
        "Restart the *gold-finger overseer* (`launchctl kickstart`; starts it "
        "if it is not running at all).\nIt reloads code and the Schwab token. "
        "Open positions and their resting GTC covers are untouched — those rest "
        "at the broker.",
    )


OVERSEER_RESTART = Tool(
    name="overseer_restart",
    description=(
        "Request a restart of the gold-finger overseer process (launchd kickstart). "
        "Use when it needs to reload code or a refreshed Schwab token. This does NOT "
        "restart anything directly: it posts an approval prompt that a human must "
        "confirm in Slack."
    ),
    parameters={"type": "object", "properties": {}},
    fn=overseer_restart,
    admin_only=True,
)


async def overseer_start() -> str:
    return await _request_approval(
        "start",
        "Start the *gold-finger overseer* — it will resume live scanning and "
        "can open new real-money positions.",
    )


OVERSEER_START = Tool(
    name="overseer_start",
    description=(
        "Request a START of the gold-finger overseer when it is not running "
        "(launchd bootstrap; reinstalls its LaunchAgent if missing, so it works "
        "even from a fully removed state). Live trading resumes. Posts an "
        "approval prompt; does not start anything by itself."
    ),
    parameters={"type": "object", "properties": {}},
    fn=overseer_start,
    admin_only=True,
)


async def overseer_stop() -> str:
    return await _request_approval(
        "stop",
        "Stop the *gold-finger overseer* — live scanning halts and it will NOT "
        "restart itself. Existing GTC covers keep resting at Schwab.",
    )


OVERSEER_STOP = Tool(
    name="overseer_stop",
    description=(
        "Request a STOP of the gold-finger overseer (launchd bootout). It stays "
        "down until started again. Posts an approval prompt; does not stop "
        "anything by itself."
    ),
    parameters={"type": "object", "properties": {}},
    fn=overseer_stop,
    admin_only=True,
)


# --- executors (run only from the approved button handler) ----------------

def _is_loaded() -> bool:
    ok, _ = _run(["launchctl", "list", settings.overseer_label], timeout=15)
    return ok


def _plist_src() -> Path:
    return settings.goldfinger_repo / "schwab" / f"{settings.overseer_label}.plist"


def execute_start(pending=None) -> tuple[bool, str]:
    """Bring the overseer up, even from nothing.

    `kickstart` cannot do this: with no job loaded it fails with "Could not
    find service ... in domain" (exit 113). And the LaunchAgent plist itself
    may be gone, so this restores it from the repo's version-controlled copy
    before bootstrapping. That is what makes the Slack bot a sufficient sole
    controller rather than one that can only restart something already alive.
    """
    src, dst = _plist_src(), PLIST_DST
    reinstalled = False
    if not dst.exists():
        if not src.exists():
            return False, f"LaunchAgent plist not found in the repo at {src}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        reinstalled = True

    ok, out = _run(
        ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(dst)], timeout=60
    )
    if not ok and "already" not in out.lower():
        return False, out or "launchctl bootstrap failed."

    # Trust the listing, not the exit code: a bootstrap can return 0 and still
    # leave nothing running, and "trading resumed" must never be a guess.
    if not _is_loaded():
        return False, "bootstrap returned ok but the job is not listed as running."

    note = " (LaunchAgent reinstalled from the repo)" if reinstalled else ""
    return True, f"Overseer started{note}."


def execute_stop(pending=None) -> tuple[bool, str]:
    ok, out = _run(["launchctl", "bootout", _overseer_target()], timeout=60)
    if not ok and "no such process" not in out.lower():
        return False, out or "launchctl bootout failed."
    return True, "Overseer stopped — it stays down until started again."


def execute_restart(pending=None) -> tuple[bool, str]:
    """Restart if running; start it if it is not loaded at all."""
    if not _is_loaded():
        ok, msg = execute_start()
        return ok, (f"Overseer was not running — {msg[0].lower()}{msg[1:]}" if ok else msg)
    ok, out = _run(["launchctl", "kickstart", "-k", _overseer_target()], timeout=60)
    if ok:
        return True, "Overseer restarted."
    return False, out or "launchctl reported a failure."



OVERSEER_HINT = (
    "\n\nYou can operate the gold-finger Schwab trading overseer with "
    "`overseer_status` (read-only report) and `overseer_restart` (posts an "
    "approval prompt; it does not restart anything by itself). Call "
    "`overseer_status` whenever asked how the overseer, the trading bot or the "
    "positions are doing, and relay its output as-is rather than summarising "
    "numbers from memory. Never claim an action succeeded unless a tool said so."
)


# --- token refresh --------------------------------------------------------
#
# A Schwab reauth on ANY machine revokes the refresh token on every other one,
# so the local token can die with TTL apparently remaining. This is the remote
# recovery path: upload the freshly minted schwab_token.json to Slack and the
# bot installs it and restarts the overseer.
#
# The file is validated BEFORE an approval prompt is posted — there is no point
# asking someone to approve installing a dead credential — and the prompt shows
# only the expiry, never the token.

REFRESH_TOKEN_TTL_S = 7 * 86400


def _validate_token(data) -> tuple[bool, str, float]:
    """(ok, reason, hours_remaining) for an uploaded schwab_token.json."""
    if not isinstance(data, dict):
        return False, "not a JSON object", 0.0
    ct = data.get("creation_timestamp")
    if not isinstance(ct, (int, float)):
        return False, "no creation_timestamp — is this a Schwab token file?", 0.0
    ttl_h = (ct + REFRESH_TOKEN_TTL_S - time.time()) / 3600
    if ttl_h <= 0:
        return False, f"already expired ({-ttl_h:.1f}h ago)", ttl_h
    inner = data.get("token") if isinstance(data.get("token"), dict) else data
    if not inner.get("refresh_token"):
        return False, "no refresh_token inside", ttl_h
    return True, f"valid, {ttl_h:.1f}h remaining", ttl_h


async def _download_slack_file(url: str) -> str:
    """Fetch a private Slack file with the bot token."""
    import aiohttp

    headers = {"Authorization": f"Bearer {settings.slack_bot_token}"}
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.text()


async def overseer_refresh_token() -> str:
    require_admin()
    files = current_files.get() or []
    candidates = [
        f for f in files
        if f.get("filetype") == "json" or (f.get("name") or "").endswith(".json")
    ]
    if not candidates:
        return (
            "No token file attached. Upload the freshly generated "
            "`schwab_token.json` with your message and ask again."
        )

    f = candidates[-1]
    if (f.get("size") or 0) > settings.max_token_bytes:
        return f"That file is {f['size']} bytes — too large to be a Schwab token."

    url = f.get("url_private_download") or f.get("url_private")
    if not url:
        return "Slack did not give a download URL for that file."
    try:
        raw = await _download_slack_file(url)
    except Exception as exc:  # noqa: BLE001
        return f"Could not download the attachment: {type(exc).__name__}: {exc}"

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return "That attachment is not valid JSON."

    ok, why, ttl_h = _validate_token(data)
    if not ok:
        # Refuse here rather than after approval: installing a dead credential
        # would take the overseer down at the next market open.
        return f"Refusing to install that token — {why}."

    expires = datetime.fromtimestamp(
        data["creation_timestamp"] + REFRESH_TOKEN_TTL_S
    ).strftime("%Y-%m-%d %H:%M")
    return await _request_approval(
        "refresh_token",
        f"Install a new Schwab token and restart the *gold-finger overseer*.\n"
        f"New token: valid *{ttl_h:.1f}h*, expires *{expires}*.\n"
        f"The current token is archived first, and the uploaded file is deleted "
        f"from Slack once it is installed.",
        payload={
            "token": data,
            "expires": expires,
            "ttl_h": ttl_h,
            "file_id": f.get("id"),
        },
    )


OVERSEER_REFRESH_TOKEN = Tool(
    name="overseer_refresh_token",
    description=(
        "Install a new Schwab OAuth token that the user has ATTACHED to their Slack "
        "message as schwab_token.json, then restart the overseer so it picks it up. "
        "Use when the overseer is failing with invalid_grant, or after the user "
        "re-authenticated Schwab on another machine. Validates the file and posts an "
        "approval prompt; installs nothing by itself. If no file is attached it will "
        "say so — tell the user to upload one."
    ),
    parameters={"type": "object", "properties": {}},
    fn=overseer_refresh_token,
    admin_only=True,
)


def _delete_slack_file(file_id: str) -> tuple[bool, str]:
    """Remove an uploaded file from Slack.

    A Schwab refresh token sitting in Slack storage is a live credential in a
    third system nobody is auditing. Needs the files:write bot scope; stdlib
    only, because this runs in the sync executor thread.
    """
    import urllib.parse
    import urllib.request

    body = urllib.parse.urlencode({"file": file_id}).encode()
    req = urllib.request.Request(
        "https://slack.com/api/files.delete",
        data=body,
        headers={
            "Authorization": f"Bearer {settings.slack_bot_token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read())
        if payload.get("ok"):
            return True, "deleted"
        return False, payload.get("error", "unknown error")
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def execute_refresh_token(pending) -> tuple[bool, str]:
    """Install the validated token, then restart. Approved path only."""
    if not pending or not pending.payload:
        return False, "the token data was lost before approval — please re-upload."
    data = pending.payload["token"]
    dst = settings.overseer_token_path

    try:
        if dst.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M")
            shutil.copy2(dst, dst.with_suffix(f".json.revoked-{stamp}"))
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(data))
        dst.chmod(0o600)
    except Exception as exc:  # noqa: BLE001
        return False, f"install failed: {type(exc).__name__}: {exc}"

    # Only now that the token is safely on disk is it right to drop the copy
    # in Slack; a failure here must not undo or mask the install.
    note = ""
    file_id = pending.payload.get("file_id")
    if file_id:
        deleted, why = _delete_slack_file(file_id)
        note = (
            " Uploaded file deleted from Slack."
            if deleted
            else f" :warning: could not delete the upload from Slack ({why}) — remove it manually."
        )

    ok, msg = execute_restart()
    expires = pending.payload.get("expires", "?")
    if not ok:
        return False, f"Token installed (expires {expires}) but the restart failed: {msg}{note}"
    return True, f"Token installed (expires {expires}). {msg}{note}"


OVERSEER_TOOLS = [
    OVERSEER_STATUS,
    OVERSEER_START,
    OVERSEER_STOP,
    OVERSEER_RESTART,
    OVERSEER_REFRESH_TOKEN,
]
