#!/usr/bin/env python3
"""make_seed.py - builds sql/seed_big.sql, a large realistic demo dataset for Harvestly.

It does NOT touch your database. It only writes a SQL file that you paste into
Database Actions > SQL (as HARVESTLY) and run with Run Script (F5).

Why the data behaves like a live system instead of random rows:
  1. A synthetic daily weather series for Eldoret (seasonal humidity, rain, temperature),
     summarised as 7-day trailing values, the same shape scheduler.py stores.
  2. Farmers register over the last ~5 weeks (more sign-ups in recent days).
  3. Every batch is replayed day by day through risk.py with that weather, as the scheduler
     would. When the risk goes up, an alert row is written in the farmer's language.
  4. Each batch's final risk_level, risk_reason and last_alert_at come from that replay.

Run:   python make_seed.py
       python make_seed.py --farmers 200 --seed 7 --humidity-shift -3

Needs risk.py in the same folder. Names are generic combinations, not real people.
Sub-county and ward names are real places in Uasin Gishu, but which farmer lives where is random.
"""
import argparse
import os
import random
from collections import Counter
from datetime import date, datetime, time, timedelta

import risk

HERE = os.path.dirname(os.path.abspath(__file__))
COUNTY = "Uasin Gishu"

# ---------------------------------------------------------------------------
# Names: a county-typical mix (mostly Kalenjin, plus Kikuyu, Luhya, Luo, Kisii, Kamba)
# ---------------------------------------------------------------------------
GROUPS = {
    "kalenjin": dict(
        w=52,
        m=["Kiprono", "Kiplagat", "Kibet", "Kimutai", "Kiptoo", "Kipkorir", "Kiprotich", "Kipngetich",
           "Kiptanui", "Kipkemboi", "Kipsang", "Kipruto", "Kiplimo", "Kipkoech", "Kipserem", "Kipchumba",
           "Kipkurui", "Kiprop", "Kipleting"],
        f=["Chebet", "Jepchirchir", "Jebet", "Chepkoech", "Cherono", "Jeptoo", "Jepkemboi", "Chelangat",
           "Jepkosgei", "Chepngetich", "Cheruto", "Jepkorir", "Chepkirui", "Jelagat", "Chepkemoi",
           "Jepleting", "Chepkorir", "Jemutai", "Chepchumba"],
        last=["Rotich", "Cheruiyot", "Koech", "Langat", "Tanui", "Sang", "Bett", "Kemboi", "Kiprotich",
              "Chepkwony", "Kosgei", "Kirui", "Korir", "Mutai", "Kiplagat", "Lagat", "Biwott", "Ngeno",
              "Terer", "Too", "Sigei", "Kandie", "Maiyo", "Kurgat", "Limo", "Rono", "Tum", "Chumba"],
    ),
    "kikuyu": dict(
        w=17,
        m=["Kamau", "Njoroge", "Mwangi", "Kariuki", "Gitau", "Kimani", "Maina", "Karanja", "Githinji",
           "Ndungu", "Muriuki", "Waweru", "Macharia", "Gathogo", "Kinyanjui", "Mburu"],
        f=["Wanjiru", "Wambui", "Njeri", "Muthoni", "Wangui", "Nyambura", "Wairimu", "Waithera",
           "Wanjiku", "Mumbi", "Wangari", "Nyokabi"],
        last=["Kamau", "Njoroge", "Mwangi", "Kariuki", "Gitau", "Kimani", "Maina", "Karanja", "Githinji",
              "Ndungu", "Waweru", "Macharia", "Mugo", "Kibe", "Ngugi", "Wachira", "Kihara", "Gachanja",
              "Thuo", "Njenga"],
    ),
    "luhya": dict(
        w=14,
        m=["Wekesa", "Wafula", "Simiyu", "Barasa", "Wanyama", "Khaemba", "Juma", "Masinde", "Mukhwana",
           "Nyongesa", "Wamalwa", "Sifuna", "Makokha"],
        f=["Nanjala", "Naliaka", "Nafula", "Nekesa", "Nasimiyu", "Naswa", "Nelima", "Nafuna", "Nabwire",
           "Namatsi"],
        last=["Wamalwa", "Sifuna", "Wangila", "Masinde", "Mutonyi", "Khisa", "Wekesa", "Wafula", "Simiyu",
              "Barasa", "Makokha", "Munyasia", "Khaemba", "Wanyonyi", "Mukhwana", "Wasike", "Shitanda",
              "Lusweti"],
    ),
    "luo": dict(
        w=6,
        m=["Otieno", "Odhiambo", "Onyango", "Ochieng", "Omondi", "Owino", "Okoth", "Oluoch", "Ouma",
           "Okello", "Ochola"],
        f=["Achieng", "Atieno", "Akinyi", "Adhiambo", "Anyango", "Awuor", "Apiyo", "Auma"],
        last=["Otieno", "Odhiambo", "Ouma", "Okumu", "Oduor", "Ogola", "Ochola", "Odongo", "Opiyo",
              "Owuor", "Oloo", "Onyango", "Ayieko", "Obonyo", "Oketch"],
    ),
    "kisii": dict(
        w=6,
        m=["Ondieki", "Ombati", "Nyakundi", "Mokaya", "Ogeto", "Momanyi", "Nyabuto", "Mogaka", "Ondimu",
           "Mongare"],
        f=["Moraa", "Nyaboke", "Kerubo", "Bosibori", "Gesare", "Kemunto", "Nyanchama", "Boke", "Kwamboka"],
        last=["Ombati", "Nyakundi", "Mogeni", "Onsongo", "Ondimu", "Getange", "Nyangau", "Mose", "Mokua",
              "Omwenga", "Nyamwange", "Obino"],
    ),
    "kamba": dict(
        w=5,
        m=["Mutua", "Musyoka", "Kioko", "Mutuku", "Muema", "Nzioka", "Kilonzo", "Mwanzia", "Mutinda"],
        f=["Mwikali", "Syokau", "Ndunge", "Mueni", "Mwende", "Kavata", "Nduku", "Kalekye"],
        last=["Mutua", "Musyoka", "Kioko", "Mutuku", "Muema", "Nzioka", "Kilonzo", "Mwanzia", "Mutinda",
              "Kyalo", "Mbithi", "Munyao"],
    ),
}
CHRISTIAN = {
    "m": ["Daniel", "Joseph", "Peter", "John", "Samuel", "Paul", "David", "Stephen", "Isaac", "Nicholas",
          "Michael", "Joshua", "Julius", "Elijah", "Benson", "Titus", "Victor", "Dennis", "Felix", "Kenneth",
          "Vincent", "Geoffrey", "Collins", "Wilson", "Philip", "Hosea", "Charles", "Hillary", "Edwin",
          "Brian", "Evans", "Robert", "Josphat", "James", "Francis", "Patrick", "Simon", "Anthony"],
    "f": ["Mercy", "Joyce", "Esther", "Grace", "Faith", "Ruth", "Sarah", "Hannah", "Lydia", "Rebecca",
          "Elizabeth", "Susan", "Nancy", "Caroline", "Beatrice", "Irene", "Gladys", "Phyllis", "Dorcas",
          "Priscilla", "Lilian", "Winnie", "Naomi", "Mary", "Jane", "Rose", "Lucy", "Margaret", "Alice",
          "Jackline", "Violet", "Tabitha", "Millicent", "Everlyne", "Purity", "Sheila", "Agnes", "Ann"],
}
# Names of well-known people we never want to generate by accident.
BLOCK = {"Samuel Wanjiru", "Julius Yego", "Wilson Kipsang", "Eliud Kipchoge", "Faith Kipyegon",
         "Beatrice Chebet", "Ruth Chepngetich", "Mary Keitany", "Paul Tergat", "David Rudisha"}

