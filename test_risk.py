"""test_risk.py - checks that the risk rules behave. Run with:  python test_risk.py"""
import risk


def level(**kwargs):
    defaults = dict(storage_type="open_sack", days_stored=10, moisture_check="dry",
                    moisture_pct=None, humidity=60, rain_mm=5, temp_c=18, vision_flag=None)
    defaults.update(kwargs)
    return risk.assess(**defaults).level


# Dry grain, airtight bags: low risk whatever the weather
assert level(storage_type="hermetic_bag", humidity=90, rain_mm=80, days_stored=200) == "low"
# Dry grain, open sacks, normal weather, short time: low
assert level() == "low"
# Borderline moisture in open sacks, normal weather: medium
assert level(moisture_check="unsure") == "medium"
# Wet grain is high risk straight away, even in hermetic bags
assert level(moisture_check="damp", storage_type="hermetic_bag") == "high"
# A meter reading wins over the field check
assert level(moisture_check="dry", moisture_pct=22.0) == "high"
assert level(moisture_check="damp", moisture_pct=12.5) == "low"
assert level(moisture_check="dry", moisture_pct=15.0, storage_type="hermetic_bag") == "medium"
# Dry grain stored a long time in open sacks in a very humid week: high
assert level(days_stored=70, humidity=85) == "high"
# Same dry grain in a humid week but only 5 days: still low/medium, not high
assert level(days_stored=5, humidity=75) in ("low", "medium")
# Aflatoxin condition: moist + warm + humid
a = risk.assess("open_sack", 10, "unsure", None, 75, 5, 27)
assert "aflatoxin" in a.codes and a.level == "high"
# Photo flags: spoiled forces high, suspect raises the score
assert level(vision_flag="spoiled") == "high"
assert level(vision_flag="suspect") == "medium"
# Unknown storage / moisture is handled without crashing
assert risk.assess(None, None, None, None, None, None, None).level in ("low", "medium", "high")

# Messages exist in both languages and contain the action and source line
for lang in ("en", "sw"):
    for case in (dict(), dict(moisture_check="damp"), dict(moisture_check="unsure")):
        a = risk.assess(**{**dict(storage_type="open_sack", days_stored=10, moisture_check="dry",
                                  humidity=60, rain_mm=5, temp_c=18), **case})
        text = risk.build_message(a, lang, "14 Oct 09:00")
        assert risk.LABELS[lang][a.level] in text and "14 Oct 09:00" in text and len(text) > 80

# ---- editable thresholds (risk_thresholds table), no database needed ----
names, problem = risk.apply_thresholds({"HEAVY_RAIN_MM": 15})
assert names == ["HEAVY_RAIN_MM"] and problem is None
assert "rainy" in risk.assess("open_sack", 10, "dry", None, 60, 20, 18).codes     # 20 mm now counts as heavy
names, problem = risk.apply_thresholds({"SAFE_MOISTURE": 30})                     # nonsense: above WET_MOISTURE
assert names == [] and problem and risk.SAFE_MOISTURE == 13.5                     # ignored, defaults kept
names, problem = risk.apply_thresholds({"HUMID": "abc"})
assert names == [] and problem
names, problem = risk.apply_thresholds({"NOT_A_THRESHOLD": 5})                    # unknown names are ignored
assert names == [] and problem is None
risk.apply_thresholds(None)                                                       # back to the defaults
assert risk.HEAVY_RAIN_MM == 30.0 and "rainy" not in risk.assess("open_sack", 10, "dry", None, 60, 20, 18).codes

# ---- message pieces, and the optional AI wording stays out of the way when switched off ----
import os
os.environ["GENAI_ENABLED"] = "false"
import explain
a = risk.assess("open_sack", 40, "unsure", None, 82, 35, 20)
for lang in ("en", "sw"):
    label, why, advice, source = risk.message_parts(a, lang, "14 Oct 09:00")
    assert risk.build_message(a, lang, "14 Oct 09:00") == f"{label}\n{why}.\n\n{advice}\n\n{source}"
    assert explain.final_message(a, lang, "14 Oct 09:00") == risk.build_message(a, lang, "14 Oct 09:00")
assert explain.simplify("text 12", "en") == ("text 12", False)

# ---- follow-up buttons ----
import prompts
for lang in ("en", "sw", "xx"):
    for rows in (prompts.feedback_rows(123456789, lang), prompts.recheck_rows(123456789, lang)):
        assert rows and all(len(row) == 1 and len(row[0][1].encode()) <= 64 for row in rows)
assert {c for c in prompts.FEEDBACK_VALUE} == {r[0][1].split(":")[2] for r in prompts.feedback_rows(1, "en")}
assert {c for c in prompts.RECHECK_VALUE} == {r[0][1].split(":")[2] for r in prompts.recheck_rows(1, "en")}
assert "2026-10-09" in prompts.recheck_text("en", "2026-10-09")

# ---- weather places ----
import weather
assert weather.place_key(" Soy ") == "soy" and weather.place_key("Nowhere") == "default" and weather.place_key(None) == "default"
assert all(len(weather.coords_for(name)) == 2 for name in ("Soy", "Turbo", "Moiben", "Kesses", "Kapseret", "Ainabkoi", None))

# ---- re-check reminder timing (no Telegram, no database) ----
from datetime import datetime, timedelta
import scheduler
scheduler.RECHECK_DAYS = 3
stamp = lambda days: (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
now = datetime.utcnow()
assert scheduler.recheck_due({"id": 1, "moisture_check": "unsure", "created_at": stamp(5)}, now)
assert not scheduler.recheck_due({"id": 2, "moisture_check": "unsure", "created_at": stamp(1)}, now)   # too soon
assert not scheduler.recheck_due({"id": 3, "moisture_check": "dry", "created_at": stamp(9)}, now)      # already dry
assert not scheduler.recheck_due({"id": 4, "moisture_check": "damp", "created_at": stamp(9),
                                  "last_recheck_at": stamp(1)}, now)                                   # asked recently
assert scheduler.recheck_due({"id": 5, "moisture_check": "dry", "moisture_pct": 18.0, "created_at": stamp(9)}, now)

print("All risk tests passed")
print()
print("Example alert (English):")
print(risk.build_message(risk.assess("open_sack", 40, "unsure", None, 82, 35, 20), "en", "14 Oct 09:00"))
