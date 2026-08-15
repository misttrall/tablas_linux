IF OBJECT_ID('dbo.etl_execution_tables', 'U') IS NULL
CREATE TABLE dbo.etl_execution_tables (
    run_id INT NOT NULL,
    table_name VARCHAR(128) NOT NULL,
    chunks_total INT NULL,
    chunks_ok INT NULL,
    rows_extracted BIGINT NULL,
    duration_s FLOAT NULL,
    status VARCHAR(20) NULL,
    PRIMARY KEY (run_id, table_name)
);
