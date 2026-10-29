/*
====================================================================
PROJECT: Parking Revenue Analytics
SCRIPT: 01_create_database_and_staging_tables.sql
LAYER: Database Infrastructure / Staging
====================================================================

PURPOSE:
    Creates the SQL Server database, schemas, and staging tables
    required by the Python ingestion pipeline.

    This script establishes the database structure. It does NOT
    import Excel files, calculate KPIs, or create reporting views.


WHEN TO RUN:
    1. Initial project setup on a new SQL Server instance.
    2. When rebuilding the database from scratch.
    3. After adding new tables or schemas to this script.

    IMPORTANT:
    You do NOT need to run this script every month.
    Monthly files are processed by the Python ingestion script.


OBJECTS CREATED:
    Database:
        parking_analytics

    Schemas:
        stg       = Imported transaction data and load tracking
        analytics = Cleaned data and business logic
        rpt       = Reporting views for Power BI

    Tables:
        stg.parking_transactions
        stg.file_load_log


IMPORTANT RULES:
    1. Do NOT change table or column names without also updating
       the Python ingestion script and dependent SQL views.

    2. Do NOT delete, truncate, or recreate staging tables when
       processing new monthly Excel files.

    3. Do NOT use DROP DATABASE, DROP TABLE, or TRUNCATE TABLE
       unless intentionally resetting data with an approved plan.

    4. Do NOT manually edit imported transaction records.
       Correct source files and reload them through Python.

    5. Preserve source_file and source_file_hash because Python
       uses them to detect previously imported and changed files.

    6. Keep financial values as DECIMAL, not FLOAT, to avoid
       floating-point precision issues in financial reporting.

    7. Keep transaction_id as an internal SQL identity key.
       It is NOT a unique identifier supplied by the parking
       system and may change when a file is reloaded.

    8. Do NOT put business calculations in this script.
       Revenue classifications, overnight parking rules,
       and management fees belong in analytical/reporting views.


WHEN TO MODIFY:
    - Adding new columns from the source Excel reports.
    - Adding new tables or schemas.
    - Introducing constraints, indexes, or audit controls.

    IMPORTANT:
    CREATE TABLE IF NOT EXISTS-style checks only prevent
    duplicate creation. They do NOT update existing tables.

    Existing tables require a separate, reviewed ALTER TABLE
    migration if their structure must change.


DEPENDENCIES:
    Before running:
        SQL Server Express must be installed and accessible.

    After running:
        1. Verify database and schemas exist.
        2. Verify both staging tables exist.
        3. Run the Python ingestion process.
        4. Create or update analytical and reporting views.


SAFETY / VERSION CONTROL:
    - Save all changes to this .sql file in GitHub.
    - Review changes before executing database modifications.
    - Never commit real transaction data or credentials.
    - Back up existing data before destructive migrations.
    - Test structural changes before applying them to
      a database containing real historical transactions.


SUCCESS CRITERIA:
    - Database parking_analytics exists.
    - Schemas stg, analytics, and rpt exist.
    - Both staging tables exist with the expected columns.
    - Re-execution does not delete data or create duplicates.
    - Python can connect and insert validated transactions.


KEY REMINDER:
    This script defines the STRUCTURE of the database.

    Python handles monthly data ingestion.
    SQL views handle business logic and reporting.
    Power BI handles visualization and user interaction.

====================================================================
*/

USE master;
GO

-- 1. Create database if it does not exist
IF DB_ID(N'parking_analytics') IS NULL
BEGIN
    CREATE DATABASE parking_analytics;
END;
GO

USE parking_analytics;
GO


-- 2. Create schemas
IF SCHEMA_ID('stg') IS NULL
    EXEC('CREATE SCHEMA stg');
GO

IF SCHEMA_ID('analytics') IS NULL
    EXEC('CREATE SCHEMA analytics');
GO

IF SCHEMA_ID('rpt') IS NULL
    EXEC('CREATE SCHEMA rpt');
GO


-- 3. Create transaction staging table
IF OBJECT_ID('stg.parking_transactions', 'U') IS NULL
BEGIN
    CREATE TABLE stg.parking_transactions
    (
        transaction_id INT IDENTITY(1,1) PRIMARY KEY,

        entry_datetime DATETIME2 NULL,
        exit_datetime DATETIME2 NULL,
        payment_amount DECIMAL(12,2) NULL,

        entry_plate_number VARCHAR(50) NULL,
        exit_plate_number VARCHAR(50) NULL,

        source_file VARCHAR(255) NOT NULL,
        source_file_hash VARCHAR(64) NOT NULL,

        loaded_at DATETIME2 NOT NULL
            DEFAULT SYSDATETIME()
    );
END;
GO


-- 4. Create file load control table
IF OBJECT_ID('stg.file_load_log', 'U') IS NULL
BEGIN
    CREATE TABLE stg.file_load_log
    (
        file_name VARCHAR(255) PRIMARY KEY,
        file_path VARCHAR(500) NOT NULL,
        file_hash VARCHAR(64) NOT NULL,

        file_size BIGINT NOT NULL,
        file_modified_at DATETIME2 NOT NULL,

        rows_loaded INT NOT NULL,
        load_status VARCHAR(50) NOT NULL,

        loaded_at DATETIME2 NOT NULL
            DEFAULT SYSDATETIME()
    );
END;
GO


-- 5. Verify tables exist
SELECT
    s.name AS schema_name,
    t.name AS table_name,
    t.create_date
FROM sys.tables AS t
INNER JOIN sys.schemas AS s
    ON t.schema_id = s.schema_id
WHERE s.name IN ('stg', 'analytics', 'rpt')
ORDER BY s.name, t.name;
GO

SELECT COUNT(*) AS total_transactions
FROM stg.parking_transactions;

SELECT COUNT(*) AS total_loaded_files
FROM stg.file_load_log;

