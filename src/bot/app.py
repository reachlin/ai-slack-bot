import asyncio
import logging
import time
from collections import OrderedDict

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from .config import settings
from .context import build_messages
from .llm import describe_error, stream_reply
from .reply import ReplyStream
from .tools import KNOWLEDGE_HINT, kb, toolbox

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
    client: AsyncWebClient, channel: str, thread_ts: str, message_ts: str, bot_user_id: str
) -> None:
    if not handled.add(f"{channel}:{message_ts}"):
        log.info("Skipping duplicate event for %s:%s", channel, message_ts)
        return

    await _react(client.reactions_add, channel, message_ts)
    try:
        replies = await client.conversations_replies(channel=channel, ts=thread_ts, limit=200)
        # Offer the knowledge tool only when there are notes to search.
        tools = None if kb.is_empty() else toolbox
        system_prompt = settings.system_prompt + (KNOWLEDGE_HINT if tools else "")
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


@app.event("app_mention")
async def on_mention(event, client, context):
    thread_ts = event.get("thread_ts") or event["ts"]
    await answer(client, event["channel"], thread_ts, event["ts"], context["bot_user_id"])


@app.event("message")
async def on_message(event, client, context):
    # Only plain user DMs; channel traffic is handled via app_mention.
    if event.get("channel_type") != "im" or event.get("subtype") or event.get("bot_id"):
        return
    thread_ts = event.get("thread_ts") or event["ts"]
    await answer(client, event["channel"], thread_ts, event["ts"], context["bot_user_id"])


@app.event("member_joined_channel")
async def ignore_event():
    pass


async def main() -> None:
    logging.basicConfig(level=settings.log_level)
    log.info("Starting bot with model=%s base_url=%s", settings.llm_model, settings.llm_base_url)
    kb.refresh()
    log.info("Knowledge: %d sections from %s", len(kb.chunks), kb.root.resolve())
    await AsyncSocketModeHandler(app, settings.slack_app_token).start_async()


if __name__ == "__main__":
    asyncio.run(main())
