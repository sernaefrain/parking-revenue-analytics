USE parking_analytics;
GO

CREATE OR ALTER VIEW rpt.vw_parking_dashboard_fact AS
SELECT
    -- Revenue recognition date
    exit_date AS transaction_date,

    -- Month fields
    DATEFROMPARTS(YEAR(exit_date), MONTH(exit_date), 1) AS month_start,
    
    -- Date/time fields
    entry_date,
    entry_time,
    exit_date,
    exit_time,
    
    -- Entry hour for hourly revenue chart
    DATEPART(HOUR, entry_time) AS entry_hour,

    -- Payment
    payment_amount,

    -- Duration
    duration_hours,

    CASE
        WHEN duration_hours >= 0 AND duration_hours < 2 THEN '0-2 hours'
        WHEN duration_hours >= 2 AND duration_hours < 4 THEN '2-4 hours'
        WHEN duration_hours >= 4 AND duration_hours < 6 THEN '4-6 hours'
        WHEN duration_hours >= 6 AND duration_hours < 8 THEN '6-8 hours'
        WHEN duration_hours >= 8 THEN '8+ hours'
        ELSE 'Unknown'
    END AS duration_bucket,

    CASE
        WHEN duration_hours >= 0 AND duration_hours < 2 THEN 1
        WHEN duration_hours >= 2 AND duration_hours < 4 THEN 2
        WHEN duration_hours >= 4 AND duration_hours < 6 THEN 3
        WHEN duration_hours >= 6 AND duration_hours < 8 THEN 4
        WHEN duration_hours >= 8 THEN 5
        ELSE 99
    END AS duration_bucket_sort,

    -- Plate quality
    bad_plate_flag,

    -- Overnight guest logic from your clean view
    overnight_guest_flag

FROM analytics.vw_parking_transactions_clean
WHERE payment_amount > 0
  AND exit_date IS NOT NULL
  AND entry_date IS NOT NULL;
GO

SELECT TOP 50 *
FROM rpt.vw_parking_dashboard_fact;
GO