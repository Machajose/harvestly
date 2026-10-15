# Harvestly

Proactive post-harvest advisory for Kenyan maize farmers (pilot: maize, Uasin Gishu County).
A Telegram bot registers a grain batch, an Oracle Autonomous Database stores it, a scheduler
works out spoilage risk from moisture, storage, time and weather, and warns the farmer
before the grain is lost. An Oracle APEX app is the admin and demo dashboard.

## Quick start
    python -m venv .venv
    .venv\Scripts\activate          (Mac/Linux: source .venv/bin/activate)
    pip install -r requirements.txt
    copy .env.example .env          (Mac/Linux: cp .env.example .env)   then edit .env
    python test_risk.py             # risk rules self-test
    python check_db.py              # database connection self-test
    python bot.py                   # run the Telegram bot
    python scheduler.py             # run the alert scheduler (second terminal)

## Files
- risk.py      the risk rules (all thresholds in one place)
- db.py        all database access, through the REST (ORDS) address
- weather.py   Open-Meteo weather with a backup copy
- bot.py       Telegram registration bot (English and Swahili)
- scheduler.py checks every batch and sends alerts
- deploy/      files for running on the Oracle Cloud VM
- sql/         table scripts

## Stack
Oracle Autonomous Database + ORDS REST + APEX, Oracle Cloud VM, Telegram Bot API, Open-Meteo.
