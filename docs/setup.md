# Setup

## Prerequisites

- Docker with Compose (for the dev container), or Python 3.12 + [uv](https://docs.astral.sh/uv/)
- A Slack workspace where you can install apps
- An API key for an OpenAI-compatible provider (DeepSeek, OpenAI, ...)

## 1. Create the Slack app

1. Go to https://api.slack.com/apps → **Create New App** → **From an app manifest**, pick the
   workspace, and paste [`manifest.yml`](../manifest.yml). It enables Socket Mode, the Messages tab,
   the `app_mention` and `message.im` events, and these bot scopes:
   `app_mentions:read`, `chat:write`, `channels:history`, `groups:history`, `im:history`,
   `im:read`, `im:write`, `reactions:write` (for the working indicator).
2. **Install App** → install to the workspace → copy the **Bot User OAuth Token** (`xoxb-...`).
3. **Basic Information → App-Level Tokens** → generate a token with scope `connections:write`
   → copy it (`xapp-...`).

After changing scopes or events, **reinstall the app** to the workspace.

## 2. Configure

```bash
cp .env.example .env
```

Fill in `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `LLM_API_KEY` and `LLM_MODEL`
(see [design.md](design.md#configuration) for all options). `.env` is git-ignored; never commit it.

## 3. Run

```bash
docker compose up --build        # foreground
docker compose up -d --build     # background; logs: docker compose logs -f bot
```

The dev container bind-mounts `src/` and `tests/` and restarts the bot on Python file changes.
`knowledge/` is mounted read-only; notes are re-indexed on the next question.
After changing dependencies: `uv add <pkg>`, then `docker compose up --build`.

Without Docker:

```bash
uv sync
uv run python -m bot.app
```

## 4. Use it

- **Channel:** `/invite @AI Bot`, then `@AI Bot <question>`. It answers in a thread; follow-ups in the
  thread need another mention.
- **DM:** open the bot from Apps and message it directly; no mention needed.

The whole thread is sent as context, so follow-up questions work naturally.

## 5. Add knowledge

Drop markdown files into `knowledge/`. Use headings: each section becomes a searchable chunk and
the heading trail is used as the citation. Ask the bot about them; no restart needed.

## Tests

```bash
docker compose exec bot pytest   # in the running dev container
uv run pytest                    # locally
```

## Production image

```bash
docker build --target prod -t ai-slack-bot .
docker run --env-file .env ai-slack-bot
```

No dev dependencies, runs as a non-root user, and bakes in `knowledge/`. Run a **single replica**
(Socket Mode + in-memory dedupe).

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Sending messages to this app has been turned off" in DMs | Enable **App Home → Messages Tab** and "Allow users to send messages", reinstall, then reload the Slack client (the desktop app caches this state) |
| Mentions work in public but not private channels | Add `groups:history`, reinstall, and invite the bot to the channel |
| `invalid_auth` / `not_authed` on startup | Wrong or swapped tokens: `SLACK_BOT_TOKEN` is `xoxb-`, `SLACK_APP_TOKEN` is `xapp-` |
| Reply shows `:warning: ...` | The LLM call failed; the note says why (bad key, balance, rate limit, timeout) |
| No :hourglass_flowing_sand: reaction, `missing_scope` warning in logs | Add `reactions:write`, reinstall |
| `RuntimeError: Event loop is closed` in dev logs | Harmless noise from the auto-restart on file changes |
