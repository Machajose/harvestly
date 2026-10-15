# Harvestly

**A proactive post-harvest spoilage advisory for Kenyan maize farmers.**
Pilot: maize only, Uasin Gishu County (Eldoret). Built for the Green Tech Strathmore Hackathon on Oracle Cloud.

Farmers lose a large share of their harvest after it is cut, mostly to mould (including aflatoxin), weevils and
moisture, and they usually find out when it is already too late. Harvestly watches each farmer's stored grain and
**messages the farmer first, when the risk gets worse**, with one clear action to take. The farmer needs only
Telegram. No app to install, no website to open, no data bundle for anything but chat.

---

## Contents
1. [How it works (the short version)](#1-how-it-works-the-short-version)
2. [The theory: why these risk rules](#2-the-theory-why-these-risk-rules)
3. [The data: farmers, batches, alerts](#3-the-data-farmers-batches-alerts)
4. [The pieces and how they talk to each other](#4-the-pieces-and-how-they-talk-to-each-other)
5. [The risk score, step by step](#5-the-risk-score-step-by-step)
6. [The scheduler loop](#6-the-scheduler-loop)
7. [The demo simulator](#7-the-demo-simulator)
8. [The APEX admin dashboard](#8-the-apex-admin-dashboard)
9. [Run it on your laptop](#9-run-it-on-your-laptop)
10. [Run it on the Oracle VM](#10-run-it-on-the-oracle-vm)
11. [Set up the database from scratch](#11-set-up-the-database-from-scratch)
12. [Backup and failover plan](#12-backup-and-failover-plan)
13. [Files in this repo](#13-files-in-this-repo)
14. [Assumptions and limits (please read)](#14-assumptions-and-limits-please-read)
15. [Team rules: secrets and Git](#15-team-rules-secrets-and-git)

---

## 1. How it works (the short version)

```
 Farmer ──Telegram──►  bot.py  ──REST──►  Oracle Autonomous Database  ◄──REST──  scheduler.py
   ▲                  (registers                (farmers, batches,                 (every 30 s:
   │                   a batch)                  alerts, weather,                   score every batch,
   │                                             simulator settings)                alert if worse)
   │                                                   ▲                                │
   └──────────────── alert message ◄───────────────────┼────────────────────────────────┘
                                                       │
                                            Oracle APEX admin app
                                         (dashboard, reports, simulator)
```

1. **Register.** The farmer chats with the Telegram bot in English or Swahili. It asks the harvest date, how
   the grain is stored, how dry it is, how many bags, and an optional free-text note.
2. **Store.** The answers are saved as one *batch* in the Oracle database.
3. **First check.** The bot scores the batch immediately and replies with the risk level, the reason, and one action.
4. **Watch.** A scheduler re-scores every batch every 30 seconds using the stored answers, days in storage, and
   the latest weather for Eldoret.
5. **Warn.** When a batch's risk gets **worse** (low to medium, medium to high), the farmer gets a Telegram
   message. A batch that simply stays high is repeated only after a 24-hour cooldown, so the farmer is never spammed.
6. **Review.** Admins (the team, mentors, an extension officer) see everything in an Oracle APEX dashboard.

The key idea: **the farmer does not have to ask.** The system comes to the farmer.

## 2. The theory: why these risk rules

Stored maize spoils for a few well-known reasons. Each one is turned into points in `risk.py`.

| Factor | Why it matters | In the score |
|---|---|---|
| **Grain moisture** | The most important factor. Maize is considered safe to store at about 13.5% moisture or less. Above about 20% it is too wet and mould grows quickly. | wet +6, borderline +3 |
| **Storage type** | Open sacks let in humid air and pests; a crib or store is better; **hermetic (airtight) bags** are a sealed environment. | open sack +2, crib +1, hermetic bag 0 |
| **Air humidity** | Dry grain re-absorbs moisture from humid air, which restarts the mould risk. | 70% or more +2, 80% or more +3 |
| **Heavy rain** | Rain wets sacks, leaks in through roofs, and raises humidity. | 30 mm or more in 7 days +1 |
| **Time in storage** | The longer grain sits in non-airtight storage, the more chances for damp, mould and pests. | over 30 days +1, over 60 days +2 |
| **Aflatoxin conditions** | Aflatoxin is a toxic mould by-product. It is a *food-safety* hazard, not just a loss. It grows when grain is not fully dry **and** the weather is warm **and** humid. | +3 |
| **Photo check** (planned) | Visible mould or discolouration. A photo can only *raise* the risk, never lower it. | suspect +3, spoiled sets HIGH |

**Why hermetic bags are special:** they are airtight, so outside humidity, rain and storage time stop
mattering. The code skips those three factors for hermetic bags. Moisture and aflatoxin still count, because
grain that goes into a sealed bag wet is still a problem.

**Levels:** score 6 or more is **HIGH**, 3 to 5 is **MEDIUM**, below 3 is **LOW**.

**One action per alert.** Every message ends with one concrete thing to do (dry it again, move it to hermetic bags,
check it this week), plus the source of the data and the time it was checked, so the farmer can trust it.

## 3. The data: farmers, batches, alerts

Three main tables. They are linked like this:

```
 farmers (1) ──< batches (many) ──< alerts (many)
```

- **farmers**: one row per person. Holds their Telegram chat id, name, language, county, sub-county.
  *One farmer can have many batches.*
- **batches**: one row per lot of harvested grain a farmer registers. **A batch is the unit we watch.** It holds the
  harvest date, storage type, moisture, bags, the farmer's free-text note, and the *latest* risk level and
  reason, plus when the last alert was sent.
- **alerts**: one row for every warning actually sent, with the message text and time. This is the history.

Two helper tables: **weather_cache** (daily weather the scheduler saved) and **sim_settings** (one row of
demo controls, see section 7).

Where do hermetic bags come in? They are one of the answers to "how is it stored?" on a batch
(`storage_type = hermetic_bag`). They change the scoring (section 2) and they are what the bot recommends when
storage is the problem.

## 4. The pieces and how they talk to each other

| Piece | What it is | What it does |
|---|---|---|
| **Telegram bot** (`bot.py`) | Python, `python-telegram-bot` | The farmer's only interface. English and Swahili. Registers batches. |
| **Scheduler** (`scheduler.py`) | Python loop | Re-scores all batches, sends alerts. |
| **Risk engine** (`risk.py`) | Plain Python, no internet | All the rules and thresholds. One file, used by both of the above. |
| **Weather** (`weather.py`) | Open-Meteo (free, no key) | Humidity, rain, temperature for Eldoret, with a backup JSON if the API is down. |
| **Database** | Oracle Autonomous Database | Stores everything. |
| **ORDS REST** | Oracle REST Data Services (AutoREST) | Exposes the tables as web addresses, so Python needs **no wallet, driver or password**, only plain web requests (`db.py`). |
| **APEX admin app** | Oracle APEX | Dashboard, reports and the demo simulator. |
| **Oracle Cloud VM** | Compute instance | Runs the bot and scheduler 24/7 as `systemd` services, so they keep running when a laptop is off. |

Because `db.py` is the only file that touches the database, and it uses just one address (`DB_BASE_URL`), the
database can be swapped for another one without changing any code (see section 12).

## 5. The risk score, step by step

Example: a farmer has maize in **open sacks**, grain they **think is damp**, stored **40 days**, and the weather
is **82% humidity**, 10 mm rain, 27 C.

| Step | Points |
|---|---|
| Damp grain counts as "wet" | +6 |
| Open sacks | +2 |
| Humidity 80% or more | +3 |
| Rain 10 mm (below 30) | +0 |
| 40 days stored (over 30) | +1 |
| Not dry and 82% humid and 27 C: aflatoxin conditions | +3 |
| **Total** | **15, which is HIGH** |

Run `python test_risk.py` to see this kind of case checked automatically. All numbers live at the top of `risk.py`.

## 6. The scheduler loop

Every `SCHEDULER_INTERVAL_SECONDS` (30 for the demo; a real deployment would be hourly or daily):

1. Read the simulator row from the database.
2. Get the weather (or the forced values from the simulator).
3. For every batch: compute days stored, call `risk.assess(...)`, save `risk_level` and `risk_reason`.
4. **Alert rule:** send a message if the level is MEDIUM or HIGH **and** it is higher than before. If it is still HIGH,
   repeat only after the cooldown (`ALERT_COOLDOWN_HOURS`, default 24).
5. Save the alert in the `alerts` table and stamp `last_alert_at`.

Demo farmers (seed data with fake ids) are scored and logged but are **never** messaged on Telegram.
The bot also logs the first HIGH or MEDIUM result itself, so the scheduler does not repeat the same alert seconds later.

## 7. The demo simulator

Real grain takes weeks to spoil, so the demo cannot wait. The APEX app has a simulator that edits the one
row in `sim_settings`:

| Setting | Effect |
|---|---|
| `day_offset` | Pretends N extra days have passed in storage. |
| `force_humidity` | Overrides the humidity (for example 85). |
| `force_rain_mm` | Overrides 7-day rain (for example 35). |

**Demo recipe:** register a batch, then set humidity to 85 and rain to 35 and watch the next alert arrive within
30 seconds. (Rain of 20 only reaches MEDIUM, because heavy rain starts at 30 mm.) **Set the values back to empty
afterwards** so real weather is used.

## 8. The APEX admin dashboard

An Oracle APEX app ("Harvestly Admin") for the team and mentors, built on the same database:
- **Overview**: totals and risk counts.
- **Charts**: batches by risk level, risk by sub-county, alerts per day.
- **Reports**: batches, farmers, alerts, and **Farmer Notes** (the free-text remarks farmers add, which can
  show factors we did not think to ask about).
- **Simulator**: edit `sim_settings`.

The queries are in `sql/apex_queries.sql`. The exported app is `sql/harvestly_admin_app.sql`.
**Re-export it after every change** (App Builder, then Export) and commit it, so it can always be re-imported.

> Tip: the "Top Apps" list on the APEX workspace home page is a usage report, not a list of your apps.
> If it looks empty, open **App Builder > Applications** to see the real list.

## 9. Run it on your laptop

You need Python 3.9 or newer, a Telegram bot token from **@BotFather**, and the database address.

```
python -m venv .venv
.venv\Scripts\activate              (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env              (Mac/Linux: cp .env.example .env)    then edit .env
python test_risk.py                 # rule self-test: no internet or database needed
python check_db.py                  # database connection self-test
python bot.py                       # the Telegram bot
python scheduler.py                 # the scheduler (second terminal)
```

`.env` settings:

| Name | Meaning |
|---|---|
| `DB_BASE_URL` | The ORDS address of the schema, like `https://<host>/ords/harvestly` (no table name, no trailing slash). |
| `TELEGRAM_BOT_TOKEN` | From @BotFather. **Secret.** |
| `SCHEDULER_INTERVAL_SECONDS` | How often to check (30 for the demo). |
| `ALERT_COOLDOWN_HOURS` | Repeat gap for a still-HIGH batch (24). |
| `WEATHER_LAT`, `WEATHER_LON` | Eldoret (0.5143, 35.2698). |

**One bot token can only be polled by one running copy.** If the VM is running the bot, stop the laptop copy
(or use a second token), otherwise Telegram reports a "Conflict".

## 10. Run it on the Oracle VM

The VM runs the bot and scheduler as services that restart themselves. Our VM uses Oracle Autonomous Linux 7
(user `opc`); Ubuntu works too.

```
ssh -i "<path to your private key>" opc@<VM public IP>
git clone https://github.com/Machajose/harvestly.git && cd harvestly
bash deploy/setup_vm.sh               # builds .venv, installs the two services
nano .env                             # paste DB_BASE_URL and the token (Ctrl+O, Enter, Ctrl+X)
.venv/bin/python check_db.py          # must say ALL CHECKS PASSED
sudo systemctl enable --now harvestly-bot harvestly-scheduler
```

Useful commands:

```
sudo systemctl status harvestly-bot harvestly-scheduler     # are they running?
sudo journalctl -u harvestly-bot -f                         # live bot log (Ctrl+C to leave)
cd ~/harvestly && git pull && sudo systemctl restart harvestly-bot harvestly-scheduler    # update
```

Notes from our own setup:
- Autonomous Linux 7 ships an old Python and may lack `git`. Install git with `sudo yum install -y git`, and
  install Python 3.11 with [`uv`](https://docs.astral.sh/uv/), then make the `.venv` with it.
  (`deploy/setup_vm.sh` targets Oracle Linux 8+/Ubuntu, where `dnf` or `apt` exists.)
- If a service fails with status `203/EXEC`, SELinux may be blocking it: try `sudo setenforce 0`.
- The VM's public IP is ephemeral. Check it before connecting. The SSH key file must not be readable by other users
  (on Windows, fix with `icacls`).

## 11. Set up the database from scratch

Do this in a fresh Oracle Autonomous Database (for example a teammate's), as the schema user (we use `HARVESTLY`).

1. In **Database Actions > SQL**, run each script with **Run Script (F5)**, in this order:
   1. `sql/schema.sql` (tables and the simulator row)
   2. `sql/schema_upgrade.sql` (location and variety columns)
   3. `sql/notes_upgrade.sql` (farmer notes column and a few demo notes)
   4. `python make_seed.py`, then run the `sql/seed_big.sql` it creates (a realistic demo dataset of fake farmers).
      `sql/seed.sql` is a smaller alternative.
2. **Turn on REST** for `farmers`, `batches`, `alerts`, `weather_cache` and `sim_settings`: Database Actions,
   **REST**, **AutoREST** (or right-click the table, **REST, Enable**). These scripts do not do this step, so it is manual.
   Our demo leaves authorization off, so the address works without a login. **Anyone with the URL can read and
   write**, which is fine for a hackathon demo and not for real farmer data.
3. Copy the base address (`https://<host>/ords/<schema>`) into `DB_BASE_URL`, then run `python check_db.py`.
4. In APEX, **App Builder > Import**: choose `sql/harvestly_admin_app.sql`, parsing schema = your schema, run and
   build, auto-assign a new application id, and answer **No** to supporting objects (the tables already exist).

## 12. Backup and failover plan

The bot and scheduler know the database **only** through `DB_BASE_URL`, so the database, the VM and APEX can each
be replaced separately.

| What breaks | What to do |
|---|---|
| **APEX app lost** | Re-import `sql/harvestly_admin_app.sql` (section 11, step 4). Tables and data are not affected. |
| **Our database is down or the account is suspended** | A teammate builds the database in their Oracle account (section 11). They send us **only their REST base address, never a password**. We change `DB_BASE_URL` in the VM's `.env`, run `check_db.py`, then `sudo systemctl restart harvestly-bot harvestly-scheduler`. No code changes. |
| **The VM dies** | Create a new VM anywhere (ours, a teammate's, any cheap Linux host), repeat section 10. The database is untouched. |
| **All of Oracle is unreachable** | Run `bot.py` and `scheduler.py` from a laptop against whichever database still works. Keep a short screen recording of the demo as a last resort. `test_risk.py` works with no internet. |

Rules that make this work:
- Keep **every SQL script and the APEX export in GitHub**. Re-export the app after changes.
- `.env` is never in GitHub, so each person keeps their own copy somewhere private (such as a password manager).
- Only one running copy per bot token. Each teammate should use their own token for their own testing.
- Real farmer data does not move by itself. Before a planned switch, export the tables from Database Actions.
- Oracle free and student resources can be stopped or reclaimed if idle, or when credits end. Log in
  regularly and know which kind of account you have.

## 13. Files in this repo

```
risk.py             the risk rules (all thresholds in one place)
db.py               all database access, through the REST (ORDS) address
weather.py          Open-Meteo weather with a backup copy
bot.py              Telegram registration bot (English and Swahili)
scheduler.py        checks every batch and sends alerts
check_db.py         database connection self-test
test_risk.py        risk rules self-test (no internet needed)
make_seed.py        builds sql/seed_big.sql (realistic demo data)
requirements.txt    Python packages
.env.example        template for settings (copy to .env; never commit .env)
deploy/             systemd service files and setup_vm.sh for the VM
sql/                schema.sql, schema_upgrade.sql, notes_upgrade.sql, seed files,
                    apex_queries.sql, and the exported APEX app
```

## 14. Assumptions and limits (please read)

Be honest about what is proven and what is not:

- **Thresholds marked ASSUMPTION in `risk.py` are placeholders**: heavy rain 30 mm, warm 25 C, and 30/60 storage
  days. They must be confirmed with KALRO or an extension officer before this is used with real farmers.
  Moisture limits (13.5% safe, 20% wet) come from the team's maize storage notes.
- The score is a **rule-based advisory**, not a laboratory test. It cannot detect mould or aflatoxin. It tells a
  farmer when conditions make spoilage likely, and what to do.
- **Weather** is one location (Eldoret) for all farmers. Real use needs weather per farm or sub-county.
- Farmers' moisture answers (dry, unsure, damp) are estimates unless they use a meter.
- **The demo data is fake.** Seeded farmers and the demo notes are invented. Their risk values come from replaying
  our own rules, so they show how the system behaves and are **not** evidence of real-world accuracy.
- The REST address has no authorization in the demo. Add it before any real use.
- The photo (vision) check is planned, not built. Maize only; other crops are future work.
- Swahili wording should be reviewed by a native speaker.

## 15. Team rules: secrets and Git

- **Never commit `.env`, a bot token, or a key file.** (`.gitignore` already excludes `.env`.) If a token is
  ever pasted into chat, a screenshot, a log or GitHub, treat it as leaked: open @BotFather, send `/revoke`, and
  put the new token in `.env`.
- Pull before you push (`git pull`), commit small, and say what changed.
- Change thresholds only in `risk.py`, then run `python test_risk.py`.
- Change database access only in `db.py`.

## Stack

Oracle Autonomous Database, ORDS REST, APEX, and Compute VM; Telegram Bot API; Open-Meteo; Python 3.
