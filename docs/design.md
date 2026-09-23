# Design

A Slack bot that answers in threads using any OpenAI-compatible LLM (DeepSeek, OpenAI, ...), with an
optional markdown knowledge base it can search through tool calling.

## Architecture

```
Slack ──(Socket Mode WebSocket)──▶ app.py ──▶ context.py ──▶ llm.py ──▶ LLM API
  ▲                                  │                         │  ▲
  │                                  │                         ▼  │ tool results
  └──── chat.postMessage/update ◀── reply.py ◀── text deltas   tools.py ──▶ knowledge.py
                                                                          (BM25 over knowledge/*.md)
```

| Module | Responsibility |
|---|---|
| `config.py` | `pydantic-settings` `Settings`, read from env / `.env` |
| `app.py` | Bolt `AsyncApp`: event handlers, dedupe, working reaction, orchestration |
| `context.py` | Slack thread → chat `messages`, trimmed to a token budget |
| `llm.py` | `AsyncOpenAI` client, streaming + tool-call loop, friendly error text |
| `reply.py` | Streams text into Slack messages; throttles edits, splits long replies |
| `tools.py` | `Tool` / `ToolBox` abstraction and the `search_knowledge` tool |
| `knowledge.py` | Markdown chunking, tokenizing and BM25 search |

## Key decisions

- **Socket Mode.** No public URL, ingress or TLS needed; the bot dials out to Slack. Good for local
  dev and a single-instance deployment. Trade-off: one connection per app token, so horizontal
  scaling needs the HTTP events API instead.
- **OpenAI-compatible client only.** One `openai` SDK client with a configurable `LLM_BASE_URL`
  covers DeepSeek, OpenAI and most hosted/local providers (vLLM, Ollama). Switching is an `.env`
  change.
- **Stateless conversation.** The bot keeps no chat history of its own; every question re-reads the
  Slack thread (`conversations.replies`, up to 200 messages). Slack is the source of truth, so
  restarts lose nothing.
- **Async end to end.** Bolt async app + `AsyncOpenAI` + `AsyncWebClient`, so concurrent questions
  don't block each other.

## Request flow

1. **Trigger.** `app_mention` in a channel, or a plain user `message` in a DM (`channel_type == "im"`,
   no subtype, no `bot_id`). Other channel traffic is ignored.
2. **Dedupe.** Slack can redeliver events; `RecentKeys` remembers `channel:ts` for 10 minutes
   (in memory) and drops repeats.
3. **Working indicator.** Add `:hourglass_flowing_sand:` to the user's message; always removed in
   `finally`. Reaction failures are logged, never fatal.
4. **Context.** `build_messages` strips `<@U...>` mentions, maps the bot's own messages to
   `assistant` and everything else to `user`, and keeps the newest messages that fit
   `MAX_CONTEXT_TOKENS` (estimated as `chars / 4`). The latest message is always kept.
5. **LLM + tools.** `stream_reply` streams the completion. If the model asks for tools, streamed
   `tool_calls` fragments are accumulated, executed via `ToolBox.call`, appended as `tool` messages,
   and the model is called again, up to `MAX_TOOL_ROUNDS = 4`. The last round is sent without
   tools to force a text answer. DeepSeek's `reasoning_content` is echoed back as required.
6. **Streaming reply.** `ReplyStream` posts the first message, then `chat.update`s at most once a
   second. Past ~3900 characters it starts a new message, keeping ``` code fences balanced across
   the split.
7. **Errors.** Exceptions become a short `:warning:` note on the reply (`describe_error` maps rate
   limits, bad key, insufficient balance, timeouts, 5xx, ...) instead of silent failure.

## Knowledge base

- **Source.** Every `*.md` under `KNOWLEDGE_DIR` (default `knowledge/`, subfolders included).
- **Chunking.** Split by markdown headings (ignoring `#` inside code fences); each chunk carries
  its heading trail, e.g. `about-reachlin.md › Experience › IBM Cloud`. Long sections are split at
  1500 characters.
- **Search.** BM25 (`k1=1.5`, `b=0.75`). Tokens are lower-cased words minus stopwords, plus
  character bigrams for Chinese/Japanese/Korean. The file name stem and heading are indexed with the
  body, so "reachlin" finds `about-reachlin.md`.
- **Freshness.** The index is rebuilt when any file's mtime/size changes, checked on each search;
  no restart needed.
- **Tool exposure.** `search_knowledge(query, top_k)` is offered only when the folder has notes.
  A system-prompt hint tells the model when to search (team/project/process questions, not general
  knowledge), to retry once with other keywords, and to cite `_Source: <file › heading>_`.

Why BM25 and not embeddings: zero extra services or API calls, deterministic, fast for hundreds of
files, and good enough for keyword-heavy notes. See the plan for when to upgrade.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `SLACK_BOT_TOKEN` | — | `xoxb-` bot token |
| `SLACK_APP_TOKEN` | — | `xapp-` app-level token with `connections:write` |
| `LLM_BASE_URL` | `https://api.deepseek.com` | OpenAI-compatible endpoint |
| `LLM_API_KEY` | — | Provider key |
| `LLM_MODEL` | — | Model name |
| `LLM_TIMEOUT_S` | `120` | Per-request timeout |
| `SYSTEM_PROMPT` | helpful Slack assistant | Base system prompt |
| `MAX_CONTEXT_TOKENS` | `8000` | Thread history budget |
| `KNOWLEDGE_DIR` | `knowledge` | Markdown notes folder |
| `LOG_LEVEL` | `INFO` | Python log level |

## Testing

`pytest` + `pytest-asyncio` with fake Slack and LLM clients, so no network or credentials are needed.
Covers context trimming, message splitting and streaming, error mapping, the tool loop, the
knowledge index (chunking, CJK, re-index) and the end-to-end `answer` flow.

## Known limitations

- Dedupe is in memory: fine for one instance, not across replicas or restarts.
- Token counting is a `chars / 4` estimate, not a real tokenizer.
- Only text is read; files and images in the thread are ignored.
- Anyone who can mention or DM the bot can use it (no allow-list or rate limit).
