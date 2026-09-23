"""Tool registry.

`toolbox_for(user_id)` decides which tools a given caller's model is even shown.
That is defence in depth, not the control itself — each privileged tool still
re-checks authorisation in its own body, because the model chooses when to call
and the text it reads is attacker-controlled. Hiding the tools simply means an
injected instruction has nothing to aim at.
"""

from ..authz import is_admin
from .base import Tool, ToolBox
from .knowledge import KNOWLEDGE_HINT, SEARCH_KNOWLEDGE, kb, search_knowledge
from .overseer import (
    OVERSEER_HINT,
    OVERSEER_TOOLS,
    execute_refresh_token,
    execute_restart,
    execute_start,
    execute_stop,
)

ALL_TOOLS: list[Tool] = [SEARCH_KNOWLEDGE, *OVERSEER_TOOLS]


def toolbox_for(user_id: str | None) -> ToolBox:
    """The tools this caller may use."""
    allowed = [t for t in ALL_TOOLS if not t.admin_only or is_admin(user_id)]
    return ToolBox(allowed)


def hint_for(user_id: str | None) -> str:
    """Extra system-prompt guidance describing the tools this caller has."""
    hint = "" if kb.is_empty() else KNOWLEDGE_HINT
    if is_admin(user_id):
        hint += OVERSEER_HINT
    return hint


# Kept for the plain knowledge-only case and existing imports.
toolbox = ToolBox([SEARCH_KNOWLEDGE])

__all__ = [
    "ALL_TOOLS",
    "KNOWLEDGE_HINT",
    "OVERSEER_HINT",
    "SEARCH_KNOWLEDGE",
    "Tool",
    "ToolBox",
    "execute_refresh_token",
    "execute_restart",
    "execute_start",
    "execute_stop",
    "hint_for",
    "kb",
    "search_knowledge",
    "toolbox",
    "toolbox_for",
]
