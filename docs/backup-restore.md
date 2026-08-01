# Backup and restore

`scripts/backup-postgres.sh` makes a PostgreSQL custom-format logical dump,
compresses it, verifies both the gzip stream and PostgreSQL archive, writes a
SHA-256 sidecar, then atomically renames it into place. It keeps seven days
locally and rsyncs each verified artifact over SSH to a VPS, where it keeps
fourteen days. It never prints database credentials.

The remote SSH account should be dedicated to backups, use a restricted key,
and only be allowed to write `BACKUP_REMOTE_PATH`. Keep the private key in the
cron user's protected SSH configuration, never in this repository.

## Configure and schedule

Set `BACKUP_DIR`, `BACKUP_SSH_TARGET`, and `BACKUP_REMOTE_PATH` in the
production `.env`. Create the local directory with restrictive ownership, then
test the plan without touching PostgreSQL or SSH:

```bash
DRY_RUN=1 scripts/backup-postgres.sh
```

Run a real backup manually once, then schedule nightly with a cron entry for a
trusted local account:

```cron
15 2 * * * cd /opt/cashbook && /opt/cashbook/scripts/backup-postgres.sh >> /var/log/cashbook-backup.log 2>&1
```

The script logs UTC timestamps and uses non-zero exit codes for configuration,
dump, validation, transfer, or retention failures. Monitor the cron exit status
and the log. A successful local backup is retained even if later off-site sync
fails, so rerun after resolving the remote issue.

## Restore drill (non-production first)

Never restore into the running production database without a confirmed outage
and an additional fresh backup. To verify a backup against a disposable target:

1. Confirm its integrity:

   ```bash
   cd /var/backups/cashbook
   gzip -t cashbook-YYYYMMDDTHHMMSSZ.dump.gz
   sha256sum -c cashbook-YYYYMMDDTHHMMSSZ.dump.gz.sha256
   ```

2. Start an isolated PostgreSQL instance and create an empty database. Do not
   point `pg_restore` at production by accident.
3. Restore after decompression:

   ```bash
   gzip -cd /var/backups/cashbook/cashbook-YYYYMMDDTHHMMSSZ.dump.gz | \
     pg_restore --clean --if-exists --no-owner --dbname "$RESTORE_DATABASE_URL"
   ```

4. Run `alembic current`, inspect expected users/categories/transactions under
the authorized maintenance procedure, and record the drill result.

For production recovery, stop Cashbook writes, preserve the failed database
volume, create a final backup if possible, restore into a newly created
database or replacement volume, migrate/check the revision, validate `/ready`,
then restart the Compose services. Rotate any credentials suspected of exposure.
