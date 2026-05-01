"""Supabaseベースの状態管理"""
import json
import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()


@lru_cache(maxsize=1)
def _client() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 未設定")
    return create_client(url, key)


def init_db():
    """旧SQLite版互換のためのno-op。Supabaseはマイグレーション済み前提"""
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---- Drive Token ----

def save_drive_token(email: str, token_json: str):
    _client().table("drive_token").upsert({
        "id": 1,
        "email": email,
        "token": json.loads(token_json),
        "updated_at": now_iso(),
    }).execute()


def get_drive_token() -> Optional[dict]:
    """{'email': ..., 'token': {...}} or None"""
    r = _client().table("drive_token").select("*").eq("id", 1).execute()
    if not r.data:
        return None
    return {"email": r.data[0]["email"], "token": r.data[0]["token"]}


def delete_drive_token():
    _client().table("drive_token").delete().eq("id", 1).execute()


# ---- Gmail accounts (with token) ----

def save_gmail_account(email: str, token_json: str):
    """OAuth成功時に呼ぶ。新規追加 or 既存トークン更新"""
    _client().table("gmail_accounts").upsert({
        "email": email,
        "token": json.loads(token_json),
        "added_at": now_iso(),
    }, on_conflict="email").execute()


def update_gmail_token(email: str, token_json: str):
    """refresh時のtoken更新"""
    _client().table("gmail_accounts").update({
        "token": json.loads(token_json),
    }).eq("email", email).execute()


def get_gmail_token(email: str) -> Optional[dict]:
    r = _client().table("gmail_accounts").select("token").eq("email", email).execute()
    if not r.data:
        return None
    return r.data[0]["token"]


def remove_gmail_account(email: str):
    c = _client()
    c.table("processed_messages").delete().eq("account_email", email).execute()
    c.table("gmail_accounts").delete().eq("email", email).execute()


def list_gmail_accounts():
    r = _client().table("gmail_accounts").select(
        "email, added_at, last_sync_at, last_sync_count, last_error"
    ).order("added_at").execute()
    return r.data or []


# 旧API互換: WebUIフォームから使われる (gmail_accounts側でtokenが先に保存される)
def add_gmail_account(email: str):
    """save_gmail_accountを呼ぶ前提で何もしない（互換用）"""
    pass


def update_account_sync(email: str, count: int, error: Optional[str] = None):
    _client().table("gmail_accounts").update({
        "last_sync_at": now_iso(),
        "last_sync_count": count,
        "last_error": error,
    }).eq("email", email).execute()


# ---- Processed messages ----

def is_processed(message_id: str, account_email: str) -> bool:
    r = _client().table("processed_messages").select("message_id").eq(
        "message_id", message_id
    ).eq("account_email", account_email).execute()
    return bool(r.data)


def mark_processed(
    message_id: str,
    account_email: str,
    drive_file_id: str,
    pdf_filename: str,
    receipt_year_month: str,
):
    _client().table("processed_messages").upsert({
        "message_id": message_id,
        "account_email": account_email,
        "drive_file_id": drive_file_id,
        "pdf_filename": pdf_filename,
        "receipt_year_month": receipt_year_month,
        "processed_at": now_iso(),
    }, on_conflict="message_id,account_email").execute()


def recent_processed(limit: int = 20):
    r = _client().table("processed_messages").select("*").order(
        "processed_at", desc=True
    ).limit(limit).execute()
    return r.data or []


def total_processed_count() -> int:
    r = _client().table("processed_messages").select(
        "message_id", count="exact"
    ).execute()
    return r.count or 0


# ---- Drive folder cache ----

def get_drive_folder_id(folder_name: str) -> Optional[str]:
    r = _client().table("drive_folders").select("drive_folder_id").eq(
        "folder_name", folder_name
    ).execute()
    return r.data[0]["drive_folder_id"] if r.data else None


def cache_drive_folder(folder_name: str, drive_folder_id: str):
    _client().table("drive_folders").upsert({
        "folder_name": folder_name,
        "drive_folder_id": drive_folder_id,
        "created_at": now_iso(),
    }, on_conflict="folder_name").execute()


# ---- Sync log ----

def start_sync_log(triggered_by: str = "manual") -> int:
    r = _client().table("sync_log").insert({
        "started_at": now_iso(),
        "triggered_by": triggered_by,
    }).execute()
    return r.data[0]["id"]


def finish_sync_log(log_id: int, accounts_scanned: int, pdfs_uploaded: int, errors: Optional[str]):
    _client().table("sync_log").update({
        "finished_at": now_iso(),
        "accounts_scanned": accounts_scanned,
        "pdfs_uploaded": pdfs_uploaded,
        "errors": errors,
    }).eq("id", log_id).execute()


def recent_sync_logs(limit: int = 5):
    r = _client().table("sync_log").select("*").order(
        "id", desc=True
    ).limit(limit).execute()
    return r.data or []
