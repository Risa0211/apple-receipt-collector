-- Supabase Data API 2026-10-30 変更への対応
-- service_role への明示GRANT
GRANT SELECT, INSERT, UPDATE, DELETE ON
  drive_token, gmail_accounts, processed_messages, drive_folders, sync_log
TO service_role;

GRANT USAGE, SELECT ON SEQUENCE sync_log_id_seq TO service_role;
