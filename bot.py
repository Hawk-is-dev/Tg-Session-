"""
┌─────────────────────────────────────────────────────────┐
│               SESSION  CONTROL  CENTER  BOT              │
│   Self Destroyer · Terminator · Generate Session (x3)    │
└─────────────────────────────────────────────────────────┘

Three top-level tools, reached from /start:

  • Self Destroyer   — logs OUT the session you send.
  • Terminator       — logs IN with the session you send and kills every
                        OTHER active session on that account.
  • Generate Session — creates a brand-new session for an account you
                        control, in one of three output shapes:
                          - String Session  (Telethon or Pyrogram)
                          - Session File    (.session / sqlite)
                          - Zip Session     (2+ accounts bundled together)

All credentials you type (API_ID / API_HASH / OTP / 2FA password) stay in
memory only for the duration of that conversation step and are discarded
once a flow finishes or is cancelled.
"""

import os
import re
import sqlite3
import zipfile
import shutil
import logging
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from telethon import TelegramClient as TelethonClient
from telethon.sessions import StringSession as TelethonStringSession, MemorySession
from telethon.crypto import AuthKey
from telethon.tl.functions.account import GetAuthorizationsRequest, ResetAuthorizationRequest
from telethon.errors import SessionPasswordNeededError as TelethonPasswordNeeded

from pyrogram import Client as PyroClient
from pyrogram.raw.functions.account import GetAuthorizations, ResetAuthorization
from pyrogram.errors import SessionPasswordNeeded as PyroPasswordNeeded

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("session-control-center")

# ───────────────────────── configuration ──────────────────────────
# BOT_TOKEN / BOT_API_ID / BOT_API_HASH belong to the BOT ITSELF and are
# only used to connect to sessions handed to Self Destroyer / Terminator.
# Generate Session always uses API_ID / API_HASH typed in by the user for
# that run, never these.
BOT_TOKEN = os.environ["BOT_TOKEN"]
BOT_API_ID = int(os.environ["API_ID"])
BOT_API_HASH = os.environ["API_HASH"]

WORK_DIR = "work"

MODE_DESTROYER = "destroyer"
MODE_TERMINATOR = "terminator"

DIVIDER = "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈"

_SMALL_CAPS = str.maketrans(
    "abcdefghijklmnopqrstuvwxyz",
    "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ",
)


def sc(text: str) -> str:
    """Render a heading in small caps for a sharper, premium look."""
    return text.lower().translate(_SMALL_CAPS)


def banner(title: str, body: str = "") -> str:
    out = f"*{sc(title)}*\n{DIVIDER}"
    if body:
        out += f"\n{body}"
    return out


# ════════════════════════════════════════════════════════════════
#  MANUAL SQLITE FALLBACK (for third-party schemas, e.g. TurboTel)
# ════════════════════════════════════════════════════════════════

