#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

backup_dir="${BACKUP_DIR:-/home/jahn/backups/namicash/postgres}"
destination="${RCLONE_DESTINATION:-gdrive-crypt:namicash/postgres}"
config="${RCLONE_CONFIG:-/home/jahn/.config/rclone/rclone.conf}"
retry_base="${REPLICATION_RETRY_BASE_SECONDS:-10}"
lock_file="${REPLICATION_LOCK_FILE:-${backup_dir}/.replicate.lock}"
mode="${1:-normal}"
[[ $# -le 1 && ( "$mode" == normal || "$mode" == --upload-only || "$mode" == --retention-dry-run ) ]] || {
  echo 'Usage: replicate-gdrive.sh [--upload-only|--retention-dry-run]' >&2; exit 2;
}
log() { printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }
archive_name() { [[ "$1" =~ ^namicash-postgres-[0-9]{8}T[0-9]{6}Z\.dump\.gz$ ]]; }
archive_epoch() {
  local stamp="${1#namicash-postgres-}"
  stamp="${stamp%.dump.gz}"
  date -u -d "${stamp:0:4}-${stamp:4:2}-${stamp:6:2} ${stamp:9:2}:${stamp:11:2}:${stamp:13:2} UTC" +%s 2>/dev/null
}

# Fixed scope: overrides may not redirect uploads or deletion to a broad path.
[[ "$destination" == 'gdrive-crypt:namicash/postgres' ]] || fail 'unsafe rclone destination'
[[ -d "$backup_dir" ]] || fail 'backup directory is unavailable'
[[ -r "$config" ]] || fail 'rclone configuration is missing or unreadable'
command -v rclone >/dev/null || fail 'rclone is unavailable'
exec 9>>"$lock_file"
flock -n 9 || fail 'another replication is running'
rclone_cmd=(rclone --config "$config")
"${rclone_cmd[@]}" listremotes | grep -Fx 'gdrive-crypt:' >/dev/null || fail 'gdrive-crypt remote is not configured'
work_dir="$(mktemp -d)"
marker_tmp=''
cleanup() {
  [[ -z "$marker_tmp" ]] || rm -f -- "$marker_tmp"
  rm -rf -- "$work_dir"
}
trap cleanup EXIT
listing="$work_dir/remote-files"

list_remote() {
  "${rclone_cmd[@]}" lsf --files-only --format p "$destination" > "$listing" ||
    fail 'encrypted remote listing failed; no retention performed'
}
remote_has() { grep -Fxq -- "$1" "$listing"; }
local_hash() {
  local name="$1" hash
  hash="$(sha256sum -- "$backup_dir/$name" | cut -d ' ' -f1)" || return 1
  [[ "$(cat -- "$backup_dir/$name.sha256")" == "$hash  $name" ]] || return 1
  printf '%s\n' "$hash"
}
# rclone cat decrypts each file through gdrive-crypt. pipefail catches a failed
# read; the archive is streamed into sha256sum, so no dump is staged on disk.
remote_pair_valid() {
  local name="$1" expected="${2:-}" hash sidecar
  remote_has "$name" && remote_has "$name.sha256" || return 1
  hash="$("${rclone_cmd[@]}" cat "$destination/$name" | sha256sum | cut -d ' ' -f1)" || return 1
  sidecar="$("${rclone_cmd[@]}" cat "$destination/$name.sha256")" || return 1
  [[ "$sidecar" == "$hash  $name" ]] || return 1
  [[ -z "$expected" || "$hash" == "$expected" ]]
}
mark_uploaded() {
  local file="$backup_dir/$1.uploaded"
  marker_tmp="$backup_dir/.$1.uploaded.tmp.$$"
  printf '%s %s\n' "$2" "$(date +%s)" > "$marker_tmp"
  chmod 600 "$marker_tmp"
  mv -- "$marker_tmp" "$file"
  marker_tmp=''
}

list_remote
replicate_pending() {
  local archive name hash marker_hash='' marker_time='' now attempt
  now="$(date +%s)"
  shopt -s nullglob
  for archive in "$backup_dir"/namicash-postgres-*.dump.gz; do
    name="$(basename "$archive")"
    archive_name "$name" || continue
    [[ -f "$archive.sha256" ]] || { log "Skipping incomplete pair $name"; continue; }
    hash="$(local_hash "$name")" || fail "local checksum mismatch: $name"
    if [[ -f "$archive.uploaded" ]]; then
      read -r marker_hash marker_time < "$archive.uploaded" || true
      if [[ "$marker_hash" == "$hash" && "$marker_time" =~ ^[0-9]+$ ]] &&
        (( marker_time <= now && now - marker_time < 3 * 86400 )) &&
        remote_has "$name" && remote_has "$name.sha256"; then
        continue
      fi
      if remote_pair_valid "$name" "$hash"; then
        mark_uploaded "$name" "$hash"
        continue
      fi
      rm -f -- "$archive.uploaded"
      log "Re-uploading missing or invalid remote pair $name"
    fi
    for attempt in 1 2 3; do
      if "${rclone_cmd[@]}" copy --ignore-times "$archive" "$destination" &&
        "${rclone_cmd[@]}" copy --ignore-times "$archive.sha256" "$destination"; then
        list_remote
        if remote_pair_valid "$name" "$hash"; then
          mark_uploaded "$name" "$hash"
          log "Replicated and verified $name"
          break
        fi
      fi
      log "Upload verification attempt $attempt failed for $name"
      (( attempt == 3 )) || sleep "$((attempt * retry_base))"
    done
    [[ -f "$archive.uploaded" ]] || fail "replication failed for $name; local copy retained"
  done
}

local_retention() {
  local archive name hash newest='' epoch newest_epoch=0 cutoff
  local -a verified=()
  cutoff=$(($(date +%s) - 7 * 86400))
  shopt -s nullglob
  for archive in "$backup_dir"/namicash-postgres-*.dump.gz; do
    name="$(basename "$archive")"
    archive_name "$name" || continue
    hash="$(local_hash "$name" 2>/dev/null)" || continue
    epoch="$(archive_epoch "$name")" || continue
    verified+=("$name")
    if (( epoch > newest_epoch )); then newest="$name"; newest_epoch="$epoch"; fi
  done
  for name in "${verified[@]}"; do
    [[ "$name" == "$newest" ]] && continue
    epoch="$(archive_epoch "$name")" || continue
    (( epoch < cutoff )) || continue
    [[ -f "$backup_dir/$name.uploaded" ]] || continue
    hash="$(local_hash "$name")" || continue
    # A marker alone is never grounds to discard a local archive.
    remote_pair_valid "$name" "$hash" || { log "Retaining $name: remote pair not verified"; continue; }
    if [[ "$mode" == --retention-dry-run ]]; then
      log "RETENTION DRY RUN: would remove local pair $name"
    else
      rm -f -- "$backup_dir/$name" "$backup_dir/$name.sha256" "$backup_dir/$name.uploaded"
      log "Removed expired local pair $name"
    fi
  done
}

cloud_retention() {
  local name epoch recent_cutoff expiry_cutoff anchor='' best=0 journal needs_cleanup=0
  recent_cutoff=$(($(date +%s) - 7 * 86400))
  expiry_cutoff=$(($(date +%s) - 30 * 86400))
  while IFS= read -r name; do
    archive_name "$name" || continue
    epoch="$(archive_epoch "$name")" || continue
    if (( epoch < expiry_cutoff )) && remote_has "$name.sha256"; then needs_cleanup=1; break; fi
  done < "$listing"
  shopt -s nullglob
  for journal in "$backup_dir"/.cloud-delete-namicash-postgres-*.dump.gz; do
    name="${journal##*/.cloud-delete-}"
    if archive_name "$name"; then needs_cleanup=1; break; fi
  done
  (( needs_cleanup )) || return 0
  # Only a verified backup created within seven days permits cloud deletion.
  while IFS= read -r name; do
    archive_name "$name" || continue
    epoch="$(archive_epoch "$name")" || continue
    (( epoch >= recent_cutoff && epoch <= $(date +%s) && epoch > best )) || continue
    if remote_pair_valid "$name"; then anchor="$name"; best="$epoch"; fi
  done < "$listing"
  [[ -n "$anchor" ]] || { log 'Cloud retention skipped: no recent verified remote backup'; return 0; }

  # A local journal lets the next run finish sidecar cleanup after an
  # interrupted archive-first deletion. The recovery baseline is not matched.
  shopt -s nullglob
  for journal in "$backup_dir"/.cloud-delete-namicash-postgres-*.dump.gz; do
    name="${journal##*/.cloud-delete-}"
    archive_name "$name" || continue
    epoch="$(archive_epoch "$name")" || continue
    (( epoch < expiry_cutoff )) || continue
    if remote_has "$name"; then
      remote_pair_valid "$name" || { log "Retaining unverified pending pair $name"; continue; }
    fi
    if [[ "$mode" == --retention-dry-run ]]; then
      log "RETENTION DRY RUN: would finish cloud deletion for $name"
    else
      if remote_has "$name"; then "${rclone_cmd[@]}" deletefile "$destination/$name" || fail "cloud archive deletion failed: $name"; fi
      if remote_has "$name.sha256"; then "${rclone_cmd[@]}" deletefile "$destination/$name.sha256" || fail "cloud sidecar deletion failed: $name"; fi
      rm -f -- "$journal"
      log "Finished cloud deletion for $name"
    fi
  done

  while IFS= read -r name; do
    archive_name "$name" || continue
    [[ "$name" != "$anchor" ]] || continue
    epoch="$(archive_epoch "$name")" || continue
    (( epoch < expiry_cutoff )) || continue
    [[ ! -f "$backup_dir/.cloud-delete-$name" ]] || continue
    remote_pair_valid "$name" || { log "Retaining unverified cloud pair $name"; continue; }
    if [[ "$mode" == --retention-dry-run ]]; then
      log "RETENTION DRY RUN: would remove cloud pair $name"
    else
      journal="$backup_dir/.cloud-delete-$name"
      : > "$journal"
      chmod 600 "$journal"
      "${rclone_cmd[@]}" deletefile "$destination/$name" || fail "cloud archive deletion failed: $name"
      "${rclone_cmd[@]}" deletefile "$destination/$name.sha256" || fail "cloud sidecar deletion failed: $name"
      rm -f -- "$journal"
      log "Removed expired cloud pair $name"
    fi
  done < "$listing"
}

if [[ "$mode" != --retention-dry-run ]]; then replicate_pending; fi
if [[ "$mode" != --upload-only ]]; then
  local_retention
  cloud_retention
fi
