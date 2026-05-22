"""共通設定"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "logs"

# credentials.json の取得元 (優先順):
#   1. GOOGLE_CREDENTIALS_JSON_BASE64 (Base64エンコードしたJSON) ... Cloud Run等のUIでクオートエスケープ事故を防ぐ
#   2. GOOGLE_CREDENTIALS_JSON (JSON文字列そのまま) ... ローカル等で素直に渡す場合
#   3. GOOGLE_CREDENTIALS_JSON_PATH (パス) ... Render Secret Files向け
#   4. ローカルの credentials.json
import base64

_creds_env_b64 = os.environ.get("GOOGLE_CREDENTIALS_JSON_BASE64")
_creds_env_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
_creds_env_path = os.environ.get("GOOGLE_CREDENTIALS_JSON_PATH")

if _creds_env_b64:
    decoded = base64.b64decode(_creds_env_b64).decode("utf-8")
    CREDENTIALS_PATH = Path("/tmp/credentials.json")
    CREDENTIALS_PATH.write_text(decoded, encoding="utf-8")
elif _creds_env_json:
    CREDENTIALS_PATH = Path("/tmp/credentials.json")
    CREDENTIALS_PATH.write_text(_creds_env_json, encoding="utf-8")
elif _creds_env_path:
    CREDENTIALS_PATH = Path(_creds_env_path)
else:
    CREDENTIALS_PATH = BASE_DIR / "credentials.json"

UI_HOST = "127.0.0.1"
UI_PORT = 8765
OAUTH_REDIRECT_BASE = f"http://localhost:{UI_PORT}"

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
# 既存フォルダ（手動作成済み）にもアクセスする必要があるため drive スコープ
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]

GMAIL_QUERY = 'from:noreply@email.apple.com subject:"請求金額のお知らせ" has:attachment filename:pdf'

# 既存フォルダ命名規則: マイドライブ/iPhone領収書/2026年04月 iPhone領収書/
DRIVE_FOLDER_NAME_TEMPLATE = "{year}年{month:02d}月 iPhone領収書"
DRIVE_ROOT_FOLDER_NAME = "iPhone領収書"

LOGS_DIR.mkdir(parents=True, exist_ok=True)
