ALTER TABLE etl_progress ADD COLUMN IF NOT EXISTS last_delta_value VARCHAR(40);
