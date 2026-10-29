/*
PROJECT: Parking Revenue Analytics
PURPOSE: Preserve invalid source rows without silently changing or discarding them.
RUN: Once after Script 01. Safe to rerun; does not alter existing tables.
NOTE: Script 01 must have already created the stg schema.
*/
USE parking_analytics;
GO

IF OBJECT_ID(N'stg.parking_load_exceptions', N'U') IS NULL
BEGIN
    CREATE TABLE stg.parking_load_exceptions
    (
        exception_id BIGINT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_parking_load_exceptions PRIMARY KEY,
        source_file VARCHAR(255) NOT NULL,
        source_file_hash CHAR(64) NOT NULL,
        excel_row_number INT NOT NULL,
        issue_code VARCHAR(60) NOT NULL,
        issue_details NVARCHAR(1000) NOT NULL,
        raw_entry_datetime NVARCHAR(255) NULL,
        raw_exit_datetime NVARCHAR(255) NULL,
        raw_payment NVARCHAR(255) NULL,
        raw_entry_plate NVARCHAR(255) NULL,
        raw_exit_plate NVARCHAR(255) NULL,
        recorded_at DATETIME2 NOT NULL
            CONSTRAINT DF_parking_load_exceptions_recorded_at DEFAULT SYSDATETIME()
    );
END;
GO

SELECT name, create_date
FROM sys.tables
WHERE object_id = OBJECT_ID(N'stg.parking_load_exceptions', N'U');
GO
