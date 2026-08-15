CREATE TABLE IF NOT EXISTS etl_execution (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    end_time TEXT NULL,
    status TEXT NOT NULL,
    message TEXT NULL
);

CREATE TABLE IF NOT EXISTS etl_progress (
    table_name TEXT PRIMARY KEY,
    rows_loaded INTEGER NULL,
    status TEXT NULL,
    updated_at TEXT NULL DEFAULT CURRENT_TIMESTAMP
);
