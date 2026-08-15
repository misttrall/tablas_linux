CREATE TABLE IF NOT EXISTS etl_execution_tables (
    run_id INTEGER NOT NULL,
    table_name TEXT NOT NULL,
    chunks_total INTEGER NULL,
    chunks_ok INTEGER NULL,
    rows_extracted INTEGER NULL,
    duration_s REAL NULL,
    status TEXT NULL,
    PRIMARY KEY (run_id, table_name)
);
