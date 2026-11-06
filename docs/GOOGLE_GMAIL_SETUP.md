# Gmail (Google) Setup Guide — JARVIS Phase 8

This guide walks you through creating the Google Cloud credentials JARVIS
needs for Gmail. You do this **once**; afterwards the OAuth refresh token
lives in your Windows Credential Manager — never in files or source control.

## 0. Prerequisites

- A Google account (use a **dedicated/test account** if possible).
- Python dependencies:

  ```powershell
  cd "C:\Users\Josh\Documents\My Devs\JarvisProject"
  .\.venv\Scripts\Activate.ps1
  python -m pip install -r requirements-gmail.txt
  ```

## 1. Create a Google Cloud project

1. Go to <https://console.cloud.google.com/> and sign in.
2. Click the project dropdown → **New Project** → name it e.g. `jarvis-gmail`
   → **Create**.
3. Select the new project.

## 2. Enable the Gmail API

1. Menu → **APIs & Services → Library**.
2. Search for **Gmail API** → click it → **Enable**.

## 3. Configure the OAuth consent screen

1. **APIs & Services → OAuth consent screen**.
2. User type: **External** → **Create**.
3. Fill in the required app name (`JARVIS`), your email, and developer email.
4. **Scopes** step: you can skip adding scopes manually (JARVIS requests
   only these, minimum necessary per the spec):
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/gmail.compose`
   - `https://www.googleapis.com/auth/gmail.send`
5. **Test users** step: **Add yourself** (while the app is in "Testing",
   only test users can authorize — that is all you need).
6. Save. Publishing is not required while in Testing mode.

> Note: Google may show an **unverified app warning** during authorization
> because the app is in Testing. Click **Advanced → Go to JARVIS (unsafe)**
> — this is your own app, so it is safe for your own account.

## 4. Create the OAuth client (Desktop app)

1. **APIs & Services → Credentials → Create credentials → OAuth client ID**.
2. Application type: **Desktop app** → name e.g. `JARVIS Desktop` → **Create**.
3. Click **Download JSON**.
4. Save the file as:

   ```
   C:\Users\Josh\Documents\My Devs\JarvisProject\config\google_client_secret.json
   ```

   This exact path is what `config/settings.yaml` points to. The file is
   already covered by `.gitignore` — never commit it or share it.

## 5. Authorize JARVIS (the manual "add the API" step)

```powershell
python -m integrations.gmail setup
```

- A browser window opens → choose your account → approve the scopes.
- JARVIS stores the refresh token in **Windows Credential Manager** under
  `jarvis/gmail-token`. No token is ever written to disk or git.

Check status / remove access later:

```powershell
python -m integrations.gmail status   # libraries + authorization state
python -m integrations.gmail revoke   # delete the stored token locally
```

To revoke from Google's side: <https://myaccount.google.com/permissions>
→ remove **JARVIS**.

## 6. Enable Gmail in JARVIS

Edit `config/settings.yaml`:

```yaml
gmail:
  enabled: true
```

Restart JARVIS. If authorization is missing, the Gmail tools are skipped
and the log explains exactly what to run — JARVIS never pretends Gmail
works when it does not.

## 7. What JARVIS can do (and what it will ask about)

| Tool | Risk | Behaviour |
|---|---|---|
| `gmail_search` | low | Search messages with Gmail query syntax |
| `gmail_read` | low | Read one message (id from search) |
| `gmail_create_draft` | low | Creates a **draft only** — never sends |
| `gmail_send` | **high** | Sends an email — **approval dialog always shown first** |

Every Gmail action is written to the audit trail (`data/audit/audit.log`).

## 8. Testing policy (spec section 21)

Automated tests never touch real Gmail: they run against a fake service
object. Never test `gmail_send` against a real mailbox with real
recipients; use a dedicated account and your own address if you try it live.

## 9. Troubleshooting

- **`client secret file not found`** → the JSON from step 4 is missing or
  misnamed (must be `config/google_client_secret.json`).
- **`access_denied` / 403 during consent** → your account is not in
  **Test users** (step 3.5), or the OAuth consent screen is unpublished
  with your account absent.
- **`invalid_grant` on use** → the token expired/revoked; run
  `python -m integrations.gmail revoke` then `setup` again.
- **Scope errors** → make sure the Gmail API is enabled (step 2) and the
  scopes in `config/settings.yaml` match what the token was granted;
  re-run setup after changing scopes.
