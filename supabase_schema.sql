-- Apple領収書コレクター: Supabaseスキーマ
-- Supabase Dashboard → SQL Editor で実行してください

-- ===== Drive保存先トークン (1行のみ) =====
CREATE TABLE IF NOT EXISTS drive_token (
  id INTEGER PRIMARY KEY DEFAULT 1,
  email TEXT NOT NULL,
  token JSONB NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now(),
  CONSTRAINT drive_token_singleton CHECK (id = 1)
);

-- ===== Gmail監視対象アカウント =====
CREATE TABLE IF NOT EXISTS gmail_accounts (
  email TEXT PRIMARY KEY,
  token JSONB NOT NULL,
  added_at TIMESTAMPTZ DEFAULT now(),
  last_sync_at TIMESTAMPTZ,
  last_sync_count INTEGER DEFAULT 0,
  last_error TEXT
);

-- ===== 処理済みメッセージ =====
CREATE TABLE IF NOT EXISTS processed_messages (
  message_id TEXT NOT NULL,
  account_email TEXT NOT NULL,
  drive_file_id TEXT,
  pdf_filename TEXT,
  receipt_year_month TEXT,
  processed_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (message_id, account_email)
);

CREATE INDEX IF NOT EXISTS processed_messages_processed_at_idx
  ON processed_messages(processed_at DESC);

-- ===== Driveフォルダキャッシュ =====
CREATE TABLE IF NOT EXISTS drive_folders (
  folder_name TEXT PRIMARY KEY,
  drive_folder_id TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- ===== 同期実行履歴 =====
CREATE TABLE IF NOT EXISTS sync_log (
  id BIGSERIAL PRIMARY KEY,
  started_at TIMESTAMPTZ DEFAULT now(),
  finished_at TIMESTAMPTZ,
  accounts_scanned INTEGER DEFAULT 0,
  pdfs_uploaded INTEGER DEFAULT 0,
  errors TEXT,
  triggered_by TEXT  -- 'manual' | 'cron'
);

CREATE INDEX IF NOT EXISTS sync_log_started_at_idx
  ON sync_log(started_at DESC);

-- ===== RLS設定 =====
-- service_roleキーでアクセスするのでRLS有効でもbypassされる
-- セキュリティのためanonアクセスは全てブロック
ALTER TABLE drive_token ENABLE ROW LEVEL SECURITY;
ALTER TABLE gmail_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE processed_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE drive_folders ENABLE ROW LEVEL SECURITY;
ALTER TABLE sync_log ENABLE ROW LEVEL SECURITY;
-- ポリシーを作らないので anon は読み書き不可、service_role のみ可能
