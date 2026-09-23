from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import openai
from openai import AsyncOpenAI

from .config import settings

if TYPE_CHECKING:
    from .tools import ToolBox

MAX_TOOL_ROUNDS = 4

# One client for every OpenAI-compatible provider; switch via LLM_BASE_URL / LLM_MODEL.
client = AsyncOpenAI(
    base_url=settings.llm_base_url,
    api_key=settings.llm_api_key,
    timeout=settings.llm_timeout_s,
    max_retries=2,
)


async def stream_reply(messages: list[dict], tools: "ToolBox | None" = None) -> AsyncIterator[str]:
    """Stream the answer text, running any tool calls the model makes along the way."""
    messages = list(messages)
    for round_ in range(MAX_TOOL_ROUNDS + 1):
        # On the last round, withhold tools so the model has to answer.
        extra = {"tools": tools.schemas} if tools and round_ < MAX_TOOL_ROUNDS else {}
        stream = await client.chat.completions.create(
            model=settings.llm_model, messages=messages, stream=True, **extra
        )

        calls: dict[int, dict] = {}
        content, reasoning = "", ""
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                content += delta.content
                yield delta.content
            # DeepSeek thinking models need their reasoning echoed back alongside tool calls.
            reasoning += getattr(delta, "reasoning_content", None) or ""
            for tc in delta.tool_calls or []:
                call = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                call["id"] = tc.id or call["id"]
                if tc.function:
                    call["name"] += tc.function.name or ""
                    call["arguments"] += tc.function.arguments or ""

        if not calls:
            return

        assistant = {
            "role": "assistant",
            "content": content or None,
            "tool_calls": [
                {"id": c["id"], "type": "function",
                 "function": {"name": c["name"], "arguments": c["arguments"]}}
                for c in calls.values()
            ],
        }
        if reasoning:
            assistant["reasoning_content"] = reasoning
        messages.append(assistant)
        for c in calls.values():
            result = await tools.call(c["name"], c["arguments"])
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": result})


def describe_error(exc: Exception) -> str:
    """A short, user-facing explanation of why a reply failed."""
    match exc:
        case openai.RateLimitError():
            return "The model is rate-limited right now. Please try again in a minute."
        case openai.AuthenticationError():
            return "The model API key was rejected. Ask the bot admin to check `LLM_API_KEY`."
        case openai.APIStatusError(status_code=402):
            return "The model account is out of credit. Ask the bot admin to top it up."
        case openai.APITimeoutError():
            return "The model took too long to respond. Please try again."
        case openai.APIConnectionError():
            return "Couldn't reach the model provider. Please try again shortly."
        case openai.APIStatusError(status_code=code) if code >= 500:
            return f"The model provider is having problems ({code}). Please try again shortly."
        case openai.APIStatusError(status_code=code):
            return f"The model rejected the request ({code})."
        case _:
            return "Something went wrong while generating the answer."
