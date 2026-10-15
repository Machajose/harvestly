"""db.py - the ONLY file that talks to your Oracle database.

It uses the REST address of your tables (ORDS), so you do not need a wallet,
a driver or a password: just plain web requests.
Every other file calls the small functions at the bottom of this file.
"""
import json
import os
import re
from datetime import date, datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()
TIMEOUT = 20
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


class DBError(Exception):
    """Raised when the database cannot be reached or refuses a request."""


# ---------------------------------------------------------------------------
# low level helpers
# ---------------------------------------------------------------------------
def _url(table, row_id=None):
    base = os.getenv("DB_BASE_URL", "").strip().rstrip("/")
    if not base:
        raise DBError("DB_BASE_URL is empty. Open your .env file and paste your database address.")
    return f"{base}/{table}/" + ("" if row_id is None else str(row_id))


def _request(method, url, what, **kwargs):
    try:
        resp = requests.request(method, url, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise DBError(f"{what}: could not reach the database ({exc.__class__.__name__}). "
                      "Check your internet and that the database is running.") from exc
    return resp


def _short(text):
    """Make an error body readable: ORDS often answers with a whole HTML page."""
    match = re.search(r"ORA-\d{5}[^<\r\n]*", text or "")
    if match:                                    # the database's own message, e.g. ORA-02292
        return match.group(0)[:300]
    if "<html" in (text or "").lower():          # drop the page's style and tags, keep the words
        text = re.sub(r"(?is)<style.*?</style>|<script.*?</script>", " ", text)
        text = re.sub(r"<[^>]+>", " ", text)
    return " ".join((text or "").split())[:300]


def _check(resp, what):
    if resp.status_code >= 400:
        raise DBError(f"{what} failed: HTTP {resp.status_code} - {_short(resp.text)}")
    return resp


def _clean(row):
    """Drop the 'links' ORDS adds and trim timestamps to seconds."""
    if not isinstance(row, dict):
        return row
    out = {}
    for key, value in row.items():
        if key == "links":
            continue
        if isinstance(value, str) and _ISO.match(value):
            value = value[:19] + "Z"
        out[key] = value
    return out


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date_str(value):
    """'2026-10-09T00:00:00Z' -> date(2026, 10, 9). Returns None if empty."""
    if not value:
        return None
    return date.fromisoformat(str(value)[:10])


def parse_dt(value):
    """'2026-10-14T08:00:00Z' -> datetime (naive, UTC). Returns None if empty."""
    if not value:
        return None
    return datetime.strptime(str(value)[:19], "%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------------------
# generic table operations
# ---------------------------------------------------------------------------
def find(table, where=None, limit=200, order=None, all_pages=False, max_rows=5000):
    """List rows, optionally filtered, e.g. find('batches', {'farmer_id': 3}).

    By default returns one page (at most `limit` rows). With all_pages=True it keeps
    asking for the next page until ORDS says there are no more (or max_rows is reached),
    which the scheduler needs once there are more than 200 batches.
    """
    query = dict(where or {})
    if order:
        query["$orderby"] = order
    rows, offset = [], 0
    while True:
        params = {"limit": limit, "offset": offset}
        if query:
            params["q"] = json.dumps(query)
        resp = _request("GET", _url(table), f"GET {table}", params=params)
        _check(resp, f"GET {table}")
        body = resp.json()
        rows.extend(_clean(item) for item in body.get("items", []))
        if not all_pages or not body.get("hasMore") or len(rows) >= max_rows:
            return rows
        offset += limit


def get(table, row_id):
    resp = _request("GET", _url(table, row_id), f"GET {table}/{row_id}")
    if resp.status_code == 404:
        return None
    _check(resp, f"GET {table}/{row_id}")
    return _clean(resp.json())


def create(table, data):
    resp = _request("POST", _url(table), f"POST {table}", json=data)
    _check(resp, f"POST {table}")
    try:
        return _clean(resp.json())
    except ValueError:
        return {}


def update(table, row_id, changes):
    """Change some columns of one row (reads the row, merges, writes it back)."""
    row = get(table, row_id)
    if row is None:
        raise DBError(f"{table} row {row_id} does not exist")
    row.update(changes)
    resp = _request("PUT", _url(table, row_id), f"PUT {table}/{row_id}", json=row)
    if resp.status_code >= 400:  # some setups prefer a body without the id
        row.pop("id", None)
        resp = _request("PUT", _url(table, row_id), f"PUT {table}/{row_id}", json=row)
    _check(resp, f"PUT {table}/{row_id}")
    return row


def delete(table, row_id):
    resp = _request("DELETE", _url(table, row_id), f"DELETE {table}/{row_id}")
    _check(resp, f"DELETE {table}/{row_id}")


# ---------------------------------------------------------------------------
# Harvestly functions (what the bot and scheduler actually call)
# ---------------------------------------------------------------------------
def get_farmer_by_chat(chat_id):
    rows = find("farmers", {"telegram_chat_id": str(chat_id)}, limit=1)
    return rows[0] if rows else None


def get_farmer(farmer_id):
    return get("farmers", farmer_id)


def create_farmer(chat_id, name, language="en", county="Uasin Gishu"):
    row = create("farmers", {"telegram_chat_id": str(chat_id), "name": (name or "")[:100],
                             "language": language, "county": county})
    if "id" not in row:
        row = get_farmer_by_chat(chat_id) or row
    return row


def set_farmer_language(farmer_id, language):
    return update("farmers", farmer_id, {"language": language})


def create_batch(farmer_id, harvest_date, storage_type, moisture_check,
                 moisture_pct=None, moisture_source="field_check", bags=None, notes=None):
    """harvest_date is a python date. notes is the farmer's optional free-text remark."""
    data = {
        "farmer_id": farmer_id,
        "crop": "maize",
        "harvest_date": harvest_date.strftime("%Y-%m-%dT00:00:00Z"),
        "storage_type": storage_type,
        "moisture_check": moisture_check,
        "moisture_source": moisture_source,
        "bags": bags,
    }
    if moisture_pct is not None:
        data["moisture_pct"] = moisture_pct
    if notes:
        data["farmer_notes"] = notes[:500]
    row = create("batches", data)
    if "id" not in row:  # fall back: newest batch of this farmer
        rows = find("batches", {"farmer_id": farmer_id}, limit=1, order={"id": "desc"})
        row = rows[0] if rows else row
    return row


def get_batches(farmer_id=None):
    return find("batches", {"farmer_id": farmer_id} if farmer_id is not None else None, all_pages=True)


def get_all_farmers():
    """Every farmer in one go (a few requests), so the scheduler does not fetch them one by one."""
    return find("farmers", all_pages=True)


def save_risk(batch_id, level, reason):
    return update("batches", batch_id, {"risk_level": level, "risk_reason": reason[:380]})


def mark_alerted(batch_id):
    return update("batches", batch_id, {"last_alert_at": now_iso()})


def log_alert(batch_id, level, message):
    return create("alerts", {"batch_id": batch_id, "risk_level": level, "message": message[:950]})


def set_farmer_sub_county(farmer_id, sub_county):
    return update("farmers", farmer_id, {"sub_county": (sub_county or "")[:40]})


def get_thresholds():
    """The editable risk numbers: {'HEAVY_RAIN_MM': 30, ...} from the risk_thresholds table.

    Raises DBError if the table is missing or not REST-enabled (sql/features_upgrade.sql).
    """
    rows = find("risk_thresholds", all_pages=True)
    return {row["name"]: row.get("value") for row in rows if row.get("name")}


def save_alert_feedback(batch_id, value):
    """Store the farmer's answer on the newest alert of this batch. Returns False if there is none."""
    rows = find("alerts", {"batch_id": batch_id}, limit=1, order={"id": "desc"})
    if not rows:
        return False
    update("alerts", rows[0]["id"], {"feedback": value, "feedback_at": now_iso()})
    return True


def mark_rechecked(batch_id):
    return update("batches", batch_id, {"last_recheck_at": now_iso()})


def apply_recheck(batch_id, moisture_check):
    """The farmer re-checked the moisture by hand: store it, drop any older meter reading."""
    changes = {"moisture_check": moisture_check, "moisture_pct": None,
               "moisture_source": "field_check", "last_recheck_at": now_iso()}
    try:
        return update("batches", batch_id, changes)
    except DBError:
        changes.pop("last_recheck_at")      # the column may not exist yet (features_upgrade.sql)
        return update("batches", batch_id, changes)


def get_sim_settings():
    """The simulator row (id 1). Returns safe defaults if it is missing."""
    row = get("sim_settings", 1)
    return row or {"id": 1, "day_offset": 0, "force_humidity": None, "force_rain_mm": None}


def save_weather(county, obs_date, humidity, rain_mm, temp_c):
    return create("weather_cache", {
        "county": county, "obs_date": obs_date.strftime("%Y-%m-%dT00:00:00Z"),
        "avg_humidity": round(humidity, 1), "rain_mm": round(rain_mm, 1), "temp_c": round(temp_c, 1)})