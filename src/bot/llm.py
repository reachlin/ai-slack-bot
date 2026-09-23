from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from .config import settings

# One client for every OpenAI-compatible provider; switch via LLM_BASE_URL / LLM_MODEL.
client = AsyncOpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)


async def stream_reply(messages: list[dict]) -> AsyncIterator[str]:
    stream = await client.chat.completions.create(
        model=settings.llm_model, messages=messages, stream=True
    )
    async for chunk in stream:
        if chunk.choices and (delta := chunk.choices[0].delta.content):
            yield delta
