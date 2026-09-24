#!/usr/bin/env bash
set -euo pipefail

namespace="namicash-staging"
manifest_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/manifests" && pwd)"
env_file="${1:-staging.env}"

if [[ ! -f "$env_file" ]]; then
  echo "Run create-secrets.sh $env_file first." >&2
  exit 1
fi

if ! kubectl -n "$namespace" get secret namicash-staging-tls >/dev/null 2>&1; then
  echo "Missing namicash-staging-tls; create the TLS secret before deploying." >&2
  exit 1
fi

kubectl apply -k "$manifest_dir"
kubectl -n "$namespace" rollout status statefulset/postgresql --timeout=10m
kubectl -n "$namespace" rollout status deployment/backend --timeout=10m
kubectl -n "$namespace" rollout status deployment/frontend --timeout=10m

echo "Staging resources are deployed. Inspect the Traefik Ingress with:"
echo "kubectl -n $namespace get ingress namicash-staging"
