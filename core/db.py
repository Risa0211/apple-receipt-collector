"""SQLiteベースの状態管理（PythonAnywhere無料枠運用向け・元Supabase版APIと互換）"""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

_DB_PATH = Path(
    os.environ.get("SQLITE_DB_PATH")
    or (Path(__file__).resolve().parent.parent / "data" / "state.sqlite3")
)
_lock = Lock()


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(_DB_PATH, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


_SCHEMA = """
CREATE TABLE IF NOT EXISTS drive_token (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  email TEXT NOT NULL,
  token TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gmail_accounts (
  email TEXT PRIMARY KEY,
  token TEXT NOT NULL,
  added_at TEXT NOT NULL,
  last_sync_at TEXT,
  last_sync_count INTEGER DEFAULT 0,
  last_error TEXT
);

CREATE TABLE IF NOT EXISTS processed_messages (
  message_id TEXT NOT NULL,
  account_email TEXT NOT NULL,
  drive_file_id TEXT,
  pdf_filename TEXT,
  receipt_year_month TEXT,
  processed_at TEXT NOT NULL,
  PRIMARY KEY (message_id, account_email)
);

CREATE INDEX IF NOT EXISTS processed_messages_processed_at_idx
  ON processed_messages(processed_at DESC);

CREATE TABLE IF NOT EXISTS drive_folders (
  folder_name TEXT PRIMARY KEY,
  drive_folder_id TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  accounts_scanned INTEGER DEFAULT 0,
  pdfs_uploaded INTEGER DEFAULT 0,
  errors TEXT,
  triggered_by TEXT
);

CREATE INDEX IF NOT EXISTS sync_log_started_at_idx
  ON sync_log(started_at DESC);
"""


def init_db():
    with _lock, _conn() as c:
        c.executescript(_SCHEMA)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---- Drive Token ----

def save_drive_token(email: str, token_json: str):
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO drive_token (id, email, token, updated_at) VALUES (1, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET email=excluded.email, token=excluded.token, updated_at=excluded.updated_at",
            (email, token_json, now_iso()),
        )


def get_drive_token() -> Optional[dict]:
    with _lock, _conn() as c:
        row = c.execute("SELECT email, token FROM drive_token WHERE id=1").fetchone()
    if not row:
        return None
    return {"email": row["email"], "token": json.loads(row["token"])}


def delete_drive_token():
    with _lock, _conn() as c:
        c.execute("DELETE FROM drive_token WHERE id=1")


# ---- Gmail accounts (with token) ----

def save_gmail_account(email: str, token_json: str):
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO gmail_accounts (email, token, added_at) VALUES (?, ?, ?) "
            "ON CONFLICT(email) DO UPDATE SET token=excluded.token",
            (email, token_json, now_iso()),
        )


def update_gmail_token(email: str, token_json: str):
    with _lock, _conn() as c:
        c.execute("UPDATE gmail_accounts SET token=? WHERE email=?", (token_json, email))


def get_gmail_token(email: str) -> Optional[dict]:
    with _lock, _conn() as c:
        row = c.execute("SELECT token FROM gmail_accounts WHERE email=?", (email,)).fetchone()
    return json.loads(row["token"]) if row else None


def remove_gmail_account(email: str):
    with _lock, _conn() as c:
        c.execute("DELETE FROM processed_messages WHERE account_email=?", (email,))
        c.execute("DELETE FROM gmail_accounts WHERE email=?", (email,))


def list_gmail_accounts():
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT email, added_at, last_sync_at, last_sync_count, last_error "
            "FROM gmail_accounts ORDER BY added_at"
        ).fetchall()
    return [dict(r) for r in rows]


def add_gmail_account(email: str):
    """互換用no-op (save_gmail_account経由でtoken保存時に作成される)"""
    pass


def update_account_sync(email: str, count: int, error: Optional[str] = None):
    with _lock, _conn() as c:
        c.execute(
            "UPDATE gmail_accounts SET last_sync_at=?, last_sync_count=?, last_error=? WHERE email=?",
            (now_iso(), count, error, email),
        )


# ---- Processed messages ----

def is_processed(message_id: str, account_email: str) -> bool:
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT 1 FROM processed_messages WHERE message_id=? AND account_email=?",
            (message_id, account_email),
        ).fetchone()
    return row is not None


def mark_processed(
    message_id: str,
    account_email: str,
    drive_file_id: str,
    pdf_filename: str,
    receipt_year_month: str,
):
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO processed_messages "
            "(message_id, account_email, drive_file_id, pdf_filename, receipt_year_month, processed_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(message_id, account_email) DO UPDATE SET "
            "drive_file_id=excluded.drive_file_id, pdf_filename=excluded.pdf_filename, "
            "receipt_year_month=excluded.receipt_year_month, processed_at=excluded.processed_at",
            (message_id, account_email, drive_file_id, pdf_filename, receipt_year_month, now_iso()),
        )


def recent_processed(limit: int = 20):
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT message_id, account_email, drive_file_id, pdf_filename, receipt_year_month, processed_at "
            "FROM processed_messages ORDER BY processed_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def total_processed_count() -> int:
    with _lock, _conn() as c:
        row = c.execute("SELECT COUNT(*) AS n FROM processed_messages").fetchone()
    return row["n"] if row else 0


# ---- Drive folder cache ----

def get_drive_folder_id(folder_name: str) -> Optional[str]:
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT drive_folder_id FROM drive_folders WHERE folder_name=?", (folder_name,)
        ).fetchone()
    return row["drive_folder_id"] if row else None


def cache_drive_folder(folder_name: str, drive_folder_id: str):
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO drive_folders (folder_name, drive_folder_id, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(folder_name) DO UPDATE SET drive_folder_id=excluded.drive_folder_id",
            (folder_name, drive_folder_id, now_iso()),
        )


# ---- Sync log ----

def start_sync_log(triggered_by: str = "manual") -> int:
    with _lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO sync_log (started_at, triggered_by) VALUES (?, ?)",
            (now_iso(), triggered_by),
        )
        return cur.lastrowid


def finish_sync_log(log_id: int, accounts_scanned: int, pdfs_uploaded: int, errors: Optional[str]):
    with _lock, _conn() as c:
        c.execute(
            "UPDATE sync_log SET finished_at=?, accounts_scanned=?, pdfs_uploaded=?, errors=? WHERE id=?",
            (now_iso(), accounts_scanned, pdfs_uploaded, errors, log_id),
        )


def recent_sync_logs(limit: int = 5):
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT id, started_at, finished_at, accounts_scanned, pdfs_uploaded, errors, triggered_by "
            "FROM sync_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
