# Cashbook Product Specification

## 1. Product scope

Cashbook is a self-hosted personal budget tracking web application deployed on a home server and exposed through an HTTPS reverse proxy at `cashbook.mafunami.me`. It provides per-user monthly budgets, transaction records, category reporting, dashboard summaries, and optional payday-based reporting periods.

This document defines the approved product scope for implementation. It intentionally contains no application code or deployment secrets.

## 2. Technical architecture

| Layer | Proposed technology | Responsibility |
| --- | --- | --- |
| Web client | React + TypeScript | Responsive, mobile-first UI and server API consumer |
| API | FastAPI + Pydantic | Authentication, authorization, financial rules, and JSON API |
| Database | PostgreSQL | Durable relational storage |
| Schema evolution | Alembic | Reviewed, repeatable database migrations |
| Charts | Recharts | Dashboard category-distribution chart |
| Deployment | Docker Compose | Application, database, and production configuration |
| Edge | Existing HTTPS reverse proxy | TLS termination and routing to the application |

The frontend is a single-page application served separately or through a production web-server container. The FastAPI service is the sole authority for business calculations and access control. PostgreSQL is never exposed to browsers.

### Proposed repository structure

```text
cashbook/
├── backend/
│   ├── app/
│   │   ├── api/                 # Route groups and request/response schemas
│   │   ├── core/                # Settings, security, middleware, logging
│   │   ├── db/                  # Engine, sessions, ORM models
│   │   ├── services/            # Financial and authorization use cases
│   │   └── main.py
│   ├── alembic/
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── api/                 # Typed API client
│   │   ├── components/          # Reusable presentational components
│   │   ├── features/            # Page-domain components and hooks
│   │   ├── routes/              # Route definitions and guards
│   │   ├── styles/              # Design tokens and global styles
│   │   └── main.tsx
│   ├── tests/
│   ├── package.json
│   └── Dockerfile
├── scripts/
│   ├── backup-postgres.sh
│   └── restore-postgres.sh
├── docs/
│   ├── PRODUCT_SPEC.md
│   ├── IMPLEMENTATION_PLAN.md
│   └── deployment-and-backup.md
├── compose.yaml
├── .env.example
└── CASHBOOK_LOGBOOK.md
```

## 3. Financial rules

### Monthly budgets

- A user has at most one overall budget for each calendar month.
- Each budget stores its value independently so historical budgets remain unchanged.
- Budget remaining is `monthly budget − outflow total` for that calendar month.
- Inflows contribute to profit/loss but never increase the spending budget.
- Budget usage percentage is `outflow / monthly budget × 100`; a zero or unset budget must be represented safely rather than divided by zero.

### Summary

For the selected calendar month, Cashbook presents total inflow, total outflow, net profit/loss (`inflow − outflow`), monthly budget, remaining budget, and budget usage percentage.

### Transactions

Every transaction has a name, type (`inflow` or `outflow`), category, positive amount, transaction date, and optional notes. Users can create, edit, and delete their own transactions. Currency values are stored as integer minor units (`BIGINT`), never floating point values.

### Categories

Categories are user-owned and have a name, color, optional icon, and transaction type. Account creation provisions preset inflow and outflow categories. A category referenced by transactions is archived, not deleted; archived categories remain visible on historic transactions but are unavailable for new transactions by default.

## 4. Database entities and relationships

All primary keys should be UUIDs. Timestamps use timezone-aware UTC values; transaction dates are local calendar dates.

| Entity | Important fields | Relationships / constraints |
| --- | --- | --- |
| `users` | email, display name, password hash, role, active, must-change-password, timestamps | Owns all financial and preference data; normalized email is unique |
| `sessions` | user ID, hashed opaque token, CSRF secret/hash, expiry, revoked time, last seen | Many sessions per user; raw session token is never stored |
| environment configuration | `INITIAL_INVITE_CODE`, registration mode | The initial invite-only code is deployment configuration only; no invite code is persisted |
| `categories` | user ID, name, color, icon, type, archived time | One user has many categories; scoped unique active names per type is recommended |
| `monthly_budgets` | user ID, month, amount minor, timestamps | One row per user and calendar month; unique `(user_id, month)` |
| `transactions` | user ID, category ID, name, type, amount minor, date, notes, timestamps | One user/category has many transactions; type must match category type |
| `user_preferences` | user ID, currency, time zone, reporting mode, appearance preference | One-to-one with user; settings drive display and reporting only |
| `login_attempts` (optional) | identity key, source fingerprint, occurred time, outcome | Supports login-rate-limit auditing |
| `audit_events` (recommended) | actor, target, event, metadata, timestamp | Records security-sensitive admin/session activity |

