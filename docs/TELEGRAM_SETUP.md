# Telegram Setup Guide — JARVIS Phase 9

Telegram bots use a simple token (no OAuth). Setup takes about 3 minutes.

## 1. Create the bot

1. Open Telegram and message **@BotFather**.
2. Send `/newbot` → choose a display name (e.g. `JARVIS`) → choose a
   username ending in `bot` (e.g. `my_jarvis_bot`).
3. BotFather replies with an **API token** like
   `123456789:AAHf...example`. Keep it secret.

## 2. Store the token (the manual "add the API" step)

```powershell
cd "C:\Users\Josh\Documents\My Devs\JarvisProject"
.\.venv\Scripts\Activate.ps1
python -m integrations.telegram setup
```

- Paste the token when prompted (input hidden).
- JARVIS verifies it against `getMe` and stores it in the **Windows
  Credential Manager** under `jarvis/telegram-bot-token` — never in files.

Check status / remove:

```powershell
python -m integrations.telegram status
python -m integrations.telegram revoke
```

(Also revoke via @BotFather → `/mybots` → your bot → API Token → Revoke.)

## 3. Enable in JARVIS

Edit `config/settings.yaml`:

```yaml
telegram:
  enabled: true
```

Restart JARVIS.

## 4. What the bot can (and cannot) do — platform rules

**Can:**
- Receive messages **sent directly to the bot** or posted in groups where
  the bot is a member **after** it joined.
- Send messages to chats it can see (with your approval — HIGH risk).

**Cannot (Telegram platform rules, not JARVIS limitations):**
- Read arbitrary chat **history** — `getUpdates` only returns recent
  updates (roughly the last 24 hours).
- Read other people's private chats.
- Message users first (a user must start the conversation with `/start`).

## 5. Using the tools

| Tool | Risk | Behaviour |
|---|---|---|
| `telegram_read_messages` | low | Recent messages with their `chat_id` |
| `telegram_send_message` | **high** | Sends to a `chat_id` — approval dialog first |

Flow: ask JARVIS to *"read my telegram"* → note the `chat_id` shown →
*"send 'done' to chat 123456"* → approve the dialog → sent and audited.

## 6. Testing policy (spec section 21)

Automated tests use a fake HTTP layer — no real Telegram traffic. If you
try it live, message your own bot from your own account.
