"""Request-scoped context for one Slack event.

Tools need to know who is asking and where to reply, but neither may be a tool
*parameter*: the LLM fills parameters in, and the text it reads is attacker
-controlled. Anything the model could forge is kept out of the function
signature and put here instead, set by the event handler from the Slack
payload before the model ever runs.
"""

from contextvars import ContextVar
from typing import Any

# Slack user id of the person whose message triggered this turn.
current_user: ContextVar[str | None] = ContextVar("current_user", default=None)

# Where a tool should post (e.g. an approval prompt).
current_channel: ContextVar[str | None] = ContextVar("current_channel", default=None)
current_thread_ts: ContextVar[str | None] = ContextVar("current_thread_ts", default=None)
current_client: ContextVar[Any] = ContextVar("current_client", default=None)

# Files attached to the triggering message. The model cannot hand a file to a
# tool, so the handler puts them here and the tool picks them up.
current_files: ContextVar[list | None] = ContextVar("current_files", default=None)
