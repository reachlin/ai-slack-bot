from collections.abc import AsyncIterator

import openai
from openai import AsyncOpenAI

from .config import settings

# One client for every OpenAI-compatible provider; switch via LLM_BASE_URL / LLM_MODEL.
client = AsyncOpenAI(
    base_url=settings.llm_base_url,
    api_key=settings.llm_api_key,
    timeout=settings.llm_timeout_s,
    max_retries=2,
)


async def stream_reply(messages: list[dict]) -> AsyncIterator[str]:
    stream = await client.chat.completions.create(
        model=settings.llm_model, messages=messages, stream=True
    )
    async for chunk in stream:
        if chunk.choices and (delta := chunk.choices[0].delta.content):
            yield delta


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
