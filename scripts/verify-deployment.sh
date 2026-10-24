#!/usr/bin/env bash
set -Eeuo pipefail
exec python3 "$(dirname "$0")/release_deployment.py" verify "$@"
