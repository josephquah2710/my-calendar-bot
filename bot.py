import os
import logging
from datetime import datetime, timedelta, time as dtime
import psycopg
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# ── Config ────────────────────────────────────────────────────────────────────
TOKEN         = os.environ.get("BOT_TOKEN", "")
YOUR_CHAT_ID  = os.environ.get("CHAT_ID", "")
REMINDER_TIME = os.environ.get("REMINDER_TIME", "21:00")
DATABASE_URL  = os.environ.get("DATABASE_URL", "")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Database ──────────────────────────────────────────────────────────────────
def get_con():
    return psycopg.connect(DATABASE_URL)

def init_db():
    with get_con() as con:
        with con.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id          SERIAL PRIMARY KEY,
                    event_date  TEXT NOT NULL,
                    event_time  TEXT NOT NULL,
                    description TEXT NOT NULL,
                    recur       TEXT DEFAULT 'none'
                )
            """)
        con.commit()
    logger.info("Database initialised")

def add_event(date_str, time_str, desc, recur="none"):
    with get_con() as con:
        with con.cursor() as cur:
            cur.execute(
                "INSERT INTO events (event_date, event_time, description, recur) VALUES (%s,%s,%s,%s)",
                (date_str, time_str, desc, recur)
            )
        con.commit()

def get_events_for_date(date_str):
    with get_con() as con:
        with con.cursor() as cur:
            cur.execute(
                "SELECT id, event_time, description, recur FROM events WHERE event_date=%s ORDER BY event_time",
                (date_str,)
            )
            rows = list(cur.fetchall())
            cur.execute(
                "SELECT id, event_date, event_time, description, recur FROM events WHERE recur != 'none'"
            )
            recur_rows = cur.fetchall()

    target = datetime.strptime(date_str, "%Y-%m-%d")
    for r in recur_rows:
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
    with get_con() as con:
        with con.cursor() as cur:
            cur.execute("DELETE FROM events WHERE id=%s", (event_id,))
        con.commit()

# ── Helpers ───────────────────────────────────────────────────────────────────
def parse_input(text):
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
    if not desc_parts:
        return None
    return date_str, time_str, " ".join(desc_parts), recur

def format_events(rows, label):
    if not rows:
        return f"📭 No events for {label}."
    lines = [f"📅 *Events for {label}:*"]
    for row in rows:
        lines.append(f"  🕐 `{row[1]}` — {row[2]}  _(id:{row[0]})_")
    return "\n".join(lines)

# ── Command Handlers ──────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 *Calendar Bot ready!*\n\n"
        "*Add an event:*\n"
        "`DDMMMYY HHMM Description`\n"
        "e.g. `20MAR25 1430 Dentist`\n\n"
        "*Recurring — add at the end:*\n"
        "`20MAR25 0800 Stand-up weekly`\n"
        "`01JAN25 1200 Lunch monthly`\n"
        "`01JAN25 0700 Morning run daily`\n\n"
        "*Commands:*\n"
        "/today — today's events\n"
        "/tomorrow — tomorrow's events\n"
        "/list DDMMMYY — events on a date\n"
        "/delete id — remove an event\n"
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
        await update.message.reply_text("Usage: /list DDMMMYY\ne.g. /list 20MAR25")
        return
    try:
        dt = datetime.strptime(ctx.args[0].upper(), "%d%b%y")
        date_str = dt.strftime("%Y-%m-%d")
        label = dt.strftime("%d %b %Y")
    except ValueError:
        await update.message.reply_text("Bad date format. Use: /list 20MAR25")
        return
    rows = get_events_for_date(date_str)
    await update.message.reply_text(format_events(rows, label), parse_mode="Markdown")

async def delete_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("Usage: /delete <id>\nGet the id number from /list or /today")
        return
    delete_event(int(ctx.args[0]))
    await update.message.reply_text(f"🗑️ Event {ctx.args[0]} deleted.")

async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    result = parse_input(text)
    if result is None:
        await update.message.reply_text(
            "Couldn't understand that.\n\n"
            "Format: `DDMMMYY HHMM Description`\n"
            "e.g. `20MAR25 1430 Dentist`\n\n"
            "For recurring: add `daily` `weekly` or `monthly` at the end.",
            parse_mode="Markdown"
        )
        return
    date_str, time_str, description, recur = result
    add_event(date_str, time_str, description, recur)
    recur_label = f"\n🔁 Repeats *{recur}*" if recur != "none" else ""
    friendly_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d %b %Y")
    await update.message.reply_text(
        f"✅ *{description}* saved!\n"
        f"📅 {friendly_date} at {time_str}{recur_label}",
        parse_mode="Markdown"
    )

# ── Daily Reminder ────────────────────────────────────────────────────────────
async def daily_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    if not YOUR_CHAT_ID:
        logger.warning("CHAT_ID not set, skipping reminder")
        return
    tomorrow = datetime.now() + timedelta(days=1)
    date_str = tomorrow.strftime("%Y-%m-%d")
    rows = get_events_for_date(date_str)
    label = tomorrow.strftime("%d %b %Y")
    msg = "🌙 *Tomorrow's agenda:*\n\n" + format_events(rows, label)
    try:
        await ctx.bot.send_message(chat_id=int(YOUR_CHAT_ID), text=msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to send reminder: {e}")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set!")
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable not set!")

    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    try:
        h, m = map(int, REMINDER_TIME.split(":"))
        reminder_time = dtime(hour=h, minute=m, second=0)
        app.job_queue.run_daily(daily_reminder, time=reminder_time)
        logger.info("Daily reminder scheduled at %s", REMINDER_TIME)
    except Exception as e:
        logger.warning("Could not schedule daily reminder: %s", e)

    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("help",     help_cmd))
    app.add_handler(CommandHandler("today",    today_cmd))
    app.add_handler(CommandHandler("tomorrow", tomorrow_cmd))
    app.add_handler(CommandHandler("list",     list_cmd))
    app.add_handler(CommandHandler("delete",   delete_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("Bot polling started")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
