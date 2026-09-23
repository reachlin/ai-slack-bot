# Plan

## Done

- [x] Bolt Socket Mode bot on any OpenAI-compatible LLM; Docker dev setup with auto-reload
- [x] Answers mentions in threads and DMs, using the whole thread as context
- [x] Streaming replies, long-reply splitting with balanced code fences
- [x] `:hourglass_flowing_sand:` working reaction, duplicate-event protection, readable LLM errors
- [x] Test suite with fake Slack and LLM clients
- [x] Markdown knowledge base with `search_knowledge` tool (BM25, CJK, citations, live re-index)

## Next

Roughly in priority order.

1. **CI.** GitHub Actions running `uv run pytest` on push and PR; build the prod image.
2. **Deploy.** Run the prod image somewhere always-on (small VM, ECS/Fargate or k8s, one replica).
   Secrets from the platform's secret store instead of `.env`.
3. **Access control and cost guardrails.** Optional allow-list of channels/users, per-user rate limit,
   and log token usage per request.
4. **Better context handling.** Real tokenizer (e.g. `tiktoken`) instead of `chars / 4`; summarize
   older thread messages instead of dropping them.
5. **Knowledge upgrades.**
   - Hybrid search (BM25 + embeddings) once notes outgrow keyword search.
   - More sources: sync from a Google Drive / Notion / GitHub wiki folder.
   - A `/kb reload` or `/kb list` slash command for visibility.
6. **More tools.** Web search, GitHub (PR/issue lookup), fetch-a-URL. Keep each one read-only by
   default, the same pattern as `search_knowledge`.
7. **Attachments.** Read text files and images (for vision-capable models) shared in the thread.
8. **Per-channel personas.** System prompt / model per channel, e.g. a cheaper model for casual
   channels.

## Later / if needed

- Move to the HTTP events API and shared dedupe (Redis) to run multiple replicas.
- Feedback buttons (👍/👎) on answers, logged for prompt and knowledge tuning.
- Scheduled summaries of busy channels.

## Open questions

- Where should production run, and who owns the Slack app and LLM billing?
- Which knowledge is safe in this public repo, and where should private notes live?
