-- Read-only database role used only for backups (run once, as a superuser).
-- Then set BACKUP_DB_USER / BACKUP_DB_PASSWORD in .env.
-- Replace <DB_NAME> and choose a strong password.

CREATE ROLE erp_backup LOGIN PASSWORD 'change-me-strong-password';
GRANT CONNECT ON DATABASE <DB_NAME> TO erp_backup;
GRANT pg_read_all_data TO erp_backup;          -- PostgreSQL 14+: read every table
-- Optional: lets pg_dumpall save roles/grants (globals.sql). Without it the
-- backup still contains all data; you only get a warning.
-- GRANT pg_read_all_settings TO erp_backup;
