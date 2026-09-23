"""Tool plumbing: the schema wrapper and the dispatcher."""

import inspect
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict  # JSON schema
    fn: Callable
    # Privileged tools are only offered to, and runnable by, allowlisted users.
    # Default False so adding a tool never silently grants power; the overseer
    # tools opt in explicitly and also re-check in their own body.
    admin_only: bool = False

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolBox:
    def __init__(self, tools: list[Tool]):
        self._tools = {t.name: t for t in tools}

    @property
    def schemas(self) -> list[dict]:
        return [t.schema for t in self._tools.values()]

    async def call(self, name: str, arguments: str) -> str:
        """Run a tool; errors are returned as text so the model can recover."""
        log.info("Tool call %s(%s)", name, arguments)
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: unknown tool {name!r}."
        try:
            args = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return "Error: arguments were not valid JSON."
        try:
            result = tool.fn(**args)
            if inspect.isawaitable(result):
                result = await result
            return str(result)
        except Exception as exc:
            log.exception("Tool %s failed", name)
            return f"Error: {exc}"