# (sub-county, weight, wards)
LOCATIONS = [
    ("Soy", 28, ["Moi's Bridge", "Ziwa", "Soy", "Kipsomba", "Kapkures", "Segero", "Kuinet"]),
    ("Turbo", 22, ["Huruma", "Ngenyilel", "Tapsagoi", "Kamagut", "Kiplombe", "Turbo"]),
    ("Moiben", 14, ["Tembelio", "Sergoit", "Karuna", "Moiben", "Kimumu"]),
    ("Kesses", 14, ["Racecourse", "Cheptiret", "Tulwet", "Tarakwa", "Kipchamo"]),
    ("Kapseret", 10, ["Simat", "Kipkenyo", "Ngeria", "Megun", "Langas"]),
    ("Ainabkoi", 12, ["Kapsoya", "Kaptagat", "Ainabkoi", "Olare"]),
]
VARIETIES = [("H614D", 30), ("H6213", 18), ("H628", 12), ("H629", 8), ("DK 8031", 8),
             ("WH505", 6), ("PH4", 6), ("Other / farm-saved seed", 12)]

# ---------------------------------------------------------------------------
# Weather (monthly climate for Eldoret; rough, tuned by --humidity-shift)
# ---------------------------------------------------------------------------
HUM_BASE = {1: 55, 2: 52, 3: 60, 4: 68, 5: 72, 6: 74, 7: 78, 8: 80, 9: 72, 10: 68, 11: 65, 12: 58}
RAIN_P = {1: .10, 2: .12, 3: .25, 4: .40, 5: .45, 6: .45, 7: .55, 8: .55, 9: .42, 10: .35, 11: .30, 12: .15}
TEMP_BASE = {1: 18.5, 2: 19.0, 3: 19.0, 4: 18.0, 5: 17.5, 6: 17.0, 7: 16.5, 8: 16.8, 9: 17.8,
             10: 18.0, 11: 17.6, 12: 17.5}


