"""risk.py - the Harvestly risk rules.

One place for every threshold, so the bot and the scheduler always agree.
Thresholds come from the team's Uasin Gishu maize notes. Lines marked
ASSUMPTION are placeholders: confirm them with KALRO / an extension officer
before the pitch.
"""
from dataclasses import dataclass, field

# ---- thresholds (change them here, nowhere else) --------------------------
SAFE_MOISTURE = 13.5        # % at or below = safe to store
WET_MOISTURE = 20.0         # % above = too wet, high risk
HUMID = 70.0                # % relative humidity: mould / re-absorption risk
VERY_HUMID = 80.0           # %
HEAVY_RAIN_MM = 30.0        # mm over the last 7 days (ASSUMPTION)
WARM_C = 25.0               # deg C: "warm" for the aflatoxin rule (ASSUMPTION)
LONG_STORAGE_DAYS = 60      # open storage (ASSUMPTION)
MEDIUM_STORAGE_DAYS = 30    # open storage (ASSUMPTION)

HIGH_SCORE = 6
MEDIUM_SCORE = 3

LEVEL_RANK = {"low": 0, "medium": 1, "high": 2}

# ---- editable thresholds ---------------------------------------------------------
# The numbers above are the DEFAULTS. The team can change them without touching code, in the
# APEX "Risk thresholds" page (table risk_thresholds). The bot and scheduler call
# apply_thresholds() with that table's rows. If the table is missing or a value is nonsense,
# the defaults are used, so a typo in APEX can never break the bot.
TUNABLE = ["SAFE_MOISTURE", "WET_MOISTURE", "HUMID", "VERY_HUMID", "HEAVY_RAIN_MM", "WARM_C",
           "LONG_STORAGE_DAYS", "MEDIUM_STORAGE_DAYS", "HIGH_SCORE", "MEDIUM_SCORE"]
DEFAULTS = {name: globals()[name] for name in TUNABLE}
_SCORES = ("HIGH_SCORE", "MEDIUM_SCORE")


def _check_thresholds(c):
    """Return a problem description, or None if the set of numbers makes sense together."""
    if any(v <= 0 for v in c.values()):
        return "every threshold must be above 0"
    if not c["SAFE_MOISTURE"] < c["WET_MOISTURE"] <= 100:
        return "SAFE_MOISTURE must be below WET_MOISTURE (and at most 100)"
    if not c["HUMID"] < c["VERY_HUMID"] <= 100:
        return "HUMID must be below VERY_HUMID (and at most 100)"
    if not c["MEDIUM_STORAGE_DAYS"] < c["LONG_STORAGE_DAYS"]:
        return "MEDIUM_STORAGE_DAYS must be below LONG_STORAGE_DAYS"
    if not c["MEDIUM_SCORE"] < c["HIGH_SCORE"]:
        return "MEDIUM_SCORE must be below HIGH_SCORE"
    return None


def apply_thresholds(values=None):
    """Use thresholds from the database. `values` is {NAME: number}. Unknown names are ignored.

    Returns (names that now differ from the defaults, problem text or None).
    On any problem NOTHING is changed from the defaults. apply_thresholds(None) resets to defaults.
    """
    candidate = dict(DEFAULTS)
    problem = None
    for name, raw in (values or {}).items():
        key = str(name).strip().upper()
        if key not in DEFAULTS:
            continue
        try:
            number = float(raw)
        except (TypeError, ValueError):
            problem = f"{key} is not a number: {raw!r}"
            break
        candidate[key] = int(round(number)) if key in _SCORES or key.endswith("_DAYS") else number
    if problem is None:
        problem = _check_thresholds(candidate)
    if problem is not None:
        candidate = dict(DEFAULTS)
    globals().update(candidate)
    return [k for k in TUNABLE if candidate[k] != DEFAULTS[k]], problem

