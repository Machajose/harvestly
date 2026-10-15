"""bot.py - the Harvestly Telegram bot.

A farmer chats with it to register a grain batch. It then saves the farmer and
batch in the Oracle database and replies with a first risk reading.
Run it with:  python bot.py
"""
import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (Application, CommandHandler, ContextTypes, ConversationHandler,
                          MessageHandler, filters)

import db
import risk
import weather

load_dotenv()
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("harvestly-bot")
# httpx logs every Telegram request URL, and that URL contains the bot token. Keep it out of the logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

LANG, HARVEST, STORAGE, MOISTURE, METER, BAGS, NOTES = range(7)
MAX_NOTE = 500   # characters kept (matches the farmer_notes column)

# ---------------------------------------------------------------------------
# Words the bot says (a Swahili speaker should check the Swahili)
# ---------------------------------------------------------------------------
TEXT = {
    "en": {
        "ask_date": "When did you harvest this maize?\nTap a button, or type a date like 2026-10-01, or the number of days ago (for example 5).",
        "bad_date": "I could not read that date. Try 2026-10-01, or a number of days ago like 5.",
        "ask_storage": "How is the maize stored right now?",
        "bad_choice": "Please tap one of the buttons.",
        "ask_moisture": "Take a kernel and bite it. What happens?",
        "ask_meter": "Type the moisture reading from the meter, for example 14.5",
        "bad_meter": "I could not read that. Type a number between 5 and 40, for example 14.5",
        "ask_bags": "How many bags (90 kg) do you have? Type a number.",
        "bad_bags": "Please type a whole number, for example 20.",
        "ask_notes": ("Last question. Is there anything else we should know about this maize or how you "
                      "store it? For example pests, a leaking roof, or how you dried it. "
                      "Type it, or tap Skip."),
        "skip": "Skip",
        "notes_saved": "Thank you, I have noted that.",
        "saved": "Thank you. Your maize is registered. Here is your first check:",
        "later": "I will message you if the risk changes. Send /status any time to see your batches.",
        "no_batches": "You have no maize registered yet. Send /start to add it.",
        "status_head": "Your maize batches:",
        "status_line": "Batch {n}: {storage}, {days} days stored, {level}",
        "cancel": "Cancelled. Send /start to begin again.",
        "today": "Today", "yesterday": "Yesterday",
        "storage": ["Open sacks", "Hermetic bags", "Crib or store"],
        "moisture": ["Cracks when bitten (dry)", "Dents, does not crack (unsure)",
                     "Soft or wet (damp)", "I have a meter reading"],
    },
    "sw": {
        "ask_date": "Ulivuna mahindi haya lini?\nBonyeza kitufe, au andika tarehe kama 2026-10-01, au idadi ya siku zilizopita (mfano 5).",
        "bad_date": "Sijaelewa tarehe hiyo. Jaribu 2026-10-01, au idadi ya siku zilizopita kama 5.",
        "ask_storage": "Mahindi yamehifadhiwa vipi sasa hivi?",
        "bad_choice": "Tafadhali bonyeza moja ya vitufe.",
        "ask_moisture": "Chukua punje moja na uiume. Inakuwaje?",
        "ask_meter": "Andika namba ya kipimo cha unyevu kutoka kwenye mita, mfano 14.5",
        "bad_meter": "Sijaelewa. Andika namba kati ya 5 na 40, mfano 14.5",
        "ask_bags": "Una magunia mangapi (kilo 90)? Andika namba.",
        "bad_bags": "Tafadhali andika namba kamili, mfano 20.",
        "ask_notes": ("Swali la mwisho. Je, kuna jambo lingine tunalopaswa kujua kuhusu mahindi haya au "
                      "jinsi unavyoyahifadhi? Mfano wadudu, paa linalovuja, au jinsi ulivyoyakausha. "
                      "Liandike, au bonyeza Ruka."),
        "skip": "Ruka",
        "notes_saved": "Asante, nimeliandika.",
        "saved": "Asante. Mahindi yako yamesajiliwa. Hii ndiyo ukaguzi wako wa kwanza:",
        "later": "Nitakutumia ujumbe hatari ikibadilika. Tuma /status wakati wowote kuona mahindi yako.",
        "no_batches": "Bado hujasajili mahindi. Tuma /start kuyaongeza.",
        "status_head": "Mahindi yako:",
        "status_line": "Kundi {n}: {storage}, siku {days}, {level}",
        "cancel": "Imeghairiwa. Tuma /start kuanza tena.",
        "today": "Leo", "yesterday": "Jana",
        "storage": ["Magunia ya wazi", "Mifuko ya hermetic", "Ghala la kienyeji"],
        "moisture": ["Inapasuka ikiumwa (kavu)", "Inabonyea, haipasuki (sina uhakika)",
                     "Laini au nyevu (unyevu)", "Nina kipimo cha mita"],
    },
}
STORAGE_CODES = ["open_sack", "hermetic_bag", "crib"]
MOISTURE_CODES = ["dry", "unsure", "damp", "meter"]