def build_weather(rng, first_day, last_day, shift):
    """{day: (humidity %, rain mm, temp C)} as 7-day trailing summaries, like the scheduler stores."""
    daily = {}
    d = first_day - timedelta(days=7)
    hum_prev = HUM_BASE[d.month] + shift
    wet = False
    while d <= last_day:
        m = d.month
        p = min(0.85, RAIN_P[m] + 0.20) if wet else RAIN_P[m] * 0.6
        rained = rng.random() < p
        wet = rained
        mm = min(55.0, rng.expovariate(1 / 9.0)) if rained else 0.0
        target = HUM_BASE[m] + shift + (8 if rained else -3) + rng.gauss(0, 4)
        hum = max(38.0, min(93.0, 0.65 * hum_prev + 0.35 * target))
        hum_prev = hum
        temp = TEMP_BASE[m] + rng.gauss(0, 1.2) - (1.2 if rained else 0.0)
        daily[d] = (hum, mm, temp)
        d += timedelta(days=1)
    summary = {}
    d = first_day
    while d <= last_day:
        window = [daily[d - timedelta(days=i)] for i in range(7)]
        summary[d] = (sum(w[0] for w in window) / 7, sum(w[1] for w in window), sum(w[2] for w in window) / 7)
        d += timedelta(days=1)
    return summary


# ---------------------------------------------------------------------------
# Farmers
# ---------------------------------------------------------------------------
def make_name(rng, gender, group, used):
    g = GROUPS[group]
    for _ in range(80):
        eth, last, xian = rng.choice(g[gender]), rng.choice(g["last"]), rng.choice(CHRISTIAN[gender])
        style = rng.random()
        if style < 0.40:
            parts = [eth, last]
        elif style < 0.75:
            parts = [xian, eth, last]
        else:
            parts = [xian, last]
        if len(set(parts)) < len(parts):
            continue
        name = " ".join(parts)
        if name in used or name in BLOCK:
            continue
        used.add(name)
        return name
    raise RuntimeError("could not build a unique name; use fewer farmers")


def reg_datetime(rng, now):
    """Registration time: more sign-ups in recent days, mostly daytime and evening."""
    days_ago = int(38 * rng.betavariate(1.0, 1.8))
    hour = rng.choices(range(6, 22), weights=[2, 3, 4, 4, 3, 3, 3, 3, 3, 4, 5, 6, 7, 6, 4, 2])[0]
    dt = datetime.combine(now.date() - timedelta(days=days_ago),
                          time(hour, rng.randint(0, 59), rng.randint(0, 59)))
    if dt > now - timedelta(hours=1):
        dt = now - timedelta(minutes=rng.randint(60, 600))
    return dt


