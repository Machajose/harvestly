"""check_db.py - proves your database connection works from this computer.

Run it with:  python check_db.py
It creates a TEST farmer and batch, changes the batch, reads it back, then deletes
both. You should see PASS on every line.
"""
import time

import db

failures = 0
state = {}


def step(name, fn):
    global failures
    try:
        result = fn()
        print(f"PASS  {name}")
        return result
    except Exception as exc:  # noqa: BLE001 - we want to show any problem
        failures += 1
        print(f"FAIL  {name}\n      -> {exc}")
        return None


def read_farmers():
    rows = db.find("farmers")
    print(f"      ({len(rows)} farmers in the database)")


def read_sim():
    row = db.get_sim_settings()
    print(f"      (simulator: day_offset={row.get('day_offset')})")


def make_farmer():
    state["chat"] = f"check-{int(time.time())}"
    state["farmer"] = db.create_farmer(state["chat"], "CHECK FARMER (safe to delete)")
    assert state["farmer"].get("id"), "no id came back"


def read_farmer():
    row = db.get_farmer_by_chat(state["chat"])
    assert row and row["id"] == state["farmer"]["id"], "could not read the farmer back"


def make_batch():
    from datetime import date, timedelta
    state["batch"] = db.create_batch(state["farmer"]["id"], date.today() - timedelta(days=5),
                                     "open_sack", "unsure", bags=10)
    assert state["batch"].get("id"), "no id came back"


def update_batch():
    db.save_risk(state["batch"]["id"], "medium", "check test")
    row = db.get("batches", state["batch"]["id"])
    assert row["risk_level"] == "medium", f"risk_level is {row['risk_level']!r}, expected 'medium'"


def read_thresholds():
    rows = db.get_thresholds()
    assert rows, "the risk_thresholds table is empty (run sql/features_upgrade.sql)"
    print(f"      ({len(rows)} thresholds, e.g. HEAVY_RAIN_MM = {rows.get('HEAVY_RAIN_MM')})")


def new_columns():
    """The feedback / re-check columns must exist, or those features cannot save anything."""
    batch = db.get("batches", state["batch"]["id"])
    db.mark_rechecked(state["batch"]["id"])
    row = db.get("batches", state["batch"]["id"])
    assert row.get("last_recheck_at"), "last_recheck_at did not save (run sql/features_upgrade.sql)"
    alert = db.create("alerts", {"batch_id": batch["id"], "risk_level": "medium", "message": "check test"})
    state["alert"] = alert
    assert db.save_alert_feedback(batch["id"], "useful"), "no alert found to save feedback on"
    back = db.get("alerts", alert["id"]) if alert.get("id") else None
    assert back is None or back.get("feedback") == "useful", "feedback did not save (run sql/features_upgrade.sql)"


def clean_up():
    if state.get("batch"):
        # Delete EVERY alert of the test batch first (a batch cannot be deleted while alerts point at it).
        # We look them up instead of trusting an id from the earlier step, which ORDS may not return.
        for alert in db.find("alerts", {"batch_id": state["batch"]["id"]}, all_pages=True):
            db.delete("alerts", alert["id"])
    if state.get("batch"):
        db.delete("batches", state["batch"]["id"])
    if state.get("farmer"):
        db.delete("farmers", state["farmer"]["id"])


print("Checking the Harvestly database...\n")
step("read the farmers table", read_farmers)
step("read the simulator settings", read_sim)
step("create a test farmer", make_farmer)
if state.get("farmer"):
    step("read the farmer back", read_farmer)
    step("create a test batch", make_batch)
if state.get("batch"):
    step("update the batch risk", update_batch)
step("read the risk thresholds table (sql/features_upgrade.sql)", read_thresholds)
if state.get("batch"):
    step("save a re-check time and alert feedback (sql/features_upgrade.sql)", new_columns)
step("delete the test rows", clean_up)

print()
if failures:
    print(f"{failures} check(s) FAILED. Copy everything above and send it to Claude.")
else:
    print("ALL CHECKS PASSED. Your database connection works.")