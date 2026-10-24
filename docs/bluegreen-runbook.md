# NamiCash Blue/Green runbook

This is an **optional, manual** deployment path. `scripts/bluegreen-release.sh` defaults to staging mode and all modifying commands require `--execute`. The existing `deploy-release.sh`, `rollback-release.sh` and `verify-deployment.sh` remain available for the current single-environment system. Nothing in this repository changes the live Caddy gateway, Cloudflare Tunnel, production containers or networks on checkout.

## Architecture and boundaries

```text
Cloudflare Tunnel (currently localhost:3004; unchanged)
future: localhost:8091 -> Caddy -> blue-frontend OR green-frontend
                                        |                 |
                                   blue-api          green-api
                                        \                 /
                                   dedicated DB network -> existing PostgreSQL
```

The initial Blue slot is the existing `cashbook-mafunami` frontend and backend. Its container IDs are captured at bootstrap. Green uses `namicash-green`; after explicitly retiring legacy Blue, future Blue candidates use `namicash-blue`. Each managed color has a private `*_app` network. Its frontend joins that network and the external `namicash-gateway` network. Its backend joins the app network and the external, internal-only `namicash-db-access` network. The existing database will be manually attached only to `namicash-db-access` with alias `db`; it remains on its existing production network and volume. Caddy joins **only** the gateway network. Managed frontends mount generated Nginx configuration routing `/api/` to their own `blue-api` or `green-api` alias. Candidate ports are never published. The internal database network intentionally blocks direct internet access from managed backends; exchange-rate fetching will use the application's local fallback unless an explicitly reviewed outbound proxy is added. Gateway routes point only to frontends.

The backend command is explicitly `uvicorn`, overriding the image default that runs Alembic. No controller command runs migrations, recreates PostgreSQL, removes volumes, prunes images or invokes `docker compose down`. The controller checks the existing database container ID and volume before staging and promotion. Its production database query reads only `alembic_version`.

## Caddy design and one-time Blue transition

The current standalone gateway at `/home/jahn/caddy-gateway/` has `admin off`, a single-file bind mount and `frontend:8080` on `cashbook-mafunami_default`. **Do not edit it for isolated staging.** Caddy's normal reload command requires an enabled admin endpoint; a protected Unix socket avoids exposing that endpoint on a TCP port. The future gateway configuration should import a single managed route snippet from a **directory** bind mount. Atomic replacement of a host file mounted individually is unsafe because the container can retain the old inode. Use [compose.bluegreen.example.yaml](../gateway/compose.bluegreen.example.yaml), [Caddyfile.bluegreen.example](../gateway/Caddyfile.bluegreen.example) and [namicash.blue.caddy](../gateway/namicash.blue.caddy) as reviewed templates. The controller requires this Caddy instance to remain dedicated to NamiCash and rejects any extra route; unrelated applications must use another gateway so this reload cannot interrupt their connections. Bind only the managed NamiCash snippet directory. The controller requires exactly one managed import and the Unix admin socket, records the exact Caddyfile hash, validates a candidate full Caddyfile before promotion, swaps the snippet atomically, and reloads Caddy through `docker exec ... caddy reload --address unix//run/caddy-admin.sock`. It verifies actual gateway homepage and `/api/v1/auth/recovery-info` traffic. A failed reload or route check restores the previous snippet and reloads Blue. The controller never uses Caddy's public admin API.

**Future manual production transition, requiring a separate change window:** first create `namicash-gateway` and an **internal** `namicash-db-access` network; attach the existing database to the DB network with alias `db`, and attach the existing Blue frontend to the gateway network with alias `blue-frontend`. Review a new standalone Caddy Compose definition with only the dedicated gateway network, the current `127.0.0.1:8091` binding, the existing Caddy image, and directory mount for managed snippets. Install the Blue snippet and protected Unix admin configuration, then restart/recreate **only Caddy** in that change window. Confirm its container has no production or DB network membership. Confirm direct production ports and existing frontend/backend/database container IDs remain unchanged. Run the controller's production `bootstrap` dry run with the manifest that actually matches the running Blue image IDs; run `bootstrap --execute` only after the Blue gateway route works. The current Caddy test configuration and all production containers stay untouched during this implementation task.

Never assume a `v1.0.2` manifest describes the currently running Blue containers. Bootstrap fails if its digests do not resolve to their image IDs. Preserve a known-good copy of the standalone gateway Compose file, Caddyfile and route snippet before any future Caddy transition.

