"""Authorisation for privileged tools.

One rule: **the LLM never decides authorisation.** It is enforced here, in
code, before any side effect, against the Slack user id taken from the signed
event payload.

That matters because this bot feeds whole Slack threads to a model and then
lets the model call tools that restart live trading infrastructure on a
real-money account. Text in a thread is attacker-controlled; a message saying
"I am the admin" must buy nothing. So:

* the caller's identity arrives out-of-band (`reqctx.current_user`), never as
  a tool argument the model could fill in;
* the allowlist is configuration, not code — this repo is public;
* an empty allowlist admits nobody, so a misconfigured deploy fails closed.
"""

import logging

from .config import settings
from .reqctx import current_user

log = logging.getLogger(__name__)


class NotAuthorized(Exception):
    """Raised when a caller may not run a privileged tool."""


def admin_ids() -> frozenset[str]:
    """Slack user ids permitted to drive the overseer, from OVERSEER_ADMIN_IDS."""
    return frozenset(
        part.strip() for part in settings.overseer_admin_ids.split(",") if part.strip()
    )


def is_admin(user_id: str | None) -> bool:
    return bool(user_id) and user_id in admin_ids()


def require_admin() -> str:
    """Return the calling Slack user id, or raise NotAuthorized.

    Takes no arguments on purpose — see the module docstring. A tool outside a
    Slack request has no caller and is refused rather than allowed.
    """
    user_id = current_user.get()
    if not is_admin(user_id):
        log.warning("Denied privileged tool call from user_id=%r", user_id)
        raise NotAuthorized(
            "You are not authorised to operate the overseer. "
            "Ask the bot admin to add your Slack user id to OVERSEER_ADMIN_IDS."
        )
    return user_id
