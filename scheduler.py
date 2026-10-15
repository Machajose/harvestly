"""scheduler.py - checks every grain batch and sends alerts without being asked.

Every few seconds (SCHEDULER_INTERVAL_SECONDS) it:
  1. reads the simulator settings from the database (day offset, forced humidity/rain),
  2. gets the weather,
  3. works out each batch's risk with risk.py and saves it,
  4. messages the farmer on Telegram if the risk got worse (or stays high past the cooldown).

Run it with:   python scheduler.py          (keeps running)
or just once:  python scheduler.py --once
"""
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

import db
import explain
import prompts
import risk
import weather

load_dotenv()
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("harvestly-scheduler")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
INTERVAL = int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "30"))
COOLDOWN_HOURS = float(os.getenv("ALERT_COOLDOWN_HOURS", "24"))
COUNTY = "Uasin Gishu"
# Re-check reminder: ask a farmer to re-test grain that was not fully dry, every N days (0 = never).
# For a quick demo set RECHECK_DAYS=0.001 in .env (about 90 seconds).
RECHECK_DAYS = float(os.getenv("RECHECK_DAYS", "3"))

_last_weather_saved = {}      # place key -> the day its weather row was last saved
_recheck_sent = {}            # batch id -> when this program last asked (a safety net)
_warned = set()               # problems already logged once, so the log is not spammed every cycle
_last_overrides = {"names": None}


def send_telegram(chat_id, text, rows=None):
    """Send a Telegram message, optionally with tap buttons (rows of (label, callback_data)).

    Raises RuntimeError when it cannot be delivered."""
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty")
    if not str(chat_id).lstrip("-").isdigit():
        raise RuntimeError("not a real Telegram chat id (demo farmer)")
    payload = {"chat_id": chat_id, "text": text}
    if rows:
        payload["reply_markup"] = {"inline_keyboard": [
            [{"text": label, "callback_data": data} for label, data in row] for row in rows]}
    resp = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                         json=payload, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"Telegram said {resp.status_code}: {resp.text[:150]}")


def should_alert(level, previous, last_alert_at):
    """Alert when the risk got worse; or when it is still high and the cooldown has passed."""
    if level not in ("medium", "high"):
        return False
    worse = risk.LEVEL_RANK[level] > risk.LEVEL_RANK.get(previous, -1)
    if worse:
        return True
    if level == "high":
        sent = db.parse_dt(last_alert_at)
        return sent is None or datetime.utcnow() - sent > timedelta(hours=COOLDOWN_HOURS)
    return False


def load_thresholds():
    """Use the team's editable numbers (risk_thresholds table). Falls back to the defaults in risk.py."""
    try:
        overridden, problem = risk.apply_thresholds(db.get_thresholds())
    except db.DBError as exc:
        overridden, problem = risk.apply_thresholds(None)[0], None
        if "thresholds-missing" not in _warned:
            _warned.add("thresholds-missing")
            log.warning("risk_thresholds table not available, using the defaults in risk.py "
                        "(run sql/features_upgrade.sql to add it): %s", str(exc)[:120])
    if problem and problem not in _warned:
        _warned.add(problem)
        log.warning("ignoring the risk_thresholds table, using defaults: %s", problem)
    if overridden != _last_overrides["names"]:
        _last_overrides["names"] = overridden
        log.info("thresholds changed from the defaults: %s", ", ".join(overridden) or "none")


def recheck_due(batch, now):
    """True when this batch's grain was not fully dry and nobody re-checked it for RECHECK_DAYS."""
    if RECHECK_DAYS <= 0:
        return False
    if risk.moisture_band(batch.get("moisture_pct"), batch.get("moisture_check")) == "safe":
        return False
    last = (db.parse_dt(batch.get("last_recheck_at")) or db.parse_dt(batch.get("created_at"))
            or _recheck_sent.get(batch["id"]))
    asked = _recheck_sent.get(batch["id"])
    if asked and (last is None or asked > last):
        last = asked
    return last is not None and now - last >= timedelta(days=RECHECK_DAYS)


