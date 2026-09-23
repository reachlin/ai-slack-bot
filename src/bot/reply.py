import time

from slack_sdk.web.async_client import AsyncWebClient

MAX_CHARS = 3900  # Slack truncates messages much beyond ~4k chars
UPDATE_INTERVAL_S = 1.0  # throttle chat.update to stay under Slack rate limits
FENCE = "```"


def split_message(text: str, limit: int = MAX_CHARS) -> tuple[str, str]:
    """Split at the last newline before `limit`, keeping code fences balanced across the cut."""
    cut = text.rfind("\n", 0, limit)
    if cut < limit // 2:
        cut = limit
    head, tail = text[:cut], text[cut:].lstrip("\n")
    if head.count(FENCE) % 2:
        head += "\n" + FENCE
        tail = FENCE + "\n" + tail
    return head, tail


class ReplyStream:
    """Streams text into a Slack thread, editing in place and rolling over to a new message when too long."""

    def __init__(self, client: AsyncWebClient, channel: str, thread_ts: str):
        self._client = client
        self._channel = channel
        self._thread_ts = thread_ts
        self._ts: str | None = None  # message currently being written
        self._text = ""
        self._written = ""
        self._last_update = 0.0
        self._posted_any = False

    async def append(self, delta: str) -> None:
        self._text += delta
        while len(self._text) > MAX_CHARS:
            head, self._text = split_message(self._text)
            await self._write(head)
            self._ts, self._written = None, ""
        if self._text.strip() and time.monotonic() - self._last_update >= UPDATE_INTERVAL_S:
            await self._write(self._text)

    async def finish(self, note: str = "") -> None:
        if note:
            self._text = f"{self._text}\n\n{note}" if self._text.strip() else note
        if self._text.strip():
            await self._write(self._text)
        elif not self._posted_any:
            await self._write("_(empty response)_")

    async def _write(self, text: str) -> None:
        if self._ts is None:
            resp = await self._client.chat_postMessage(
                channel=self._channel, thread_ts=self._thread_ts, text=text
            )
            self._ts = resp["ts"]
        elif text != self._written:
            await self._client.chat_update(channel=self._channel, ts=self._ts, text=text)
        self._written = text
        self._last_update = time.monotonic()
        self._posted_any = True
