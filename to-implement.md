# Dashboard and Mobile Navigation Improvements

## Objective

Improve dashboard customization, category-budget clarity, and mobile navigation without changing the existing outflow mix, recent activity, remaining budget, or optional-allocation card behavior beyond the category-budget details specified below.

## 1. Configurable Summary Cards

Add a compact **Customize summary** control near the financial summary. It should open an accessible popover or menu containing checkboxes for:

- Inflow
- Outflow
- Profit / loss
- Budget used

The selections only control whether these four summary cards are rendered. They must not alter dashboard calculations, API queries, charts, recent activity, reporting periods, or other cards.

Show all four cards by default. Permit hiding every card; when none are selected, remove the summary section entirely so it leaves no empty space. The current selection may remain component-local and reset after a reload in this phase.

## 2. Category Budget Remaining Amounts

Update each category-budget row to emphasize the remaining amount while retaining useful usage context. Suggested copy:

```text
₱3,000 remaining · ₱2,000 of ₱5,000 used
```

When overspent, display `₱500 over budget` rather than a negative remaining value. Preserve the existing progress bar and warning/danger tones.

Correct the dashboard API so every configured category budget is returned, including categories with no transactions. A zero-spend ₱5,000 category budget should display as fully remaining. Add backend coverage for zero-spend and overspent categories and frontend coverage for the display formatting.

## 3. Mobile Hamburger Navigation

Keep the desktop navigation unchanged. Below the existing mobile breakpoint, replace the horizontally scrolling top navigation with a header containing the application/current-page label and a hamburger button.

The opened menu must include every permitted navigation destination, the signed-in user's display name, and **Sign out**. Close it after navigation, on outside interaction, and when Escape is pressed. Expose open state with `aria-expanded`, connect the button and menu with `aria-controls`, support keyboard operation, and use touch-friendly targets.

## Deferred: Account-Level Preference Storage

Do not use `localStorage` for summary-card choices. Persisting these choices across sessions and devices will be a separate phase using an account-level preference stored by the backend. That phase should include a database migration, authenticated preference API/schema updates, frontend loading and saving states, and tests confirming preferences are owner-scoped and survive sign-in on another device.

## Verification

Run:

```bash
cd backend && python -m pytest && python -m ruff check . && python -m ruff format --check .
cd frontend && npm run check && npm run test && npm run build
```

Manually verify the summary layout at zero through four visible cards, category budgets with no spending and overspending, and mobile menu behavior with touch and keyboard input.