# ---- wording ---------------------------------------------------------------
LABELS = {
    "en": {"high": "HIGH RISK", "medium": "MEDIUM RISK", "low": "LOW RISK"},
    "sw": {"high": "HATARI KUBWA", "medium": "HATARI YA WASTANI", "low": "HATARI NDOGO"},
}

REASONS = {
    "en": {
        "wet": "your grain is still too wet (above about 20% moisture)",
        "borderline": "your grain is not fully dry yet (about 13.5-20% moisture)",
        "open_storage": "it is in open sacks",
        "crib_storage": "it is in a crib or store",
        "humid": "the air has been humid",
        "very_humid": "the air has been very humid",
        "rainy": "there has been heavy rain",
        "long_storage": "it has been stored for a long time",
        "aflatoxin": "warm, humid weather with grain this moist can grow aflatoxin mould",
        "visible_spoilage": "the photo shows visible spoilage",
        "visible_suspect": "the photo shows possible spoilage",
    },
    "sw": {
        "wet": "nafaka bado ina unyevu mwingi (zaidi ya asilimia 20)",
        "borderline": "nafaka bado haijakauka kabisa (asilimia 13.5-20)",
        "open_storage": "imehifadhiwa kwenye magunia ya wazi",
        "crib_storage": "imehifadhiwa kwenye ghala la kienyeji",
        "humid": "hewa imekuwa na unyevu",
        "very_humid": "hewa imekuwa na unyevu mwingi sana",
        "rainy": "kumekuwa na mvua nyingi",
        "long_storage": "imehifadhiwa kwa muda mrefu",
        "aflatoxin": "joto na unyevu pamoja na nafaka yenye unyevu vinaweza kusababisha ukungu wa aflatoksini",
        "visible_spoilage": "picha inaonyesha uharibifu unaoonekana",
        "visible_suspect": "picha inaonyesha dalili za uharibifu",
    },
}

# One clear action per alert (a Swahili speaker should check these).
ADVICE = {
    "en": {
        "mould": "Dry it again today, pick out any mouldy or discoloured kernels, and do not eat or sell it if it smells musty.",
        "wet": "Do not store it yet. Spread it thin on a tarpaulin in the sun, off the ground, and turn it often until it is dry. Cover it when rain comes.",
        "storage": "Move it into hermetic bags or an airtight container, off the floor and away from walls, or sell it now.",
        "check": "Check it this week. Dry it a little longer or move it into hermetic bags.",
        "ok": "It looks fine for now. Keep it dry, sealed and off the ground. I will warn you if anything changes.",
    },
    "sw": {
        "mould": "Ikaushe tena leo, ondoa punje zenye ukungu au zilizobadilika rangi, na usiitumie wala kuiuza ikiwa ina harufu ya ukungu.",
        "wet": "Usiihifadhi bado. Isambaze nyembamba juani kwenye turubai, mbali na ardhi, na uigeuze mara kwa mara hadi ikauke. Ifunike mvua ikinyesha.",
        "storage": "Iweke kwenye mifuko ya hermetic au chombo kisichopitisha hewa, juu ya godoro, mbali na ukuta, au iuze sasa.",
        "check": "Ikague wiki hii. Ikaushe zaidi kidogo au iweke kwenye mifuko ya hermetic.",
        "ok": "Iko salama kwa sasa. Iweke kavu, imefungwa vizuri na juu ya godoro. Nitakuonya kukiwa na mabadiliko.",
    },
}

SOURCE_LINE = {
    "en": "Based on your answers and the weather near you (Open-Meteo). Checked {t}.",
    "sw": "Kulingana na majibu yako na hali ya hewa karibu nawe (Open-Meteo). Imekaguliwa {t}.",
}


@dataclass
class Assessment:
    level: str
    score: int
    codes: list = field(default_factory=list)


