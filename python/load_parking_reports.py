"""Load monthly parking transaction Excel files into SQL Server.

Expected SQL objects (created separately):
  stg.parking_transactions(entry_datetime, exit_datetime, payment_amount,
      entry_plate_number, exit_plate_number, source_file, source_file_hash)
  stg.file_load_log(file_name, file_path, file_hash, file_size,
      file_modified_at, rows_loaded, load_status)

By default, scans <repository>/data/raw for .xlsx files, and loads each file
atomically. An existing successful file with the same hash and matching row
count is skipped. A changed file is validated BEFORE replacing its records.

This version maintains a CURRENT-STATE file_load_log (one success record per
filename); it does not preserve a full history of earlier loads. It matches
the original script's SQL column contract without requiring a new schema.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sys
from datetime import datetime
from contextlib import closing
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
import pyodbc

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_FOLDER = Path(os.getenv("PARKING_RAW_FOLDER", str(PROJECT_ROOT / "data" / "incoming")))
SQL_SERVER = os.getenv("PARKING_SQL_SERVER", r"DESKTOP-09F84RC\SQLEXPRESS")
SQL_DATABASE = os.getenv("PARKING_SQL_DATABASE", "parking_analytics")
ODBC_DRIVER = os.getenv("PARKING_ODBC_DRIVER", "ODBC Driver 18 for SQL Server")

REQUIRED_COLUMNS = {
    "Entry Date/Time": "entry_datetime",
    "Exit Date/Time": "exit_datetime",
    "Payment": "payment_amount",
    "Entry Plate Number": "entry_plate_number",
    "Exit Plate Number": "exit_plate_number",
}

LOG = logging.getLogger("parking_ingest")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def connect() -> pyodbc.Connection:
    # Windows integrated authentication; no password stored in source control.
    connection_string = (
        f"DRIVER={{{ODBC_DRIVER}}};"
        f"SERVER={SQL_SERVER};"
        f"DATABASE={SQL_DATABASE};"
        "Trusted_Connection=yes;"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
        "Connection Timeout=15;"
    )
    return pyodbc.connect(connection_string, autocommit=False)


def normalize_plate(value: object) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip().upper()
    return None if text in {"", "NAN", "NONE", "NULL", "-"} else text


def load_and_validate(path: Path) -> list[tuple]:
    try:
        df = pd.read_excel(path, engine="openpyxl", dtype={
            "Entry Plate Number": "string",
            "Exit Plate Number": "string",
        })
    except Exception as exc:
        raise ValueError(f"Cannot read Excel file {path.name}: {exc}") from exc

    missing = set(REQUIRED_COLUMNS).difference(df.columns)
    if missing:
        raise ValueError(f"{path.name}: missing required columns: {sorted(missing)}")

    df = df[list(REQUIRED_COLUMNS)].rename(columns=REQUIRED_COLUMNS)
    if df.empty:
        raise ValueError(f"{path.name}: spreadsheet contains no transaction rows")

    # Treat fully empty rows as spreadsheet padding, not transactions.
    df = df.dropna(how="all", subset=list(REQUIRED_COLUMNS.values()))
    if df.empty:
        raise ValueError(f"{path.name}: no nonempty transaction rows")

    for column in ("entry_datetime", "exit_datetime"):
        raw = df[column]
        values = pd.to_datetime(raw, errors="coerce")
        invalid = values.isna()
        if invalid.any():
            excel_rows = (df.index[invalid] + 2).tolist()[:10]
            raise ValueError(f"{path.name}: invalid/missing {column} at Excel row(s): {excel_rows}")
        df[column] = values

    bad_order = df["exit_datetime"] < df["entry_datetime"]
    if bad_order.any():
        excel_rows = (df.index[bad_order] + 2).tolist()[:10]
        raise ValueError(f"{path.name}: exit precedes entry at Excel row(s): {excel_rows}")

    # Preserve genuine zero and negative payment amounts (e.g. refunds).
    # Never silently convert invalid values into $0.
    payments = []
    invalid_payments = []
    for idx, value in df["payment_amount"].items():
        try:
            if pd.isna(value):
                raise InvalidOperation("missing payment")
            amount = Decimal(str(value).strip().replace(",", "").replace("$", ""))
            if not amount.is_finite():
                raise InvalidOperation("non-finite payment")
            if amount != amount.quantize(Decimal("0.01")):
                raise InvalidOperation("payment has more than 2 decimals")
            payments.append(amount)
        except (InvalidOperation, ValueError, TypeError):
            invalid_payments.append(int(idx) + 2)
            payments.append(None)
    if invalid_payments:
        raise ValueError(f"{path.name}: invalid/missing payment at Excel row(s): {invalid_payments[:10]}")

    rows = []
    for (_, item), amount in zip(df.iterrows(), payments):
        rows.append((
            item["entry_datetime"].to_pydatetime(),
            item["exit_datetime"].to_pydatetime(),
            amount,
            normalize_plate(item["entry_plate_number"]),
            normalize_plate(item["exit_plate_number"]),
        ))
    return rows


def get_previous_state(cursor: pyodbc.Cursor, name: str) -> tuple[str, int] | None:
    cursor.execute(
        """SELECT TOP (1) file_hash, rows_loaded
           FROM stg.file_load_log
           WHERE file_name = ? AND load_status = 'SUCCESS'
           ORDER BY file_modified_at DESC, file_hash DESC""",
        name,
    )
    row = cursor.fetchone()
    return (str(row[0]), int(row[1])) if row else None


def get_existing_row_count(cursor: pyodbc.Cursor, name: str) -> int:
    cursor.execute(
        "SELECT COUNT_BIG(*) FROM stg.parking_transactions WHERE source_file = ?", name
    )
    return int(cursor.fetchone()[0])


def process_file(conn: pyodbc.Connection, path: Path) -> str:
    name = path.name
    digest = file_hash(path)
    cursor = conn.cursor()
    try:
        previous = get_previous_state(cursor, name)
        existing_count = get_existing_row_count(cursor, name)
        if previous and previous[0] == digest and previous[1] == existing_count:
            conn.rollback()  # end the read-only transaction
            LOG.info("SKIP %s: same file content, %s records", name, existing_count)
            return "skipped"

        # Do not replace orphaned SQL data without a matching load-log record.
        if previous is None and existing_count:
            raise RuntimeError(
                f"{name}: {existing_count} SQL records exist without a successful "
                "load-log entry. Investigate before overwriting."
            )

        # If a file is unchanged but its row count differs, fail for manual
        # reconciliation rather than quietly overwriting externally changed data.
        if previous and previous[0] == digest and previous[1] != existing_count:
            raise RuntimeError(
                f"{name}: SQL count {existing_count} differs from load-log "
                f"count {previous[1]}; investigate before reloading."
            )

        rows = load_and_validate(path)  # validates before any deletion
        stat = path.stat()

        # Replace records and their CURRENT-STATE log together, in one transaction.
        cursor.execute("DELETE FROM stg.parking_transactions WHERE source_file = ?", name)
        cursor.execute("DELETE FROM stg.file_load_log WHERE file_name = ?", name)
        insert_sql = """
            INSERT INTO stg.parking_transactions (
                entry_datetime, exit_datetime, payment_amount,
                entry_plate_number, exit_plate_number, source_file, source_file_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        # Regular executemany is more predictable for small/medium workloads;
        # switch to fast_executemany only after verifying driver compatibility.
        cursor.executemany(insert_sql, [(a, b, c, d, e, name, digest) for a, b, c, d, e in rows])
        cursor.execute(
            """INSERT INTO stg.file_load_log (
                file_name, file_path, file_hash, file_size,
                file_modified_at, rows_loaded, load_status
            ) VALUES (?, ?, ?, ?, ?, ?, 'SUCCESS')""",
            name, str(path), digest, stat.st_size,
            datetime.fromtimestamp(stat.st_mtime), len(rows),
        )
        # Verify inserted count before committing.
        actual = get_existing_row_count(cursor, name)
        if actual != len(rows):
            raise RuntimeError(f"Inserted row-count mismatch: expected {len(rows)}, got {actual}")
        conn.commit()
        action = "RELOADED" if previous else "LOADED"
        LOG.info("%s %s: %s rows", action, name, len(rows))
        return "reloaded" if previous else "loaded"
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    LOG.info("Folder: %s", RAW_FOLDER)
    LOG.info("SQL Server: %s | Database: %s", SQL_SERVER, SQL_DATABASE)
    if not RAW_FOLDER.is_dir():
        LOG.error("Data folder does not exist: %s", RAW_FOLDER)
        return 1
    files = sorted(path for path in RAW_FOLDER.glob("*.xlsx")
                   if not path.name.startswith("~$"))
    if not files:
        LOG.warning("No .xlsx files found in %s", RAW_FOLDER)
        return 0

    results = {"loaded": 0, "reloaded": 0, "skipped": 0}
    try:
        with closing(connect()) as conn:
            for path in files:
                outcome = process_file(conn, path)
                results[outcome] += 1
    except Exception:
        LOG.exception("Pipeline FAILED; current file's SQL changes were rolled back")
        return 1
    LOG.info("Complete | New: %s | Replaced: %s | Unchanged: %s",
             results["loaded"], results["reloaded"], results["skipped"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
