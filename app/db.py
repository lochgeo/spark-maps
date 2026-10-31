"""SQLite storage for constituency results and district headquarters.

The database is a small, disposable cache built from ``data/results.csv`` and
``data/district_hqs.csv``. It is created automatically on startup and rebuilt
whenever the source files are newer or the schema version changes.
"""

from __future__ import annotations

import csv
import os
import sqlite3
from pathlib import Path

SCHEMA_VERSION = "2"

SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
    ac_no            INTEGER NOT NULL,
    election_year    INTEGER NOT NULL,
    name             TEXT NOT NULL,
    district         TEXT NOT NULL,
    winner           TEXT NOT NULL,
    party            TEXT NOT NULL,
    alliance         TEXT NOT NULL,
    votes            INTEGER NOT NULL,
    vote_share       REAL NOT NULL,
    runner_up        TEXT NOT NULL,
    runner_up_party  TEXT NOT NULL,
    margin           INTEGER NOT NULL,
    PRIMARY KEY (ac_no, election_year)
);
CREATE INDEX IF NOT EXISTS idx_results_year ON results (election_year);
CREATE INDEX IF NOT EXISTS idx_results_district ON results (district);

CREATE TABLE IF NOT EXISTS district_hqs (
    district      TEXT PRIMARY KEY,
    headquarters  TEXT NOT NULL,
    latitude      REAL NOT NULL,
    longitude     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""

RESULT_FIELDS = (
    "ac_no",
    "election_year",
    "name",
    "district",
    "winner",
    "party",
    "alliance",
    "votes",
    "vote_share",
    "runner_up",
    "runner_up_party",
    "margin",
)


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _seed_results(conn: sqlite3.Connection, csv_path: Path) -> None:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = [
            (
                int(row["ac_no"]),
                int(row["election_year"]),
                row["name"],
                row["district"],
                row["winner"],
                row["party"],
                row["alliance"],
                int(row["votes"]),
                float(row["vote_share"]),
                row["runner_up"],
                row["runner_up_party"],
                int(row["margin"]),
            )
            for row in csv.DictReader(handle)
        ]
    conn.executemany(
        f"INSERT INTO results ({', '.join(RESULT_FIELDS)}) "
        f"VALUES ({', '.join('?' * len(RESULT_FIELDS))})",
        rows,
    )
    conn.commit()


def _seed_headquarters(conn: sqlite3.Connection, csv_path: Path) -> None:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = [
            (
                row["district"],
                row["headquarters"],
                float(row["latitude"]),
                float(row["longitude"]),
            )
            for row in csv.DictReader(handle)
        ]
    conn.executemany(
        "INSERT INTO district_hqs (district, headquarters, latitude, longitude) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def _schema_version(conn: sqlite3.Connection) -> str | None:
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.OperationalError:
        return None
    return row["value"] if row else None


def _database_is_current(db_path: Path, newest_csv: float) -> bool:
    if not db_path.exists() or db_path.stat().st_mtime < newest_csv:
        return False
    conn = connect(db_path)
    try:
        if _schema_version(conn) != SCHEMA_VERSION:
            return False
        count = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]
        return count > 0
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


def ensure_database(db_path: Path, results_csv: Path, hq_csv: Path) -> None:
    """Create or refresh the SQLite database from the source CSVs atomically."""
    for path in (results_csv, hq_csv):
        if not path.exists():
            raise FileNotFoundError(f"Data file not found: {path}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    newest_csv = max(results_csv.stat().st_mtime, hq_csv.stat().st_mtime)
    if _database_is_current(db_path, newest_csv):
        return

    tmp_path = db_path.with_name(f"{db_path.name}.tmp.{os.getpid()}")
    tmp_path.unlink(missing_ok=True)
    conn = connect(tmp_path)
    try:
        conn.executescript(SCHEMA)
        _seed_results(conn, results_csv)
        _seed_headquarters(conn, hq_csv)
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
            (SCHEMA_VERSION,),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        os.replace(tmp_path, db_path)
    except PermissionError:
        # On Windows, if another process has db_path open, fall back to in-place update
        tmp_path.unlink(missing_ok=True)
        if not _database_is_current(db_path, newest_csv):
            conn = connect(db_path)
            try:
                conn.executescript(
                    "DROP TABLE IF EXISTS results;"
                    "DROP TABLE IF EXISTS district_hqs;"
                    "DROP TABLE IF EXISTS meta;"
                )
                conn.executescript(SCHEMA)
                _seed_results(conn, results_csv)
                _seed_headquarters(conn, hq_csv)
                conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                    (SCHEMA_VERSION,),
                )
                conn.commit()
            finally:
                conn.close()


def fetch_results(db_path: Path) -> list[dict]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM results ORDER BY election_year, ac_no"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def fetch_headquarters(db_path: Path) -> list[dict]:
    conn = connect(db_path)
    try:
        rows = conn.execute("SELECT * FROM district_hqs ORDER BY district").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