def manual_telethon_session_from_sqlite(session_file_path: str):
    conn = sqlite3.connect(session_file_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT dc_id, server_address, port, auth_key FROM sessions LIMIT 1")
        row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        raise RuntimeError("no row in sessions table")

    dc_id, server_address, port, auth_key_bytes = row
    if not auth_key_bytes or len(auth_key_bytes) < 256:
        raise RuntimeError("auth_key missing or too short")

    session = MemorySession()
    session.set_dc(dc_id, server_address, port)
    session.auth_key = AuthKey(data=auth_key_bytes)
    return session


# ════════════════════════════════════════════════════════════════
#  SELF DESTROYER / TERMINATOR — shared connection helpers
# ════════════════════════════════════════════════════════════════

async def get_authorized_telethon_client(session_path_no_ext=None, session_string=None):
    if session_string:
        client = TelethonClient(TelethonStringSession(session_string), BOT_API_ID, BOT_API_HASH)
        await client.connect()
    else:
        session_file_path = session_path_no_ext + ".session"
        try:
            client = TelethonClient(session_path_no_ext, BOT_API_ID, BOT_API_HASH)
            await client.connect()
        except Exception:
            manual_session = manual_telethon_session_from_sqlite(session_file_path)
            client = TelethonClient(manual_session, BOT_API_ID, BOT_API_HASH)
            await client.connect()

    if not await client.is_user_authorized():
        try:
            await client.disconnect()
        except Exception:
            pass
        raise RuntimeError("not authorized")
    return client


async def get_authorized_pyrogram_client(session_path_no_ext=None, session_string=None):
    if session_string:
        client = PyroClient(
            name="mem", api_id=BOT_API_ID, api_hash=BOT_API_HASH,
            session_string=session_string, in_memory=True,
        )
    else:
        workdir = os.path.dirname(session_path_no_ext) or "."
        name = os.path.basename(session_path_no_ext)
        client = PyroClient(name=name, api_id=BOT_API_ID, api_hash=BOT_API_HASH, workdir=workdir)

    await client.connect()
    try:
        await client.get_me()
    except Exception:
        try:
            await client.disconnect()
        except Exception:
            pass
        raise
    return client


async def disconnect_quietly(client, lib):
    try:
        if lib == "Pyrogram":
            if client.is_connected:
                await client.disconnect()
        else:
            await client.disconnect()
    except Exception:
        pass


def phone_label(me) -> str:
    """Prefer the account's real phone number (from Telegram itself), fall
    back to username, then numeric id."""
    phone = getattr(me, "phone", None) or getattr(me, "phone_number", None)
    if phone:
        phone = str(phone)
        return phone if phone.startswith("+") else f"+{phone}"
    username = getattr(me, "username", None)
    if username:
        return f"@{username}"
    return str(getattr(me, "id", "unknown"))


async def do_destroy(client, lib):
    await client.log_out()


async def do_terminate(client, lib):
    if lib == "Telethon":
        auths = await client(GetAuthorizationsRequest())
        for a in auths.authorizations:
            if a.current:
                continue
            try:
                await client(ResetAuthorizationRequest(hash=a.hash))
            except Exception:
                pass
            await asyncio.sleep(0.3)
    else:
        auths = await client.invoke(GetAuthorizations())
        for a in auths.authorizations:
            if a.current:
                continue
            try:
                await client.invoke(ResetAuthorization(hash=a.hash))
            except Exception:
                pass
            await asyncio.sleep(0.3)


async def process_one(display_name, mode, session_path_no_ext=None, session_string=None):
    """Returns (ok: bool, line: str) — line is the ready-to-send result message."""
    client, lib = None, None
    e_tel = e_pyro = None

    try:
        client = await get_authorized_telethon_client(session_path_no_ext, session_string)
        lib = "Telethon"
    except Exception as e1:
        e_tel = e1
        try:
            client = await get_authorized_pyrogram_client(session_path_no_ext, session_string)
            lib = "Pyrogram"
        except Exception as e2:
            e_pyro = e2

    if client is None:
        return False, (
            f"❌ Failed — {display_name}\n"
            f"    Telethon: {type(e_tel).__name__}: {e_tel}\n"
            f"    Pyrogram: {type(e_pyro).__name__}: {e_pyro}"
        )

    try:
        me = await client.get_me()
        label = phone_label(me)
        if mode == MODE_TERMINATOR:
            await do_terminate(client, lib)
            return True, f"Terminated {label}"
        else:
            await do_destroy(client, lib)
            return True, f"Destroyed {label}"
    except Exception as e:
        return False, f"❌ Failed — {display_name}: {type(e).__name__}: {e}"
    finally:
        await disconnect_quietly(client, lib)


def collect_targets(root_dir):
    session_files = []
    string_entries = []

    for dirpath, _, files in os.walk(root_dir):
        for f in files:
            full = os.path.join(dirpath, f)
            if f.endswith(".session"):
                session_files.append((full[: -len(".session")], f))
            elif f.endswith(".txt"):
                try:
                    with open(full, "r", encoding="utf-8", errors="ignore") as fh:
                        for i, line in enumerate(fh.read().splitlines(), 1):
                            line = line.strip()
                            if line:
                                string_entries.append((line, f"{f}:line{i}"))
                except Exception:
                    pass

    return session_files, string_entries


async def process_and_report(update: Update, mode, session_files, string_entries):
    total = len(session_files) + len(string_entries)
    if total == 0:
        await update.message.reply_text("⚠️ No session files or string sessions found.")
        return

    await update.message.reply_text(f"🔎 Found {total} session(s). Processing one by one...")

    success_count = 0
    fail_count = 0

    for path_no_ext, name in session_files:
        ok, line = await process_one(name, mode, session_path_no_ext=path_no_ext)
        await update.message.reply_text(line)
        success_count += 1 if ok else 0
        fail_count += 0 if ok else 1
        await asyncio.sleep(1)

    for s, name in string_entries:
        ok, line = await process_one(name, mode, session_string=s)
        await update.message.reply_text(line)
        success_count += 1 if ok else 0
        fail_count += 0 if ok else 1
        await asyncio.sleep(1)

    await update.message.reply_text(
        f"All done 👍\n\nSuccess ({success_count})\nFail ({fail_count})"
    )


# ════════════════════════════════════════════════════════════════
#  GENERATE SESSION — String / File / Zip
# ════════════════════════════════════════════════════════════════

def safe_phone(phone: str) -> str:
    return re.sub(r"[^0-9]", "", phone)


async def gen_dir_for(update: Update) -> str:
    chat_id = update.effective_chat.id
    d = os.path.join(WORK_DIR, str(chat_id), "generated")
    os.makedirs(d, exist_ok=True)
    return d


async def cancel_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, reason: str, client=None):
    if client is not None:
        try:
            await client.disconnect()
        except Exception:
            pass
    await update.message.reply_text(f"❌ {reason}")
    context.user_data.pop("gen_flow", None)


