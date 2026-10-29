"""Load valid parking rows and quarantine invalid source rows in SQL Server.

Prerequisites: SQL Script 01 and 07_create_ingestion_exceptions.sql.
One transaction per monthly file; changed versions replace earlier valid and
exception rows together. The file_load_log is current-state, not load history.
"""
from __future__ import annotations

import hashlib
import logging
import os
import sys
from contextlib import closing
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
import pyodbc

ROOT = Path(__file__).resolve().parent.parent
INPUT_FOLDER = Path(os.getenv('PARKING_RAW_FOLDER', str(ROOT / 'data' / 'incoming')))
SQL_SERVER = os.getenv('PARKING_SQL_SERVER', r'DESKTOP-09F84RC\SQLEXPRESS')
SQL_DATABASE = os.getenv('PARKING_SQL_DATABASE', 'parking_analytics')
ODBC_DRIVER = os.getenv('PARKING_ODBC_DRIVER', 'ODBC Driver 18 for SQL Server')
REQUIRED = {
    'Entry Date/Time': 'entry_datetime',
    'Exit Date/Time': 'exit_datetime',
    'Payment': 'payment_amount',
    'Entry Plate Number': 'entry_plate_number',
    'Exit Plate Number': 'exit_plate_number',
}
LOG = logging.getLogger('parking_ingest')


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def connect() -> pyodbc.Connection:
    connection_string = (
        f'DRIVER={{{ODBC_DRIVER}}};SERVER={SQL_SERVER};DATABASE={SQL_DATABASE};'
        'Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes;'
        'Connection Timeout=15;'
    )
    return pyodbc.connect(connection_string, autocommit=False)


def raw_text(value: object) -> str | None:
    if pd.isna(value):
        return None
    return str(value)[:255]


def plate(value: object) -> str | None:
    text = raw_text(value)
    if text is None:
        return None
    result = text.strip().upper()
    return None if result in {'', 'NAN', 'NONE', 'NULL', '-'} else result[:50]


def parse_date(value: object) -> datetime | None:
    if pd.isna(value):
        return None
    try:
        parsed = pd.to_datetime(value, errors='coerce')
        if pd.isna(parsed):
            return None
        return parsed.to_pydatetime()
    except (ValueError, TypeError, OverflowError):
        return None


def parse_money(value: object) -> Decimal | None:
    if pd.isna(value):
        return None
    try:
        amount = Decimal(str(value).strip().replace('$', '').replace(',', ''))
        if not amount.is_finite() or amount != amount.quantize(Decimal('0.01')):
            return None
        if abs(amount) >= Decimal('10000000000'):
            return None
        return amount
    except (InvalidOperation, TypeError, ValueError):
        return None


def prepare_rows(path: Path) -> tuple[list[tuple], list[tuple], int]:
    df = pd.read_excel(path, engine='openpyxl', dtype={
        'Entry Plate Number': 'string', 'Exit Plate Number': 'string'
    })
    missing = set(REQUIRED) - set(df.columns)
    if missing:
        raise ValueError(f'{path.name}: missing required columns: {sorted(missing)}')
    df = df[list(REQUIRED)]
    df = df.dropna(how='all')
    if df.empty:
        raise ValueError(f'{path.name}: no transaction rows found')

    valid, invalid = [], []
    for ix, record in df.iterrows():
        excel_row = int(ix) + 2  # Assumes one header row, no skipped Excel rows
        entry = parse_date(record['Entry Date/Time'])
        exit_ = parse_date(record['Exit Date/Time'])
        amount = parse_money(record['Payment'])
        issues = []
        if entry is None:
            issues.append('INVALID_ENTRY_DATETIME')
        if exit_ is None:
            issues.append('INVALID_EXIT_DATETIME')
        if amount is None:
            issues.append('INVALID_PAYMENT')
        if entry is not None and exit_ is not None and exit_ < entry:
            issues.append('EXIT_BEFORE_ENTRY')

        if issues:
            invalid.append((
                excel_row, '|'.join(issues)[:60], ', '.join(issues),
                raw_text(record['Entry Date/Time']),
                raw_text(record['Exit Date/Time']),
                raw_text(record['Payment']),
                raw_text(record['Entry Plate Number']),
                raw_text(record['Exit Plate Number']),
            ))
        else:
            valid.append((
                entry, exit_, amount,
                plate(record['Entry Plate Number']),
                plate(record['Exit Plate Number']),
            ))
    return valid, invalid, len(df)


