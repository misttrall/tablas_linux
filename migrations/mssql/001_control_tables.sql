IF OBJECT_ID('dbo.etl_execution', 'U') IS NULL
CREATE TABLE dbo.etl_execution (
    id INT IDENTITY(1,1) PRIMARY KEY,
    start_time DATETIME2 NOT NULL DEFAULT GETDATE(),
    end_time DATETIME2 NULL,
    status VARCHAR(20) NOT NULL,
    message NVARCHAR(MAX) NULL
);

IF OBJECT_ID('dbo.etl_progress', 'U') IS NULL
CREATE TABLE dbo.etl_progress (
    table_name VARCHAR(128) NOT NULL PRIMARY KEY,
    rows_loaded BIGINT NULL,
    status VARCHAR(20) NULL,
    updated_at DATETIME2 NULL DEFAULT GETDATE()
);
