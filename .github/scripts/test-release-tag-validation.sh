#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

git init --bare --initial-branch=main "$tmp_dir/remote.git" >/dev/null
git init --initial-branch=main "$tmp_dir/source" >/dev/null
git -C "$tmp_dir/source" config user.name "NamiCash CI test"
git -C "$tmp_dir/source" config user.email "ci-test@example.invalid"
git -C "$tmp_dir/source" commit --allow-empty -m "validation fixture" >/dev/null
commit="$(git -C "$tmp_dir/source" rev-parse HEAD)"
git -C "$tmp_dir/source" remote add origin "$tmp_dir/remote.git"
git -C "$tmp_dir/source" push -u origin main >/dev/null
git -C "$tmp_dir/source" tag -a v1.0.0 -m "annotated fixture"
git -C "$tmp_dir/source" tag v1.0.1 "$commit"
git -C "$tmp_dir/source" push origin refs/tags/v1.0.0 refs/tags/v1.0.1 >/dev/null

git clone -q "$tmp_dir/remote.git" "$tmp_dir/checkout"
git -C "$tmp_dir/checkout" checkout --detach "$commit" >/dev/null 2>&1
# Reproduce checkout resolving the tag name to its commit in the local tag ref.
git -C "$tmp_dir/checkout" update-ref refs/tags/v1.0.0 "$commit"

(
  cd "$tmp_dir/checkout"
  source "$repo_root/.github/scripts/release-tag-validation.sh"

  tag_commit="$(fetch_annotated_release_tag_commit v1.0.0)"
  remote_tag_object="$(git rev-parse refs/namicash/verified-tags/v1.0.0)"
  expected_tag_object="$(git --git-dir="$tmp_dir/remote.git" rev-parse refs/tags/v1.0.0)"
  [[ "$remote_tag_object" == "$expected_tag_object" ]]
  [[ "$tag_commit" == "$commit" ]]
  [[ "$tag_commit" == "$(git rev-parse HEAD)" ]]
  [[ "$tag_commit" == "$(git rev-parse origin/main)" ]]

  if fetch_annotated_release_tag_commit v1.0.1 >/dev/null; then
    echo "Lightweight tag was incorrectly accepted." >&2
    exit 1
  fi
)

echo "Release tag validation regression checks passed."
