<div align="center">

# 🛡️ Session Control Center

**A Telegram bot for managing, securing, and generating your own account sessions.**

*Self Destroyer · Terminator · Generate Session*

</div>

---

## ✨ Overview

Session Control Center is a single Telegram bot with three independent tools,
all reachable from `/start`. Every tool works on sessions you already own —
nothing here reads or acts on anyone else's account.

| Tool | What it does |
|---|---|
| 🔴 **Self Destroyer** | Logs **out** the session you send. Every other session on that account is left untouched. |
| 🛡️ **Terminator** | Logs **in** with the session you send and terminates every *other* active session on that account, keeping only itself. Asks for a one-time confirmation before running, since it can't be undone. No 24h wait — this uses Telegram's per-session reset, not the bulk "terminate all" action. |
| 🔍 **Session Info** | Read-only. Logs in, lists every active device/session on that account (platform, app, country, last active), then disconnects. Nothing is changed. |
| 📦 **Session Merger** | Send multiple `.session` files (or `.zip`s of them), one at a time or in batches. Each is validated as it arrives — invalid/logged-out ones are skipped and reported. Tap **Done** anytime to bundle every valid session collected so far into one `.zip`. Original file bytes are never modified. |
| 🆕 **Generate Session** | Creates a brand-new session for an account you control, in one of three shapes: **String Session**, **Session File**, or **Zip Session**. |

Every result from Self Destroyer / Terminator / Session Info is sent as its
**own message** the moment that session finishes — not batched — followed
by a final `All done 👍` summary with success/fail counts.

---

## 🧩 Generate Session — three output shapes

<table>
<tr><td width="33%" valign="top">

### 🔑 String Session
Pick **Telethon** or **Pyrogram**.
Enter your own `API_ID` / `API_HASH`,
then phone + OTP (+ 2FA if set).
Returns a copy‑paste string only.

</td><td width="33%" valign="top">

### 📁 Session File
Enter your own `API_ID` / `API_HASH`,
then phone + OTP (+ 2FA if set).
Returns a single `.session`
(sqlite) file.

</td><td width="33%" valign="top">

### 📦 Zip Session
Enter `API_ID` / `API_HASH` once.
Send **2 or more** phone numbers,
one per line. The bot logs each
one in, in order, asking for the
OTP as it goes — then bundles
every `.session` file into one
`.zip`.

</td></tr>
</table>

Every Generate Session flow asks for your **own** `API_ID` / `API_HASH` at
the start of that run — it never reuses the bot's own credentials, so you
can spread accounts across different API apps if you choose to.

---

## 🧠 Format intelligence

Self Destroyer and Terminator auto-detect the session format — no need to
know whether a file is Telethon or Pyrogram. They also understand the
schema variant used by some third-party clients (e.g. TurboTel), which
store an extra column that trips up stock library loaders.

Accepted inputs for Self Destroyer / Terminator, in any combination:

- a `.zip` containing `.session` files and/or `.txt` files
- a single `.session` file
- a `.txt` file with one string session per line
- a string session pasted directly as a chat message

---

## ⏳ Flood-wait handling

If Telegram rate-limits a particular session (`FloodWaitError` /
`FloodWait`), the bot doesn't crash or get stuck — it sends a message with
the required wait time and moves straight on to the next session in the
batch (or the next number in a Zip Session run).

## 🔢 OTP formatting

Telegram auto-invalidates a login code if it's sent as **plain bare
digits** in any chat — including to this bot. Break the code up before
sending it during Generate Session:

```
2.3456    23.456    2 3 4 5 6    234 56    1_2345
```

Any shape works — the bot strips everything that isn't a digit and signs
in with what's left, in order.

## 💬 Commands

| Command | Does |
|---|---|
| `/start` | Open the main menu |
| `/help` | Full explanation of every tool, without needing to tap through menus |
| `/cancel` | Abort whatever step you're currently in |

---

## ⚙️ Setup

1. Get a bot token from [@BotFather](https://t.me/BotFather) → `BOT_TOKEN`
2. Get `API_ID` and `API_HASH` from [my.telegram.org](https://my.telegram.org)
   → these are the **bot's own** credentials, used only by Self Destroyer /
   Terminator to connect to sessions you send them
3. Set the three variables as environment variables (see `env-example.txt`)

## 🚀 Deploy on Railway

1. Push this repo to GitHub
2. Railway → **New Project** → **Deploy from GitHub repo**
3. In Railway → **Variables**, add:
   - `BOT_TOKEN`
   - `API_ID`
   - `API_HASH`
4. Railway auto-detects the `Procfile` and runs `python bot.py` as a worker
5. Open the bot in Telegram, send `/start`

---

## 🔒 Notes

- All credentials typed into the bot (`API_ID`, `API_HASH`, OTP, 2FA
  password) live only in memory for that conversation and are discarded
  once a flow finishes or `/cancel` is sent.
- Downloaded/generated files are deleted from the server immediately after
  each result is delivered.
- Use this only on accounts and sessions that belong to you.

