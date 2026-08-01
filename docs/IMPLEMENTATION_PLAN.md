# Cashbook Implementation Plan

## Guardrail

This plan is proposed only. No application code is created until approval is given. Each phase preserves working behavior, uses reviewed migrations, and has explicit acceptance criteria.

## Phase 0 — Decisions and project baseline

**Scope**

- Confirm unresolved product decisions in `PRODUCT_SPEC.md`.
- Establish a valid Git repository/baseline if desired.
- Create the agreed directory layout, environment-variable contract, linting/formatting conventions, and Compose skeleton.

**Acceptance criteria**

- Currency policy, running-balance semantics, budget colors, CSRF mechanism, invite workflow, and initial-admin bootstrap are decided.
- `.env.example` contains names and safe placeholders only.
- No secret is committed.
- Local developer and production configuration responsibilities are documented.

## Phase 1 — Backend foundation, database, and security

**Scope**

- Configure FastAPI, PostgreSQL connectivity, Alembic, structured error handling, health checks, and settings validation.
- Implement initial migrations for users, sessions, invites, categories, preferences, budgets, and transactions.
- Implement Argon2id authentication, secure cookie sessions, CSRF protection, session expiry/revocation, login rate limiting, and role checks.

**Acceptance criteria**

- A new database can be migrated from empty state using Alembic.
- Session cookies have correct production attributes and raw tokens are absent from the database.
- Protected data is inaccessible without authentication, across users, and across roles.
- Temporary-password users are blocked from normal routes until their password changes.
- Authentication and authorization integration tests pass.

## Phase 2 — Financial domain API

**Scope**

- Implement preset-category provisioning, category lifecycle, monthly budgets, transactions, summary calculations, and calendar/payday report services.
- Add query filtering, pagination, sorting, and deterministic running-balance behavior.

**Acceptance criteria**

- All money is stored and returned in integer minor units.
- Inflows affect net balance but not budget remaining.
- One budget exists per user per calendar month and history is retained.
- Archived categories remain attached to historical transactions and cannot be selected for new entries by default.
- Payday tests cover month ends, February, leap years, and cross-year boundaries.
- Cross-user API-access tests pass for every resource group.

## Phase 3 — Frontend foundation and authentication views

**Scope**

- Set up React/TypeScript routing, typed API client, query/cache strategy, forms, global design tokens, and responsive application shell.
- Implement sign-in, sign-up, manual recovery information, session handling, route guards, forced-password-change view, and basic settings shell.

**Acceptance criteria**

- Navigation and route protection work on mobile and desktop widths.
- Authentication uses cookie credentials and includes the chosen CSRF mechanism.
- Authentication errors are understandable without revealing account existence.
- Visual tokens reflect the navy/blue-gray/cyan/high-contrast design direction.

## Phase 4 — Dashboard and transaction management

**Scope**

- Implement dashboard metrics, remaining-budget display/progress state, month selector, category donut chart, recent transactions, and add/edit/delete transaction flow.
- Implement monthly-budget editing.

**Acceptance criteria**

- Dashboard numbers agree with API fixtures for selected months.
- The outflow distribution excludes inflows and handles no-data states.
- Progress states follow the approved thresholds and are legible at narrow widths.
- Transaction create/edit/delete immediately results in accurate dashboard data after refresh/invalidation.

## Phase 5 — Records, categories, settings, and administration

**Scope**

- Build records filtering, sorting, desktop table, mobile row/card display, and calendar/payday segmented views.
- Build category management, archive behavior, preferences/payday settings, and minimal administrator user/invite management.

**Acceptance criteria**

- Records filters combine correctly and have deterministic ordering/running balances.

Stage 9 implementation note: completed owner-scoped account settings for display
name and persisted appearance preference, with the existing budget mode,
effective-dated payday schedules, allowances, and category allocations exposed
from settings navigation. Added an administrator-only account-management API and
screen for non-financial user listing, account enable/disable, server-generated
temporary passwords, forced password changes, and session revocation.

Stage 8 implementation note: completed a responsive statement view with
owner-scoped pagination, date/type/category/search filters, sorting,
calendar/payday presentation grouping, and server-calculated lifetime net
cash-flow balances. Segment grouping is not persisted.
- Segmented periods match the specified date rules.
- A non-administrator cannot reach or call administrator features. This is
  covered by PostgreSQL-backed authorization tests.
- Category archive/delete rules are enforced in UI and API.
- Accessibility and responsive checks pass for the primary paths.

## Phase 6 — Deployment, backup, and hardening

**Scope**

- Finalize Docker Compose, production containers, proxy-facing settings, environment documentation, backup and restore scripts, logging, and operational runbook.
- Perform security review and backup/restore rehearsal.

**Acceptance criteria**

- A clean host can deploy from documented inputs without committed credentials.
- Health/readiness endpoints work through the intended Compose topology.
- Backup produces a verified, atomic, checksum-recorded artifact.
- A restore drill succeeds against a non-production database and is documented.
- Cookie/TLS/proxy configuration is confirmed at `cashbook.mafunami.me` before exposing real user data.

Stage 10 implementation note: added a production Compose topology with a
persistent PostgreSQL volume and no database host port, loopback-only frontend
and backend ports, production environment validation, container health checks,
and a static production frontend image. Added a host-Nginx/TLS runbook and a
dry-run-capable nightly backup script that validates compressed PostgreSQL
archives, atomically publishes them, retains local/off-site copies, and
documents a restore drill.

## Phase 7 — Final verification and release readiness

**Scope**

- Run the complete test suite, review migrations, perform a mobile/desktop UI pass, and validate the operational documentation with the deployment owner.

**Acceptance criteria**

- Unit, integration, API, frontend, and end-to-end tests pass in CI or the documented equivalent.
- No secrets, floating-point money values, or cross-user access paths are present in reviewed code.
- All routes in the product specification are implemented or explicitly deferred.
- Known limitations and recovery procedures are documented before production use.

## Recommended implementation order within each phase

1. Write/adjust acceptance tests for the narrow feature.
2. Add the smallest database migration needed, when applicable.
3. Implement server-side rules and authorization.
4. Implement typed client and responsive UI.
5. Add focused unit/integration/end-to-end coverage.
6. Review migration rollback/operational impact before advancing.

## Approval gate

Approval is required before Phase 0 implementation begins. The first approval should also resolve the decisions noted in [`PRODUCT_SPEC.md`](PRODUCT_SPEC.md), or explicitly authorize the documented recommendations as v1 defaults.
