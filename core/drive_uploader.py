"""Drive: 月別フォルダ管理 + PDFアップロード"""
import io
from typing import Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from config import DRIVE_FOLDER_NAME_TEMPLATE, DRIVE_ROOT_FOLDER_NAME
from core import db
from core.auth import load_drive_credentials


_service_cache = None


def get_service():
    global _service_cache
    if _service_cache is None:
        creds = load_drive_credentials()
        if not creds:
            raise RuntimeError("Driveアカウント未設定")
        _service_cache = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _service_cache


def reset_service_cache():
    global _service_cache
    _service_cache = None


def folder_name_for(year: int, month: int) -> str:
    return DRIVE_FOLDER_NAME_TEMPLATE.format(year=year, month=month)


def _find_folder(name: str, parent_id: Optional[str] = None) -> Optional[str]:
    svc = get_service()
    q = (
        f"mimeType = 'application/vnd.google-apps.folder' "
        f"and name = '{_escape(name)}' and trashed = false"
    )
    if parent_id:
        q += f" and '{parent_id}' in parents"
    resp = svc.files().list(
        q=q, fields="files(id, name)", pageSize=10, spaces="drive",
    ).execute()
    files = resp.get("files", [])
    return files[0]["id"] if files else None


def _create_folder(name: str, parent_id: Optional[str] = None) -> str:
    svc = get_service()
    body = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        body["parents"] = [parent_id]
    f = svc.files().create(body=body, fields="id").execute()
    return f["id"]


def ensure_root_folder() -> str:
    cached = db.get_drive_folder_id(DRIVE_ROOT_FOLDER_NAME)
    if cached:
        return cached
    fid = _find_folder(DRIVE_ROOT_FOLDER_NAME)
    if not fid:
        fid = _create_folder(DRIVE_ROOT_FOLDER_NAME)
    db.cache_drive_folder(DRIVE_ROOT_FOLDER_NAME, fid)
    return fid


def ensure_month_folder(year: int, month: int) -> str:
    name = folder_name_for(year, month)
    cached = db.get_drive_folder_id(name)
    if cached:
        return cached
    root_id = ensure_root_folder()
    fid = _find_folder(name, parent_id=root_id)
    if not fid:
        fid = _create_folder(name, parent_id=root_id)
    db.cache_drive_folder(name, fid)
    return fid


def file_already_in_folder(folder_id: str, filename: str) -> Optional[str]:
    svc = get_service()
    q = (
        f"'{folder_id}' in parents and name = '{_escape(filename)}' "
        f"and trashed = false"
    )
    resp = svc.files().list(
        q=q, fields="files(id, name)", pageSize=5, spaces="drive",
    ).execute()
    files = resp.get("files", [])
    return files[0]["id"] if files else None


def upload_pdf(folder_id: str, filename: str, data: bytes) -> str:
    svc = get_service()
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype="application/pdf", resumable=False)
    body = {"name": filename, "parents": [folder_id]}
    f = svc.files().create(body=body, media_body=media, fields="id").execute()
    return f["id"]


def get_drive_account_email() -> Optional[str]:
    try:
        svc = get_service()
        about = svc.about().get(fields="user(emailAddress)").execute()
        return about.get("user", {}).get("emailAddress")
    except (HttpError, Exception):
        return None


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")
