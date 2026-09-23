import os

# Fake credentials so bot.config loads without a real .env; nothing in the tests hits the network.
os.environ.update(
    SLACK_BOT_TOKEN="xoxb-test",
    SLACK_APP_TOKEN="xapp-test",
    LLM_API_KEY="sk-test",
)

import pytest  # noqa: E402


class FakeSlack:
    """Records Slack Web API calls made by the bot."""

    def __init__(self, thread=None, reaction_error=None):
        self.thread = thread or []
        self.reaction_error = reaction_error
        self.calls: list[tuple[str, dict]] = []
        self.messages: dict[str, str] = {}

    async def conversations_replies(self, **kw):
        self.calls.append(("conversations_replies", kw))
        return {"messages": self.thread}

    async def chat_postMessage(self, **kw):
        self.calls.append(("chat_postMessage", kw))
        ts = f"reply-{len(self.messages) + 1}"
        self.messages[ts] = kw["text"]
        return {"ts": ts}

    async def chat_update(self, **kw):
        self.calls.append(("chat_update", kw))
        self.messages[kw["ts"]] = kw["text"]

    async def reactions_add(self, **kw):
        self.calls.append(("reactions_add", kw))
        if self.reaction_error:
            raise self.reaction_error

    async def reactions_remove(self, **kw):
        self.calls.append(("reactions_remove", kw))
        if self.reaction_error:
            raise self.reaction_error

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


@pytest.fixture
def fake_slack():
    return FakeSlack
