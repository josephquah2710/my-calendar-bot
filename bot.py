import os
import logging
import sqlite3
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# ── Config ──────────────────────────────────────────────────────────────────
TOKEN         = os.environ.get("BOT_TOKEN")          # set in Railway env vars
YOUR_CHAT_ID  = int(os.environ.get("CHAT_ID", "0"))  # set in Railway env vars
REMINDER_TIME = os.environ.get("REMINDER_TIME", "21:00")  # 24h HH:MM, your timezone
DB_PATH       = "calendar.db"

logging.basicConfig(level=logging.INFO)

# ── Database ─────────────────────────────────────────────────────────────────
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_date  TEXT NOT NULL,   -- YYYY-MM-DD
            event_time  TEXT NOT NULL,   -- HH:MM
            description TEXT NOT NULL,
            recur       TEXT DEFAULT 'none'  -- none | daily | weekly | monthly
        )
    """)
    con.commit()
    con.close()

def add_event(date_str, time_str, desc, recur="none"):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT INTO events (event_date, event_time, description, recur) VALUES (?,?,?,?)",
        (date_str, time_str, desc, recur)
    )
    con.commit()
    con.close()

def get_events_for_date(date_str):
    con = sqlite3.connect(DB_PATH)
    # direct matches
    rows = con.execute(
        "SELECT id, event_time, description, recur FROM events WHERE event_date=? ORDER BY event_time",
        (date_str,)
    ).fetchall()

    # recurrent events
    target = datetime.strptime(date_str, "%Y-%m-%d")
    all_rows = con.execute(
        "SELECT id, event_date, event_time, description, recur FROM events WHERE recur != 'none'"
    ).fetchall()
    con.close()

    for r in all_rows:
        rid, rdate, rtime, rdesc, rrecur = r
        origin = datetime.strptime(rdate, "%Y-%m-%d")
        if origin >= target:
            continue
        match = False
        if rrecur == "daily":
            match = True
        elif rrecur == "weekly" and (target - origin).days % 7 == 0:
            match = True
        elif rrecur == "monthly" and origin.day == target.day:
            match = True
        if match:
            rows.append((rid, rtime, f"{rdesc} [🔁 {rrecur}]", rrecur))

    return sorted(rows, key=lambda x: x[1])

def delete_event(event_id):
    con = sqlite3.connect(DB_PATH)
    con.execute("DELETE FROM events WHERE id=?", (event_id,))
    con.commit()
    con.close()

# ── Helpers ───────────────────────────────────────────────────────────────────
def parse_input(text):
    """
    Accepts:  20MAR25 1430 Dentist appointment [daily|weekly|monthly]
    Returns:  (date_str, time_str, description, recur) or None
    """
    parts = text.strip().split()
    if len(parts) < 3:
        return None
    try:
        dt = datetime.strptime(parts[0].upper(), "%d%b%y")
        date_str = dt.strftime("%Y-%m-%d")
    except ValueError:
        return None
    try:
        t = datetime.strptime(parts[1], "%H%M")
        time_str = t.strftime("%H:%M")
    except ValueError:
        return None

    recur = "none"
    desc_parts = parts[2:]
    if desc_parts and desc_parts[-1].lower() in ("daily", "weekly", "monthly"):
        recur = desc_parts[-1].lower()
        desc_parts = desc_parts[:-1]
    description = " ".join(desc_parts)
    return date_str, time_str, description, recur

def format_events(rows, label):
    if not rows:
        return f"📭 No events for {label}."
    lines = [f"📅 *Events for {label}:*"]
    for row in rows:
        lines.append(f"  🕐 {row[1]} — {row[2]}  _(id:{row[0]})_")
    return "\n".join(lines)

# ── Handlers ──────────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 *Calendar Bot ready!*\n\n"
        "*Add an event:*\n"
        "`DDMMMYY HHMM Description [daily|weekly|monthly]`\n"
        "e.g. `20MAR25 1430 Dentist`\n"
        "e.g. `01APR25 0800 Stand-up weekly`\n\n"
        "*Commands:*\n"
        "/list `DDMMMYY` — events on a date\n"
        "/today — today's events\n"
        "/tomorrow — tomorrow's events\n"
        "/delete `<id>` — remove an event\n"
        "/help — show this message"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await start(update, ctx)

async def today_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    date_str = datetime.now().strftime("%Y-%m-%d")
    rows = get_events_for_date(date_str)
    label = datetime.now().strftime("%d %b %Y")
    await update.message.reply_text(format_events(rows, label), parse_mode="Markdown")

async def tomorrow_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tomorrow = datetime.now() + timedelta(days=1)
    date_str = tomorrow.strftime("%Y-%m-%d")
    rows = get_events_for_date(date_str)
    label = tomorrow.strftime("%d %b %Y")
    await update.message.reply_text(format_events(rows, label), parse_mode="Markdown")

async def list_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /list DDMMMYY  e.g. /list 20MAR25")
        return
    try:
        dt = datetime.strptime(ctx.args[0].upper(), "%d%b%y")
        date_str = dt.strftime("%Y-%m-%d")
        label = dt.strftime("%d %b %Y")
    except ValueError:
        await update.message.reply_text("❌ Bad date. Use format: 20MAR25")
        return
    rows = get_events_for_date(date_str)
    await update.message.reply_text(format_events(rows, label), parse_mode="Markdown")

async def delete_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("Usage: /delete <id>  — get the id from /list")
        return
    delete_event(int(ctx.args[0]))
    await update.message.reply_text(f"🗑️ Event {ctx.args[0]} deleted.")

async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    result = parse_input(text)
    if result is None:
        await update.message.reply_text(
            "❓ Couldn't parse that.\n"
            "Format: `DDMMMYY HHMM Description`\n"
            "e.g. `20MAR25 1430 Dentist`",
            parse_mode="Markdown"
        )
        return
    date_str, time_str, description, recur = result
    add_event(date_str, time_str, description, recur)
    recur_label = f" (repeats {recur})" if recur != "none" else ""
    await update.message.reply_text(
        f"✅ Saved: *{description}*{recur_label}\n"
        f"📅 {datetime.strptime(date_str,'%Y-%m-%d').strftime('%d %b %Y')} at {time_str}",
        parse_mode="Markdown"
    )

# ── Daily Reminder Job ────────────────────────────────────────────────────────
async def daily_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    tomorrow = datetime.now() + timedelta(days=1)
    date_str = tomorrow.strftime("%Y-%m-%d")
    rows = get_events_for_date(date_str)
    label = tomorrow.strftime("%d %b %Y")
    msg = "🌙 *Tomorrow's agenda:*\n\n" + format_events(rows, label)
    await ctx.bot.send_message(chat_id=YOUR_CHAT_ID, text=msg, parse_mode="Markdown")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    # parse reminder time
    h, m = map(int, REMINDER_TIME.split(":"))

    # schedule daily reminder
    app.job_queue.run_daily(
        daily_reminder,
        time=datetime.now().replace(hour=h, minute=m, second=0, microsecond=0).timetz()
    )

    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("help",     help_cmd))
    app.add_handler(CommandHandler("today",    today_cmd))
    app.add_handler(CommandHandler("tomorrow", tomorrow_cmd))
    app.add_handler(CommandHandler("list",     list_cmd))
    app.add_handler(CommandHandler("delete",   delete_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print("Bot running…")
    app.run_polling()

if __name__ == "__main__":
    main()
