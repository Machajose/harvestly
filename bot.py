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
from telegram import (BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup,
                      ReplyKeyboardRemove, Update)
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          ConversationHandler, MessageHandler, filters)

import db
import explain
import prompts
import risk
import weather

load_dotenv()
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("harvestly-bot")
# httpx logs every Telegram request URL, and that URL contains the bot token. Keep it out of the logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

LANG, HARVEST, STORAGE, MOISTURE, METER, BAGS, SUBCOUNTY, NOTES = range(8)
MAX_NOTE = 500   # characters kept (matches the farmer_notes column)
SUB_COUNTIES = ["Ainabkoi", "Kapseret", "Kesses", "Moiben", "Soy", "Turbo"]   # Uasin Gishu
MAX_SHOWN = 8    # /mybatches lists at most this many batches (Telegram messages are length-limited)
ICON = {"low": "\U0001F7E2", "medium": "\U0001F7E1", "high": "\U0001F534"}   # green, yellow, red

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
        "ask_subcounty": "Which sub-county are you in? I use the weather near you.",
        "other_place": "Another place",
        "ask_notes": ("Last question. Is there anything else we should know about this maize or how you "
                      "store it? For example pests, a leaking roof, or how you dried it. "
                      "Type it, or tap Skip."),
        "skip": "Skip",
        "notes_saved": "Thank you, I have noted that.",
        "saved": "Thank you. Your maize is registered. Here is your first check:",
        "later": "I will message you if the risk changes. Send /mybatches any time to see your batches.",
        "no_batches": "You have no maize registered yet. Send /start to add it.",
        "status_head": "Your maize batches:",
        "mybatch": ("{icon} Batch {n}: {storage}\n   Harvested {harvest} ({days} days ago), {bags} bags\n"
                    "   {level}: {why}"),
        "mybatches_more": "Send /start to add more maize.",
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
        "ask_subcounty": "Uko kaunti ndogo gani? Ninatumia hali ya hewa karibu nawe.",
        "other_place": "Mahali pengine",
        "ask_notes": ("Swali la mwisho. Je, kuna jambo lingine tunalopaswa kujua kuhusu mahindi haya au "
                      "jinsi unavyoyahifadhi? Mfano wadudu, paa linalovuja, au jinsi ulivyoyakausha. "
                      "Liandike, au bonyeza Ruka."),
        "skip": "Ruka",
        "notes_saved": "Asante, nimeliandika.",
        "saved": "Asante. Mahindi yako yamesajiliwa. Hii ndiyo ukaguzi wako wa kwanza:",
        "later": "Nitakutumia ujumbe hatari ikibadilika. Tuma /mybatches wakati wowote kuona mahindi yako.",
        "no_batches": "Bado hujasajili mahindi. Tuma /start kuyaongeza.",
        "status_head": "Mahindi yako:",
        "mybatch": ("{icon} Kundi {n}: {storage}\n   Lilivunwa {harvest} (siku {days} zilizopita), "
                    "magunia {bags}\n   {level}: {why}"),
        "mybatches_more": "Tuma /start kuongeza mahindi zaidi.",
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


def inline_keyboard(rows):
    """Rows of (label, callback_data) -> Telegram tap buttons under a message."""
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data) for label, data in row]
                                 for row in rows])


def prepare():
    """Blocking. Load the team's editable thresholds, and return the simulator settings."""
    try:
        risk.apply_thresholds(db.get_thresholds())
    except db.DBError:
        risk.apply_thresholds(None)       # table not created yet: use the defaults in risk.py
    return db.get_sim_settings()


def assess_batch(storage_type, harvest_date, moisture_check, moisture_pct, sub_county, sim,
                 vision_flag=None):
    """Blocking. Score one batch now, with the weather of the farmer's sub-county."""
    humidity, rain, temp_c, _ = weather.effective_weather(sim, sub_county)
    days = (date.today() - harvest_date).days + int(sim.get("day_offset") or 0)
    return risk.assess(storage_type, days, moisture_check, moisture_pct, humidity, rain, temp_c,
                       vision_flag)


def time_stamp():
    return datetime.now(timezone(timedelta(hours=3))).strftime("%d %b %H:%M")


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
    try:     # only ask the sub-county if we do not know it yet
        known = await asyncio.to_thread(db.get_farmer_by_chat, str(update.effective_chat.id))
    except db.DBError:
        known = None
    context.user_data["ask_subcounty"] = not (known and known.get("sub_county"))
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
    """Blocking work: save the farmer and batch, then compute the first risk.

    Returns (message, alert_batch_id). alert_batch_id is the batch id when this first check was also
    logged as a warning (medium or high), so the bot can add the "was this useful?" buttons."""
    lang = data["lang"]
    farmer = db.get_farmer_by_chat(chat_id)
    if farmer is None:
        farmer = db.create_farmer(chat_id, name, language=lang)
    elif farmer.get("language") != lang:
        db.set_farmer_language(farmer["id"], lang)
    sub_county = data.get("sub_county") or farmer.get("sub_county")
    if data.get("sub_county") and data["sub_county"] != farmer.get("sub_county"):
        try:
            db.set_farmer_sub_county(farmer["id"], data["sub_county"])
        except db.DBError as exc:
            log.warning("could not save the sub-county: %s", exc)
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
    sim = prepare()
    a = assess_batch(data["storage_type"], data["harvest_date"], data["moisture_check"],
                     data.get("moisture_pct"), sub_county, sim)
    db.save_risk(batch["id"], a.level, risk.reason_text(a, "en"))
    message = explain.final_message(a, lang, time_stamp())
    alert_batch = None
    if a.level in ("medium", "high"):
        # This first check already warns the farmer. Log it and mark the batch, so the
        # scheduler does not send the very same warning again a few seconds later.
        try:
            db.log_alert(batch["id"], a.level, message)
            db.mark_alerted(batch["id"])
            alert_batch = batch["id"]
        except db.DBError as exc:
            log.warning("could not log the first alert: %s", exc)
    return message, alert_batch