# ---------- String Session & single Session File (shared step logic) ----------

async def gen_ask_api_id(reply_fn):
    await reply_fn(banner("Step 1 / 3 — API Credentials") + "\nSend your *API_ID*:", parse_mode="Markdown")


async def gen_ask_api_hash(reply_fn):
    await reply_fn("Now send your *API_HASH*:", parse_mode="Markdown")


async def gen_ask_phone(reply_fn, label="Step 2 / 3 — Phone Number"):
    await reply_fn(
        f"{banner(label)}\nSend the phone number with country code, e.g. `+919876543210`:",
        parse_mode="Markdown",
    )


async def handle_single_gen_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles both 'string' and 'file' generate flows (single account)."""
    flow = context.user_data["gen_flow"]
    step = flow["step"]
    text = (update.message.text or "").strip()
    kind = flow["kind"]          # "string" | "file"
    fmt = flow.get("format")     # "telethon" | "pyrogram"  (string only)

    if step == "api_id":
        if not text.isdigit():
            await update.message.reply_text("⚠️ API_ID must be numeric. Send it again:")
            return
        flow["api_id"] = int(text)
        flow["step"] = "api_hash"
        await gen_ask_api_hash(update.message.reply_text)
        return

    if step == "api_hash":
        flow["api_hash"] = text
        flow["step"] = "phone"
        await gen_ask_phone(update.message.reply_text)
        return

    if step == "phone":
        phone = text
        api_id, api_hash = flow["api_id"], flow["api_hash"]
        try:
            if kind == "string" and fmt == "pyrogram":
                client = PyroClient(name="mem", api_id=api_id, api_hash=api_hash, in_memory=True)
                await client.connect()
                sent = await client.send_code(phone)
                phone_code_hash = sent.phone_code_hash
            elif kind == "file":
                gen_dir = await gen_dir_for(update)
                file_path = os.path.join(gen_dir, safe_phone(phone))
                client = TelethonClient(file_path, api_id, api_hash)
                await client.connect()
                sent = await client.send_code_request(phone)
                phone_code_hash = sent.phone_code_hash
            else:  # string + telethon
                client = TelethonClient(TelethonStringSession(), api_id, api_hash)
                await client.connect()
                sent = await client.send_code_request(phone)
                phone_code_hash = sent.phone_code_hash
        except Exception as e:
            await cancel_flow(update, context, f"Could not send code: {type(e).__name__}: {e}")
            return

        flow.update({"phone": phone, "client": client, "phone_code_hash": phone_code_hash, "step": "otp"})
        await update.message.reply_text(
            f"{banner('Step 3 / 3 — Verification Code')}\n📩 Code sent. Enter it here:",
            parse_mode="Markdown",
        )
        return

    if step == "otp":
        otp = text
        client = flow["client"]
        phone = flow["phone"]
        try:
            if kind == "string" and fmt == "pyrogram":
                await client.sign_in(phone_number=phone, phone_code_hash=flow["phone_code_hash"], phone_code=otp)
            else:
                await client.sign_in(phone=phone, code=otp, phone_code_hash=flow["phone_code_hash"])
        except (TelethonPasswordNeeded, PyroPasswordNeeded):
            flow["step"] = "2fa"
            await update.message.reply_text("🔒 2-Step Verification is enabled. Send the password:")
            return
        except Exception as e:
            await cancel_flow(update, context, f"{type(e).__name__}: {e}", client)
            return
        await finish_single_gen(update, context)
        return

    if step == "2fa":
        password = text
        client = flow["client"]
        try:
            if kind == "string" and fmt == "pyrogram":
                await client.check_password(password)
            else:
                await client.sign_in(password=password)
        except Exception as e:
            await cancel_flow(update, context, f"Incorrect password / error: {type(e).__name__}: {e}", client)
            return
        await finish_single_gen(update, context)
        return


async def finish_single_gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    flow = context.user_data["gen_flow"]
    kind = flow["kind"]
    fmt = flow.get("format")
    client = flow["client"]

    me = await client.get_me()
    label = getattr(me, "username", None) or getattr(me, "id", "unknown")

    if kind == "string":
        if fmt == "pyrogram":
            session_string = await client.export_session_string()
        else:
            session_string = client.session.save()
        await client.disconnect()
        await update.message.reply_text(
            f"{banner('Session Ready')}\n"
            f"👤 Account: {label}\n🔧 Format: {fmt.capitalize()}\n\n"
            f"🔑 *String Session:*\n`{session_string}`",
            parse_mode="Markdown",
        )
    else:  # file
        client.session.save()
        await client.disconnect()
        gen_dir = await gen_dir_for(update)
        file_path = os.path.join(gen_dir, safe_phone(flow["phone"]) + ".session")
        await update.message.reply_text(
            f"{banner('Session Ready')}\n👤 Account: {label}\n🔧 Format: Session File (.session)",
            parse_mode="Markdown",
        )
        await update.message.reply_document(file_path, caption="📁 Keep this file private.")

    chat_id = update.effective_chat.id
    shutil.rmtree(os.path.join(WORK_DIR, str(chat_id)), ignore_errors=True)
    context.user_data.pop("gen_flow", None)


# ---------- Zip Session (2+ accounts, sequential) ----------

async def handle_zip_gen_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    flow = context.user_data["gen_flow"]
    step = flow["step"]
    text = (update.message.text or "").strip()

    if step == "api_id":
        if not text.isdigit():
            await update.message.reply_text("⚠️ API_ID must be numeric. Send it again:")
            return
        flow["api_id"] = int(text)
        flow["step"] = "api_hash"
        await gen_ask_api_hash(update.message.reply_text)
        return

    if step == "api_hash":
        flow["api_hash"] = text
        flow["step"] = "phones"
        await update.message.reply_text(
            f"{banner('Step 2 / 3 — Phone Numbers')}\n"
            "Send 2 or more phone numbers with country code, *one per line*:\n\n"
            "`+919876543210`\n`+14155551234`",
            parse_mode="Markdown",
        )
        return

    if step == "phones":
        numbers = [l.strip() for l in text.splitlines() if l.strip()]
        numbers = [n for n in numbers if n.startswith("+") and n[1:].replace(" ", "").isdigit()]
        if len(numbers) < 2:
            await update.message.reply_text(
                "⚠️ Send at least 2 valid numbers (with country code), one per line."
            )
            return
        flow["phones"] = numbers
        flow["index"] = 0
        flow["collected"] = []
        gen_dir = await gen_dir_for(update)
        flow["gen_dir"] = gen_dir
        await update.message.reply_text(
            f"{banner('Step 3 / 3 — Sequential Login')}\n"
            f"Queued {len(numbers)} numbers. Processing in the order sent."
        )
        await zip_send_code_for_current(update, context)
        return

    if step == "zip_otp":
        await zip_handle_otp(update, context, text)
        return

    if step == "zip_2fa":
        await zip_handle_password(update, context, text)
        return


async def zip_send_code_for_current(update: Update, context: ContextTypes.DEFAULT_TYPE):
    flow = context.user_data["gen_flow"]
    i = flow["index"]
    phone = flow["phones"][i]
    api_id, api_hash = flow["api_id"], flow["api_hash"]
    file_path = os.path.join(flow["gen_dir"], safe_phone(phone))

    try:
        client = TelethonClient(file_path, api_id, api_hash)
        await client.connect()
        sent = await client.send_code_request(phone)
    except Exception as e:
        await update.message.reply_text(
            f"❌ {phone} — could not send code: {type(e).__name__}: {e}. Skipping."
        )
        await zip_advance(update, context)
        return

    flow["client"] = client
    flow["phone_code_hash"] = sent.phone_code_hash
    flow["step"] = "zip_otp"
    await update.message.reply_text(f"📩 [{i+1}/{len(flow['phones'])}] Code sent to {phone}. Enter it:")


async def zip_handle_otp(update: Update, context: ContextTypes.DEFAULT_TYPE, otp: str):
    flow = context.user_data["gen_flow"]
    client = flow["client"]
    phone = flow["phones"][flow["index"]]
    try:
        await client.sign_in(phone=phone, code=otp, phone_code_hash=flow["phone_code_hash"])
    except TelethonPasswordNeeded:
        flow["step"] = "zip_2fa"
        await update.message.reply_text(f"🔒 {phone} has 2-Step Verification. Send the password:")
        return
    except Exception as e:
        await update.message.reply_text(f"❌ {phone} — {type(e).__name__}: {e}. Skipping.")
        try:
            await client.disconnect()
        except Exception:
            pass
        await zip_advance(update, context)
        return
    await zip_finish_current(update, context)


async def zip_handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE, password: str):
    flow = context.user_data["gen_flow"]
    client = flow["client"]
    phone = flow["phones"][flow["index"]]
    try:
        await client.sign_in(password=password)
    except Exception as e:
        await update.message.reply_text(f"❌ {phone} — incorrect password / error: {type(e).__name__}: {e}. Skipping.")
        try:
            await client.disconnect()
        except Exception:
            pass
        await zip_advance(update, context)
        return
    await zip_finish_current(update, context)


async def zip_finish_current(update: Update, context: ContextTypes.DEFAULT_TYPE):
    flow = context.user_data["gen_flow"]
    client = flow["client"]
    phone = flow["phones"][flow["index"]]

    me = await client.get_me()
    label = getattr(me, "username", None) or getattr(me, "id", "unknown")
    client.session.save()
    await client.disconnect()

    file_path = os.path.join(flow["gen_dir"], safe_phone(phone) + ".session")
    flow["collected"].append({"phone": phone, "label": label, "file": file_path})
    await update.message.reply_text(f"✅ [{flow['index']+1}/{len(flow['phones'])}] {phone} — {label} done.")
    await zip_advance(update, context)


async def zip_advance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    flow = context.user_data["gen_flow"]
    flow.pop("client", None)
    flow.pop("phone_code_hash", None)
    flow["index"] += 1

    if flow["index"] < len(flow["phones"]):
        await zip_send_code_for_current(update, context)
        return

    # all done — bundle into a zip
    collected = flow["collected"]
    chat_id = update.effective_chat.id
    if not collected:
        await update.message.reply_text("⚠️ No sessions were generated.")
    else:
        zip_path = os.path.join(flow["gen_dir"], "sessions.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in collected:
                zf.write(item["file"], arcname=os.path.basename(item["file"]))
        await update.message.reply_text(
            f"{banner('Zip Ready')}\n{len(collected)} / {len(flow['phones'])} accounts generated."
        )
        await context.bot.send_document(
            chat_id, zip_path, caption=f"📦 {len(collected)} .session files — keep this private."
        )

    shutil.rmtree(os.path.join(WORK_DIR, str(chat_id)), ignore_errors=True)
    context.user_data.pop("gen_flow", None)


# ════════════════════════════════════════════════════════════════
#  TELEGRAM HANDLERS / MENUS
# ════════════════════════════════════════════════════════════════

EXPLAIN = {
    "destroyer": (
        "Send a session (zip / .session / .txt / pasted string).\n"
        "That exact session will be logged *out*. Every other session on "
        "that account stays signed in and untouched."
    ),
    "terminator": (
        "Send a session (zip / .session / .txt / pasted string).\n"
        "The bot logs *in* with it and terminates every *other* active "
        "session on that account — the one you sent stays alive. Useful "
        "for securing an ID instantly, no 24h wait."
    ),
    "generate": (
        "Create a brand-new session for an account you control. "
        "Choose an output shape below."
    ),
    "gen_string": "Produces only a copy-paste *string session* — Telethon or Pyrogram format.",
    "gen_file": "Produces a *.session* (sqlite) file for one account — asks for your own API_ID / API_HASH.",
    "gen_zip": "Produces *2 or more* .session files at once, bundled into a single .zip.",
}


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 Self Destroyer", callback_data="menu:destroyer")],
        [InlineKeyboardButton("🛡️ Terminator", callback_data="menu:terminator")],
        [InlineKeyboardButton("🆕 Generate Session", callback_data="menu:generate")],
    ])


def generate_submenu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 String Session", callback_data="gen:string")],
        [InlineKeyboardButton("📁 Session File", callback_data="gen:file")],
        [InlineKeyboardButton("📦 Zip Session", callback_data="gen:zip")],
    ])


def string_format_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔸 Telethon String", callback_data="genfmt:telethon")],
        [InlineKeyboardButton("🔹 Pyrogram String", callback_data="genfmt:pyrogram")],
    ])


START_FOOTER = (
    "\n\n_We do not store any of your data — everything stays in your control. "
    "Facing an issue? Contact the bot owner @izoph._"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        f"{banner('Session Control Center')}\n"
        "Pick a tool to begin:"
        f"{START_FOOTER}",
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown",
    )


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Cancelled. Send /start for the menu.")


async def on_menu_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":", 1)[1]
    context.user_data.clear()

    if choice in (MODE_DESTROYER, MODE_TERMINATOR):
        context.user_data["mode"] = choice
        title = "Self Destroyer" if choice == MODE_DESTROYER else "Terminator"
        await query.edit_message_text(
            f"{banner(title)}\n{EXPLAIN[choice]}\n\n"
            "Send a .zip, a .session file, a .txt (one string per line), "
            "or paste a string session as text.\n\nSend /start to change mode.",
            parse_mode="Markdown",
        )
        return

    # choice == "generate"
    await query.edit_message_text(
        f"{banner('Generate Session')}\n{EXPLAIN['generate']}",
        reply_markup=generate_submenu_keyboard(),
        parse_mode="Markdown",
    )


async def on_gen_kind_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kind = query.data.split(":", 1)[1]  # string | file | zip

    if kind == "string":
        context.user_data["gen_flow"] = {"kind": "string"}
        await query.edit_message_text(
            f"{banner('String Session')}\n{EXPLAIN['gen_string']}\n\nChoose a format:",
            reply_markup=string_format_keyboard(),
            parse_mode="Markdown",
        )
        return

    if kind == "file":
        context.user_data["gen_flow"] = {"kind": "file", "step": "api_id"}
        await query.edit_message_text(
            f"{banner('Session File')}\n{EXPLAIN['gen_file']}",
            parse_mode="Markdown",
        )
        await gen_ask_api_id(query.message.reply_text)
        return

    # kind == "zip"
    context.user_data["gen_flow"] = {"kind": "zip", "step": "api_id"}
    await query.edit_message_text(
        f"{banner('Zip Session')}\n{EXPLAIN['gen_zip']}",
        parse_mode="Markdown",
    )
    await gen_ask_api_id(query.message.reply_text)


async def on_string_format_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    fmt = query.data.split(":", 1)[1]
    flow = context.user_data.get("gen_flow")
    if not flow or flow.get("kind") != "string":
        await query.edit_message_text("Session expired. Send /start to begin again.")
        return
    flow["format"] = fmt
    flow["step"] = "api_id"
    await query.edit_message_text(f"Format: *{fmt.capitalize()}*", parse_mode="Markdown")
    await gen_ask_api_id(query.message.reply_text)


# ---------------- document / text dispatch ----------------

async def require_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "mode" not in context.user_data:
        await update.message.reply_text("Pick a tool first:", reply_markup=main_menu_keyboard())
        return None
    return context.user_data["mode"]


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "gen_flow" in context.user_data:
        await update.message.reply_text("Finish the current step with text, or /cancel to abort.")
        return

    mode = await require_mode(update, context)
    if not mode:
        return

    doc = update.message.document
    chat_id = update.effective_chat.id
    session_work_dir = os.path.join(WORK_DIR, str(chat_id))
    shutil.rmtree(session_work_dir, ignore_errors=True)
    os.makedirs(session_work_dir, exist_ok=True)

    fname = doc.file_name or "file"
    local_path = os.path.join(session_work_dir, fname)
    tg_file = await doc.get_file()
    await tg_file.download_to_drive(local_path)

    if fname.lower().endswith(".zip"):
        extract_dir = os.path.join(session_work_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        try:
            with zipfile.ZipFile(local_path, "r") as z:
                z.extractall(extract_dir)
        except zipfile.BadZipFile:
            await update.message.reply_text("❌ That file isn't a valid zip.")
            return
        session_files, string_entries = collect_targets(extract_dir)

    elif fname.lower().endswith(".session"):
        session_files = [(local_path[: -len(".session")], fname)]
        string_entries = []

    elif fname.lower().endswith(".txt"):
        session_files = []
        _, string_entries = collect_targets(session_work_dir)

    else:
        await update.message.reply_text(
            "Send a .zip, a .session file, or a .txt file with string session(s)."
        )
        return

    await process_and_report(update, mode, session_files, string_entries)
    shutil.rmtree(session_work_dir, ignore_errors=True)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    flow = context.user_data.get("gen_flow")
    if flow:
        if flow["kind"] == "zip":
            await handle_zip_gen_text(update, context)
        else:
            await handle_single_gen_text(update, context)
        return

    mode = await require_mode(update, context)
    if not mode:
        return

    text = update.message.text or ""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return
    string_entries = [(line, f"pasted line {i+1}") for i, line in enumerate(lines)]
    await process_and_report(update, mode, [], string_entries)


def main():
    os.makedirs(WORK_DIR, exist_ok=True)
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CallbackQueryHandler(on_menu_chosen, pattern=r"^menu:"))
    app.add_handler(CallbackQueryHandler(on_gen_kind_chosen, pattern=r"^gen:"))
    app.add_handler(CallbackQueryHandler(on_string_format_chosen, pattern=r"^genfmt:"))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    log.info("Session Control Center bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
