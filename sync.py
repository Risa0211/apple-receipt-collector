"""launchd / 手動実行用 同期スクリプト"""
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import LOGS_DIR
from core import db
from core.sync_engine import run_sync


def main():
    db.init_db()
    log_file = LOGS_DIR / "sync.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logging.info("===== sync 開始 (%s) =====", datetime.now().isoformat())
    result = run_sync()
    logging.info("===== sync 終了: %s =====", result)
    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
