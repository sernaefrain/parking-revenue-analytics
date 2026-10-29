USE parking_analytics;
GO

-- I need a view that has these columns
CREATE OR ALTER VIEW analytics.vw_parking_transactions_clean AS
SELECT
	-- entry date, entry time, entry day of the week
	CAST(entry_datetime AS date) AS entry_date,
	CAST(entry_datetime AS time(0)) AS entry_time,
	DATENAME(WEEKDAY, entry_datetime) AS entry_day_of_week,

	-- payment
	payment_amount,

	-- exit date, exit time, exit day of the week
	CAST(exit_datetime AS date) AS exit_date,
	CAST(exit_datetime AS time(0)) AS exit_time,
	DATENAME(WEEKDAY, exit_datetime) AS exit_day_of_week,

	-- duration in hours
	CAST(
		DATEDIFF(MINUTE, entry_datetime, exit_datetime) / 60.0
		AS decimal(10,2)
		) AS duration_hours,

	-- bad plate column if entry and exit plate are not equal or has # or -
	entry_plate_number,
	exit_plate_number,
	CASE 
		WHEN entry_plate_number IS NULL 
          OR exit_plate_number IS NULL
          OR entry_plate_number <> exit_plate_number
          OR entry_plate_number LIKE '#'
          OR exit_plate_number LIKE '#'
          OR entry_plate_number LIKE '-'
          OR exit_plate_number LIKE '-'
        THEN 1
        ELSE 0
    END AS bad_plate_flag,

	-- overnight guest column if entry and exit date are different and duration in 8+ hours
	CASE
		WHEN CAST(entry_datetime AS date) <> CAST(exit_datetime AS date)
			AND DATEDIFF(MINUTE, entry_datetime, exit_datetime) >= 480
		THEN 1
		ELSE 0
	END AS overnight_guest_flag

FROM stg.parking_transactions

-- keep only payment greater than 0
WHERE payment_amount > 0;
GO

SELECT TOP 50 *
FROM analytics.vw_parking_transactions_clean
ORDER BY exit_date DESC, exit_time DESC;

