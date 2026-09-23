"""The human gate in front of anything that mutates live trading state.

Even with the allowlist, the LLM is the thing deciding *when* to call a tool,
and it can be steered by text in the thread. The approval step makes that
harmless: a hijacked model can, at worst, post a button nobody presses. The
click is the real authorisation, because Slack signs the clicker's identity.

A pending action is therefore one-shot and short-lived.
"""
import pytest

from bot.approval import ApprovalStore, approval_blocks

ADMIN = "U02DQJ9KKFZ"


def test_register_returns_an_action_with_a_unique_id():
    store = ApprovalStore(ttl_s=300)
    a = store.register("restart", requested_by=ADMIN, channel="C1", thread_ts="1.0")
    b = store.register("restart", requested_by=ADMIN, channel="C1", thread_ts="1.0")
    assert a.id != b.id
    assert a.action == "restart" and a.requested_by == ADMIN


def test_take_returns_the_action_once_then_never_again():
    """One-shot. A double-click, or Slack redelivering the interaction, must
    not restart the overseer twice."""
    store = ApprovalStore(ttl_s=300)
    a = store.register("restart", requested_by=ADMIN, channel="C1", thread_ts="1.0")
    assert store.take(a.id) is a
    assert store.take(a.id) is None


def test_take_of_an_unknown_id_is_none():
    assert ApprovalStore(ttl_s=300).take("no-such-id") is None


def test_expired_actions_are_not_executable():
    """An approval button found hours later in scrollback must be inert —
    the state it was approved against is long gone."""
    clock = [1000.0]
    store = ApprovalStore(ttl_s=300, now=lambda: clock[0])
    a = store.register("restart", requested_by=ADMIN, channel="C1", thread_ts="1.0")
    clock[0] += 301
    assert store.take(a.id) is None


def test_action_just_inside_the_window_still_works():
    clock = [1000.0]
    store = ApprovalStore(ttl_s=300, now=lambda: clock[0])
    a = store.register("restart", requested_by=ADMIN, channel="C1", thread_ts="1.0")
    clock[0] += 299
    assert store.take(a.id) is a


def test_expiry_does_not_leak_pending_actions():
    clock = [1000.0]
    store = ApprovalStore(ttl_s=300, now=lambda: clock[0])
    for _ in range(5):
        store.register("restart", requested_by=ADMIN, channel="C1", thread_ts="1.0")
    clock[0] += 301
    store.register("restart", requested_by=ADMIN, channel="C1", thread_ts="1.0")
    assert len(store) == 1


def test_blocks_carry_the_action_id_and_both_choices():
    store = ApprovalStore(ttl_s=300)
    a = store.register("restart", requested_by=ADMIN, channel="C1", thread_ts="1.0")
    blocks = approval_blocks(a, "Restart the overseer")

    dumped = str(blocks)
    assert a.id in dumped
    action_ids = [
        el["action_id"]
        for b in blocks
        if b["type"] == "actions"
        for el in b["elements"]
    ]
    assert action_ids == ["overseer_approve", "overseer_reject"]
    values = [
        el["value"]
        for b in blocks
        if b["type"] == "actions"
        for el in b["elements"]
    ]
    assert values == [a.id, a.id]


def test_blocks_name_the_requester_so_the_approver_sees_who_asked():
    store = ApprovalStore(ttl_s=300)
    a = store.register("restart", requested_by=ADMIN, channel="C1", thread_ts="1.0")
    assert ADMIN in str(approval_blocks(a, "Restart the overseer"))


def test_approve_button_is_styled_as_destructive():
    """Restarting live trading infrastructure should not look like a safe
    default in the Slack UI."""
    store = ApprovalStore(ttl_s=300)
    a = store.register("restart", requested_by=ADMIN, channel="C1", thread_ts="1.0")
    approve = [
        el
        for b in approval_blocks(a, "x")
        if b["type"] == "actions"
        for el in b["elements"]
        if el["action_id"] == "overseer_approve"
    ][0]
    assert approve["style"] == "danger"
