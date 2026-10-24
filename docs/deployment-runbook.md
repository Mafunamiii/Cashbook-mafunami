# Controlled GHCR deployment

## Scope and prerequisites

The production project is `cashbook-mafunami`. `compose.ghcr.yaml` is an explicit copy of the production service configuration with digest images and no `build` or `migrate` service. The backend image starts `uvicorn` without running migrations; both deployment Compose files also specify direct `uvicorn` commands. Run migrations only through the explicit `migrate` profile in `compose.production.yaml` after separate approval. The deploy tool checks resolved Compose parity against `compose.production.yaml` before any change. It targets only `backend` and `frontend` with `--no-deps --no-build --pull never`; the database, network, PostgreSQL volume, environment file and published ports must retain their identities. It never runs migrations. Application rollback does **not** recover or reverse database changes.

Run as the production Docker operator from the repository. Keep `.env.prod` readable to that operator. The release manifest is an externally supplied artifact; verify its release workflow, source commit and intended version before use. Do not edit `.env.prod` to select images.

The tool requires a verified local PostgreSQL backup newer than 48 hours and verifies its encrypted off-site archive and checksum directly through `rclone cat`. A `.uploaded` marker alone is ignored. The read can take time. GHCR manifests must be accessible and include `linux/amd64`. Previous images must already be available locally by immutable GHCR digest and match the **running image IDs**. Docker/Compose access, production container health, exact four port bindings, network, DB container and DB volume are required. A mismatch stops the deployment.

The supplied v1.0.2 release manifest is `/home/jahn/namicash-releases/v1.0.2/release-manifest.json`. The supplied older digest candidates are:

```text
ghcr.io/mafunamiii/namicash-backend@sha256:0b3a42cf1f9f6381f6818b43ef3e90304b1f3f766abe5736123055da48ae0c24
ghcr.io/mafunamiii/namicash-frontend@sha256:23b781578479ea6e9533087334f76631ecac05fc636799ce2dde97f9f86f8f66
```

Use them as `--previous-*` only after confirming each local digest resolves to the image ID of its running container. The execution script saves and SHA-256 checks local archives of both previous images under `deployment-state/images/` before replacing either container. Keep those archives and the append-only history; do not prune the images. The tool checks free disk space before saving. If the GHCR digest disappears locally, rollback checks the archive checksum, loads it only with `--execute`, and uses its verified immutable image ID. Store a separate copy of the state directory on durable operator-controlled storage because host loss would otherwise remove both archives and history.

## Dry run and production deployment

```sh
MANIFEST=/home/jahn/namicash-releases/v1.0.2/release-manifest.json
python3 scripts/release_deployment.py validate-manifest --manifest "$MANIFEST"
scripts/deploy-release.sh --manifest "$MANIFEST"
```

Dry run takes a deployment lock, checks Docker, Compose parity, environment availability, database and application health, container/network/volume identity, exact ports, current GHCR access, previous local digest availability, latest local backup checksum and current encrypted off-site bytes. It prints a plan. It does not pull images, recreate containers or write a deployment record. The lock directory may be created at `/home/jahn/namicash-releases/deployment-state`.

If the running image has no discoverable immutable GHCR reference, pass both verified older digests explicitly:

```sh
scripts/deploy-release.sh --manifest "$MANIFEST" \
  --previous-backend 'ghcr.io/mafunamiii/namicash-backend@sha256:0b3a42cf1f9f6381f6818b43ef3e90304b1f3f766abe5736123055da48ae0c24' \
  --previous-frontend 'ghcr.io/mafunamiii/namicash-frontend@sha256:23b781578479ea6e9533087334f76631ecac05fc636799ce2dde97f9f86f8f66'
```

Only after reviewing the successful plan, repeat with `--execute`. The execution archives both previous images, records previous references and start time, pulls and checks both images on `linux/amd64`, rechecks database identity, replaces backend and waits for health, then replaces frontend and verifies health, image IDs/digests, ports, DB container, volume and network before recording success. A failed step records failure and stops. It does not automatically revert application containers. Deployment history is append-only JSONL in the state directory. Do not edit it manually.

```sh
scripts/deploy-release.sh --manifest "$MANIFEST" --execute
scripts/verify-deployment.sh --manifest "$MANIFEST"
```

## Rollback and troubleshooting

```sh
scripts/rollback-release.sh
scripts/rollback-release.sh --execute
scripts/verify-deployment.sh
```

Rollback uses the previous references captured by the latest deployment attempt, including a failed attempt. It requires those local digest images or checksum-verified saved archives, current containers to match that attempt, and the original DB/network/port identities. It replaces backend then frontend with no dependencies, waits for both health checks, and appends the outcome to history. If prerequisites fail, stop and investigate; database recovery is a separate procedure in `docs/backup-restore.md`. No migration is automatically reversed.

If preflight fails, inspect the named condition without changing production. For a missing previous digest, confirm the candidate digest matches the running image ID; if a saved archive exists, verify its checksum. Execution loads the archive and pins the restored immutable image ID. For backup failures, fix backup or cloud replication, then rerun the dry run. For GHCR failures, confirm registry access and image retention. For a failed deployment, inspect `history.jsonl` and container health/logs, then run rollback dry run. Never use `docker compose down`, `down -v`, or `up` without the targeted script in production.

## Isolated staging validation (manual only)

`compose.staging.yaml` defines a separate `namicash-staging` project, a named `namicash-staging-postgres-data` volume, no published host ports, and memory limits of 512 MiB DB, 512 MiB backend and 256 MiB frontend. It requires a separate `.env.staging` with staging-only database credentials and `DATABASE_URL`; do not copy production secrets. Check available memory and disk before running. The staging commands are deliberately manual and are not run by CI or this implementation. They do not use production containers or the production database volume.

After validating the manifest, set `BACKEND_IMAGE` and `FRONTEND_IMAGE` to the two exact manifest digest references, and run:

```sh
docker compose -p namicash-staging --env-file .env.staging -f compose.staging.yaml config --quiet
docker compose -p namicash-staging --env-file .env.staging -f compose.staging.yaml up -d --no-build
docker compose -p namicash-staging --env-file .env.staging -f compose.staging.yaml ps
```

With a known-good older pair available locally, change only the two image environment variables to their older digests, then run `up -d --no-deps --no-build --pull never backend`, wait for backend health, and run the same targeted command for frontend. Confirm both health and image IDs, and that staging DB container ID and volume are unchanged. Repeat in the forward direction to test deployment. For failure paths, use the isolated unit tests below; they cover malformed manifests, missing backup/cloud evidence, unhealthy DB, unexpected volume, absent rollback digest, failed health, lock contention, ports, no database recreation and no migrations. Do not deliberately make production unhealthy to test them.

When finished, stop the staging project without removing its volume unless separately authorized. No production project command is part of staging validation.

```sh
python3 -m unittest discover -s tests -p 'test_release_deployment.py'
bash scripts/test-backups.sh
```

## Blue/Green option

The existing digest-pinned deployment commands above remain the single-environment fallback. The separate blue/green controller, staging procedure, Caddy transition, and recovery rules are in [bluegreen-runbook.md](bluegreen-runbook.md). No blue/green automation is activated by this repository.
