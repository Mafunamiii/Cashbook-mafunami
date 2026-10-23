#!/usr/bin/env bash
set -Eeuo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/backups" "$tmp/config" "$tmp/remote" "$tmp/work"
export PATH="$tmp/bin:$PATH" TEST_TMP="$tmp" TMPDIR="$tmp/work"
export BACKUP_DIR="$tmp/backups" RCLONE_CONFIG="$tmp/config/rclone.conf"
export REPLICATION_RETRY_BASE_SECONDS=0
backup="$root/scripts/backup-postgres.sh"
replicate="$root/scripts/replicate-gdrive.sh"
fail() { echo "FAIL: $*" >&2; exit 1; }
expect_fail() { if "$@" >/dev/null 2>&1; then fail "unexpected success: $*"; fi; }

cat > "$tmp/bin/docker" <<'MOCK'
#!/usr/bin/env bash
[[ "${1:-}" == inspect ]] && { [[ "${MOCK_NO_CONTAINER:-0}" == 0 ]]; exit; }
[[ "${1:-}" == exec && "${2:-}" == -i ]] && { cat >/dev/null; exit; }
[[ "${1:-}" == exec ]] && { printf 'fake custom archive'; exit; }
exit 1
MOCK
cat > "$tmp/bin/rclone" <<'MOCK'
#!/usr/bin/env bash
set -e
[[ "${1:-}" == --config ]] && shift 2
cmd="$1"; shift
printf '%s\n' "$cmd" >> "$TEST_TMP/rclone-commands"
case "$cmd" in
  listremotes) printf 'gdrive-crypt:\n' ;;
  lsf) (cd "$TEST_TMP/remote" && find . -maxdepth 1 -type f -printf '%f\n' | sort) ;;
  copy)
    [[ "${MOCK_COPY_FAIL:-0}" == 0 ]] || exit 1
    cp -- "$2" "$TEST_TMP/remote/$(basename "$2")"
    if [[ "${MOCK_CORRUPT_ARCHIVE:-0}" == 1 && "$2" == *.dump.gz ]]; then
      printf corrupt > "$TEST_TMP/remote/$(basename "$2")"
    fi
    if [[ "${MOCK_CORRUPT_SIDECAR:-0}" == 1 && "$2" == *.sha256 ]]; then
      printf corrupt > "$TEST_TMP/remote/$(basename "$2")"
    fi
    ;;
  cat)
    file="${1##*/}"
    cat -- "$TEST_TMP/remote/$file"
    ;;
  deletefile)
    file="${1##*/}"
    if [[ "$file" == *.sha256 && "${MOCK_SIDECAR_FAIL_ONCE:-0}" == 1 && ! -e "$TEST_TMP/sidecar-failed" ]]; then
      : > "$TEST_TMP/sidecar-failed"; exit 1
    fi
    rm -- "$TEST_TMP/remote/$file"
    ;;
  *) exit 1 ;;
esac
MOCK
chmod +x "$tmp/bin/"*

