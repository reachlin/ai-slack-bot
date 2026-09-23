"""Human approval gate for actions that change live trading state.

The allowlist says *who* may ask; this says *nothing happens until a human
clicks*. That containment is what makes an LLM-driven control path acceptable
here: a model steered by injected text can, at worst, post a button. The click
carries a Slack-signed identity, so the approval itself cannot be forged.

Pending actions are deliberately in-memory: a bot restart drops them, which is
the safe direction to fail.
"""

import time
import uuid
from dataclasses import dataclass

from .config import settings


@dataclass(frozen=True)
class PendingAction:
    id: str
    action: str
    requested_by: str
    channel: str
    thread_ts: str
    created_at: float
    # Data captured when the request was made, because the Slack request
    # context is long gone by the time someone clicks Approve.
    payload: dict | None = None


class ApprovalStore:
    """Short-lived, one-shot pending actions."""

    def __init__(self, ttl_s: float | None = None, now=time.time):
        self._ttl = settings.approval_ttl_s if ttl_s is None else ttl_s
        self._now = now
        self._pending: dict[str, PendingAction] = {}

    def __len__(self) -> int:
        return len(self._pending)

    def register(
        self,
        action: str,
        *,
        requested_by: str,
        channel: str,
        thread_ts: str,
        payload: dict | None = None,
    ) -> PendingAction:
        self._purge()
        pending = PendingAction(
            id=uuid.uuid4().hex[:12],
            action=action,
            requested_by=requested_by,
            channel=channel,
            thread_ts=thread_ts,
            created_at=self._now(),
            payload=payload,
        )
        self._pending[pending.id] = pending
        return pending

    def take(self, action_id: str) -> PendingAction | None:
        """Pop an action if it exists and is still fresh.

        One-shot: a double-click, or Slack redelivering the interaction, must
        not execute twice.
        """
        self._purge()
        return self._pending.pop(action_id, None)

    def _purge(self) -> None:
        cutoff = self._now() - self._ttl
        for key in [k for k, v in self._pending.items() if v.created_at <= cutoff]:
            del self._pending[key]


def approval_blocks(pending: PendingAction, summary: str) -> list[dict]:
    """Block Kit for an approve/reject prompt.

    The action id rides in each button's `value`, so the handler works from
    the interaction payload alone and never has to trust message text.
    """
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Approval needed*\n{summary}\n"
                    f"_Requested by <@{pending.requested_by}> · "
                    f"expires in {int(settings.approval_ttl_s // 60)} min_"
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": "overseer_approve",
                    "style": "danger",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "value": pending.id,
                },
                {
                    "type": "button",
                    "action_id": "overseer_reject",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "value": pending.id,
                },
            ],
        },
    ]


store = ApprovalStore()