## Database compatibility and resources

Production `prepare`, `stage`, `verify` and `promote` require a reviewed JSON attestation supplied with global `--schema-attestation /path/to/attestation.json`:

```json
{
  "compatible": true,
  "revision": "actual_alembic_version",
  "active_backend": "ghcr.io/mafunamiii/namicash-backend@sha256:<64 lowercase hex>",
  "candidate_backend": "ghcr.io/mafunamiii/namicash-backend@sha256:<64 lowercase hex>",
  "approved_by": "operator identifier"
}
```

The controller checks the live read-only revision, exact active/candidate backend digests, approval field and attestation file hash. If evidence is missing or changes, production staging/promotion stops. An operator must separately review both application versions against the **same** schema. Use expand-and-contract migrations: add compatible fields first, deploy both versions, then remove old fields only after the old version is retired. Never rely on application rollback to reverse a schema change. This tool does not authorize or execute migrations.

A candidate is limited to 512 MiB backend and 256 MiB frontend, with PID limits. Production preflight retains its 1,536 MiB `MemAvailable`, 2,048 MiB free disk, and 24-running-container gates. Its approximate 1,024 MiB additional footprint includes 256 MiB for runtime overhead. These gates are not a capacity guarantee; inspect other workloads and disk before a real stage. Retire the inactive managed slot explicitly after the observation period to avoid two complete environments indefinitely.

## Fully isolated staging (manual; no production access)

Staging uses `namicash-bg-stage-*` Compose projects, `namicash-bg-stage-database` and `namicash-bg-stage-gateway` networks, disposable `namicash-bg-stage-postgres-data`, synthetic fixture SQL, its own Caddy container on **127.0.0.1:18091**, and `.env.bluegreen.staging` credentials. It never joins a production network or publishes a production port. The fixture marks the disposable database. Automated staging explicitly applies Blue and then candidate Alembic migrations in this isolated database, checks the resulting revision against each image head, and probes Blue again after candidate migration. This exercises compatibility but cannot prove every application path is safe; production still requires reviewed schema evidence. Do not use production credentials. The controller rejects a missing staging marker, a non-staging DB name, a database URL outside the isolated `db` alias, or non-staging containers on the staging DB network.

Staging setup budgets the four container limits: 512 MiB database, 128 MiB gateway, 512 MiB backend, and 256 MiB frontend (1,408 MiB total). It adds 256 MiB for Docker/process overhead and keeps 768 MiB `MemAvailable` for the host, requiring 2,432 MiB before setup. A later candidate adds only backend and frontend (768 MiB), requiring 1,792 MiB. The controller checks remaining capacity before each successive container startup. Staging uses measured available memory rather than a Docker container-count cap: container count alone does not measure load. The 2,048 MiB disk gate still applies. The reserve and overhead are conservative planning allowances, not measured peak consumption; check memory PSI, swap-in/out, and other host workloads throughout an operator-run deployment.

From the repository root, copy [staging/env.example](../staging/env.example) to `.env.bluegreen.staging`, replace the example password in **both** `POSTGRES_PASSWORD` and `DATABASE_URL` with the same distinct synthetic credential, and keep the file untracked. Inspect host memory and disk first. These are the exact manual staging commands; none are run by CI:

```sh
MANIFEST=/home/jahn/namicash-releases/v1.0.2/release-manifest.json
python3 scripts/release_deployment.py validate-manifest --manifest "$MANIFEST"
scripts/bluegreen-release.sh staging-setup --manifest "$MANIFEST"
scripts/bluegreen-release.sh staging-setup --manifest "$MANIFEST" --execute
scripts/bluegreen-release.sh bootstrap --manifest "$MANIFEST"
scripts/bluegreen-release.sh bootstrap --manifest "$MANIFEST" --execute
scripts/bluegreen-release.sh plan --manifest "$MANIFEST"
scripts/bluegreen-release.sh prepare --manifest "$MANIFEST" --execute
scripts/bluegreen-release.sh stage --manifest "$MANIFEST" --execute
scripts/bluegreen-release.sh verify
scripts/bluegreen-release.sh status
```

To simulate an unhealthy candidate, stop **only** the staging Green backend, confirm promotion dry run fails, then restart it and wait for health:

```sh
docker stop namicash-bg-stage-green-backend-1
scripts/bluegreen-release.sh promote
docker start namicash-bg-stage-green-backend-1
scripts/bluegreen-release.sh verify
```