def make_farmer(rng, idx, now, used):
    gender = "m" if rng.random() < 0.52 else "f"
    group = rng.choices(list(GROUPS), weights=[GROUPS[k]["w"] for k in GROUPS])[0]
    sub, _, wards = rng.choices(LOCATIONS, weights=[x[1] for x in LOCATIONS])[0]
    acres = round(min(60.0, max(1.0, rng.lognormvariate(1.3, 0.8))) * 2) / 2
    return dict(chat=f"seed-{idx:04d}", name=make_name(rng, gender, group, used),
                lang="sw" if rng.random() < 0.42 else "en", sub=sub, ward=rng.choice(wards),
                acres=acres, reg=reg_datetime(rng, now))


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------
def pick_storage(rng, bags, old):
    weights = (20, 50, 30) if old else (35, 25, 40) if bags > 120 else (46, 28, 26)
    return rng.choices(["open_sack", "hermetic_bag", "crib"], weights=weights)[0]


def pick_moisture(rng, days_at_reg, maturity, old):
    """Returns (check, meter_pct or None, estimated_pct)."""
    if old:
        check = "dry" if rng.random() < 0.88 else "unsure"
    else:
        p_dry = min(0.85, 0.40 + 0.03 * days_at_reg)
        p_damp = max(0.04, 0.26 - 0.015 * days_at_reg) + (0.08 if maturity == "no" else 0.0)
        r = rng.random()
        check = "damp" if r < p_damp else "dry" if rng.random() < p_dry else "unsure"
    band = {"dry": (11.2, 13.5), "unsure": (13.6, 19.5), "damp": (20.2, 26.0)}[check]
    pct = round(rng.uniform(*band), 1)
    if rng.random() < 0.25:                       # farmer had a meter reading
        return check, pct, pct
    return check, None, pct


def make_batches(rng, f, today, now):
    n = 1 + (rng.random() < 0.35) + (rng.random() < 0.12)
    if f["acres"] > 15:
        n = max(n, 2)
    total_bags = f["acres"] * rng.uniform(10, 22)
    out, used_dates = [], set()
    for i in range(n):
        if i == 0:
            created = f["reg"]
        else:
            created = min(f["reg"] + timedelta(days=rng.randint(1, 12), hours=rng.randint(0, 8)),
                          now - timedelta(hours=1))
            if created <= f["reg"]:
                break
        old = rng.random() < (0.03 if i == 0 else 0.10)       # stock held over from the last season
        if old:
            harvest = date(today.year - 1, 12, 1) + timedelta(days=rng.randint(0, 90))
            bags = rng.randint(8, 140)
        else:
            harvest = created.date() - timedelta(days=int(rng.triangular(1, 28, 6)))
            harvest = min(max(harvest, date(today.year, 9, 1)), created.date())
            bags = int(round(total_bags * rng.uniform(0.6, 1.2) / n * rng.uniform(0.4, 1.0)))
            bags = max(3, min(450, bags))
        while harvest in used_dates:
            harvest -= timedelta(days=1)
        used_dates.add(harvest)

        maturity = "no" if (not old and rng.random() < 0.18) else "yes"
        check, pct, est = pick_moisture(rng, (created.date() - harvest).days, maturity, old)
        if old:
            harvest_moist = round(rng.uniform(20, 28), 1)
        elif maturity == "no":
            harvest_moist = round(rng.uniform(30, 37), 1)
        else:
            harvest_moist = round(max(20.0, min(33.0, rng.gauss(26, 2.8))), 1)
        out.append(dict(
            chat=f["chat"], created=created, harvest=harvest, maturity=maturity,
            storage=pick_storage(rng, bags, old), check=check, pct=pct,
            source="meter" if pct is not None else "field_check",
            harvest_moist=harvest_moist, est_moist=est, bags=bags,
            variety=rng.choices([v[0] for v in VARIETIES], weights=[v[1] for v in VARIETIES])[0],
            level=None, reason=None, last_alert=None))
    return out


# ---------------------------------------------------------------------------
# Replay: run each batch day by day through risk.py and write alerts as they would have fired
# ---------------------------------------------------------------------------
def alert_time(rng, day, now):
    start, end = datetime.combine(day, time(5, 30)), datetime.combine(day, time(18, 30))
    if day == now.date():
        end = min(end, now - timedelta(minutes=5))
    if end <= start:
        return None
    return start + timedelta(seconds=rng.randint(0, int((end - start).total_seconds())))


