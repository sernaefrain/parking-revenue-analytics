# Parking Revenue Analytics

**End-to-End Business Intelligence & Data Automation Project**

SQL Server | Python | Power BI | Git & GitHub

## Project Overview

An end-to-end validated, repeatable analytics pipeline project that automatically processes monthly parking transaction files and updates a management dashboard.

The sustem tracks parking revenue, transaction volume, cusomter usage patterns, and management fee eligibility.

### Business Questions

- How much revenue does the parking operation generate?
- How much revenue is attributable to hotel-classified parking?
- What revenue is eligible for management fee calculations?
- How much is owed in management fees?
- How does revenue change by day, month, and year?
- Which vehicle entry hours and weekdays generate the most revenue?

## Technology Stack
| Tool | Purpose |
|----|----|
| SQL Server | Data storage, business logic, and reporting views | 
| Python (pandas) | File ingestion, cleaning, validation, and automation |
| Power BI | Interactive dashboards and KPI monitoring |
| Git & GitHub | Version control and project documentation |

## Data Pipeline

    1. Add files: drop new files into the raw data folder.
    2. Run Python: the loader reads each file, validates its columns, loads only new or changed files, and logs what happened. 
    3. Review load results:
    4. Refresh PowerBI



### Hotel Parking Classification

A transaction is classified as hotel parking when:

1. Entry date and exit date are different.
2. Parking duration is at least 8 hours.

Article labels are excluded because they are not reliable identifiers.

### Management Fee

- Eligible Revenue = Total Revenue - Hotel Revenue
- Annual Threshold = $300,000
- Management Fee = 5% x MAX(0, Annual Eligible Revenue - $300,000)

The threshold applies to eligible revenue within each calendar year.

## Planned Architecture

The following diagram illustrates the planned end-to-end
data pipeline, from monthly Excel exports to interactive
Power BI dashboards.

![Parking Analytics Data Pipeline](docs/Workflow.png)

## Local SQL Server Setup

- Database engine: SQL Server 2025 Standard Developer
- Instance: MSSQLSERVER (default instance)
- SSMS server name: localhost
- Authentication: Windows Authentication
