import httpx2
import openai
import pytest
from slack_sdk.errors import SlackApiError

import bot.app as bot_app

THREAD = [{"user": "U1", "ts": "100.1", "text": "<@UBOT> hi"}]


@pytest.fixture(autouse=True)
def fresh_dedupe(monkeypatch):
    monkeypatch.setattr(bot_app, "handled", bot_app.RecentKeys())


def fake_llm(monkeypatch, chunks=(), error=None):
    async def stream_reply(messages):
        for chunk in chunks:
            yield chunk
        if error:
            raise error

    monkeypatch.setattr(bot_app, "stream_reply", stream_reply)


async def _answer(client):
    await bot_app.answer(client, "C1", "100.1", "100.1", "UBOT")


async def test_reaction_wraps_the_reply(monkeypatch, fake_slack):
    fake_llm(monkeypatch, ["Hello", " there"])
    client = fake_slack(THREAD)
    await _answer(client)

    names = client.names()
    assert names[0] == "reactions_add"
    assert names[-1] == "reactions_remove"
    assert names.index("chat_postMessage") < names.index("reactions_remove")
    for name, kw in client.calls:
        if name.startswith("reactions_"):
            assert kw == {"channel": "C1", "timestamp": "100.1", "name": "hourglass_flowing_sand"}
    assert list(client.messages.values()) == ["Hello there"]


async def test_duplicate_event_is_ignored(monkeypatch, fake_slack):
    fake_llm(monkeypatch, ["Hi"])
    client = fake_slack(THREAD)
    await _answer(client)
    await _answer(client)
    assert client.names().count("chat_postMessage") == 1


async def test_llm_error_shows_warning_and_removes_reaction(monkeypatch, fake_slack):
    req = httpx2.Request("POST", "https://llm.example")
    err = openai.RateLimitError("slow down", response=httpx2.Response(429, request=req), body=None)
    fake_llm(monkeypatch, ["Partial"], error=err)
    client = fake_slack(THREAD)
    await _answer(client)

    (text,) = client.messages.values()
    assert text.startswith("Partial\n\n:warning:")
    assert "rate-limited" in text
    assert client.names()[-1] == "reactions_remove"


async def test_reaction_failure_does_not_block_reply(monkeypatch, fake_slack):
    fake_llm(monkeypatch, ["Still here"])
    err = SlackApiError("no", {"ok": False, "error": "missing_scope"})
    client = fake_slack(THREAD, reaction_error=err)
    await _answer(client)
    assert list(client.messages.values()) == ["Still here"]


async def test_slack_failure_still_removes_reaction(monkeypatch, fake_slack):
    fake_llm(monkeypatch, ["x"])
    client = fake_slack(THREAD)

    async def broken(**kw):
        raise SlackApiError("down", {"ok": False, "error": "internal_error"})

    client.conversations_replies = broken
    with pytest.raises(SlackApiError):
        await _answer(client)
    assert client.names() == ["reactions_add", "reactions_remove"]


def test_recent_keys_expire(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(bot_app.time, "monotonic", lambda: now[0])
    keys = bot_app.RecentKeys(ttl=60)
    assert keys.add("a")
    assert not keys.add("a")
    now[0] += 61
    assert keys.add("a")