def replay(rng, b, lang, wx, today, now, alerts):
    prev, last_alert_day, reminders = None, None, 0
    day = b["created"].date()
    final = None
    while day <= today:
        hum, rain, temp = wx[day]
        a = risk.assess(b["storage"], (day - b["harvest"]).days, b["check"], b["pct"], hum, rain, temp)
        final = a
        if prev is not None:
            since = None if last_alert_day is None else (day - last_alert_day).days
            escalated_high = a.level == "high" and prev != "high"
            escalated_med = a.level == "medium" and prev == "low" and (since is None or since >= 3)
            nag = a.level == "high" and since is not None and since >= 4 and reminders < 2
            if escalated_high or escalated_med or nag:
                sent = alert_time(rng, day, now)
                if sent is not None:
                    msg = risk.build_message(a, lang, sent.strftime("%d %b %H:%M"))[:950]
                    alerts.append(dict(chat=b["chat"], harvest=b["harvest"], sent=sent, level=a.level, message=msg))
                    b["last_alert"] = sent
                    last_alert_day = day
                    if nag and not (escalated_high or escalated_med):
                        reminders += 1
        prev = a.level
        day += timedelta(days=1)
    b["level"] = final.level
    b["reason"] = risk.reason_text(final, "en")[:380]


# ---------------------------------------------------------------------------
# SQL output
# ---------------------------------------------------------------------------
def q(s):
    if s is None:
        return "NULL"
    s = str(s)
    assert "&" not in s, f"'&' would trigger a substitution prompt in Run Script: {s!r}"
    return "'" + s.replace("'", "''").replace("\n", "' || CHR(10) || '") + "'"


def num(x):
    if x is None:
        return "NULL"
    return f"{x:.1f}" if isinstance(x, float) else str(x)


def dd(d):
    return f"DATE '{d:%Y-%m-%d}'"


def ts(dt):
    return f"TIMESTAMP '{dt:%Y-%m-%d %H:%M:%S}'"