Simulate a Caddy reload failure. The controller must restore Blue, and `status` must still show Blue healthy:

```sh
scripts/bluegreen-release.sh promote --inject-failure reload --execute
scripts/bluegreen-release.sh status
```

Simulate a controller crash after Caddy reload, then recover the previous route from the durable journal and route snapshot:

```sh
scripts/bluegreen-release.sh promote --inject-failure crash-after-reload --execute
scripts/bluegreen-release.sh status
scripts/bluegreen-release.sh rollback --execute
scripts/bluegreen-release.sh status
```

Finally test a normal promotion and rollback, keeping both environments available:

```sh
scripts/bluegreen-release.sh promote --execute
scripts/bluegreen-release.sh status
scripts/bluegreen-release.sh rollback --execute
scripts/bluegreen-release.sh status
```

Test HTTP/1.1 keep-alive with `python3 scripts/probe-bluegreen-keepalive.py --before blue --after green` in one terminal, run the normal staging `promote --execute` command in another, then press Enter in the probe. It reports whether the held connection retained the old route or reconnected and requires a fresh connection to reach Green. Do not assume reload drains in-flight requests. Caddy's `stream_close_delay 5m` in the managed route limits WebSocket disruption during reload. NamiCash currently has no WebSocket endpoint; when one is added, hold a staging WebSocket open through promotion and rollback and verify its documented reconnection behavior before production use.

The automated off-host rehearsal captures staging logs, then removes only containers, networks, and the volume with verified staging identities. The older manual procedure above remains an operator-controlled path.

## Production operation after separate approval

All commands below are **future** procedures; do not run them for this implementation. Add `--mode production` before the command, use the actual running Blue manifest for bootstrap, and supply schema attestation for candidate operations:

```sh
scripts/bluegreen-release.sh --mode production bootstrap --manifest /path/to/blue-manifest.json
scripts/bluegreen-release.sh --mode production bootstrap --manifest /path/to/blue-manifest.json --execute
scripts/bluegreen-release.sh --mode production --schema-attestation /secure/compatibility.json plan --manifest /path/to/candidate-manifest.json
scripts/bluegreen-release.sh --mode production --schema-attestation /secure/compatibility.json prepare --manifest /path/to/candidate-manifest.json --execute
scripts/bluegreen-release.sh --mode production --schema-attestation /secure/compatibility.json stage --manifest /path/to/candidate-manifest.json --execute
scripts/bluegreen-release.sh --mode production --schema-attestation /secure/compatibility.json verify
scripts/bluegreen-release.sh --mode production --schema-attestation /secure/compatibility.json promote
scripts/bluegreen-release.sh --mode production --schema-attestation /secure/compatibility.json promote --execute
scripts/bluegreen-release.sh --mode production status
scripts/bluegreen-release.sh --mode production rollback --execute
```

`plan` is read-only apart from creating its lock directory. `prepare` pulls digest images only with `--execute`. `stage` starts only inactive backend/frontend with `--no-deps --no-build --pull never`; the database service is absent from candidate Compose. `verify` checks container health, image IDs, private networks, frontend-to-backend API connectivity, Caddy routing of the active slot, database health and initial Blue IDs. `promote` checks both slots, schema evidence, Caddy configuration hash and actual route before changing anything. `finalize --color <inactive> --execute` stops only inactive managed application containers; it never deletes them or their images. Retiring the initial legacy Blue requires the additional `--allow-legacy-blue` flag and is only appropriate after Green has proved stable. It stops the two legacy application services, not PostgreSQL.

State is in `/home/jahn/namicash-releases/deployment-state/bluegreen-production/state.json` with append-only `events.jsonl` and the previous route snapshot. Copy this directory to durable operator-controlled storage. A state phase `promoting` or `recovery-required` after interruption blocks new promotion. Run `rollback --execute` to restore the recorded previous snippet and verify its route. Production rollback refuses a changed database schema revision because earlier compatibility evidence would no longer apply. A phase `stage-failed` leaves the active route unchanged; inspect candidate health, then retry stage with the same manifest or explicitly finalize it. Do not hand-edit the state or managed route while the controller is in use.

## Tunnel migration, monitoring and failure recovery