def moisture_band(moisture_pct=None, moisture_check=None):
    """Turn a meter reading or a field check into a band: safe / borderline / wet."""
    if moisture_pct is not None:
        if moisture_pct > WET_MOISTURE:
            return "wet"
        if moisture_pct > SAFE_MOISTURE:
            return "borderline"
        return "safe"
    return {"dry": "safe", "unsure": "borderline", "damp": "wet"}.get(moisture_check, "borderline")


def assess(storage_type, days_stored, moisture_check=None, moisture_pct=None,
           humidity=None, rain_mm=None, temp_c=None, vision_flag=None):
    """Return an Assessment(level, score, codes). No wording here, just the decision."""
    score = 0
    codes = []
    band = moisture_band(moisture_pct, moisture_check)
    sealed = storage_type == "hermetic_bag"

    # 1. How wet is the grain? (the most important factor)
    if band == "wet":
        score += 6
        codes.append("wet")
    elif band == "borderline":
        score += 3
        codes.append("borderline")

    # 2. How is it stored?
    if storage_type == "open_sack":
        score += 2
        codes.append("open_storage")
    elif storage_type == "crib":
        score += 1
        codes.append("crib_storage")

    # 3. Weather, storage time: these only matter if the store is not airtight.
    if not sealed:
        if humidity is not None:
            if humidity >= VERY_HUMID:
                score += 3
                codes.append("very_humid")
            elif humidity >= HUMID:
                score += 2
                codes.append("humid")
        if rain_mm is not None and rain_mm >= HEAVY_RAIN_MM:
            score += 1
            codes.append("rainy")
        if days_stored is not None:
            if days_stored > LONG_STORAGE_DAYS:
                score += 2
                codes.append("long_storage")
            elif days_stored > MEDIUM_STORAGE_DAYS:
                score += 1
                codes.append("long_storage")

    # 4. Aflatoxin condition: moist grain + warm + humid (food-safety hazard).
    if (band != "safe" and humidity is not None and temp_c is not None
            and humidity >= HUMID and temp_c >= WARM_C):
        score += 3
        codes.append("aflatoxin")

    # 5. A photo check can only raise the risk, never lower it.
    if vision_flag == "spoiled":
        score = max(score, HIGH_SCORE)
        codes.append("visible_spoilage")
    elif vision_flag == "suspect":
        score += 3
        codes.append("visible_suspect")

    level = "high" if score >= HIGH_SCORE else "medium" if score >= MEDIUM_SCORE else "low"
    return Assessment(level=level, score=score, codes=codes)


def reason_text(a, lang="en"):
    """A readable list of the reasons, e.g. 'it is in open sacks, the air has been humid'."""
    table = REASONS.get(lang, REASONS["en"])
    parts = [table[c] for c in a.codes if c in table]
    if not parts:
        return {"en": "no problems found", "sw": "hakuna tatizo lililoonekana"}.get(lang, "no problems found")
    return "; ".join(parts)


def advice_key(a):
    if "visible_spoilage" in a.codes or "aflatoxin" in a.codes:
        return "mould"
    if "wet" in a.codes:
        return "wet"
    if a.level == "high":
        return "storage"
    if a.level == "medium":
        return "check"
    return "ok"


def advice_text(a, lang="en"):
    return ADVICE.get(lang, ADVICE["en"])[advice_key(a)]


def message_parts(a, lang="en", checked_at=""):
    """The four pieces of an alert: (level label, reason sentence, action, source line)."""
    lang = lang if lang in LABELS else "en"
    why = reason_text(a, lang)
    why = why[0].upper() + why[1:] if why else why
    source = SOURCE_LINE[lang].format(t=checked_at or "just now")
    return LABELS[lang][a.level], why, advice_text(a, lang), source


def build_message(a, lang="en", checked_at=""):
    """The full alert: level, why, one action, and where the information came from."""
    label, why, advice, source = message_parts(a, lang, checked_at)
    return f"{label}\n{why}.\n\n{advice}\n\n{source}"
