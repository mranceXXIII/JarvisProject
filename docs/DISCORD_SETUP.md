# Discord Setup Guide — JARVIS Phase 9

Discord bots use a token from the Developer Portal plus a server invite.
Setup takes about 5 minutes.

## 1. Create the application and bot

1. Go to <https://discord.com/developers/applications> → **New Application**
   → name it e.g. `JARVIS` → **Create**.
2. Left menu → **Bot** → under **Token** click **Reset Token** → copy it
   (you will paste it in step 3). Keep it secret.
3. On the same **Bot** page, scroll to **Privileged Gateway Intents** and
   enable **Message Content Intent** (required for JARVIS to read message
   text; without it content arrives empty).

## 2. Invite the bot to your server

1. Left menu → **OAuth2 → URL Generator**.
2. Scopes: check **bot**.
3. Bot Permissions: check **View Channels**, **Read Message History**,
   **Send Messages**.
4. Copy the generated URL, open it, choose your server, **Authorize**.

(The bot can only see the server(s)/channels you invite it to.)

## 3. Store the token (the manual "add the API" step)

```powershell
cd "C:\Users\Josh\Documents\My Devs\JarvisProject"
.\.venv\Scripts\Activate.ps1
python -m integrations.discord setup
```

- Paste the token when prompted (input hidden).
- JARVIS verifies it against `/users/@me` and stores it in the **Windows
  Credential Manager** under `jarvis/discord-bot-token` — never in files.

Check status / remove:

```powershell
python -m integrations.discord status   # shows servers the bot is in
python -m integrations.discord revoke
```

(Also revoke/reset the token any time in the Developer Portal.)

## 4. Enable in JARVIS

Edit `config/settings.yaml`:

```yaml
discord:
  enabled: true
```

Restart JARVIS.

## 5. Using the tools

| Tool | Risk | Behaviour |
|---|---|---|
| `discord_list_guilds` | low | Servers the bot is in (gives `guild_id`) |
| `discord_list_channels` | low | Text channels of a server (gives `channel_id`) |
| `discord_read_messages` | low | Recent messages of a channel |
| `discord_send_message` | **high** | Posts to a channel — approval dialog first |

Flow: *"list my discord servers"* → *"list channels of guild 123"* →
*"read discord channel 456"* → *"post 'done' to channel 456"* → approve.

## 6. Testing policy (spec section 21)

Automated tests use a fake HTTP layer — no real Discord traffic. If you
try it live, use your own test server.