def previous_state(cur: pyodbc.Cursor, name: str) -> tuple[str, int] | None:
    row = cur.execute(
        "SELECT file_hash, rows_loaded FROM stg.file_load_log "
        "WHERE file_name=? AND load_status='SUCCESS'", name
    ).fetchone()
    return (str(row[0]), int(row[1])) if row else None


def count_for_file(cur: pyodbc.Cursor, table: str, name: str) -> int:
    # The table argument comes exclusively from fixed source-code literals.
    return int(cur.execute(
        f'SELECT COUNT_BIG(*) FROM {table} WHERE source_file=?', name
    ).fetchone()[0])


def process_file(conn: pyodbc.Connection, path: Path) -> str:
    name = path.name
    digest = sha256(path)
    cur = conn.cursor()
    try:
        prev = previous_state(cur, name)
        existing = count_for_file(cur, 'stg.parking_transactions', name)
        except_count = count_for_file(cur, 'stg.parking_load_exceptions', name)
        if prev and prev[0] == digest and prev[1] == existing:
            conn.rollback()
            LOG.info('SKIP %s: %s valid rows, %s exceptions', name, existing, except_count)
            return 'skipped'
        if not prev and (existing or except_count):
            raise RuntimeError(f'{name}: orphaned SQL rows exist without a load-log entry')
        if prev and prev[0] == digest and prev[1] != existing:
            raise RuntimeError(f'{name}: SQL count and load-log count do not match')

        valid, invalid, source_count = prepare_rows(path)
        if not valid:
            raise ValueError(f'{name}: no valid transactions; no SQL data was replaced')
        stat = path.stat()

        cur.execute('DELETE FROM stg.parking_transactions WHERE source_file=?', name)
        cur.execute('DELETE FROM stg.parking_load_exceptions WHERE source_file=?', name)
        cur.execute('DELETE FROM stg.file_load_log WHERE file_name=?', name)

        cur.executemany('''INSERT INTO stg.parking_transactions (
            entry_datetime, exit_datetime, payment_amount, entry_plate_number,
            exit_plate_number, source_file, source_file_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?)''',
            [(a, b, c, d, e, name, digest) for a, b, c, d, e in valid])

        if invalid:
            cur.executemany('''INSERT INTO stg.parking_load_exceptions (
                source_file, source_file_hash, excel_row_number,
                issue_code, issue_details, raw_entry_datetime, raw_exit_datetime,
                raw_payment, raw_entry_plate, raw_exit_plate
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                [(name, digest, *r) for r in invalid])

        cur.execute('''INSERT INTO stg.file_load_log (
            file_name, file_path, file_hash, file_size, file_modified_at,
            rows_loaded, load_status
        ) VALUES (?, ?, ?, ?, ?, ?, 'SUCCESS')''',
            name, str(path), digest, stat.st_size,
            datetime.fromtimestamp(stat.st_mtime), len(valid))

        if count_for_file(cur, 'stg.parking_transactions', name) != len(valid):
            raise RuntimeError(f'{name}: inserted valid-row count mismatch')
        if count_for_file(cur, 'stg.parking_load_exceptions', name) != len(invalid):
            raise RuntimeError(f'{name}: inserted exception-row count mismatch')
        conn.commit()
        action = 'REPLACED' if prev else 'LOADED'
        LOG.info('%s %s | source=%s valid=%s exceptions=%s',
                 action, name, source_count, len(valid), len(invalid))
        return 'replaced' if prev else 'loaded'
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    LOG.info('Folder: %s', INPUT_FOLDER)
    LOG.info('SQL Server: %s | Database: %s', SQL_SERVER, SQL_DATABASE)
    if not INPUT_FOLDER.is_dir():
        LOG.error('Folder does not exist: %s', INPUT_FOLDER)
        return 1
    files = sorted(p for p in INPUT_FOLDER.glob('*.xlsx') if not p.name.startswith('~$'))
    if not files:
        LOG.warning('No .xlsx files found')
        return 0
    totals = {'loaded': 0, 'replaced': 0, 'skipped': 0}
    try:
        with closing(connect()) as conn:
            for path in files:
                totals[process_file(conn, path)] += 1
    except Exception:
        LOG.exception('Pipeline FAILED; changes to current file rolled back')
        return 1
    LOG.info('Complete | New=%s Replaced=%s Unchanged=%s',
             totals['loaded'], totals['replaced'], totals['skipped'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