Database constraints and service checks must enforce positive transaction amounts, valid transaction types, ownership of every referenced category, and user scoping in every query. Indexes should cover user/date transaction retrieval, user/category/date reporting, session token lookup, and monthly-budget lookup.

## 5. API groups

All endpoints are versioned below `/api/v1`; the API returns amounts as integer minor units.

| Group | Intended operations |
| --- | --- |
| Authentication | registration, sign in, sign out, sign out all, session lookup, password change, manual recovery information |
| Dashboard and reports | selected-month summary, budget status, outflow-by-category, recent transactions, calendar/payday period metadata |
| Budgets | get, create, and update a budget for a specified calendar month |
| Transactions | paginated list with search/filter/sort/date range; create; get; edit; delete |
| Categories | list active/archived, create, edit, archive, and safe deletion only when unreferenced |
| Account | read/update display and appearance settings, reporting preference, paydays, and password |
| Administration | list account-only user metadata, enable/disable accounts, generate temporary passwords, force password changes, and revoke sessions; persisted invite management is a later extension |
| Operations | health/readiness endpoints for Compose and proxy monitoring |

Mutation endpoints require an authenticated session and valid CSRF protection. Server-side filtering always derives the user identity from the session; client-supplied user IDs are never accepted for ordinary data operations.

## 6. Frontend routes and components

### Routes

- `/sign-in`
- `/sign-up`
- `/password-recovery` — manual recovery instructions only
- `/dashboard`
- `/records`
- `/categories`
- `/settings`
- `/admin/users` — administrator-only

Unauthenticated visitors are redirected to sign-in. A user with a temporary administrator-issued password is redirected to a password-change view until the password is changed.

### Shared components

- Application shell with desktop navigation and mobile bottom/compact navigation
- Route guard and administrator guard
- Month selector and payday-period selector
- Financial metric card, remaining-budget display, and responsive budget progress bar
- Transaction form, type selector, money input, category selector, and confirmation dialog
- Transaction table for desktop and transaction card/row list for mobile
- Search/filter/sort controls and empty/loading/error states
- Category chips and archive state indicators
- Recharts donut chart for outflow distribution

### Visual direction

The interface follows the attached ClipTrack inspiration: deep navy page backgrounds, blue-gray card surfaces, subtle borders, high-contrast typography, generous whitespace, and a restrained cyan accent. The design is mobile-first, with touch-friendly controls and responsive desktop data tables. Remaining-budget states use green, yellow, orange, and red; proposed thresholds are listed as an unresolved decision below.

## 7. Authentication and authorization flow

1. Registration is invite-only by default. The initial invite code is loaded only from `INITIAL_INVITE_CODE` environment configuration; configuration may explicitly enable open registration.
2. On successful registration, the server creates preset categories and preference defaults.
3. Passwords are hashed using Argon2id. Plaintext passwords and reusable password-reset tokens are never stored.
4. Sign-in is rate-limited and returns non-enumerating errors.
5. The server creates a cryptographically random opaque session token and stores only its hash, expiry, revocation metadata, and user reference.
6. The browser receives the raw token only in a `Secure`, `HttpOnly`, `SameSite=Lax` cookie. HTTPS is mandatory in production.
7. State-changing requests require a server-validated double-submit CSRF token: a same-origin readable CSRF cookie must exactly match `X-CSRF-Token`, and its hash must match the authenticated server session. The session cookie remains HTTP-only.
8. Each protected request resolves the user from the session and authorizes every object query by that user ID. Administrative actions additionally require the administrator role.
9. Sessions expire, can be revoked individually or globally, and are invalidated when appropriate after credential changes.
10. An administrator-issued temporary password is generated server-side, returned only once to the administrator, stored only as an Argon2id hash, revokes the target's sessions, and sets `must_change_password`. That state blocks normal application access until changed.

The reverse proxy must be explicitly trusted only when it is the known upstream, so secure-cookie and original-scheme handling cannot be spoofed by arbitrary clients.

## 8. Payday-period algorithm

Payday segmentation is a reporting and presentation feature. Transactions stay in one table, and calendar-month budgets remain calendar-month budgets.

Users configure two distinct payday day numbers, `A` and `B`, sorted so `A < B` (for example, 12 and 27). When a nominal day exceeds a month's length, it is clamped to that month's final day. All calculations use the user's configured time zone and transaction `date`, not server timestamps.

