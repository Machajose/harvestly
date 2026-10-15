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
import risk
import weather

load_dotenv()
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("harvestly-scheduler")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
INTERVAL = int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "30"))
COOLDOWN_HOURS = float(os.getenv("ALERT_COOLDOWN_HOURS", "24"))
COUNTY = "Uasin Gishu"

_last_weather_saved = {"day": None}


def send_telegram(chat_id, text):
    """Send a Telegram message. Raises RuntimeError when it cannot be delivered."""
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty")
    if not str(chat_id).lstrip("-").isdigit():
        raise RuntimeError("not a real Telegram chat id (demo farmer)")
    resp = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                         json={"chat_id": chat_id, "text": text}, timeout=15)
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


def run_once():
    sim = db.get_sim_settings()
    offset = int(sim.get("day_offset") or 0)
    humidity, rain, temp_c, w = weather.effective_weather(sim)
    today = date.today()

    if _last_weather_saved["day"] != today and w.get("source") == "open-meteo":
        try:
            db.save_weather(COUNTY, today, w["humidity"], w["rain_mm"], w["temp_c"])
            _last_weather_saved["day"] = today
        except db.DBError as exc:
            log.warning("could not save weather row: %s", exc)

    stamp = datetime.now(timezone(timedelta(hours=3))).strftime("%d %b %H:%M")
    farmers = {}
    log.info("simulator: +%s days | humidity %.0f%% | rain %.0f mm", offset, humidity, rain)

    for batch in db.get_batches():
        harvested = db.parse_date_str(batch.get("harvest_date"))
        if harvested is None:
            continue
        farmer_id = batch.get("farmer_id")
        if farmer_id not in farmers:
            farmers[farmer_id] = db.get_farmer(farmer_id) or {}
        farmer = farmers[farmer_id]
        lang = farmer.get("language") or "en"

        days = (today - harvested).days + offset
        a = risk.assess(batch.get("storage_type"), days, batch.get("moisture_check"),
                        batch.get("moisture_pct"), humidity, rain, temp_c,
                        batch.get("vision_flag"))
        reason_en = risk.reason_text(a, "en")
        previous = batch.get("risk_level")
        log.info("batch %s | %s | %d days | %s (score %d)", batch["id"], farmer.get("name", "?"),
                 days, a.level.upper(), a.score)

        if a.level != previous or reason_en[:380] != (batch.get("risk_reason") or ""):
            db.save_risk(batch["id"], a.level, reason_en)

        if should_alert(a.level, previous, batch.get("last_alert_at")):
            message = risk.build_message(a, lang, stamp)
            try:
                send_telegram(farmer.get("telegram_chat_id"), message)
                log.info("ALERT sent to %s", farmer.get("name"))
                db.log_alert(batch["id"], a.level, message)
            except RuntimeError as exc:
                log.warning("alert NOT delivered to %s: %s", farmer.get("name"), exc)
                db.log_alert(batch["id"], a.level, f"[not delivered: {exc}] {message}")
            db.mark_alerted(batch["id"])


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
