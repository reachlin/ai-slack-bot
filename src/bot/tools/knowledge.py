"""The knowledge-base search tool."""

import json
import logging

from ..config import settings
from ..knowledge import KnowledgeBase
from .base import Tool

log = logging.getLogger(__name__)


kb = KnowledgeBase(settings.knowledge_dir)

KNOWLEDGE_HINT = (
    "\n\nYou can call `search_knowledge` to search the team's preloaded notes. "
    "Use it for questions about the team, its projects, processes or this bot; skip it for "
    "general knowledge, small talk and arithmetic. If a search finds nothing, try once more "
    "with different keywords. When your answer uses the notes, end it with a line "
    "_Source: <citation>_ using the citation shown in brackets. If the notes don't cover "
    "the question, say so and answer from general knowledge."
)


def search_knowledge(query: str, top_k: int = 5) -> str:
    hits = kb.search(query, k=max(1, min(int(top_k), 10)))
    if not hits:
        return "No matching notes found."
    return "\n\n---\n\n".join(f"[{chunk.citation}]\n{chunk.text}" for _, chunk in hits)


SEARCH_KNOWLEDGE = Tool(
    name="search_knowledge",
    description=(
        "Keyword search over the team's preloaded markdown notes. "
        "Returns the most relevant sections with their source file and heading."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keywords to search for, in the language of the notes.",
            },
            "top_k": {
                "type": "integer",
                "description": "Number of sections to return (1-10, default 5).",
            },
        },
        "required": ["query"],
    },
    fn=search_knowledge,
)
