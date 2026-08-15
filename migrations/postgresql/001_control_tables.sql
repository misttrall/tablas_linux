CREATE TABLE IF NOT EXISTS etl_execution (
    id SERIAL PRIMARY KEY,
    start_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    end_time TIMESTAMPTZ NULL,
    status VARCHAR(20) NOT NULL,
    message TEXT NULL
);

CREATE TABLE IF NOT EXISTS etl_progress (
    table_name VARCHAR(128) PRIMARY KEY,
    rows_loaded BIGINT NULL,
    status VARCHAR(20) NULL,
    updated_at TIMESTAMPTZ NULL DEFAULT NOW()
);
