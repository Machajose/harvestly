-- Run as the HARVESTLY user in Database Actions > SQL, using Run Script (F5).
CREATE TABLE farmers (
  id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  telegram_chat_id VARCHAR2(40) UNIQUE,
  name VARCHAR2(100),
  county VARCHAR2(50) DEFAULT 'Uasin Gishu',
  language VARCHAR2(10) DEFAULT 'en',
  created_at TIMESTAMP DEFAULT SYSTIMESTAMP
);

CREATE TABLE batches (
  id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  farmer_id NUMBER REFERENCES farmers(id),
  crop VARCHAR2(30) DEFAULT 'maize',
  harvest_date DATE,
  maturity_confirmed VARCHAR2(5),
  storage_type VARCHAR2(30),
  moisture_check VARCHAR2(10),
  moisture_pct NUMBER,
  moisture_source VARCHAR2(20),
  harvest_moisture_pct NUMBER,
  estimated_moisture_pct NUMBER,
  bags NUMBER,
  photo_url VARCHAR2(400),
  vision_flag VARCHAR2(20),
  vision_notes VARCHAR2(400),
  risk_level VARCHAR2(10),
  risk_reason VARCHAR2(400),
  last_alert_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT SYSTIMESTAMP
);

CREATE TABLE weather_cache (
  id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  county VARCHAR2(50),
  obs_date DATE,
  avg_humidity NUMBER,
  rain_mm NUMBER,
  temp_c NUMBER,
  fetched_at TIMESTAMP DEFAULT SYSTIMESTAMP
);

CREATE TABLE alerts (
  id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  batch_id NUMBER REFERENCES batches(id),
  sent_at TIMESTAMP DEFAULT SYSTIMESTAMP,
  risk_level VARCHAR2(10),
  message VARCHAR2(1000)
);

CREATE TABLE sim_settings (
  id NUMBER PRIMARY KEY,
  day_offset NUMBER DEFAULT 0,
  force_humidity NUMBER,
  force_rain_mm NUMBER
);
INSERT INTO sim_settings (id, day_offset) VALUES (1, 0);
COMMIT;
