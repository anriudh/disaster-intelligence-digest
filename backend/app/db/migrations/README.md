# Migrations

Applied in order at startup by `backend/app/db/migrate.py`, after `schema.sql`.

- Name files `NNNN_short_name.sql` or `NNNN_short_name.py`. Other files are ignored.
- **Additive only:** `ALTER TABLE ... ADD COLUMN`, new tables and indexes. No `DROP`, no `DELETE`.
- A `.py` migration defines `migrate(conn)`. It runs inside the migration's transaction and must not commit.
- Before a backfill changes a value, it copies the original into `legacy_values`.
- Never edit a migration after it has been applied: the runner refuses to start if a file's checksum changes. Add a new migration instead.
- Rollback means restoring the backup that the runner writes before applying anything: `<db>.bak-<version>-<timestamp>`.
- The committed `backend/data/disaster_intel.db` is migrated only as an explicit, reviewed step.
