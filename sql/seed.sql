-- Demo rows for APEX. Run with Run Script (F5). Safe to run once.
INSERT INTO farmers (telegram_chat_id, name) VALUES ('demo-1','Demo Farmer A');
INSERT INTO farmers (telegram_chat_id, name) VALUES ('demo-2','Demo Farmer B');
COMMIT;
INSERT INTO batches (farmer_id, harvest_date, storage_type, moisture_check, bags, risk_level, risk_reason)
  SELECT id, SYSDATE-5, 'hermetic_bag', 'dry', 20, 'low', 'no problems found' FROM farmers WHERE telegram_chat_id='demo-1';
INSERT INTO batches (farmer_id, harvest_date, storage_type, moisture_check, bags, risk_level, risk_reason)
  SELECT id, SYSDATE-18, 'open_sack', 'unsure', 35, 'medium', 'not fully dry, in open sacks' FROM farmers WHERE telegram_chat_id='demo-2';
INSERT INTO batches (farmer_id, harvest_date, storage_type, moisture_check, bags, risk_level, risk_reason)
  SELECT id, SYSDATE-30, 'open_sack', 'damp', 12, 'high', 'still too wet, in open sacks' FROM farmers WHERE telegram_chat_id='demo-2';
COMMIT;
