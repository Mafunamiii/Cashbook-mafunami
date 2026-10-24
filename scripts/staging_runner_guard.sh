#!/usr/bin/env bash
# Install outside the runner work directory as ACTIONS_RUNNER_HOOK_JOB_STARTED.
set -euo pipefail
[[ "${GITHUB_REPOSITORY:-}" == "Mafunamiii/Cashbook-mafunami" ]]
[[ "${GITHUB_EVENT_NAME:-}" == "workflow_dispatch" ]]
[[ "${GITHUB_REF:-}" == "refs/heads/main" ]]
[[ "${GITHUB_WORKFLOW_REF:-}" == "Mafunamiii/Cashbook-mafunami/.github/workflows/staging-validation.yml@refs/heads/main" ]]
[[ "${GITHUB_JOB:-}" == "rehearse" ]]
