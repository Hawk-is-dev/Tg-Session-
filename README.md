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
| 🛡️ **Terminator** | Logs **in** with the session you send and terminates every *other* active session on that account, keeping only itself. No 24h wait — this uses Telegram's per-session reset, not the bulk "terminate all" action. |
| 🆕 **Generate Session** | Creates a brand-new session for an account you control, in one of three shapes: **String Session**, **Session File**, or **Zip Session**. |

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

