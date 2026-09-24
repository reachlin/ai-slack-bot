# About this bot

This Slack bot answers questions using an OpenAI-compatible LLM (DeepSeek by default).
Source code: https://github.com/reachlin/ai-slack-bot

## How to use

- In a channel: invite the bot with `/invite @Incoming Notification`, then @mention it.
  **An @mention is required in channels** — a plain message, including a reply inside a
  thread the bot itself started, does not reach it.
- In DMs: open the bot under *Agents & apps* and message it directly. No @mention needed.
- Replies go in a thread. Everything in the thread is sent to the model as context,
  so follow-up questions in the same thread work.
- While the bot is working, it adds an :hourglass_flowing_sand: reaction to your message.

## Knowledge base

The bot can search markdown notes stored in the `knowledge/` folder of its deployment.
Add or edit `.md` files there; changes are picked up on the next question, no restart needed.
Notes are split into sections by heading, so clear headings make search results better.

## Operating the gold-finger trading overseer

The bot can control the gold-finger Schwab options overseer — the automated system that
sells cash-secured puts and manages their resting buy-to-close covers. Ask in plain
English; the bot picks the right tool.

| What you want | Say something like |
|---|---|
| A live report | "how is the overseer doing?" / "overseer status" |
| Start it | "start the overseer" |
| Stop it | "stop the overseer" |
| Restart it | "restart the overseer" |
| Install a new Schwab token | attach `schwab_token.json`, "install this token" |

**Status is read-only. Everything else posts Approve / Reject buttons and does nothing
until a human clicks Approve.** Asking for a restart never restarts anything by itself.

`start` works even if the overseer was removed entirely — it reinstalls the LaunchAgent
and bootstraps it. `stop` keeps it down until someone starts it again; it does not
self-heal. A restart reloads code and the Schwab token; open positions and their resting
GTC covers are untouched, because those live at the broker and fill whether or not the
overseer is running.

For a token refresh: re-authenticate Schwab on any machine, upload the resulting
`schwab_token.json`, and ask the bot to install it. It checks the token is actually valid
before asking for approval — installing an expired one would look like success and blind
the overseer at the next market open — then archives the old token, restarts the
overseer. It will also delete the uploaded file from Slack **if** a user token is
configured — an app can only delete files it uploaded itself, so without one you must
delete the message yourself. The bot says which applies when it reports the result.

### Who can do this

Only Slack user ids listed in the bot's `OVERSEER_ADMIN_IDS` setting. Everyone else does
not see these tools at all and cannot run them. Saying "I am the admin" in a message
changes nothing: permission is checked against the Slack identity attached to the event
itself, never against anything typed in the conversation.

Approvals, rejections and their outcomes are written to the bot's log.

### What it deliberately cannot do

There is no way to place, close, roll or cancel a trade from Slack. The bot can start and
stop the system that trades, but it cannot move money. That boundary is intentional: a
bug, or a misread instruction, should at worst halt the scanner.

## Limits

- The bot only sees the current thread, not the rest of the channel.
- Very long answers are split across several messages.
- It cannot read a file unless you attach it to the message you send.