The Cloudflare Tunnel currently points to `http://localhost:3004`. **No tunnel file or DNS setting is changed here.** In a future separately approved change window, first complete the Blue gateway transition and verify `http://127.0.0.1:8091/` and `/api/v1/auth/recovery-info` return HTTP 200 through Caddy with `X-Nami-Route: blue`; also verify direct `localhost:3004` remains healthy. Only then change the tunnel origin to `http://localhost:8091` in the external tunnel configuration and restart the tunnel under its operator procedure. Verify the public hostname, API, sessions and logs. Retain the old origin and Caddyfile backups for rapid reversal.

If Caddy is unavailable, restore the previous tunnel origin `http://localhost:3004`; the existing Blue frontend remains on that port until explicitly retired. If a candidate fails, use `status`, check candidate container health and Caddy logs, and route back using `rollback --execute`. If a Caddy reload fails, the controller attempts an immediate return to the previous known-good snippet and records whether recovery is still needed. To restore the previous production routing configuration, restore the backed-up standalone Caddy Compose and Caddyfile only in a separate maintenance window, validate Caddy, and point the tunnel back to port 3004. Avoid assuming old HTTP keep-alive or streaming requests drain on reload. Review proxy access logs, backend readiness, database health, and the event journal after every future promotion.

Caddy reload behavior and the Unix-socket admin option are documented in the [Caddy command reference](https://caddyserver.com/docs/command-line) and [global options](https://caddyserver.com/docs/caddyfile/options). The [reverse proxy documentation](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy) describes streaming connection behavior and `stream_close_delay`.

## On-demand off-host staging on the Legion

The [staging-validation workflow](../.github/workflows/staging-validation.yml) runs only on `workflow_dispatch` from protected `main`. A GitHub-hosted gate checks the repository, branch, mode and successful tagged `Release images` runs before the dedicated `[self-hosted, Linux, X64, namicash, legion-staging]` runner starts. The staging job checks out that exact controller commit, downloads the two release manifests, and verifies each manifest's version, source commit and workflow URL against its successful release run. It uses `contents: read`, `actions: read` and `packages: read`; no production credential or automatic production job is included. Concurrency allows one staging rehearsal at a time, with 10- and 90-minute job limits. Protect `main` and require review of `.github/workflows/`, `scripts/bluegreen_deployment.py`, `scripts/staging_validation.py`, and `scripts/staging_evidence.py`; workflow trust relies on that branch protection, since anyone able to alter the trusted workflow can control a Docker-capable runner. Pull request events are absent from this workflow. A staging report alone never authorizes production.

Use a dedicated Linux VM on the Lenovo Legion, preferably amd64 with at least 8 GiB RAM and 20 GiB free disk, Docker Engine and Compose v2, Python 3.11+, Git, GitHub CLI, OpenSSL and outbound access to GitHub and GHCR. Give the VM its own disk and network, with no shared personal home directories, SSH keys, or production VPN/credentials. Keep port 18091 bound only to VM loopback. Create a dedicated non-root `namicash-runner` account. Membership in the `docker` group grants effectively root access to the VM; treat that account and all jobs on it as privileged. Prefer a single-job ephemeral runner; provision a fresh VM snapshot or re-register after each job. GitHub-hosted runners perform the admission gate, but this is not a substitute for protecting the repository's workflow definitions.

Example VM preparation, as an administrator after installing Docker Engine, Compose and GitHub CLI from their maintained package sources:

```sh
sudo useradd --create-home --shell /bin/bash namicash-runner
sudo usermod -aG docker namicash-runner
sudo install -d -o namicash-runner -g namicash-runner -m 0700 /opt/namicash-runner
sudo -iu namicash-runner
cd /opt/namicash-runner
# Download the current Linux x64 runner archive and verify its checksum using
# the exact commands shown under repository Settings > Actions > Runners > New.
# Extract it here, then register with a fresh repository-scoped token:
read -rs -p 'One-time runner registration token: ' REG_TOKEN; printf '\n'
./config.sh --url https://github.com/Mafunamiii/Cashbook-mafunami \
  --token "$REG_TOKEN" --labels namicash,legion-staging --unattended --ephemeral
unset REG_TOKEN
# Install the guard below before starting ./run.sh.
```

Install the fail-closed [runner job guard](../scripts/staging_runner_guard.sh) from reviewed `main` outside the runner work directory before starting `run.sh`. It checks the repository, event, branch, workflow path and job before any workflow step. For example, after obtaining a reviewed checkout: `sudo install -o root -g root -m 0555 scripts/staging_runner_guard.sh /opt/namicash-runner-guard.sh`, then add `ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/namicash-runner-guard.sh` to the runner application's `.env` file before invoking `./run.sh`. Confirm the hook is active in a test job's runner setup log. If organization runner groups with selected-workflow policy are available, additionally allow only `Mafunamiii/Cashbook-mafunami/.github/workflows/staging-validation.yml@refs/heads/main` and this repository. [GitHub documents the pre-job hook](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/run-scripts), which fails the job when the script exits nonzero. The guard protects against an unrelated job selecting the labels. Docker access can still alter host files from within a job, so the strongest boundary is an organization runner group's selected-workflow policy or a fresh single-job VM.

Never paste registration or removal tokens into a command recorded by shell history or a CI log. Do not configure this runner at organization scope or add generic labels that unrelated workflows use. GitHub's repository runner settings should show only this repository. Stop `run.sh` before shutting down the VM. An ephemeral runner deregisters after its job; start a newly registered runner for the next rehearsal. For a persistent runner, stop it, obtain a fresh removal token from repository runner settings, and run `./config.sh remove --token "$REMOVE_TOKEN"` in the VM without logging the token. Remove its working directory and Docker configuration only after preserving the report artifact and confirming no job is active. Running the runner as a system service is optional; a controlled `run.sh` session better fits a laptop that is powered off routinely. If the laptop is offline, the staging job queues; production stays unaffected.

In Actions > **Off-host staging validation** > **Run workflow**, select `main`, choose `infrastructure` for the same successful release run in both fields, or `release` for the current production release as Blue and a distinct candidate release as Green. Enter the numeric `Release images` workflow run IDs, not mutable tags. The GHCR package must grant this repository's `GITHUB_TOKEN` read access. No staging process starts on checkout or on a push. The runner generates a random staging-only database password in its temporary directory; the script uses synthetic SQL and never contacts production PostgreSQL. For a local dry setup, create an untracked staging env file from [staging/env.example](../staging/env.example), then run `scripts/staging_validation.py --help`; the script itself executes and cleans up staging, so invoke it only on the isolated VM.

The script checks architecture, Docker/Compose, port 18091, memory, disk, and absence of known production networks. It removes a stale staging stack only after checking exact Compose labels, creates the isolated networks/database, applies Blue migrations to the disposable database, verifies Blue, pulls Green by manifest digest, applies candidate migrations to that same disposable database, verifies Blue again, starts and verifies Green, switches Caddy to Green, then rolls back to Blue and checks application/database health. It records `staging-report.json`, `staging-report.md`, and capped, redacted container logs in the `staging-validation-<run>-<attempt>` Actions artifact. The JSON includes both release versions, source commits and backend/frontend digests, controller commit, run ID, schema revision and both image heads, individual test results, promotion/rollback results, completion time and overall PASS/FAIL. A failed mandatory step makes the run fail. Container images are cached between runs; the disposable database volume is removed after each run. After a failed or interrupted run, start another run on the same VM: it first checks resource identities and removes only the staging stack. If cleanup fails, inspect the artifact logs and VM Docker state; never use `docker system prune` or `docker compose down -v` against an unverified project.

Routine smoke tests validate health, API connectivity, digest identity, isolated networks, Caddy routing, promotion and rollback. Injected health failures and crash recovery remain separate controller tests and manual fault exercises; routine workflow runs do not deliberately crash the live rehearsal. A passing smoke report establishes tested paths only, not universal backward schema compatibility.

### Manual production approval design (inactive)

A separate future workflow must require `workflow_dispatch` with explicit Blue/candidate release run IDs, the successful **release-mode** staging run ID and attempt, and an operator confirmation string identifying the exact candidate digest. It should download the original release manifests and staging report from GitHub, verify all source commits, workflow identities, exact backend/frontend digests and controller commit, report PASS, successful promotion and rollback, and freshness (currently the evidence helper uses a 72-hour limit). Validate the staging workflow's run conclusion, repository, `main` ref, artifact identity and GitHub run URL; do not accept a locally supplied JSON file as authorization. Require a separate operator review of schema compatibility and migration plan. On the production host, check resources, current release identity, database revision, latest usable backup and restore procedure before any prepare or promotion. Never run migrations implicitly. Keep the actual production controller invocation behind a separate explicit manual step after these checks; no such workflow is active in this phase. The Legion can be powered off after evidence upload because GitHub stores the artifact and production has no connection to the VM.
