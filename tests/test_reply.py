from bot.reply import MAX_CHARS, ReplyStream, split_message


def test_split_prefers_newline():
    text = "a" * 3000 + "\n" + "b" * 2000
    head, tail = split_message(text)
    assert head == "a" * 3000
    assert tail == "b" * 2000


def test_split_hard_cut_without_newline():
    head, tail = split_message("x" * 5000)
    assert len(head) == MAX_CHARS
    assert head + tail == "x" * 5000


def test_split_balances_code_fence():
    text = "intro\n```python\n" + "x = 1\n" * 1000 + "```\nend"
    head, tail = split_message(text)
    assert head.count("```") % 2 == 0
    assert tail.startswith("```\n")


async def _stream(client, chunks, note=""):
    reply = ReplyStream(client, "C1", "T1")
    for chunk in chunks:
        await reply.append(chunk)
    await reply.finish(note)
    return client.messages


async def test_short_reply_is_one_message(fake_slack):
    msgs = await _stream(fake_slack(), ["Hel", "lo", "!"])
    assert list(msgs.values()) == ["Hello!"]


async def test_long_reply_rolls_over_without_losing_text(fake_slack):
    chunks = [f"line {i} of a long answer\n" for i in range(700)]
    msgs = await _stream(fake_slack(), chunks)
    assert len(msgs) > 1
    assert all(len(m) <= 4000 for m in msgs.values())
    assert "".join(msgs.values()).replace("\n", "") == "".join(chunks).replace("\n", "")


async def test_empty_reply_posts_placeholder(fake_slack):
    assert list((await _stream(fake_slack(), [])).values()) == ["_(empty response)_"]


async def test_whitespace_only_start_does_not_post(fake_slack):
    client = fake_slack()
    reply = ReplyStream(client, "C1", "T1")
    await reply.append("\n")
    assert client.calls == []


async def test_note_appended_to_partial_reply(fake_slack):
    msgs = await _stream(fake_slack(), ["partial"], ":warning: oops")
    assert list(msgs.values()) == ["partial\n\n:warning: oops"]


async def test_note_alone_when_no_text(fake_slack):
    msgs = await _stream(fake_slack(), [], ":warning: oops")
    assert list(msgs.values()) == [":warning: oops"]