def t(lang, key):
    return TEXT.get(lang, TEXT["en"])[key]


def lookup(lang, key, text, codes):
    """Match the label the farmer tapped to its code."""
    labels = TEXT[lang][key]
    return codes[labels.index(text)] if text in labels else None


def keyboard(rows):
    return ReplyKeyboardMarkup(rows, one_time_keyboard=True, resize_keyboard=True)


def parse_harvest_date(text, lang):
    """today / yesterday / a number of days ago / YYYY-MM-DD / DD/MM/YYYY."""
    text = text.strip().lower()
    today = date.today()
    result = None
    if text in (TEXT[lang]["today"].lower(), "today", "leo"):
        result = today
    elif text in (TEXT[lang]["yesterday"].lower(), "yesterday", "jana"):
        result = today - timedelta(days=1)
    elif text.isdigit():
        result = today - timedelta(days=int(text))
    else:
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                result = datetime.strptime(text, fmt).date()
                break
            except ValueError:
                continue
    if result is None or result > today or (today - result).days > 400:
        return None
    return result


# ---------------------------------------------------------------------------
# Conversation steps
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "Karibu / Welcome to Harvestly.\nI warn you before your stored maize spoils.\n\n"
        "Choose your language / Chagua lugha:",
        reply_markup=keyboard([["English", "Kiswahili"]]))
    return LANG


async def got_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = "sw" if "swa" in update.message.text.lower() else "en"
    context.user_data["lang"] = lang
    await update.message.reply_text(
        t(lang, "ask_date"),
        reply_markup=keyboard([[t(lang, "today"), t(lang, "yesterday")]]))
    return HARVEST


async def got_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data["lang"]
    harvested = parse_harvest_date(update.message.text, lang)
    if harvested is None:
        await update.message.reply_text(t(lang, "bad_date"))
        return HARVEST
    context.user_data["harvest_date"] = harvested
    labels = t(lang, "storage")
    await update.message.reply_text(t(lang, "ask_storage"),
                                    reply_markup=keyboard([[x] for x in labels]))
    return STORAGE


async def got_storage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data["lang"]
    code = lookup(lang, "storage", update.message.text, STORAGE_CODES)
    if code is None:
        await update.message.reply_text(t(lang, "bad_choice"))
        return STORAGE
    context.user_data["storage_type"] = code
    await update.message.reply_text(
        t(lang, "ask_moisture"),
        reply_markup=keyboard([[x] for x in t(lang, "moisture")]))
    return MOISTURE


async def got_moisture(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data["lang"]
    code = lookup(lang, "moisture", update.message.text, MOISTURE_CODES)
    if code is None:
        await update.message.reply_text(t(lang, "bad_choice"))
        return MOISTURE
    if code == "meter":
        await update.message.reply_text(t(lang, "ask_meter"), reply_markup=ReplyKeyboardRemove())
        return METER
    context.user_data.update(moisture_check=code, moisture_pct=None, moisture_source="field_check")
    await update.message.reply_text(t(lang, "ask_bags"), reply_markup=ReplyKeyboardRemove())
    return BAGS


async def got_meter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data["lang"]
    try:
        value = float(update.message.text.replace(",", ".").strip())
        if not 5 <= value <= 40:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t(lang, "bad_meter"))
        return METER
    check = "damp" if value > risk.WET_MOISTURE else "unsure" if value > risk.SAFE_MOISTURE else "dry"
    context.user_data.update(moisture_check=check, moisture_pct=value, moisture_source="meter")
    await update.message.reply_text(t(lang, "ask_bags"))
    return BAGS


