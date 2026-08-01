# Cashbook

Cashbook is a self-hosted budget tracker. The repository currently includes the
project foundation, financial-domain schema, authentication, categories,
transactions, budget configuration, dashboard, records, settings, and minimal
administration.

## Prerequisites

- Docker Engine with Docker Compose v2
- Optional for running tools outside containers: Python 3.11+ and Node.js 20+

## Start the development stack

1. Create a local environment file and choose a strong database password:

   ```bash
   cp .env.example .env
   ```

2. Start the services:

   ```bash
   docker compose up --build
   ```

3. Check service health:

   ```bash
   curl http://127.0.0.1:8000/health
   curl http://127.0.0.1:8000/ready
   curl http://127.0.0.1:3004
   ```

The app is also available to devices on the same LAN at
`http://<host-ip>:3004` (for example, `http://192.168.1.20:3004`). The
frontend proxies API requests internally, so clients only need access to port
3004. Allow that TCP port through the host firewall if necessary. PostgreSQL
has no host `ports` mapping and is reachable only by Compose services.

Stop the stack with `docker compose down`. Add `--volumes` only when you intentionally want to remove local database data.

## Database migrations

The backend applies pending migrations automatically before starting the API.
To apply or inspect them manually:

```bash
docker compose run --rm backend alembic upgrade head
```

Check the current revision with `docker compose run --rm backend alembic current`.

## Main administrator

Create the first administrator after the backend is running:

```bash
docker compose exec backend python -m scripts.bootstrap_admin \
  --email admin@example.com \
  --display-name "Main Administrator"
```

The command prints a generated temporary password once. It is idempotent: for
an existing email it promotes and re-enables that account, resets its password,
and requires a password change at the next sign-in.

## Authentication configuration

Registration defaults to invite-only. Set `INITIAL_INVITE_CODE` to a long,
random value in `.env`; it is read only from the environment and is never
stored in the database. Set `COOKIE_SECURE=false` only for a local HTTP
development session. It must remain `true` behind the HTTPS reverse proxy.

`FRONTEND_ORIGIN` is the one allowed browser origin for credentialed API
requests. Set it to `https://cashbook.mafunami.me` in production. Do not use a
wildcard origin with cookie authentication.

## Local checks

Backend dependencies are defined in `backend/pyproject.toml`; frontend dependencies in `frontend/package.json`.

```bash
cd backend && python -m pytest && python -m ruff check . && python -m ruff format --check .
cd frontend && npm ci && npm run check && npm run test && npm run build
```

## Category management

New accounts receive four inflow and eight outflow presets. The category API
supports custom inflow/outflow categories, curated colors, optional icon labels,
editing, archive, and restore. `DELETE /api/v1/categories/{id}` remains a safe
archive operation for compatibility; it never deletes a category or its
historical transaction relationships.

## Transaction management

`/api/v1/transactions` provides owner-scoped creation, retrieval, editing,
hard deletion, and paginated listing. Lists support date range, transaction
type, category, text search, and newest/oldest sort filters. Amounts are
positive integer minor units only; omitted API transaction dates default to the
server's current calendar date. The current frontend exposes a responsive
**Add transaction** form: it is a desktop dialog and a mobile full-screen
sheet, with category choices filtered by inflow/outflow type.

## Budget configuration

`/api/v1/budgets/{month_start}` stores and reports the historical overall
monthly envelope. Optional category allocations and payday allowances are
subdivisions of that envelope, not additional funds; only outflows consume
them. The API reports warning state when configured allowance totals differ
from the monthly budget and permits overspending.

Payday cutoff changes create an effective-dated schedule version through
`POST /api/v1/budget-settings/payday-schedules`. Its `effective_from` date
must be a start boundary under its own cutoff rules, preserving earlier
periods and allowance records. The responsive **Budget settings** page exposes
the configuration controls and is available from the temporary application
navigation.

## Dashboard

The Dashboard uses `GET /api/v1/dashboard` to report either a selected
calendar month or a configured payday period. Its chart groups only outflow
transactions by owned category and has a keyboard-operable text summary for
the same amounts and percentages. It presents the latest five owner-scoped
transactions and optional configured category allocations. If no spending is
recorded for a period, the chart displays a clear empty state.

## Environment variables

`.env.example` documents every required development variable. Do not commit `.env`, passwords, connection URLs containing production credentials, or any other secret.

## Error monitoring

Sentry monitoring is optional and remains disabled when its DSNs are blank.
Create separate React and FastAPI projects, then set `SENTRY_FRONTEND_DSN` and
`SENTRY_BACKEND_DSN` in `.env`. Set `SENTRY_RELEASE` to the deployed Git SHA so
events from both projects share the same release identifier. The default trace
sample rate is 5%; request bodies, default PII collection, and Session Replay
are disabled to keep financial and authentication data out of monitoring.

The frontend DSN is embedded in the browser build and is therefore public. A
Sentry auth token is a separate secret and must never be assigned to a
`VITE_`-prefixed variable.

## Production and backups

Use [`docs/deployment.md`](docs/deployment.md) with
`.env.production.example` to deploy behind host Nginx at the HTTPS endpoint.
The production Compose topology preserves PostgreSQL in an internal Docker
network and binds frontend/backend to loopback only. The deployment guide
includes the Nginx proxy configuration and forwarded-header assumptions.

Use [`docs/backup-restore.md`](docs/backup-restore.md) to configure and test
the nightly, verified PostgreSQL backup. It includes atomic local creation,
seven-day local and fourteen-day off-site retention, dry-run operation, and a
non-production restore drill.
# Cashbook-mafunami
