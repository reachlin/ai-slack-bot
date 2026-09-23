# About this bot

This Slack bot answers questions using an OpenAI-compatible LLM (DeepSeek by default).
Source code: https://github.com/reachlin/ai-slack-bot

## How to use

- In a channel: invite the bot with `/invite @Incoming Notification`, then @mention it.
- In DMs: open the bot under *Agents & apps* and message it directly.
- Replies go in a thread. Everything in the thread is sent to the model as context,
  so follow-up questions in the same thread work.
- While the bot is working, it adds an :hourglass_flowing_sand: reaction to your message.

## Knowledge base

The bot can search markdown notes stored in the `knowledge/` folder of its deployment.
Add or edit `.md` files there; changes are picked up on the next question, no restart needed.
Notes are split into sections by heading, so clear headings make search results better.

## Limits

- The bot only sees the current thread, not the rest of the channel.
- Very long answers are split across several messages.
