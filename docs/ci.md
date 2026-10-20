# Continuous integration

`.github/workflows/ci.yml` runs on pull requests targeting `dev` or `main`, pushes
to either branch, and manual `workflow_dispatch`. CI uses GitHub-hosted Ubuntu
runners, read-only repository access, and disposable PostgreSQL 16 databases. It
does not use production credentials, publish images, or deploy.

## Jobs and required checks

The stable job checks are `backend`, `frontend`, `integration`, and `migration`.
Configure these four names as required status checks in the `dev` and `main`
rulesets after the workflow has run once.

- `backend`: installs `.[dev]`, runs Ruff lint and format checks, then pytest
  outside `tests/integration`.
- `frontend`: runs `npm ci`, ESLint, Prettier, Vitest, and the TypeScript/Vite
  production build.
- `integration`: runs PostgreSQL-backed tests against an isolated database
  named `cashbook_integration_test`.
- `migration`: applies Alembic to a fresh `cashbook_migration_test` database and
  verifies revision `20260811_0010` is at head.

## Local equivalents

Backend commands (from `backend/`):

```sh
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
pytest tests --ignore=tests/integration
```

Frontend commands (from `frontend/`):

```sh
npm ci
npm run lint
npm run format
npm test
npm run build
```

For integration and migration checks, first provide a disposable local
PostgreSQL 16 instance and use only databases with names ending in `_test`:

```sh
cd backend
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/cashbook_integration_test pytest tests/integration
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/cashbook_migration_test alembic upgrade head
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/cashbook_migration_test alembic current
```

The integration fixture refuses a database name without the `_test` suffix.
The migration commands must also target a disposable database; never point them
at production.

## Failures and reruns

Open the failed job in the pull request’s **Checks** tab and use its first
failing step and log output to identify the cause. Push a fix to rerun the
workflow, use **Re-run failed jobs** in the Actions run, or use **Run workflow**
to manually dispatch CI for a selected branch.
