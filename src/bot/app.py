import asyncio
import logging
import time
from collections import OrderedDict

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from .approval import store
from .authz import is_admin
from .config import settings
from .context import build_messages
from .llm import describe_error, stream_reply
from .reply import ReplyStream
from .reqctx import (
    current_channel,
    current_client,
    current_files,
    current_thread_ts,
    current_user,
)
from .tools import (
    execute_refresh_token,
    execute_restart,
    execute_start,
    execute_stop,
    hint_for,
    kb,
    toolbox_for,
)

log = logging.getLogger(__name__)
app = AsyncApp(token=settings.slack_bot_token)

WORKING_REACTION = "hourglass_flowing_sand"


class RecentKeys:
    """Remembers keys for `ttl` seconds; used to drop events Slack delivers more than once."""

    def __init__(self, ttl: float = 600.0):
        self._ttl = ttl
        self._seen: OrderedDict[str, float] = OrderedDict()

    def add(self, key: str) -> bool:
        """Record `key`; return False if it was already seen recently."""
        now = time.monotonic()
        while self._seen and next(iter(self._seen.values())) < now - self._ttl:
            self._seen.popitem(last=False)
        if key in self._seen:
            return False
        self._seen[key] = now
        return True


handled = RecentKeys()


async def _react(method, channel: str, ts: str) -> None:
    try:
        await method(channel=channel, timestamp=ts, name=WORKING_REACTION)
    except SlackApiError as e:
        log.warning("Reaction update failed: %s", e.response["error"])


async def answer(
    client: AsyncWebClient,
    channel: str,
    thread_ts: str,
    message_ts: str,
    bot_user_id: str,
    user_id: str | None = None,
    files: list | None = None,
) -> None:
    if not handled.add(f"{channel}:{message_ts}"):
        log.info("Skipping duplicate event for %s:%s", channel, message_ts)
        return

    # Request-scoped identity. It comes from the signed Slack payload and is
    # deliberately NOT a tool argument: the model reads attacker-controlled
    # thread text, so anything it could write must not decide authorisation.
    tokens = [
        current_user.set(user_id),
        current_channel.set(channel),
        current_thread_ts.set(thread_ts),
        current_client.set(client),
        current_files.set(files or []),
    ]

    await _react(client.reactions_add, channel, message_ts)
    try:
        replies = await client.conversations_replies(channel=channel, ts=thread_ts, limit=200)
        # Offer only the tools this caller may actually use.
        if is_admin(user_id):
            log.info("AUDIT privileged session user=%s channel=%s", user_id, channel)
        box = toolbox_for(user_id)
        tools = box if box.schemas else None
        system_prompt = settings.system_prompt + hint_for(user_id)
        messages = build_messages(
            replies["messages"], bot_user_id, system_prompt, settings.max_context_tokens
        )

        reply = ReplyStream(client, channel, thread_ts)
        note = ""
        try:
            async for delta in stream_reply(messages, tools):
                await reply.append(delta)
        except Exception as exc:
            log.exception("Reply failed")
            note = f":warning: {describe_error(exc)}"
        await reply.finish(note)
    finally:
        await _react(client.reactions_remove, channel, message_ts)
        for token in reversed(tokens):
            token.var.reset(token)


@app.event("app_mention")
async def on_mention(event, client, context):
    thread_ts = event.get("thread_ts") or event["ts"]
    await answer(
        client, event["channel"], thread_ts, event["ts"], context["bot_user_id"],
        event.get("user"), event.get("files"),
    )


@app.event("message")
async def on_message(event, client, context):
    # Only plain user DMs; channel traffic is handled via app_mention.
    if event.get("channel_type") != "im" or event.get("subtype") or event.get("bot_id"):
        return
    thread_ts = event.get("thread_ts") or event["ts"]
    await answer(
        client, event["channel"], thread_ts, event["ts"], context["bot_user_id"],
        event.get("user"), event.get("files"),
    )


@app.event("member_joined_channel")
async def ignore_event():
    pass


# --- approval buttons ------------------------------------------------------
#
# This is where the authorisation that matters happens. The clicker's id comes
# from the interaction payload, which Slack signs, so it cannot be forged by
# anything written in a thread. Even a fully hijacked model can at worst get a
# button posted; it cannot press it.

EXECUTORS = {
    "start": execute_start,
    "stop": execute_stop,
    "restart": execute_restart,
    "refresh_token": execute_refresh_token,
}


async def _settle(client, body, outcome: str) -> None:
    """Replace the prompt with its outcome so no stale buttons remain."""
    try:
        await client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            text=outcome,
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": outcome}}],
        )
    except SlackApiError as e:
        log.warning("Could not update approval message: %s", e.response["error"])


@app.action("overseer_approve")
async def on_approve(ack, body, client):
    await ack()
    clicker = body["user"]["id"]
    if not is_admin(clicker):
        log.warning("Rejected approval click from unauthorised user %s", clicker)
        await _settle(client, body, f":no_entry: <@{clicker}> is not authorised to approve this.")
        return

    pending = store.take(body["actions"][0]["value"])
    if pending is None:
        await _settle(client, body, ":hourglass: That request expired or was already handled.")
        return

    executor = EXECUTORS.get(pending.action)
    if executor is None:
        await _settle(client, body, f":warning: Unknown action {pending.action!r}.")
        return

    ok, detail = await asyncio.to_thread(executor, pending)
    # Audit trail. Reconstructing who halted live trading, and when, must not
    # require correlating process start times against Slack timestamps.
    log.info(
        "AUDIT %s approved by=%s requested_by=%s channel=%s ok=%s detail=%s",
        pending.action, clicker, pending.requested_by, pending.channel, ok, detail,
    )
    icon = ":white_check_mark:" if ok else ":x:"
    await _settle(client, body, f"{icon} *{pending.action}* approved by <@{clicker}> — {detail}")


@app.action("overseer_reject")
async def on_reject(ack, body, client):
    await ack()
    clicker = body["user"]["id"]
    if not is_admin(clicker):
        await _settle(client, body, f":no_entry: <@{clicker}> is not authorised to act on this.")
        return
    pending = store.take(body["actions"][0]["value"])
    if pending is None:
        await _settle(client, body, ":hourglass: That request expired or was already handled.")
        return
    log.info(
        "AUDIT %s rejected by=%s requested_by=%s channel=%s",
        pending.action, clicker, pending.requested_by, pending.channel,
    )
    await _settle(client, body, f":no_entry_sign: *{pending.action}* rejected by <@{clicker}>.")


async def main() -> None:
    logging.basicConfig(level=settings.log_level)
    log.info("Starting bot with model=%s base_url=%s", settings.llm_model, settings.llm_base_url)
    kb.refresh()
    log.info("Knowledge: %d sections from %s", len(kb.chunks), kb.root.resolve())
    await AsyncSocketModeHandler(app, settings.slack_app_token).start_async()


if __name__ == "__main__":
    asyncio.run(main())
