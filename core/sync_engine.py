"""同期処理本体: 全Gmailアカウントを順次スキャン → Drive保存"""
import logging
import traceback
from typing import Callable, Optional

from core import auth, db, drive_uploader, gmail_scanner

log = logging.getLogger("sync")


def run_sync(
    progress: Optional[Callable[[str], None]] = None,
    triggered_by: str = "manual",
) -> dict:
    """全アカウントを同期。

    Returns:
        {"accounts": int, "uploaded": int, "errors": [str, ...]}
    """
    def emit(msg):
        log.info(msg)
        if progress:
            progress(msg)

    accounts = db.list_gmail_accounts()
    log_id = db.start_sync_log(triggered_by=triggered_by)

    total_uploaded = 0
    errors = []

    if not accounts:
        emit("Gmailアカウント未登録")
        db.finish_sync_log(log_id, 0, 0, None)
        return {"accounts": 0, "uploaded": 0, "errors": []}

    if not auth.load_drive_credentials():
        msg = "Driveアカウント未設定。先に設定してください。"
        emit(msg)
        db.finish_sync_log(log_id, 0, 0, msg)
        return {"accounts": 0, "uploaded": 0, "errors": [msg]}

    drive_uploader.reset_service_cache()

    for acc in accounts:
        email = acc["email"]
        emit(f"[{email}] スキャン開始")
        try:
            uploaded = _sync_account(email, emit)
            total_uploaded += uploaded
            db.update_account_sync(email, uploaded, None)
            emit(f"[{email}] 完了: {uploaded}件保存")
        except Exception as e:
            tb = traceback.format_exc()
            log.error("[%s] エラー: %s\n%s", email, e, tb)
            errors.append(f"[{email}] {e}")
            db.update_account_sync(email, 0, str(e))
            emit(f"[{email}] エラー: {e}")

    err_str = "\n".join(errors) if errors else None
    db.finish_sync_log(log_id, len(accounts), total_uploaded, err_str)
    emit(f"全体完了: {len(accounts)}アカウント / {total_uploaded}件保存")
    return {"accounts": len(accounts), "uploaded": total_uploaded, "errors": errors}


def _sync_account(email: str, emit) -> int:
    uploaded_count = 0
    seen_in_run = set()

    for msg_summary in gmail_scanner.iter_matching_messages(email):
        message_id = msg_summary["id"]
        if message_id in seen_in_run:
            continue
        seen_in_run.add(message_id)

        if db.is_processed(message_id, email):
            continue

        msg = gmail_scanner.fetch_message_with_pdfs(email, message_id)
        if not msg["pdfs"]:
            db.mark_processed(message_id, email, "", "", "")
            continue

        received = msg["received_dt"]
        year = received.year
        month = received.month
        ym = f"{year}-{month:02d}"

        folder_id = drive_uploader.ensure_month_folder(year, month)

        for pdf in msg["pdfs"]:
            filename = pdf["filename"] or f"{message_id}.pdf"
            existing = drive_uploader.file_already_in_folder(folder_id, filename)
            if existing:
                db.mark_processed(message_id, email, existing, filename, ym)
                emit(f"[{email}] 既存スキップ: {filename}")
                continue
            file_id = drive_uploader.upload_pdf(folder_id, filename, pdf["data"])
            db.mark_processed(message_id, email, file_id, filename, ym)
            uploaded_count += 1
            emit(f"[{email}] 保存: {filename} → {ym}")

    return uploaded_count
