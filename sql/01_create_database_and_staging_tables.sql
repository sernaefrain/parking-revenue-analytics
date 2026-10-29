CREATE DATABASE parking_analytics;
GO

USE parking_analytics;
GO

-- Create schema and tables

CREATE SCHEMA stg;
GO

CREATE SCHEMA analytics;
GO

CREATE SCHEMA rpt;
GO

-- parking_transactions will store the clean parking data.
CREATE TABLE stg.parking_transactions (
    transaction_id INT IDENTITY(1,1) PRIMARY KEY,
    entry_datetime DATETIME2 NULL,
    exit_datetime DATETIME2 NULL,
    payment_amount DECIMAL(12,2) NULL,
    entry_plate_number VARCHAR(50) NULL,
    exit_plate_number VARCHAR(50) NULL,

    source_file VARCHAR(255) NOT NULL,
    source_file_hash VARCHAR(64) NOT NULL,
    loaded_at DATETIME2 NOT NULL DEFAULT SYSDATETIME()
);
GO

-- file_load_log will be the control table, it will let Python know whether a file is new, unchanged, or changed.
CREATE TABLE stg.file_load_log (
    file_name VARCHAR(255) PRIMARY KEY,
    file_path VARCHAR(500) NOT NULL,
    file_hash VARCHAR(64) NOT NULL,
    file_size BIGINT NOT NULL,
    file_modified_at DATETIME2 NOT NULL,
    rows_loaded INT NOT NULL,
    load_status VARCHAR(50) NOT NULL,
    loaded_at DATETIME2 NOT NULL DEFAULT SYSDATETIME()
);
GO

-- Get my server name
SELECT @@SERVERNAME AS server_name;