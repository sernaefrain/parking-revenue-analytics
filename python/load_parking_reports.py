from pathlib import Path
from datetime import datetime
import hashlib
import pandas as pd
import pyodbc


# ------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------

RAW_FOLDER = Path(r"C:\Users\ES-10\Documents\parking_analytics\data\raw")

SQL_SERVER = r"DESKTOP-09F84RC\SQLEXPRESS"
SQL_DATABASE = "parking_analytics"

CONNECTION_STRING = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    f"SERVER={SQL_SERVER};"
    f"DATABASE={SQL_DATABASE};"
    "Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)


# ------------------------------------------------------------
# HELPER FUNCTIONS
# ------------------------------------------------------------

def calculate_file_hash(file_path: Path) -> str:
    """
    Creates a SHA-256 hash of the file contents.
    If the file changes, the hash changes.
    This is how we detect overwritten monthly files.
    """
    sha256 = hashlib.sha256()

    with open(file_path, "rb") as file:
        for chunk in iter(lambda: file.read(8192), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


def get_connection():
    """
    Creates a connection to SQL Server.
    """
    return pyodbc.connect(CONNECTION_STRING)


def file_already_loaded_and_unchanged(cursor, file_name: str, file_hash: str) -> bool:
    """
    Checks the file_load_log table to see whether this exact file version
    has already been loaded.
    """
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM stg.file_load_log
        WHERE file_name = ?
          AND file_hash = ?
          AND load_status = 'SUCCESS';
        """,
        file_name,
        file_hash
    )

    return cursor.fetchone()[0] > 0


def file_exists_with_different_hash(cursor, file_name: str, file_hash: str) -> bool:
    """
    Checks whether the file was loaded before but has since changed.
    This handles your middle-of-month overwrite scenario.
    """
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM stg.file_load_log
        WHERE file_name = ?
          AND file_hash <> ?
          AND load_status = 'SUCCESS';
        """,
        file_name,
        file_hash
    )

    return cursor.fetchone()[0] > 0


def delete_old_file_data(cursor, file_name: str):
    """
    Removes old rows for a file before reloading the updated version.
    """
    cursor.execute(
        """
        DELETE FROM stg.parking_transactions
        WHERE source_file = ?;
        """,
        file_name
    )

    cursor.execute(
        """
        DELETE FROM stg.file_load_log
        WHERE file_name = ?;
        """,
        file_name
    )


def clean_parking_file(file_path: Path, file_hash: str) -> pd.DataFrame:
    """
    Reads one Excel file, keeps only the required columns,
    renames them for SQL, and prepares clean data for loading.
    """

    required_columns = [
        "Entry Date/Time",
        "Exit Date/Time",
        "Payment",
        "Entry Plate Number",
        "Exit Plate Number"
    ]

    df = pd.read_excel(
        file_path,
        engine="openpyxl",
        usecols=required_columns
    )

    df = df.rename(columns={
        "Entry Date/Time": "entry_datetime",
        "Exit Date/Time": "exit_datetime",
        "Payment": "payment_amount",
        "Entry Plate Number": "entry_plate_number",
        "Exit Plate Number": "exit_plate_number"
    })

    df["entry_datetime"] = pd.to_datetime(df["entry_datetime"], errors="coerce")
    df["exit_datetime"] = pd.to_datetime(df["exit_datetime"], errors="coerce")

    df["payment_amount"] = pd.to_numeric(df["payment_amount"], errors="coerce").fillna(0)

    df["entry_plate_number"] = (
        df["entry_plate_number"]
        .astype(str)
        .str.strip()
        .str.upper()
        .replace({"NAN": None, "-": None})
    )

    df["exit_plate_number"] = (
        df["exit_plate_number"]
        .astype(str)
        .str.strip()
        .str.upper()
        .replace({"NAN": None, "-": None})
    )

    df["source_file"] = file_path.name
    df["source_file_hash"] = file_hash

    return df


def insert_transactions(cursor, df: pd.DataFrame):
    """
    Inserts cleaned transaction rows into SQL Server.
    """

    insert_sql = """
        INSERT INTO stg.parking_transactions (
            entry_datetime,
            exit_datetime,
            payment_amount,
            entry_plate_number,
            exit_plate_number,
            source_file,
            source_file_hash
        )
        VALUES (?, ?, ?, ?, ?, ?, ?);
    """

    rows = list(df[[
        "entry_datetime",
        "exit_datetime",
        "payment_amount",
        "entry_plate_number",
        "exit_plate_number",
        "source_file",
        "source_file_hash"
    ]].itertuples(index=False, name=None))

    cursor.fast_executemany = True
    cursor.executemany(insert_sql, rows)


def insert_load_log(cursor, file_path: Path, file_hash: str, rows_loaded: int):
    """
    Records a successful file load in the control table.
    """

    file_stat = file_path.stat()

    cursor.execute(
        """
        INSERT INTO stg.file_load_log (
            file_name,
            file_path,
            file_hash,
            file_size,
            file_modified_at,
            rows_loaded,
            load_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        file_path.name,
        str(file_path),
        file_hash,
        file_stat.st_size,
        datetime.fromtimestamp(file_stat.st_mtime),
        rows_loaded,
        "SUCCESS"
    )


# ------------------------------------------------------------
# MAIN PIPELINE
# ------------------------------------------------------------

def main():
    excel_files = sorted(
        list(RAW_FOLDER.glob("*.xlsx")) + list(RAW_FOLDER.glob("*.xls"))
    )

    if not excel_files:
        print(f"No Excel files found in: {RAW_FOLDER}")
        return

    conn = get_connection()
    cursor = conn.cursor()

    total_loaded_files = 0
    total_skipped_files = 0
    total_reloaded_files = 0

    try:
        for file_path in excel_files:
            file_name = file_path.name
            file_hash = calculate_file_hash(file_path)

            print(f"\nChecking file: {file_name}")

            if file_already_loaded_and_unchanged(cursor, file_name, file_hash):
                print("Skipped: file already loaded and unchanged.")
                total_skipped_files += 1
                continue

            if file_exists_with_different_hash(cursor, file_name, file_hash):
                print("Changed file detected. Deleting old rows and reloading.")
                delete_old_file_data(cursor, file_name)
                total_reloaded_files += 1
            else:
                print("New file detected. Loading.")

            df = clean_parking_file(file_path, file_hash)

            if df.empty:
                print("Skipped: file had no rows.")
                continue

            insert_transactions(cursor, df)
            insert_load_log(cursor, file_path, file_hash, len(df))

            conn.commit()

            print(f"Loaded {len(df):,} rows from {file_name}.")
            total_loaded_files += 1

        print("\nPipeline complete.")
        print(f"Files loaded: {total_loaded_files}")
        print(f"Files reloaded because they changed: {total_reloaded_files}")
        print(f"Files skipped because unchanged: {total_skipped_files}")

    except Exception as error:
        conn.rollback()
        print("Pipeline failed. Changes were rolled back.")
        print(error)

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()