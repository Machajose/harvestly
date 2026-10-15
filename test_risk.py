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

print("All risk tests passed")
print()
print("Example alert (English):")
print(risk.build_message(risk.assess("open_sack", 40, "unsure", None, 82, 35, 20), "en", "14 Oct 09:00"))
