#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

backup_dir="${BACKUP_DIR:-/home/jahn/backups/namicash/postgres}"
container="${DB_CONTAINER:-cashbook-mafunami-db-1}"
lock_file="${BACKUP_LOCK_FILE:-${backup_dir}/.backup.lock}"
log() { printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }

mkdir -p -m 700 -- "$backup_dir"
chmod 700 "$backup_dir"
exec 9>"$lock_file"
flock -n 9 || fail 'another backup is running'
command -v docker >/dev/null || fail 'docker is unavailable'
command -v gzip >/dev/null || fail 'gzip is unavailable'
docker inspect --type container "$container" >/dev/null 2>&1 || fail 'database container is unavailable'

timestamp="$(date -u +'%Y%m%dT%H%M%SZ')"
filename="namicash-postgres-${timestamp}.dump.gz"
final="$backup_dir/$filename"
tmp="$backup_dir/.${filename}.tmp.$$"
sum_tmp="$backup_dir/.${filename}.sha256.tmp.$$"
cleanup() { rm -f -- "$tmp" "$sum_tmp"; }
trap cleanup EXIT
[[ ! -e "$final" && ! -e "${final}.sha256" ]] || fail 'backup filename already exists'

log 'Creating PostgreSQL custom-format archive'
docker exec "$container" sh -c 'exec pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom' | gzip -c > "$tmp"
gzip -t -- "$tmp" || fail 'gzip integrity check failed'
gzip -cd -- "$tmp" | docker exec -i "$container" pg_restore --list >/dev/null || fail 'PostgreSQL archive validation failed'
chmod 600 "$tmp"
mv -- "$tmp" "$final"
(cd "$backup_dir" && sha256sum -- "$filename") > "$sum_tmp"
chmod 600 "$sum_tmp"
mv -- "$sum_tmp" "${final}.sha256"
log "Published verified backup $filename"
