#!/usr/bin/env bash
set -euo pipefail

namespace="namicash-staging"
env_file="${1:-staging.env}"

if [[ ! -f "$env_file" ]]; then
  echo "Missing $env_file; copy staging.env.example and replace its placeholders." >&2
  exit 1
fi

for key in POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD DATABASE_URL INITIAL_INVITE_CODE; do
  if ! grep -Eq "^${key}=.+" "$env_file"; then
    echo "$env_file must define $key" >&2
    exit 1
  fi
done

if grep -Eqi 'replace-with|cashbook-postgres-production|cashbook\.mafunami\.me' "$env_file"; then
  echo "$env_file still contains a placeholder or production value" >&2
  exit 1
fi

if ! grep -Eq '^DATABASE_URL=postgresql\+psycopg://[^@]+@postgresql:5432/' "$env_file"; then
  echo "DATABASE_URL must target the in-cluster postgresql service" >&2
  exit 1
fi

kubectl create namespace "$namespace" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "$namespace" create secret generic namicash-staging-secrets \
  --from-env-file="$env_file" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Applied staging secrets to namespace $namespace. Values were not written to the repository."