def register(chat_id, name, data):
    """Blocking work: save the farmer and batch, then compute the first risk."""
    lang = data["lang"]
    farmer = db.get_farmer_by_chat(chat_id)
    if farmer is None:
        farmer = db.create_farmer(chat_id, name, language=lang)
    elif farmer.get("language") != lang:
        db.set_farmer_language(farmer["id"], lang)
    fields = dict(moisture_pct=data.get("moisture_pct"), moisture_source=data["moisture_source"],
                  bags=data["bags"])
    notes = data.get("notes")
    try:
        batch = db.create_batch(farmer["id"], data["harvest_date"], data["storage_type"],
                                data["moisture_check"], notes=notes, **fields)
    except db.DBError:
        if not notes:
            raise
        # most likely the farmer_notes column does not exist yet (sql/notes_upgrade.sql not run)
        log.warning("could not save the note, saving the batch without it")
        batch = db.create_batch(farmer["id"], data["harvest_date"], data["storage_type"],
                                data["moisture_check"], **fields)
    sim = db.get_sim_settings()
    humidity, rain, temp_c, _ = weather.effective_weather(sim)
    days = (date.today() - data["harvest_date"]).days + int(sim.get("day_offset") or 0)
    a = risk.assess(data["storage_type"], days, data["moisture_check"], data.get("moisture_pct"),
                    humidity, rain, temp_c)
    db.save_risk(batch["id"], a.level, risk.reason_text(a, "en"))
    stamp = datetime.now(timezone(timedelta(hours=3))).strftime("%d %b %H:%M")
    return risk.build_message(a, lang, stamp)


async def got_bags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data["lang"]
    text = update.message.text.strip()
    if not text.isdigit() or not 0 < int(text) < 100000:
        await update.message.reply_text(t(lang, "bad_bags"))
        return BAGS
    context.user_data["bags"] = int(text)
    await update.message.reply_text(t(lang, "ask_notes"),
                                    reply_markup=keyboard([[t(lang, "skip")]]))
    return NOTES


async def got_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data["lang"]
    text = (update.message.text or "").strip()
    skipped = text.lower() in ("skip", "ruka", "")
    context.user_data["notes"] = None if skipped else text[:MAX_NOTE]
    if not skipped:
        await update.message.reply_text(t(lang, "notes_saved"), reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text("OK", reply_markup=ReplyKeyboardRemove())
    try:
        message = await asyncio.to_thread(
            register, str(update.effective_chat.id),
            update.effective_user.full_name if update.effective_user else "", context.user_data)
    except db.DBError as exc:
        log.error("database error: %s", exc)
        await update.message.reply_text("Sorry, I could not save that right now. Please try /start again in a minute.")
        return ConversationHandler.END
    await update.message.reply_text(t(lang, "saved"))
    await update.message.reply_text(message)
    await update.message.reply_text(t(lang, "later"))
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get("lang", "en")
    await update.message.reply_text(t(lang, "cancel"), reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# /status
# ---------------------------------------------------------------------------
def load_status(chat_id):
    farmer = db.get_farmer_by_chat(chat_id)
    if farmer is None:
        return "en", []
    return farmer.get("language") or "en", db.get_batches(farmer["id"])


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        lang, batches = await asyncio.to_thread(load_status, str(update.effective_chat.id))
    except db.DBError as exc:
        log.error("database error: %s", exc)
        await update.message.reply_text("Sorry, I could not reach the database right now.")
        return
    if not batches:
        await update.message.reply_text(t(lang, "no_batches"))
        return
    lines = [t(lang, "status_head")]
    for number, batch in enumerate(batches, start=1):
        harvested = db.parse_date_str(batch.get("harvest_date"))
        days = (date.today() - harvested).days if harvested else "?"
        level = risk.LABELS[lang].get(batch.get("risk_level") or "low", "")
        lines.append(t(lang, "status_line").format(
            n=number, storage=batch.get("storage_type") or "?", days=days, level=level))
    await update.message.reply_text("\n".join(lines))


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is empty. Paste your bot token into the .env file.")
    # Generous timeouts: on slow or filtered networks the default 5 seconds is too short.
    app = (Application.builder().token(token)
           .connect_timeout(30).read_timeout(30).write_timeout(30).pool_timeout(30)
           .get_updates_connect_timeout(30).get_updates_read_timeout(30)
           .build())
    text_only = filters.TEXT & ~filters.COMMAND
    conversation = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            LANG: [MessageHandler(text_only, got_language)],
            HARVEST: [MessageHandler(text_only, got_date)],
            STORAGE: [MessageHandler(text_only, got_storage)],
            MOISTURE: [MessageHandler(text_only, got_moisture)],
            METER: [MessageHandler(text_only, got_meter)],
            BAGS: [MessageHandler(text_only, got_bags)],
            NOTES: [MessageHandler(text_only, got_notes)],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
    )
    app.add_handler(conversation)
    app.add_handler(CommandHandler("status", status))
    log.info("Harvestly bot is running. Press Ctrl+C to stop.")
    app.run_polling(bootstrap_retries=-1)   # keep retrying until Telegram is reachable


if __name__ == "__main__":
    main()