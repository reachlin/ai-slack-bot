import re

MENTION = re.compile(r"<@[A-Z0-9]+>")


def _estimate_tokens(text: str) -> int:
    # Rough heuristic; good enough for budgeting across providers with different tokenizers.
    return len(text) // 4 + 1


def build_messages(
    thread: list[dict], bot_user_id: str, system_prompt: str, budget: int
) -> list[dict]:
    """Turn a Slack thread into chat messages, keeping the newest that fit the token budget."""
    history = []
    for msg in thread:
        text = MENTION.sub("", msg.get("text", "")).strip()
        if not text:
            continue
        role = "assistant" if msg.get("user") == bot_user_id else "user"
        history.append({"role": role, "content": text})

    kept, used = [], _estimate_tokens(system_prompt)
    for msg in reversed(history):
        used += _estimate_tokens(msg["content"])
        if used > budget and kept:
            break
        kept.append(msg)

    return [{"role": "system", "content": system_prompt}, *reversed(kept)]
