import json
from types import SimpleNamespace as NS

import bot.llm as llm
from bot.tools import knowledge as tools
from bot.knowledge import KnowledgeBase
from bot.tools import Tool, ToolBox


def _box():
    async def add(a, b):
        return a + b

    def boom():
        raise ValueError("nope")

    return ToolBox([
        Tool("add", "Add numbers", {"type": "object"}, add),
        Tool("boom", "Fails", {"type": "object"}, boom),
    ])


async def test_toolbox_runs_tools_and_reports_errors():
    box = _box()
    assert await box.call("add", '{"a": 2, "b": 3}') == "5"
    assert await box.call("missing", "{}") == "Error: unknown tool 'missing'."
    assert await box.call("add", "{not json") == "Error: arguments were not valid JSON."
    assert await box.call("boom", "") == "Error: nope"
    assert [s["function"]["name"] for s in box.schemas] == ["add", "boom"]


def test_search_knowledge_formats_citations(tmp_path, monkeypatch):
    (tmp_path / "faq.md").write_text("# FAQ\n## VPN\nUse the corp VPN client.\n", encoding="utf-8")
    monkeypatch.setattr(tools, "kb", KnowledgeBase(tmp_path))
    assert tools.search_knowledge("vpn") == "[faq.md › FAQ › VPN]\nUse the corp VPN client."
    assert tools.search_knowledge("payroll") == "No matching notes found."


# --- tool-calling loop in llm.stream_reply ---------------------------------


def _chunk(content=None, tool_calls=None):
    return NS(choices=[NS(delta=NS(content=content, tool_calls=tool_calls))])


def _tc(index, id=None, name=None, args=None):
    return NS(index=index, id=id, function=NS(name=name, arguments=args))


class FakeCompletions:
    """Replays scripted streams, recording each request."""

    def __init__(self, *rounds):
        self.rounds = list(rounds)
        self.requests = []

    async def create(self, **kw):
        self.requests.append({**kw, "messages": list(kw["messages"])})
        chunks = self.rounds.pop(0)

        async def gen():
            for c in chunks:
                yield c

        return gen()


def _fake_client(monkeypatch, *rounds):
    completions = FakeCompletions(*rounds)
    monkeypatch.setattr(llm, "client", NS(chat=NS(completions=completions)))
    return completions


async def _collect(messages, box):
    return "".join([d async for d in llm.stream_reply(messages, box)])


async def test_stream_reply_runs_tool_then_answers(monkeypatch):
    fake = _fake_client(
        monkeypatch,
        # Round 1: tool call streamed in fragments
        [_chunk(tool_calls=[_tc(0, id="call_1", name="add", args='{"a": 2,')]),
         _chunk(tool_calls=[_tc(0, args=' "b": 3}')])],
        # Round 2: final answer
        [_chunk("It's "), _chunk("5.")],
    )
    text = await _collect([{"role": "user", "content": "2+3?"}], _box())

    assert text == "It's 5."
    second = fake.requests[1]["messages"]
    assert second[1]["tool_calls"][0]["function"] == {"name": "add", "arguments": '{"a": 2, "b": 3}'}
    assert second[2] == {"role": "tool", "tool_call_id": "call_1", "content": "5"}
    assert "tools" in fake.requests[0]


async def test_stream_reply_without_tools_sends_none(monkeypatch):
    fake = _fake_client(monkeypatch, [_chunk("hi")])
    assert await _collect([{"role": "user", "content": "hi"}], None) == "hi"
    assert "tools" not in fake.requests[0]


async def test_stream_reply_stops_offering_tools_after_max_rounds(monkeypatch):
    call = [_chunk(tool_calls=[_tc(0, id="c", name="add", args=json.dumps({"a": 1, "b": 1}))])]
    rounds = [call] * llm.MAX_TOOL_ROUNDS + [[_chunk("done")]]
    fake = _fake_client(monkeypatch, *rounds)

    assert await _collect([{"role": "user", "content": "loop"}], _box()) == "done"
    assert "tools" not in fake.requests[-1]
    assert len(fake.requests) == llm.MAX_TOOL_ROUNDS + 1