def send_recheck(batch, farmer, lang, now):
    chat_id = farmer.get("telegram_chat_id")
    if not str(chat_id or "").lstrip("-").isdigit():
        return                                    # demo farmers are never messaged
    harvested = db.parse_date_str(batch.get("harvest_date"))
    text = prompts.recheck_text(lang, harvested.isoformat() if harvested else "")
    try:
        send_telegram(chat_id, text, prompts.recheck_rows(batch["id"], lang))
    except RuntimeError as exc:
        log.warning("re-check reminder NOT delivered to %s: %s", farmer.get("name"), exc)
    else:
        log.info("RE-CHECK reminder sent to %s (batch %s)", farmer.get("name"), batch["id"])
    _recheck_sent[batch["id"]] = now              # remember, so we never ask twice in one period
    try:
        db.mark_rechecked(batch["id"])
    except db.DBError as exc:
        if "recheck-column" not in _warned:
            _warned.add("recheck-column")
            log.warning("could not save last_recheck_at (run sql/features_upgrade.sql?): %s", str(exc)[:120])


def run_once():
    load_thresholds()
    sim = db.get_sim_settings()
    offset = int(sim.get("day_offset") or 0)
    today = date.today()
    now = datetime.utcnow()

    weather_by_place = {}

    def weather_for(place):
        """Weather for a sub-county (looked up once per cycle, however many batches use it)."""
        key = weather.place_key(place)
        if key not in weather_by_place:
            weather_by_place[key] = weather.effective_weather(sim, place)
            humidity_, rain_, temp_, w_ = weather_by_place[key]
            if _last_weather_saved.get(key) != today and w_.get("source") == "open-meteo":
                try:
                    db.save_weather(COUNTY if key == "default" else key.title(), today, w_["humidity"],
                                    w_["rain_mm"], w_["temp_c"])
                    _last_weather_saved[key] = today
                except db.DBError as exc:
                    log.warning("could not save weather row: %s", exc)
        return weather_by_place[key]

    humidity, rain, _, _ = weather_for(None)
    stamp = datetime.now(timezone(timedelta(hours=3))).strftime("%d %b %H:%M")
    farmers = {f["id"]: f for f in db.get_all_farmers()}   # one fetch instead of one per batch
    log.info("simulator: +%s days | Eldoret humidity %.0f%% | rain %.0f mm", offset, humidity, rain)

    for batch in db.get_batches():
        harvested = db.parse_date_str(batch.get("harvest_date"))
        if harvested is None:
            continue
        farmer_id = batch.get("farmer_id")
        if farmer_id not in farmers:
            farmers[farmer_id] = db.get_farmer(farmer_id) or {}
        farmer = farmers[farmer_id]
        lang = farmer.get("language") or "en"
        humidity, rain, temp_c, _ = weather_for(farmer.get("sub_county"))

        days = (today - harvested).days + offset
        a = risk.assess(batch.get("storage_type"), days, batch.get("moisture_check"),
                        batch.get("moisture_pct"), humidity, rain, temp_c,
                        batch.get("vision_flag"))
        reason_en = risk.reason_text(a, "en")
        previous = batch.get("risk_level")
        log.info("batch %s | %s | %s | %d days | %s (score %d)", batch["id"], farmer.get("name", "?"),
                 farmer.get("sub_county") or "-", days, a.level.upper(), a.score)

        if a.level != previous or reason_en[:380] != (batch.get("risk_reason") or ""):
            db.save_risk(batch["id"], a.level, reason_en)

        if should_alert(a.level, previous, batch.get("last_alert_at")):
            message = explain.final_message(a, lang, stamp)
            asked = message + "\n\n" + prompts.FEEDBACK_ASK[lang if lang in prompts.FEEDBACK_ASK else "en"]
            try:
                send_telegram(farmer.get("telegram_chat_id"), asked, prompts.feedback_rows(batch["id"], lang))
                log.info("ALERT sent to %s", farmer.get("name"))
                db.log_alert(batch["id"], a.level, message)
            except RuntimeError as exc:
                log.warning("alert NOT delivered to %s: %s", farmer.get("name"), exc)
                db.log_alert(batch["id"], a.level, f"[not delivered: {exc}] {message}")
            db.mark_alerted(batch["id"])
        elif recheck_due(batch, now):
            send_recheck(batch, farmer, lang, now)


def main():
    once = "--once" in sys.argv
    log.info("Harvestly scheduler started (every %s seconds). Press Ctrl+C to stop.", INTERVAL)
    while True:
        try:
            run_once()
        except db.DBError as exc:
            log.error("database problem: %s", exc)
        except Exception:  # keep running whatever happens
            log.exception("unexpected error")
        if once:
            break
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
