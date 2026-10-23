# NamiCash PostgreSQL backups

## Flow and retention

`backup-postgres.sh` runs `pg_dump --format=custom` inside the running
`cashbook-mafunami-db-1` container, using its existing `POSTGRES_USER` and
`POSTGRES_DB`. It does not invoke Compose or read `.env`. The compressed archive
is gzip-tested, checked with `pg_restore --list` inside the database container,
then published with a
SHA-256 sidecar. Files are mode 0600 in the mode 0700 backup directory. A lock
prevents overlapping dumps.

`replicate-gdrive.sh` uploads checksum-verified archives and sidecars to
`gdrive-crypt:namicash/postgres/`, using `/home/jahn/.config/rclone/rclone.conf`.
The crypt remote must wrap `gdrive-backups:`; files are never sent to the
unencrypted remote directly. The destination is fixed to this dedicated path.
It retries transfer and streamed checksum verification three times. Failures
retain local files and return failure for systemd retry. Markers record the
archive hash and verification time. Each run checks that both remote files
still exist; pairs older than three days are reverified byte for byte.

`--upload-only` uploads and verifies pending or stale pairs, then exits without
local or cloud retention. `--retention-dry-run` only evaluates retention: it
does not upload, update markers, or delete files. It may read remote archive
bytes to verify retention decisions. The default mode uploads, verifies, then
applies retention.

Local retention is seven days and removes only expired, checksum-valid pairs
whose current remote copy verifies byte for byte; it preserves the newest
verified local backup. Cloud retention is 30 days. It runs only when a remote
backup created within the last seven days verifies byte for byte, then deletes
only expired `namicash-postgres-YYYYMMDDTHHMMSSZ.dump.gz` pairs in the
dedicated destination. It preserves the recent verified backup. Archive
deletion precedes sidecar deletion; a local journal resumes sidecar cleanup
after interruption. If listing or verification fails, deletion stops or skips
the affected pair.

**Recovery baseline:** `namicash-20261023T050337Z.dump.gz` is the manually
verified backup. Keep its local and encrypted cloud copies and checksum during
initial activation. Automated retention only matches the newer
`namicash-postgres-...` naming pattern, so it does not delete this baseline.

## Install and schedule

Install the repository at the unit files' `ExecStart` path (or edit those
paths). Ensure `jahn` belongs to the Docker group and owns the backup
directory. The replication service runs as `jahn` and needs read/write access
to `/home/jahn/.config/rclone` so rclone can refresh its token:

```sh
sudo install -d -o jahn -g jahn -m 0700 /home/jahn/backups/namicash/postgres
sudo install -m 0644 systemd/namicash-backup.{service,timer} /etc/systemd/system/
sudo install -m 0644 systemd/namicash-replicate.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
```

Keep `/home/jahn/.config/rclone` owned by `jahn` with mode 0700 and
`rclone.conf` with mode 0600. Before activation, verify that the repository
path, backup directory, Docker group membership, and rclone configuration are
accessible to `jahn`. Do not print the configuration file.

Run manually first:

```sh
sudo -u jahn /home/jahn/Cashbook-mafunami/scripts/backup-postgres.sh
sudo -u jahn /home/jahn/Cashbook-mafunami/scripts/replicate-gdrive.sh --upload-only
sudo -u jahn /home/jahn/Cashbook-mafunami/scripts/replicate-gdrive.sh --retention-dry-run
```

After review, activate (installation does not enable timers):

```sh
sudo systemctl enable --now namicash-backup.timer namicash-replicate.timer
systemctl list-timers 'namicash-*'
journalctl -u namicash-backup.service -u namicash-replicate.service
```

The backup timer runs daily with missed-run catch-up. Replication runs at boot
and retries hourly. Check freshness from the latest local archive/sidecar and
encrypted remote listing, and inspect the service journal for failures.

## Verify, download, and restore

Use the crypt remote for downloads, never its underlying unencrypted remote.
Keep the original filename so `sha256sum -c` can use the sidecar unchanged:

```sh
name=namicash-postgres-YYYYMMDDTHHMMSSZ.dump.gz
rclone --config /home/jahn/.config/rclone/rclone.conf copyto \
  "gdrive-crypt:namicash/postgres/$name" "/secure/restore/$name"
rclone --config /home/jahn/.config/rclone/rclone.conf copyto \
  "gdrive-crypt:namicash/postgres/$name.sha256" "/secure/restore/$name.sha256"
cd /secure/restore
sha256sum -c "$name.sha256"
gzip -t "$name"
gzip -cd "$name" | pg_restore --list
```

Restore only into a newly created isolated PostgreSQL 16 instance. Confirm the
target identity; do not use production Compose or its volume. Example, using a
fresh disposable container and `_restore_test` database:

```sh
gzip -cd "$name" | pg_restore --no-owner \
  --dbname='postgresql://restore_user@127.0.0.1:55432/cashbook_restore_test'
```

The connection is a placeholder. Supply its password through a protected
`.pgpass` or prompt, not on the command line. Confirm tables and Alembic revision
in the isolated database. Never validate restores against production.

## Homeserver loss and encryption key custody

On a replacement host, install Docker, PostgreSQL 16 client tools and rclone.
Recover the rclone configuration and crypt password/salt from a separate
encrypted offline secret store, configure access to `gdrive-crypt:`, then
download and verify as above. Drive data is unrecoverable without crypt
credentials. Keep a protected offline copy available to authorized recovery
operators; never put it in this repository, beside backups, or in logs. Limit
access to jahn and periodically test credential recovery.

Disable automation with:

```sh
sudo systemctl disable --now namicash-backup.timer namicash-replicate.timer
```

This stops future scheduled runs without removing existing backups.

## Safe tests

Run `bash scripts/test-backups.sh`. Tests use temporary paths and fake Docker,
rclone and pg_restore commands; they need no production credentials and do not
connect to any database. CI runs the same script.