expect_fail env MOCK_NO_CONTAINER=1 "$backup"
"$backup" >/dev/null
archive=("$BACKUP_DIR"/*.dump.gz)
[[ -f "${archive[0]}.sha256" ]] || fail 'backup checksum missing'
name="$(basename "${archive[0]}")"

expect_fail env RCLONE_CONFIG="$tmp/config/missing" "$replicate" --upload-only
: > "$RCLONE_CONFIG"
expect_fail env RCLONE_DESTINATION='gdrive-crypt:' "$replicate" --upload-only
expect_fail env RCLONE_DESTINATION='gdrive-backups:namicash/postgres' "$replicate" --upload-only
expect_fail env MOCK_COPY_FAIL=1 "$replicate" --upload-only
[[ -f "${archive[0]}" && ! -f "${archive[0]}.uploaded" ]] || fail 'failed upload changed local recovery state'

"$replicate" --retention-dry-run >/dev/null
[[ ! -f "$tmp/remote/$name" && ! -f "${archive[0]}.uploaded" ]] || fail 'retention dry-run uploaded a pending backup'

expect_fail env MOCK_CORRUPT_ARCHIVE=1 "$replicate" --upload-only
[[ ! -f "${archive[0]}.uploaded" ]] || fail 'corrupt uploaded archive received a marker'
[[ -z "$(find "$TMPDIR" -mindepth 1 -print -quit)" ]] || fail 'verification left temporary files'
expect_fail env MOCK_CORRUPT_SIDECAR=1 "$replicate" --upload-only
[[ ! -f "${archive[0]}.uploaded" ]] || fail 'corrupt uploaded checksum received a marker'
[[ -z "$(find "$TMPDIR" -mindepth 1 -print -quit)" ]] || fail 'sidecar verification left temporary files'

old='namicash-postgres-20200101T000000Z.dump.gz'
printf old-backup > "$tmp/remote/$old"
(cd "$tmp/remote" && sha256sum "$old" > "$old.sha256")
cp "$tmp/remote/$old" "$BACKUP_DIR/$old"
cp "$tmp/remote/$old.sha256" "$BACKUP_DIR/$old.sha256"

"$replicate" --upload-only >/dev/null
[[ -f "$tmp/remote/$name" && -f "$tmp/remote/$name.sha256" ]] || fail 'upload-only did not upload pair'
[[ -f "${archive[0]}.uploaded" ]] || fail 'verified upload marker missing'
[[ -f "$tmp/remote/$old" && -f "$tmp/remote/$old.sha256" ]] || fail 'upload-only performed retention'
[[ -f "$BACKUP_DIR/$old" && -f "$BACKUP_DIR/$old.sha256" ]] || fail 'upload-only removed an expired local pair'
if grep -Fxq deletefile "$tmp/rclone-commands"; then fail 'upload-only attempted deletion'; fi

# A fresh marker cannot hide a missing remote member; an old marker triggers
# full byte verification and repairs a corrupt archive.
rm -- "$tmp/remote/$name"
"$replicate" --upload-only >/dev/null
cmp -s "${archive[0]}" "$tmp/remote/$name" || fail 'missing remote archive was not repaired'
printf corrupt > "$tmp/remote/$name"
hash="$(sha256sum "${archive[0]}" | cut -d ' ' -f1)"
printf '%s %s\n' "$hash" "$(($(date +%s) - 4 * 86400))" > "${archive[0]}.uploaded"
"$replicate" --upload-only >/dev/null
cmp -s "${archive[0]}" "$tmp/remote/$name" || fail 'corrupt remote archive was not repaired'

printf x >> "${archive[0]}"
expect_fail "$replicate" --upload-only
truncate -s -1 "${archive[0]}"

# The recovery baseline and unrelated files are outside the deletion scope.
printf baseline > "$tmp/remote/namicash-20261023T050337Z.dump.gz"
printf unrelated > "$tmp/remote/other.dump.gz"
"$replicate" --retention-dry-run > "$tmp/dry-run-output"
grep -Fq "would remove cloud pair $old" "$tmp/dry-run-output" || fail 'dry-run missed expired cloud pair'
[[ -f "$tmp/remote/$old" && -f "$tmp/remote/$old.sha256" ]] || fail 'dry-run deleted remote pair'
[[ -f "$tmp/remote/namicash-20261023T050337Z.dump.gz" ]] || fail 'dry-run touched baseline'

printf corrupted > "$tmp/remote/$old"
"$replicate" --retention-dry-run > "$tmp/corrupt-old-output"
if grep -Fq "would remove cloud pair $old" "$tmp/corrupt-old-output"; then fail 'corrupt cloud pair marked for deletion'; fi
printf old-backup > "$tmp/remote/$old"

expect_fail env MOCK_SIDECAR_FAIL_ONCE=1 "$replicate"
[[ ! -f "$tmp/remote/$old" && -f "$tmp/remote/$old.sha256" ]] || fail 'partial deletion state was not preserved'
[[ -f "$BACKUP_DIR/.cloud-delete-$old" ]] || fail 'partial deletion journal missing'
"$replicate" >/dev/null
[[ ! -f "$tmp/remote/$old.sha256" && ! -f "$BACKUP_DIR/.cloud-delete-$old" ]] || fail 'partial deletion was not resumed'
[[ -f "$tmp/remote/namicash-20261023T050337Z.dump.gz" && -f "$tmp/remote/other.dump.gz" ]] || fail 'retention deleted unrelated files'

# No recent verified remote backup means no cloud deletion.
rm -- "$tmp/remote/$name"
printf old-again > "$tmp/remote/$old"
(cd "$tmp/remote" && sha256sum "$old" > "$old.sha256")
"$replicate" --retention-dry-run > "$tmp/no-anchor-output"
grep -Fq 'no recent verified remote backup' "$tmp/no-anchor-output" || fail 'missing recent anchor was accepted'
[[ -f "$tmp/remote/$old" ]] || fail 'old archive removed without recent anchor'
cp "$tmp/remote/$old" "$BACKUP_DIR/$old"
cp "$tmp/remote/$old.sha256" "$BACKUP_DIR/$old.sha256"
"$replicate" --retention-dry-run > "$tmp/unreplicated-output"
if grep -Fq "would remove local pair $old" "$tmp/unreplicated-output"; then fail 'unreplicated local backup marked for deletion'; fi

# Locks reject concurrent backup and replication.
expect_fail flock -n "$BACKUP_DIR/.backup.lock" "$backup"
expect_fail flock -n "$BACKUP_DIR/.replicate.lock" "$replicate" --upload-only
echo 'Backup safety tests passed.'
