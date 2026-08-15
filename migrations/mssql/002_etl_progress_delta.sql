IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dbo.etl_progress') AND name = 'last_delta_value'
)
ALTER TABLE dbo.etl_progress ADD last_delta_value VARCHAR(40) NULL;
