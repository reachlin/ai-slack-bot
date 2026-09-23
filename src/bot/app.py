import asyncio
import logging
import time

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp
from slack_sdk.web.async_client import AsyncWebClient

from .config import settings
from .context import build_messages
from .llm import stream_reply

log = logging.getLogger(__name__)
app = AsyncApp(token=settings.slack_bot_token)

UPDATE_INTERVAL_S = 1.0  # throttle chat.update to stay under Slack rate limits


async def answer(client: AsyncWebClient, channel: str, thread_ts: str, bot_user_id: str) -> None:
    replies = await client.conversations_replies(channel=channel, ts=thread_ts, limit=200)
    messages = build_messages(
        replies["messages"], bot_user_id, settings.system_prompt, settings.max_context_tokens
    )

    placeholder = await client.chat_postMessage(
        channel=channel, thread_ts=thread_ts, text="_Thinking…_"
    )
    ts = placeholder["ts"]

    text, last_update = "", 0.0
    try:
        async for delta in stream_reply(messages):
            text += delta
            if time.monotonic() - last_update >= UPDATE_INTERVAL_S:
                await client.chat_update(channel=channel, ts=ts, text=text)
                last_update = time.monotonic()
    except Exception:
        log.exception("LLM request failed")
        text += "\n\n:warning: Sorry, something went wrong talking to the model."

    await client.chat_update(channel=channel, ts=ts, text=text or "_(empty response)_")


@app.event("app_mention")
async def on_mention(event, client, context):
    thread_ts = event.get("thread_ts") or event["ts"]
    await answer(client, event["channel"], thread_ts, context["bot_user_id"])


@app.event("message")
async def on_message(event, client, context):
    # Only plain user DMs; channel traffic is handled via app_mention.
    if event.get("channel_type") != "im" or event.get("subtype") or event.get("bot_id"):
        return
    thread_ts = event.get("thread_ts") or event["ts"]
    await answer(client, event["channel"], thread_ts, context["bot_user_id"])


async def main() -> None:
    logging.basicConfig(level=settings.log_level)
    log.info("Starting bot with model=%s base_url=%s", settings.llm_model, settings.llm_base_url)
    await AsyncSocketModeHandler(app, settings.slack_app_token).start_async()


if __name__ == "__main__":
    asyncio.run(main())