async def ask_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data["lang"]
    await update.message.reply_text(t(lang, "ask_notes"), reply_markup=keyboard([[t(lang, "skip")]]))
    return NOTES


async def got_bags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data["lang"]
    text = update.message.text.strip()
    if not text.isdigit() or not 0 < int(text) < 100000:
        await update.message.reply_text(t(lang, "bad_bags"))
        return BAGS
    context.user_data["bags"] = int(text)
    if context.user_data.get("ask_subcounty"):
        rows = [SUB_COUNTIES[i:i + 2] for i in range(0, len(SUB_COUNTIES), 2)] + [[t(lang, "other_place")]]
        await update.message.reply_text(t(lang, "ask_subcounty"), reply_markup=keyboard(rows))
        return SUBCOUNTY
    return await ask_notes(update, context)


async def got_subcounty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data["lang"]
    text = update.message.text.strip()
    match = next((name for name in SUB_COUNTIES if name.lower() == text.lower()), None)
    if match is None and text != t(lang, "other_place"):
        await update.message.reply_text(t(lang, "bad_choice"))
        return SUBCOUNTY
    context.user_data["sub_county"] = match      # None = "another place": Eldoret weather is used
    return await ask_notes(update, context)


async def reply_with_feedback(chat, lang, text, alert_batch):
    """Send `text`; when it was a logged warning, add the 'was this useful?' buttons under it."""
    if alert_batch:
        ask = prompts.FEEDBACK_ASK[lang if lang in prompts.FEEDBACK_ASK else "en"]
        await chat.send_message(text + "\n\n" + ask,
                                reply_markup=inline_keyboard(prompts.feedback_rows(alert_batch, lang)))
    else:
        await chat.send_message(text)


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
        message, alert_batch = await asyncio.to_thread(
            register, str(update.effective_chat.id),
            update.effective_user.full_name if update.effective_user else "", context.user_data)
    except db.DBError as exc:
        log.error("database error: %s", exc)
        await update.message.reply_text("Sorry, I could not save that right now. Please try /start again in a minute.")
        return ConversationHandler.END
    await update.message.reply_text(t(lang, "saved"))
    await reply_with_feedback(update.effective_chat, lang, message, alert_batch)
    await update.message.reply_text(t(lang, "later"))
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get("lang", "en")
    await update.message.reply_text(t(lang, "cancel"), reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# /mybatches  (and /status, the same thing)
# ---------------------------------------------------------------------------
def load_mybatches(chat_id):
    """Blocking. Returns (language, [dict per batch]) with a fresh risk reading for each batch."""
    farmer = db.get_farmer_by_chat(chat_id)
    if farmer is None:
        return "en", []
    lang = farmer.get("language") or "en"
    batches = sorted(db.get_batches(farmer["id"]), key=lambda b: b.get("id") or 0)
    if not batches:
        return lang, []
    sim = prepare()
    total = len(batches)
    shown = batches[-MAX_SHOWN:]
    items = []
    for number, batch in enumerate(shown, start=total - len(shown) + 1):
        harvested = db.parse_date_str(batch.get("harvest_date"))
        if harvested is None:
            continue
        a = assess_batch(batch.get("storage_type"), harvested, batch.get("moisture_check"),
                         batch.get("moisture_pct"), farmer.get("sub_county"), sim, batch.get("vision_flag"))
        items.append({"n": number, "storage_type": batch.get("storage_type"), "harvest": harvested,
                      "days": (date.today() - harvested).days, "bags": batch.get("bags"), "a": a})
    return lang, items


async def mybatches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        lang, items = await asyncio.to_thread(load_mybatches, str(update.effective_chat.id))
    except db.DBError as exc:
        log.error("database error: %s", exc)
        await update.message.reply_text("Sorry, I could not reach the database right now.")
        return
    if not items:
        await update.message.reply_text(t(lang, "no_batches"))
        return
    storage_labels = dict(zip(STORAGE_CODES, t(lang, "storage")))
    blocks = [t(lang, "status_head")]
    for item in items:
        a = item["a"]
        blocks.append(t(lang, "mybatch").format(
            icon=ICON[a.level], n=item["n"], storage=storage_labels.get(item["storage_type"], "?"),
            harvest=item["harvest"].isoformat(), days=item["days"],
            bags=item["bags"] if item["bags"] is not None else "?",
            level=risk.LABELS[lang][a.level], why=risk.reason_text(a, lang)))
    blocks.append(t(lang, "mybatches_more"))
    await update.message.reply_text("\n\n".join(blocks))


# ---------------------------------------------------------------------------
# Button taps: "was this warning useful?" (fb) and the moisture re-check (mc)
# ---------------------------------------------------------------------------
def own_batch(chat_id, batch_id):
    """Blocking. (farmer, batch) if this batch belongs to the person who tapped, else (farmer, None)."""
    farmer = db.get_farmer_by_chat(chat_id)
    batch = db.get("batches", batch_id) if farmer else None
    if batch is not None and batch.get("farmer_id") != farmer["id"]:
        batch = None
    return farmer, batch


def handle_feedback(chat_id, batch_id, code):
    """Blocking. Returns (language, [(text, alert_batch_or_None)])."""
    farmer, batch = own_batch(chat_id, batch_id)
    lang = (farmer or {}).get("language") or "en"
    if batch is None or code not in prompts.FEEDBACK_VALUE:
        return lang, []
    db.save_alert_feedback(batch_id, prompts.FEEDBACK_VALUE[code])
    return lang, [(prompts.FEEDBACK_THANKS[lang if lang in prompts.FEEDBACK_THANKS else "en"], None)]


def handle_recheck(chat_id, batch_id, code):
    """Blocking. Store the farmer's new moisture answer, re-score the batch, return the reply."""
    farmer, batch = own_batch(chat_id, batch_id)
    lang = (farmer or {}).get("language") or "en"
    if batch is None or code not in prompts.RECHECK_VALUE:
        return lang, []
    db.apply_recheck(batch_id, prompts.RECHECK_VALUE[code])
    batch = db.get("batches", batch_id) or batch
    harvested = db.parse_date_str(batch.get("harvest_date"))
    if harvested is None:
        return lang, []
    sim = prepare()
    a = assess_batch(batch.get("storage_type"), harvested, batch.get("moisture_check"),
                     batch.get("moisture_pct"), farmer.get("sub_county"), sim, batch.get("vision_flag"))
    db.save_risk(batch_id, a.level, risk.reason_text(a, "en"))
    message = explain.final_message(a, lang, time_stamp())
    alert_batch = None
    if a.level in ("medium", "high"):
        try:
            db.log_alert(batch_id, a.level, message)
            db.mark_alerted(batch_id)
            alert_batch = batch_id
        except db.DBError as exc:
            log.warning("could not log the re-check alert: %s", exc)
    return lang, [(prompts.RECHECK_THANKS[lang if lang in prompts.RECHECK_THANKS else "en"], None),
                  (message, alert_batch)]


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        kind, batch_text, code = (query.data or "").split(":")
        batch_id = int(batch_text)
    except ValueError:
        await query.answer()
        return
    chat = update.effective_chat
    work = handle_feedback if kind == "fb" else handle_recheck
    try:
        lang, replies = await asyncio.to_thread(work, str(chat.id), batch_id, code)
    except db.DBError as exc:
        log.error("database error on button %s: %s", kind, exc)
        await query.answer("Sorry, please try again in a minute.", show_alert=True)
        return
    await query.answer()
    if not replies:
        return
    try:                       # remove the buttons so one question is answered once
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001 - an old message can no longer be edited; that is fine
        pass
    for text, alert_batch in replies:
        await reply_with_feedback(chat, lang, text, alert_batch)


async def post_init(app):
    """Fill the Telegram command menu (the button next to the typing box)."""
    try:
        await app.bot.set_my_commands([
            BotCommand("start", "Register maize / Sajili mahindi"),
            BotCommand("mybatches", "My maize and its risk / Mahindi yangu"),
            BotCommand("cancel", "Cancel / Ghairi"),
        ])
    except Exception as exc:  # noqa: BLE001 - the menu is a nicety, never a reason to stop
        log.warning("could not set the command menu: %s", exc)


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is empty. Paste your bot token into the .env file.")
    # Generous timeouts: on slow or filtered networks the default 5 seconds is too short.
    app = (Application.builder().token(token)
           .connect_timeout(30).read_timeout(30).write_timeout(30).pool_timeout(30)
           .get_updates_connect_timeout(30).get_updates_read_timeout(30)
           .post_init(post_init)
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
            SUBCOUNTY: [MessageHandler(text_only, got_subcounty)],
            NOTES: [MessageHandler(text_only, got_notes)],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
    )
    app.add_handler(conversation)
    app.add_handler(CommandHandler(["mybatches", "status"], mybatches))
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^(fb|mc):\d+:[a-z]$"))
    log.info("Harvestly bot is running. Press Ctrl+C to stop.")
    app.run_polling(bootstrap_retries=-1)   # keep retrying until Telegram is reachable


if __name__ == "__main__":
    main()
