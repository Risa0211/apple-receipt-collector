"""OAuth flow と トークン管理（Supabaseバックエンド）"""
import json
import os
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from config import (
    CREDENTIALS_PATH,
    DRIVE_SCOPES,
    GMAIL_SCOPES,
)
from core import db


def public_base_url() -> str:
    """OAuth redirect URI用のベースURL（環境変数優先）"""
    return os.environ.get("PUBLIC_BASE_URL", "http://localhost:8765").rstrip("/")


def _redirect_uri(kind: str) -> str:
    return f"{public_base_url()}/oauth/{kind}/callback"


def credentials_exist() -> bool:
    return CREDENTIALS_PATH.exists()


def build_flow(kind: str) -> Flow:
    """kind: 'drive' | 'gmail'"""
    scopes = DRIVE_SCOPES if kind == "drive" else GMAIL_SCOPES
    return Flow.from_client_secrets_file(
        str(CREDENTIALS_PATH),
        scopes=scopes,
        redirect_uri=_redirect_uri(kind),
    )


def authorize_url(kind: str, state: str) -> str:
    flow = build_flow(kind)
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="false",
        prompt="consent",
        state=state,
    )
    return url


def exchange_code(kind: str, full_callback_url: str) -> Credentials:
    flow = build_flow(kind)
    flow.fetch_token(authorization_response=full_callback_url)
    return flow.credentials


# ---- Token loading from Supabase + auto refresh ----

def _credentials_from_dict(token_dict: dict, scopes: list) -> Credentials:
    return Credentials.from_authorized_user_info(token_dict, scopes)


def load_drive_credentials() -> Optional[Credentials]:
    rec = db.get_drive_token()
    if not rec:
        return None
    creds = _credentials_from_dict(rec["token"], DRIVE_SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        db.save_drive_token(rec["email"], creds.to_json())
    return creds


def load_gmail_credentials(email: str) -> Optional[Credentials]:
    token = db.get_gmail_token(email)
    if not token:
        return None
    creds = _credentials_from_dict(token, GMAIL_SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        db.update_gmail_token(email, creds.to_json())
    return creds


def has_drive_account() -> bool:
    return db.get_drive_token() is not None


def get_drive_account_email_cached() -> Optional[str]:
    rec = db.get_drive_token()
    return rec["email"] if rec else None


# ---- Save credentials after OAuth ----

def save_drive_credentials(email: str, creds: Credentials):
    db.save_drive_token(email, creds.to_json())


def save_gmail_credentials(email: str, creds: Credentials):
    db.save_gmail_account(email, creds.to_json())


def remove_drive_account():
    db.delete_drive_token()
