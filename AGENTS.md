# Repository Guidelines

## Project Structure & Module Organization

Backend code lives in `backend/app/`: routes are under `api/`, shared utilities under `core/`, persistence under `db/`, and financial rules under `domain/`. Alembic migrations are in `backend/alembic/versions/`; tests live in `backend/tests/`, including `domain/` and `integration/`.

The React/Vite client lives in `frontend/src/`, with components and models grouped under `features/`. Frontend tests sit beside code as `*.test.ts` or `*.test.tsx`.

Operational guidance belongs in `docs/`, and maintenance utilities in `scripts/`.

Before modifying a feature, inspect the relevant route, schema/model, domain logic, frontend component/model, and existing tests. Reuse existing conventions rather than introducing parallel patterns.

## Build, Test, and Development Commands

* `cp .env.example .env` creates local configuration; replace placeholder secrets.
* `docker compose up --build` starts PostgreSQL, FastAPI, and the frontend.
* `docker compose down` stops services without deleting database data.
* `cd backend && python -m pytest` runs backend tests with coverage reporting.
* `cd backend && python -m ruff check . && python -m ruff format --check .` checks Python lint and formatting.
* `cd frontend && npm ci && npm run check && npm run test && npm run build` installs locked dependencies, checks style, runs Vitest, and verifies the production build.
* `cd frontend && npm run dev` starts the Vite development server.

For targeted work, run the narrowest relevant tests first, then run the full verification commands before considering the task complete.

Do not change tests solely to make an incorrect implementation pass. Distinguish pre-existing failures from failures introduced by the current change.

## Coding Style & Naming Conventions

Python targets 3.11, uses four-space indentation, double quotes, a 100-character line target, and Ruff rules `E`, `F`, `I`, and `UP`.

Use `snake_case` for Python modules/functions and `PascalCase` for classes.

TypeScript and TSX use two-space indentation and Prettier defaults. Name React components and component files in `PascalCase`; use `camelCase` for functions, variables, hooks, and model utilities.

Keep business and financial rules in domain/model modules rather than duplicating calculations in UI components or route handlers.

Prefer narrow changes over broad refactors. Do not rewrite working architecture for stylistic reasons unless explicitly requested.

## Financial and Dashboard Semantics

Persisted monetary values and financial calculations must preserve the project's existing monetary representation and rounding conventions.

Changes to balances, budgets, category spending, profit/loss, reporting periods, or payday calculations are regression-sensitive and require focused tests.

Presentation-only controls must not silently alter API queries, financial calculations, reporting periods, chart inputs, or unrelated dashboard state.

Configured budgets with no matching transactions are still valid budgets and must not disappear merely because aggregate transaction results contain no row for them.

For remaining-budget displays:

* zero spending should preserve the full configured budget as remaining
* overspending should be represented explicitly rather than as a negative remaining amount
* existing warning/danger semantics should remain consistent unless the task explicitly changes them

## Frontend and Responsive Behavior

Reuse existing breakpoints, layout primitives, components, and visual conventions where practical.

Desktop behavior must remain unchanged when a task is explicitly scoped to mobile.

Interactive controls must support keyboard operation and appropriate ARIA relationships. Menus, popovers, dialogs, and similar transient UI should implement expected dismissal behavior such as Escape and outside interaction where applicable.

Use touch-friendly targets for mobile controls.

Avoid persistence mechanisms such as `localStorage` when the task explicitly defers persistence or requires future account-scoped storage.

Do not introduce backend or database changes for component-local UI state unless explicitly required.

## Backend and API Behavior

Preserve existing API contracts unless the task explicitly changes them.

When an endpoint combines configured entities with aggregates, verify that entities with no matching aggregate rows are still represented when required by the domain behavior.

Use SQLAlchemy/Alembic conventions already present in the repository.

Schema changes must include an Alembic migration and preserve existing data where practical. Do not perform destructive migrations unless explicitly requested.

Authorization and data access must remain owner-scoped.

## Testing Guidelines

Pytest discovers `backend/tests/test_*.py`; mark database-backed tests with `integration` and provide an isolated `TEST_DATABASE_URL`.

Vitest discovers colocated `*.test.ts(x)` files.

Add focused tests for changed:

* financial rules
* API aggregation behavior
* authorization boundaries
* UI model/formatting behavior
* responsive or interactive state when practical

No fixed coverage threshold is configured, but avoid reducing meaningful coverage.

For bug fixes, include a regression test when the behavior can reasonably be automated.

## Accessibility

For new interactive UI:

* use semantic controls where possible
* preserve visible focus behavior
* ensure keyboard accessibility
* provide appropriate accessible names
* use `aria-expanded` for disclosure state when applicable
* connect controlling elements and controlled regions with `aria-controls` when applicable
* ensure transient menus/popovers can be dismissed predictably

Do not add ARIA attributes that duplicate or conflict with native semantics.

## Commit & Pull Request Guidelines

History favors short, imperative subjects such as `Preserve homeserver changes before merge`.

Keep commits focused and explain non-obvious migration, security, or financial-behavior effects in the body.

Pull requests should summarize behavior, list verification commands, link relevant issues, call out schema or environment changes, and include screenshots for visible UI updates.

Do not commit or push unless explicitly instructed.

## Security & Configuration

Never commit `.env`, credentials, production connection strings, session secrets, API tokens, or Sentry tokens.

Keep PostgreSQL unexposed to the host, preserve secure-cookie and explicit-origin settings in production, and review migration and backup implications for schema changes.

Preserve authentication, authorization, CSRF, session, and per-user data-isolation behavior unless the task explicitly requires changes.

## Task Execution

For implementation tasks:

1. Read the task requirements completely.
2. Inspect the relevant existing implementation and tests.
3. Identify the smallest set of files that needs to change.
4. Preserve explicitly out-of-scope behavior.
5. Implement the change using existing project conventions.
6. Add or update focused tests.
7. Run targeted verification.
8. Run the full requested verification suite.
9. Summarize changed files, behavior, and verification results.

When asked only to inspect, assess, or plan, do not modify files.

Requirements marked as deferred are out of scope unless the user explicitly moves them into the current phase.
