"""Flask WebUI: アカウント管理 + 手動同期 + 認証"""
import hmac
import os
import secrets
import threading
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

load_dotenv()

from config import UI_HOST, UI_PORT
from core import auth, db, drive_uploader
from core.sync_engine import run_sync

db.init_db()


# 本番（HTTPS）では1にしない。Render経由のhttps://はFlaskにはhttpに見えるのでFlaskの動作的にはこれを許可する必要あり
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
# Renderのプロキシ越しでもscheme=httpsとして扱う
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET_KEY") or secrets.token_hex(32)

APP_PASSWORD = os.environ.get("APP_PASSWORD")  # 未設定なら認証なし（開発時）
CRON_TRIGGER_TOKEN = os.environ.get("CRON_TRIGGER_TOKEN")

_oauth_state = {}
_sync_lock = threading.Lock()
_last_sync_progress = []


# ============= 認証 =============

def require_login(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if APP_PASSWORD and not session.get("logged_in"):
            wants_json = (
                request.headers.get("X-Requested-With") == "fetch"
                or "application/json" in request.headers.get("Accept", "")
            )
            if wants_json:
                return jsonify({"status": "unauthorized", "login_url": url_for("login")}), 401
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    if not APP_PASSWORD:
        session["logged_in"] = True
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        if hmac.compare_digest(password, APP_PASSWORD):
            session["logged_in"] = True
            session.permanent = True
            return redirect(request.args.get("next") or url_for("index"))
        error = "パスワードが違います"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ============= ホーム =============

@app.route("/")
@require_login
def index():
    drive_record = db.get_drive_token()
    drive_email = drive_record["email"] if drive_record else None
    gmail_accounts = db.list_gmail_accounts()
    sync_logs = db.recent_sync_logs(5)
    recent = db.recent_processed(20)
    return render_template(
        "index.html",
        credentials_set=auth.credentials_exist(),
        drive_email=drive_email,
        gmail_accounts=gmail_accounts,
        sync_logs=sync_logs,
        recent=recent,
        total_processed=db.total_processed_count(),
        active_tab="home",
    )


@app.route("/guide")
@require_login
def guide():
    return render_template("guide.html", active_tab="guide")


# ============= OAuth =============

@app.route("/oauth/<kind>/start")
@require_login
def oauth_start(kind):
    if kind not in ("drive", "gmail"):
        return "invalid kind", 400
    if not auth.credentials_exist():
        return "credentials.json が見つかりません。", 400
    state = secrets.token_urlsafe(24)
    _oauth_state[state] = kind
    return redirect(auth.authorize_url(kind, state))


@app.route("/oauth/<kind>/callback")
def oauth_callback(kind):
    state = request.args.get("state", "")
    expected_kind = _oauth_state.pop(state, None)
    if expected_kind != kind:
        return "state不一致 (再度お試しください)", 400

    # https越しでもFlaskにhttpで見えることがあるので、X-Forwarded-Protoを尊重
    full_url = request.url
    forwarded_proto = request.headers.get("X-Forwarded-Proto")
    if forwarded_proto == "https" and full_url.startswith("http://"):
        full_url = "https://" + full_url[len("http://"):]

    creds = auth.exchange_code(kind, full_url)

    if kind == "drive":
        # Driveアカウントのemailを取得
        from googleapiclient.discovery import build
        svc = build("drive", "v3", credentials=creds, cache_discovery=False)
        about = svc.about().get(fields="user(emailAddress)").execute()
        email = about["user"]["emailAddress"]
        auth.save_drive_credentials(email, creds)
        drive_uploader.reset_service_cache()
        return redirect(url_for("index"))

    # gmail
    from googleapiclient.discovery import build
    svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile = svc.users().getProfile(userId="me").execute()
    email = profile["emailAddress"]
    auth.save_gmail_credentials(email, creds)
    return redirect(url_for("index"))


# ============= アカウント管理 =============

@app.route("/accounts/remove", methods=["POST"])
@require_login
def remove_account():
    email = request.form.get("email", "").strip()
    if not email:
        return "email必須", 400
    db.remove_gmail_account(email)
    return redirect(url_for("index"))


@app.route("/drive/remove", methods=["POST"])
@require_login
def remove_drive():
    auth.remove_drive_account()
    drive_uploader.reset_service_cache()
    return redirect(url_for("index"))


# ============= 同期 =============

@app.route("/sync", methods=["POST"])
@require_login
def manual_sync():
    if not _sync_lock.acquire(blocking=False):
        return jsonify({"status": "busy", "message": "同期実行中です"}), 409
    try:
        _last_sync_progress.clear()
        result = run_sync(
            triggered_by="manual",
            progress=lambda m: _last_sync_progress.append(m),
        )
        return jsonify({"status": "ok", "result": result, "log": _last_sync_progress})
    finally:
        _sync_lock.release()


@app.route("/sync/progress")
@require_login
def sync_progress():
    return jsonify({"log": list(_last_sync_progress)})


@app.route("/api/sync/trigger", methods=["POST", "GET"])
def cron_sync_trigger():
    """cron-job.org等の外部スケジューラから叩くエンドポイント。
    ?token=... or X-Cron-Token ヘッダで認証"""
    if not CRON_TRIGGER_TOKEN:
        return jsonify({"status": "error", "message": "CRON_TRIGGER_TOKEN not configured"}), 500
    token = request.args.get("token") or request.headers.get("X-Cron-Token", "")
    if not hmac.compare_digest(token, CRON_TRIGGER_TOKEN):
        abort(403)
    if not _sync_lock.acquire(blocking=False):
        return jsonify({"status": "busy"}), 200
    try:
        result = run_sync(triggered_by="cron")
        return jsonify({"status": "ok", "result": result})
    finally:
        _sync_lock.release()


@app.route("/health")
def health():
    return "ok"


if __name__ == "__main__":
    print(f"WebUI: http://localhost:{UI_PORT}")
    app.run(host=UI_HOST, port=UI_PORT, debug=False)
