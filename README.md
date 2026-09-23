# ai-slack-bot

Slack bot backed by any OpenAI-compatible LLM (OpenAI, DeepSeek, ...). Python + Slack Bolt (Socket Mode) + `openai` SDK.

## Local dev (Docker)

1. Create a Slack app at https://api.slack.com/apps → *From an app manifest* → paste `manifest.yml`.
   - Install to workspace → copy the **Bot token** (`xoxb-...`).
   - Basic Information → App-Level Tokens → create one with `connections:write` (`xapp-...`).
2. `cp .env.example .env` and fill in tokens + LLM key.
3. `docker compose up --build`

`src/` is bind-mounted; the bot restarts automatically on file changes.
After changing dependencies: `uv add <pkg>` then `docker compose up --build`.

Usage: `@AI Bot <question>` in a channel (invite it first), or DM it. Replies stream into the thread; the whole thread is sent as context.

## Switch provider

Edit `.env` — no code changes:

| Provider | LLM_BASE_URL | LLM_MODEL |
|---|---|---|
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat`, `deepseek-reasoner` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini`, ... |

## Production image

`docker build --target prod -t ai-slack-bot .` — no dev deps, non-root user.
