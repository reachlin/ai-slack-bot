from bot.context import build_messages

BOT = "UBOT"


def test_roles_and_mention_stripping():
    thread = [
        {"user": "U1", "text": "<@UBOT> what is 2+2?"},
        {"user": BOT, "text": "4"},
        {"user": "U1", "text": "  "},
        {"user": "U1", "text": "and 3+3?"},
    ]
    msgs = build_messages(thread, BOT, "sys", budget=1000)
    assert msgs == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "what is 2+2?"},
        {"role": "assistant", "content": "4"},
        {"role": "user", "content": "and 3+3?"},
    ]


def test_budget_keeps_newest_messages():
    thread = [{"user": "U1", "text": f"msg{i} " + "x" * 400} for i in range(10)]
    msgs = build_messages(thread, BOT, "sys", budget=300)
    assert msgs[0]["role"] == "system"
    assert msgs[-1]["content"].startswith("msg9")
    assert len(msgs) < 11


def test_latest_message_kept_even_if_over_budget():
    msgs = build_messages([{"user": "U1", "text": "x" * 10_000}], BOT, "sys", budget=10)
    assert len(msgs) == 2
