"""Gmail検索 + PDF添付ファイル抽出"""
import base64
from datetime import datetime, timezone
from typing import Iterator

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import GMAIL_QUERY
from core.auth import load_gmail_credentials


def _service(email: str):
    creds = load_gmail_credentials(email)
    if not creds:
        raise RuntimeError(f"Gmail認証情報なし: {email}")
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def get_account_email(email: str) -> str:
    """Gmail APIで実際のアドレスを確認"""
    svc = _service(email)
    profile = svc.users().getProfile(userId="me").execute()
    return profile["emailAddress"]


def iter_matching_messages(email: str) -> Iterator[dict]:
    """Apple領収書メールをページングで全件返す"""
    svc = _service(email)
    page_token = None
    while True:
        resp = svc.users().messages().list(
            userId="me",
            q=GMAIL_QUERY,
            pageToken=page_token,
            maxResults=100,
        ).execute()
        for m in resp.get("messages", []):
            yield m
        page_token = resp.get("nextPageToken")
        if not page_token:
            break


def fetch_message_with_pdfs(email: str, message_id: str):
    """1メッセージとPDF添付ファイルを取得して返す。

    Returns:
        dict: {
            "message_id": str,
            "received_dt": datetime,  # JST に変換した日時
            "subject": str,
            "pdfs": [{"filename": str, "data": bytes}, ...],
        }
        該当PDFがなければ pdfs は空リスト
    """
    svc = _service(email)
    msg = svc.users().messages().get(
        userId="me",
        id=message_id,
        format="full",
    ).execute()

    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    subject = headers.get("subject", "")

    internal_ms = int(msg["internalDate"])
    received_dt = datetime.fromtimestamp(internal_ms / 1000, tz=timezone.utc).astimezone()

    pdfs = []
    for part in _iter_parts(msg.get("payload", {})):
        filename = part.get("filename") or ""
        if not filename.lower().endswith(".pdf"):
            continue
        body = part.get("body", {})
        attachment_id = body.get("attachmentId")
        if not attachment_id:
            data = body.get("data")
            if data:
                pdfs.append({
                    "filename": filename,
                    "data": base64.urlsafe_b64decode(data),
                })
            continue
        try:
            att = svc.users().messages().attachments().get(
                userId="me",
                messageId=message_id,
                id=attachment_id,
            ).execute()
            pdfs.append({
                "filename": filename,
                "data": base64.urlsafe_b64decode(att["data"]),
            })
        except HttpError as e:
            raise RuntimeError(f"添付取得失敗 ({message_id} / {filename}): {e}")

    return {
        "message_id": message_id,
        "received_dt": received_dt,
        "subject": subject,
        "pdfs": pdfs,
    }


def _iter_parts(payload):
    """payloadを再帰的に走査して全partを返す"""
    yield payload
    for p in payload.get("parts", []) or []:
        yield from _iter_parts(p)
