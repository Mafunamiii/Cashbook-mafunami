#!/usr/bin/env bash
# Create an encrypted-in-transit, verified PostgreSQL logical backup through
# Compose. The artifact is compressed, atomically published, checksummed, and
# copied to an off-site SSH destination. This script deliberately never prints
# credentials or connection strings.
set -Eeuo pipefail
umask 077

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="${COMPOSE_FILE:-$project_dir/compose.production.yaml}"
env_file="${BACKUP_ENV_FILE:-$project_dir/.env}"
dry_run="${DRY_RUN:-0}"

log() { printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"; }
fail() { log "ERROR: $*" >&2; exit 2; }
on_error() {
  local exit_code=$?
  log "ERROR: backup failed (exit code $exit_code)" >&2
  exit "$exit_code"
}
trap on_error ERR

[[ "$dry_run" == "0" || "$dry_run" == "1" ]] || fail "DRY_RUN must be 0 or 1"
[[ -f "$env_file" ]] || fail "Environment file was not found"

# Read only the three non-secret backup settings. This intentionally does not
# source .env as shell code and gives explicit process environment precedence.
read_env_value() {
  sed -n "s/^$1=//p" "$env_file" | tail -n 1
}
backup_dir="${BACKUP_DIR:-$(read_env_value BACKUP_DIR)}"
ssh_target="${BACKUP_SSH_TARGET:-$(read_env_value BACKUP_SSH_TARGET)}"
remote_path="${BACKUP_REMOTE_PATH:-$(read_env_value BACKUP_REMOTE_PATH)}"

[[ -n "$backup_dir" ]] || fail "BACKUP_DIR is required"
[[ -n "$ssh_target" ]] || fail "BACKUP_SSH_TARGET is required"
[[ "$remote_path" =~ ^/[A-Za-z0-9._/-]+$ ]] || fail "BACKUP_REMOTE_PATH must be an absolute safe path"
[[ "$ssh_target" =~ ^[A-Za-z0-9._@:-]+$ ]] || fail "BACKUP_SSH_TARGET contains unsupported characters"
[[ -f "$compose_file" ]] || fail "Compose file was not found"

compose=(docker compose --project-directory "$project_dir" --env-file "$env_file" -f "$compose_file")
timestamp="$(date -u +'%Y%m%dT%H%M%SZ')"
filename="cashbook-${timestamp}.dump.gz"
final_file="$backup_dir/$filename"
temporary_file="$backup_dir/.${filename}.tmp.$$"

if [[ "$dry_run" == "1" ]]; then
  log "DRY RUN: would create, verify, and atomically publish $final_file"
  log "DRY RUN: would retain seven local days and rsync to ${ssh_target}:${remote_path}"
  log "DRY RUN: would retain fourteen off-site days"
  exit 0
fi

mkdir -p "$backup_dir"
[[ ! -e "$final_file" ]] || fail "Refusing to overwrite existing backup $filename"

log "Creating PostgreSQL backup"
"${compose[@]}" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' \
  | gzip -c > "$temporary_file"

log "Validating gzip stream"
gzip -t "$temporary_file"
log "Validating PostgreSQL archive"
gzip -cd "$temporary_file" | "${compose[@]}" exec -T db pg_restore --list >/dev/null

mv "$temporary_file" "$final_file"
(cd "$backup_dir" && sha256sum "$filename" > "${filename}.sha256")
log "Published verified backup $filename"

log "Applying seven-day local retention"
find "$backup_dir" -maxdepth 1 -type f -name 'cashbook-*.dump.gz' -mtime +6 -delete
find "$backup_dir" -maxdepth 1 -type f -name 'cashbook-*.dump.gz.sha256' -mtime +6 -delete

log "Synchronizing backup off-site"
ssh "$ssh_target" "mkdir -p -- $remote_path"
rsync --archive --protect-args "$final_file" "${final_file}.sha256" "${ssh_target}:${remote_path}/"
log "Verifying off-site checksum"
ssh "$ssh_target" "cd -- $remote_path && sha256sum -c -- ${filename}.sha256"
log "Applying fourteen-day off-site retention"
ssh "$ssh_target" "find $remote_path -maxdepth 1 -type f \\( -name 'cashbook-*.dump.gz' -o -name 'cashbook-*.dump.gz.sha256' \\) -mtime +13 -delete"

log "Backup completed successfully"