For a date `D` in a month containing effective paydays `A` and `B`:

1. If `D >= B`, the segment starts on `B` in the current month and ends the day before `A` in the next month.
2. If `A <= D < B`, the segment starts on `A` and ends the day before `B` in the current month.
3. If `D < A`, the segment starts on `B` in the previous month and ends the day before `A` in the current month.

This yields 27 July–11 August and 12 August–26 August for payday days 12 and 27. Leap years and all variable month lengths work through date arithmetic rather than fixed day counts.

### Running balance semantics

The records running balance is the user's cumulative net cash flow, not their
configured spending budget or a bank-reconciled account balance. Starting from
the earliest retained transaction, inflows add and outflows subtract. It is
computed deterministically by transaction date, then `created_at`, then UUID
as a final tie-breaker.

The balance is calculated before statement filters, pagination, segment
grouping, or selected newest/oldest display order. Therefore it remains
consistent when a row is viewed in a narrowed search or in either sort
direction. Calendar/payday segments remain presentation and query metadata;
all records stay in the single `transactions` table.

## 9. Testing strategy

| Test layer | Coverage |
| --- | --- |
| Unit | Money arithmetic, budget rules, authorization helpers, CSRF/session utilities, and all payday boundary cases |
| Database/integration | Alembic upgrade from empty database, constraints, data isolation, CRUD, archive behavior, session revocation, rate limits |
| API | Request validation, cookie/CSRF behavior, role guards, no cross-user reads/writes, pagination/filter/sort correctness |
| Frontend component | Forms, validation, loading/empty/error states, mobile/desktop transaction representations |
| End-to-end | Sign-up/in, forced password change, transaction lifecycle, budget dashboard, records filters, category archive, admin flow |
| Responsive/accessibility | Keyboard operation, contrast, labelled controls, narrow mobile and desktop viewport checks |
| Operations | Compose startup, health checks, backup verification, restore rehearsal to a non-production database |

Test fixtures must use test-only database credentials and must not include production secrets.

## 10. Backup and restore requirements

Provide a PostgreSQL backup script suitable for scheduling. It uses a compatible `pg_dump` to write a custom-format backup to a temporary file on the destination filesystem, verifies it with `pg_restore --list`, records a checksum, restricts file permissions, and atomically renames the verified file into place. Configuration and credentials come only from environment variables or deployment-managed secrets; none are committed.

Restoration is documented and scripted for a confirmed non-live target: verify the backup, restore with `pg_restore`, run migrations/health checks as appropriate, and validate a known user/login and record counts. Destructive restore flags must require explicit operator intent. Backup restore drills are part of operational acceptance.

## 11. Contradictions, risks, and unresolved decisions

| Topic | Issue / decision needed |
| --- | --- |
| Design attachment | No ClipTrack image is available in the workspace. The stated visual description will guide initial styling unless the reference is supplied later. |
| Currency | Requirements mandate minor units but do not say whether every user has one configured currency or transactions can have different currencies. Recommended: one display currency per user for v1. |
| Budget state thresholds | Green/yellow/orange/red are required but thresholds are unspecified. Proposed: green >=50% remaining, yellow 20–49%, orange 0–19%, red below 0%. |
| Transaction deletion | User deletion is required, but accounting retention/auditing expectations are not specified. Recommended: hard delete initially with audit metadata, unless retention is required. |
| Category type changes | Changing an existing category's type could conflict with historic transactions. Recommended: prohibit type changes once used. |
| Payday settings | The specification mentions examples but not whether one or two paydays are allowed. Proposed v1 rule: exactly two distinct days, each 1–31. |
| Initial invitation delivery | The initial environment-configured invite code must be distributed through a trusted out-of-band channel. Persisted admin-generated invitations are deferred. |
| Password recovery | This is explicitly a manual information page; no email-reset delivery system is in scope. |
| Rate-limit storage | PostgreSQL-backed rate limits are sufficient for a single home-server instance; Redis is unnecessary unless scaling requires it. |
| Reverse proxy | Proxy software, forwarding headers, and allowed upstream network are unspecified and must be documented during deployment. |
| Admin bootstrap | The initial administrator creation method needs a secure deployment-time procedure. |

## 12. Current repository assessment

At the time of this specification, the workspace contains no application code, package manifests, Docker configuration, tests, migrations, or reusable user-interface components. The only existing project file is a planning logbook. The `.git` directory is present but does not currently behave as a valid Git worktree. Therefore no working implementation should be rewritten, and no reusable application components have been identified.