def write_sql(path, farmers, batches, alerts, wx, today, now):
    L = []
    add = L.append
    add("-- Harvestly demo data (generated by make_seed.py on %s)." % now.strftime("%Y-%m-%d %H:%M"))
    add("-- Run as HARVESTLY in Database Actions > SQL with Run Script (F5).")
    add("-- Re-running is safe: it first removes earlier seed rows (chat ids starting 'seed-').")
    add("-- Real registrations from the Telegram bot are left alone.")
    add("")
    add("DELETE FROM alerts WHERE batch_id IN (SELECT b.id FROM batches b JOIN farmers f ON f.id = b.farmer_id WHERE f.telegram_chat_id LIKE 'seed-%');")
    add("DELETE FROM batches WHERE farmer_id IN (SELECT id FROM farmers WHERE telegram_chat_id LIKE 'seed-%');")
    add("DELETE FROM farmers WHERE telegram_chat_id LIKE 'seed-%';")
    add("DELETE FROM weather_cache;")
    add("COMMIT;")
    add("")
    add("-- Farmers: %d" % len(farmers))
    for f in farmers:
        add("INSERT INTO farmers (telegram_chat_id, name, county, language, sub_county, ward, farm_acres, created_at) "
            f"VALUES ({q(f['chat'])}, {q(f['name'])}, {q(COUNTY)}, {q(f['lang'])}, {q(f['sub'])}, {q(f['ward'])}, "
            f"{num(f['acres'])}, {ts(f['reg'])});")
    add("COMMIT;")
    add("")
    add("-- Batches: %d" % len(batches))
    for b in batches:
        add("INSERT INTO batches (farmer_id, crop, harvest_date, maturity_confirmed, storage_type, moisture_check, "
            "moisture_pct, moisture_source, harvest_moisture_pct, estimated_moisture_pct, bags, variety, "
            "risk_level, risk_reason, last_alert_at, created_at) "
            f"SELECT id, 'maize', {dd(b['harvest'])}, {q(b['maturity'])}, {q(b['storage'])}, {q(b['check'])}, "
            f"{num(b['pct'])}, {q(b['source'])}, {num(b['harvest_moist'])}, {num(b['est_moist'])}, {b['bags']}, "
            f"{q(b['variety'])}, {q(b['level'])}, {q(b['reason'])}, "
            f"{ts(b['last_alert']) if b['last_alert'] else 'NULL'}, {ts(b['created'])} "
            f"FROM farmers WHERE telegram_chat_id = {q(b['chat'])};")
    add("COMMIT;")
    add("")
    add("-- Alerts: %d" % len(alerts))
    for a in sorted(alerts, key=lambda x: x["sent"]):
        add("INSERT INTO alerts (batch_id, sent_at, risk_level, message) "
            f"SELECT b.id, {ts(a['sent'])}, {q(a['level'])}, {q(a['message'])} "
            "FROM batches b JOIN farmers f ON f.id = b.farmer_id "
            f"WHERE f.telegram_chat_id = {q(a['chat'])} AND b.harvest_date = {dd(a['harvest'])};")
    add("COMMIT;")
    add("")
    add("-- Weather history (7-day trailing values, one row a day, same as scheduler.py stores)")
    d = today - timedelta(days=59)
    while d < today:                              # up to yesterday; the scheduler adds today's row itself
        h, r, t = wx[d]
        add("INSERT INTO weather_cache (county, obs_date, avg_humidity, rain_mm, temp_c, fetched_at) "
            f"VALUES ({q(COUNTY)}, {dd(d)}, {h:.1f}, {r:.1f}, {t:.1f}, {ts(datetime.combine(d, time(6, 0, 5)))});")
        d += timedelta(days=1)
    add("COMMIT;")
    add("")
    add("-- Check: expect the counts printed by make_seed.py")
    add("SELECT (SELECT COUNT(*) FROM farmers WHERE telegram_chat_id LIKE 'seed-%') AS seed_farmers,")
    add("       (SELECT COUNT(*) FROM batches) AS batches, (SELECT COUNT(*) FROM alerts) AS alerts,")
    add("       (SELECT COUNT(*) FROM weather_cache) AS weather_rows FROM dual;")
    add("SELECT risk_level, COUNT(*) AS batches, SUM(bags) AS bags FROM batches GROUP BY risk_level ORDER BY 1;")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser(description="Generate the Harvestly demo dataset as a SQL file.")
    ap.add_argument("--farmers", type=int, default=160, help="number of farmers (default 160)")
    ap.add_argument("--seed", type=int, default=2026, help="random seed: same seed = same data")
    ap.add_argument("--humidity-shift", type=float, default=0.0,
                    help="add to the monthly humidity (e.g. -4 = drier weather, fewer alerts)")
    ap.add_argument("--out", default=os.path.join(HERE, "sql", "seed_big.sql"))
    args = ap.parse_args()

    rng = random.Random(args.seed)
    now = datetime.now().replace(microsecond=0)
    today = now.date()
    wx = build_weather(rng, today - timedelta(days=59), today, args.humidity_shift)

    farmers, batches, alerts, used = [], [], [], set()
    lang_of = {}
    for i in range(1, args.farmers + 1):
        f = make_farmer(rng, i, now, used)
        farmers.append(f)
        lang_of[f["chat"]] = f["lang"]
        for b in make_batches(rng, f, today, now):
            replay(rng, b, f["lang"], wx, today, now, alerts)
            batches.append(b)

    write_sql(args.out, farmers, batches, alerts, wx, today, now)

    sub_of = {f["chat"]: f["sub"] for f in farmers}
    levels = Counter(b["level"] for b in batches)
    print(f"Wrote {args.out}")
    print(f"  farmers: {len(farmers)}   batches: {len(batches)}   alerts: {len(alerts)}   weather rows: 59")
    print(f"  bags tracked: {sum(b['bags'] for b in batches)}   "
          f"bags at HIGH risk: {sum(b['bags'] for b in batches if b['level'] == 'high')}")
    print("  risk now:      " + "  ".join(f"{k}={levels.get(k, 0)}" for k in ("low", "medium", "high")))
    print("  storage:       " + "  ".join(f"{k}={v}" for k, v in Counter(b["storage"] for b in batches).items()))
    print("  language:      " + "  ".join(f"{k}={v}" for k, v in Counter(lang_of.values()).items()))
    print("  sub-county:    " + "  ".join(f"{k}={v}" for k, v in Counter(sub_of.values()).most_common()))
    print("  alerts by level: " + "  ".join(f"{k}={v}" for k, v in Counter(a['level'] for a in alerts).items()))
    print("Next: open the .sql file, copy all, paste into Database Actions > SQL, press Run Script (F5).")
    print("If 'high' is far above ~25% of batches, rerun with  --humidity-shift -4  for a calmer picture.")


if __name__ == "__main__":
    main()
