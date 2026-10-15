-- Queries for the APEX pages and charts. Paste each one into a region's Source > SQL Query.
-- (Chart regions: set Label/Value/Series columns to the aliases shown.)

-- 1. KPI strip (one row: use a Cards or Classic Report region)
SELECT (SELECT COUNT(*) FROM farmers) AS farmers,
       (SELECT COUNT(*) FROM batches) AS batches,
       (SELECT NVL(SUM(bags), 0) FROM batches) AS bags_tracked,
       (SELECT NVL(SUM(bags), 0) FROM batches WHERE risk_level = 'high') AS bags_high_risk,
       (SELECT COUNT(*) FROM alerts WHERE sent_at >= SYSDATE - 7) AS alerts_last_7_days
FROM dual;

-- 2. Batches report, worst first (Interactive Report). Apply the red/amber/green highlight on RISK_LEVEL.
SELECT b.id, f.name AS farmer, f.sub_county, f.ward, b.variety, b.bags, b.storage_type,
       b.moisture_check, b.moisture_pct, TRUNC(SYSDATE - b.harvest_date) AS days_stored,
       b.risk_level, b.risk_reason, b.last_alert_at
FROM batches b JOIN farmers f ON f.id = b.farmer_id
ORDER BY CASE b.risk_level WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
         b.last_alert_at DESC NULLS LAST;

-- 3. Farmers report (use this as the Farmers page's SQL Query source)
SELECT f.id, f.name, f.sub_county, f.ward, f.language, f.farm_acres,
       COUNT(b.id) AS batches, NVL(SUM(b.bags), 0) AS bags,
       CASE MAX(CASE b.risk_level WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END)
            WHEN 3 THEN 'high' WHEN 2 THEN 'medium' WHEN 1 THEN 'low' ELSE NULL END AS worst_risk,
       f.created_at
FROM farmers f LEFT JOIN batches b ON b.farmer_id = f.id
GROUP BY f.id, f.name, f.sub_county, f.ward, f.language, f.farm_acres, f.created_at
ORDER BY f.created_at DESC;

-- 4. Latest alerts (Interactive Report)
SELECT a.sent_at, f.name AS farmer, f.sub_county, a.risk_level,
       SUBSTR(REPLACE(a.message, CHR(10), ' '), 1, 140) AS message_start
FROM alerts a JOIN batches b ON b.id = a.batch_id JOIN farmers f ON f.id = b.farmer_id
ORDER BY a.sent_at DESC;

-- 5. Chart: batches by risk level (donut / pie)
SELECT risk_level AS label, COUNT(*) AS value FROM batches GROUP BY risk_level;

-- 6. Chart: bags at risk with an estimated value (bar).
--    3500 is an ASSUMED price per 90 kg bag in KES: replace it with a sourced local price before you quote it.
SELECT risk_level AS label, SUM(bags) AS bags, SUM(bags) * 3500 AS est_value_kes
FROM batches GROUP BY risk_level;

-- 7. Chart: risk by sub-county (stacked bar: Label = SUB_COUNTY, Series = RISK_LEVEL, Value = VALUE)
SELECT NVL(f.sub_county, 'Other') AS sub_county, b.risk_level, COUNT(*) AS value
FROM batches b JOIN farmers f ON f.id = b.farmer_id
GROUP BY NVL(f.sub_county, 'Other'), b.risk_level;

-- 8. Chart: risk by storage type (stacked bar). Shows why hermetic bags matter.
SELECT b.storage_type, b.risk_level, COUNT(*) AS value
FROM batches b GROUP BY b.storage_type, b.risk_level;

-- 9. Chart: alerts sent per day, last 30 days (bar)
SELECT TRUNC(sent_at) AS day, COUNT(*) AS alerts
FROM alerts WHERE sent_at >= SYSDATE - 30
GROUP BY TRUNC(sent_at) ORDER BY 1;

-- 10. Chart: farmer sign-ups per day and running total (line)
SELECT TRUNC(created_at) AS day, COUNT(*) AS new_farmers,
       SUM(COUNT(*)) OVER (ORDER BY TRUNC(created_at)) AS total_farmers
FROM farmers GROUP BY TRUNC(created_at) ORDER BY 1;

-- 11. Chart: weather trend (line: 7-day average humidity, rain and temperature)
SELECT obs_date, avg_humidity, rain_mm, temp_c
FROM weather_cache WHERE county = 'Uasin Gishu' ORDER BY obs_date;

-- 12. Farmer notes page (Interactive Report): what farmers told us that we did not ask.
--     Needs sql/notes_upgrade.sql to have been run first.
SELECT b.id AS batch_id, f.name AS farmer, f.sub_county, b.storage_type, b.risk_level,
       b.farmer_notes AS note, b.created_at
FROM batches b JOIN farmers f ON f.id = b.farmer_id
WHERE b.farmer_notes IS NOT NULL
ORDER BY b.created_at DESC;

-- 13. Chart: how farmers rated our warnings (stacked bar: risk level, split by answer).
--     Needs sql/features_upgrade.sql. Rows only appear once farmers tap the buttons.
--     Label = RISK_LEVEL, Series Name = ANSWER, Value = VALUE.
SELECT a.risk_level, NVL(a.feedback, 'no answer') AS answer, COUNT(*) AS value
FROM alerts a
WHERE a.message NOT LIKE '[not delivered%'
GROUP BY a.risk_level, NVL(a.feedback, 'no answer');

-- 13b. KPI: share of answered warnings that farmers called useful
SELECT COUNT(*) AS answered,
       SUM(CASE WHEN feedback = 'useful' THEN 1 ELSE 0 END) AS useful,
       ROUND(100 * SUM(CASE WHEN feedback = 'useful' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0)) AS useful_pct
FROM alerts WHERE feedback IS NOT NULL;

-- 14. Risk thresholds page: make it an Interactive Grid (editable) straight on the table
--     RISK_THRESHOLDS, no query needed. See README.md, "Editable thresholds".

-- 15. Weather by place (Interactive Report). Rows are saved once a day per sub-county.
SELECT county AS place, obs_date, avg_humidity, rain_mm, temp_c
FROM weather_cache ORDER BY obs_date DESC, county;

-- 16. Re-check page (Interactive Report): grain that is not fully dry, and when we last asked.
SELECT b.id AS batch_id, f.name AS farmer, f.sub_county, b.moisture_check, b.moisture_pct,
       b.risk_level, b.last_recheck_at, b.created_at
FROM batches b JOIN farmers f ON f.id = b.farmer_id
WHERE b.moisture_check IN ('unsure', 'damp')
   OR b.moisture_pct > (SELECT value FROM risk_thresholds WHERE name = 'SAFE_MOISTURE')
ORDER BY b.created_at DESC;
