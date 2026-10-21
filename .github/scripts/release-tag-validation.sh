#!/usr/bin/env bash

fetch_annotated_release_tag_commit() {
  local tag="$1"
  local verified_ref="refs/namicash/verified-tags/$tag"
  local tag_object object_type

  # Fetch the advertised remote tag ref into a separate namespace so the
  # checkout action's local ref or detached-HEAD resolution cannot mask its type.
  git fetch --no-tags origin "refs/tags/$tag:$verified_ref" >&2 || return 1

  tag_object="$(git rev-parse --verify "$verified_ref")" || return 1
  object_type="$(git cat-file -t "$tag_object")" || return 1
  if [[ "$object_type" != "tag" ]]; then
    echo "Release tags must be annotated Git tags (remote object type: $object_type)." >&2
    return 1
  fi

  git rev-parse --verify "$tag_object^{commit}"
}
