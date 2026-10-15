-- Harvestly feature upgrade: farmer feedback, moisture re-check, editable risk thresholds.
-- Run this ONCE in Database Actions > SQL, as the HARVESTLY user, with Run Script (F5).
-- Run it BEFORE you start the new bot.py / scheduler.py (they work without it, but the new
-- features stay switched off until these columns and the table exist).
-- If a line says "name is already used by an existing object" or "column already exists",
-- that part was done before: ignore it and carry on.

-- 1. Feedback: the farmer's answer to "Was this warning useful?" is saved on the alert row.
--    Values: useful, already_spoiling, not_needed  (empty = no answer yet)
ALTER TABLE alerts ADD (feedback VARCHAR2(20), feedback_at TIMESTAMP);

-- 2. Re-check: when we last asked the farmer to re-test grain that was not fully dry.
ALTER TABLE batches ADD (last_recheck_at TIMESTAMP);

-- 3. Editable thresholds: the numbers behind every risk decision, changeable from APEX.
--    status:  ASSUMPTION = a placeholder nobody has confirmed (confirm with KALRO / an extension officer)
--             TEAM NOTES = comes from the team's maize storage notes
--             CONFIRMED  = checked with an expert (fill in confirmed_by and source_note)
CREATE TABLE risk_thresholds (
  id           NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name         VARCHAR2(40)  NOT NULL UNIQUE,
  value        NUMBER        NOT NULL,
  unit         VARCHAR2(20),
  meaning      VARCHAR2(300),
  status       VARCHAR2(20)  DEFAULT 'ASSUMPTION' CHECK (status IN ('ASSUMPTION', 'TEAM NOTES', 'CONFIRMED')),
  confirmed_by VARCHAR2(100),
  source_note  VARCHAR2(300),
  updated_at   TIMESTAMP     DEFAULT SYSTIMESTAMP
);

-- The starting values are exactly the defaults written in risk.py.
MERGE INTO risk_thresholds t
USING (
  SELECT 'SAFE_MOISTURE' name, 13.5 value, '%' unit, 'At or below this grain moisture, maize is safe to store' meaning, 'TEAM NOTES' status FROM dual UNION ALL
  SELECT 'WET_MOISTURE', 20, '%', 'Above this grain moisture the maize is too wet: high risk straight away', 'TEAM NOTES' FROM dual UNION ALL
  SELECT 'HUMID', 70, '% humidity', 'Air humidity from which grain re-absorbs moisture (mould risk)', 'TEAM NOTES' FROM dual UNION ALL
  SELECT 'VERY_HUMID', 80, '% humidity', 'Air humidity that counts as very humid (more points)', 'TEAM NOTES' FROM dual UNION ALL
  SELECT 'HEAVY_RAIN_MM', 30, 'mm / 7 days', 'Rain over the last 7 days that counts as heavy', 'ASSUMPTION' FROM dual UNION ALL
  SELECT 'WARM_C', 25, 'deg C', 'Temperature that counts as warm for the aflatoxin rule', 'ASSUMPTION' FROM dual UNION ALL
  SELECT 'MEDIUM_STORAGE_DAYS', 30, 'days', 'Days in non-airtight storage after which risk starts to rise (+1)', 'ASSUMPTION' FROM dual UNION ALL
  SELECT 'LONG_STORAGE_DAYS', 60, 'days', 'Days in non-airtight storage that count as a long time (+2)', 'ASSUMPTION' FROM dual UNION ALL
  SELECT 'MEDIUM_SCORE', 3, 'points', 'Risk score from which a batch is MEDIUM', 'TEAM NOTES' FROM dual UNION ALL
  SELECT 'HIGH_SCORE', 6, 'points', 'Risk score from which a batch is HIGH', 'TEAM NOTES' FROM dual
) s
ON (t.name = s.name)
WHEN NOT MATCHED THEN
  INSERT (name, value, unit, meaning, status) VALUES (s.name, s.value, s.unit, s.meaning, s.status);

-- Stamp the time whenever a row is edited in APEX.
CREATE OR REPLACE TRIGGER risk_thresholds_bu
BEFORE UPDATE ON risk_thresholds
FOR EACH ROW
BEGIN
  :NEW.updated_at := SYSTIMESTAMP;
END;
/

-- Make the table reachable by the bot and scheduler, like your other tables (REST, no login in the demo).
-- If this block gives an error, do it by hand instead: Database Actions > REST > AutoREST,
-- find RISK_THRESHOLDS, switch it on.
BEGIN
  ORDS.ENABLE_OBJECT(p_enabled => TRUE, p_object => 'RISK_THRESHOLDS',
                     p_object_type => 'TABLE', p_object_alias => 'risk_thresholds',
                     p_auto_rest_auth => FALSE);
  COMMIT;
END;
/

COMMIT;

-- Checks. Expect: 10 thresholds, and the two new columns listed.
SELECT COUNT(*) AS thresholds FROM risk_thresholds;
SELECT table_name, column_name FROM user_tab_columns
 WHERE (table_name = 'ALERTS' AND column_name IN ('FEEDBACK', 'FEEDBACK_AT'))
    OR (table_name = 'BATCHES' AND column_name = 'LAST_RECHECK_AT')
 ORDER BY table_name, column_name;
