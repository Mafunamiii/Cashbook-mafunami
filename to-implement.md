# NamiCash — Next Implementation Work

## 1. Freeform Category Color Picker

Replace the current preset-only category color selection with a freeform visual color picker.

Requirements:

* Allow the user to select arbitrary colors rather than only predefined swatches.
* Provide an interactive color field/picker suitable for mouse and touch input.
* Preserve the existing category color value format unless changing it is necessary.
* Existing category colors must continue to load correctly.
* Category creation and category editing must both support the new picker.
* Preserve existing validation, API behavior, category ownership, and category display behavior.
* Avoid introducing a large UI dependency if the browser/platform capabilities or a small existing-compatible implementation are sufficient.
* Maintain keyboard accessibility and a usable fallback for entering/selecting a color.
* Add focused frontend tests for any extracted color-model/validation behavior where practical.

Do not redesign the Categories page beyond what is required for the picker.

---

## 2. Per-Transaction Currency with Base-Currency Conversion

NamiCash has one account-level/main currency used for reporting and aggregate financial values.

Allow individual transactions to use a different currency while converting their value into the user's main currency for calculations and reporting.

### Transaction Data

Each transaction should retain:

* original transaction amount
* original transaction currency
* converted amount in the user's main/base currency
* exchange rate used for that conversion
* sufficient rate metadata to make historical financial results reproducible

Existing transactions must remain compatible.

### Transaction Entry

When adding or editing a transaction:

* default the transaction currency to the user's main currency
* allow selecting another supported currency
* show the original amount/currency clearly
* when another currency is selected, obtain the applicable exchange rate and show the converted base-currency amount
* transactions already using the base currency should not require an exchange-rate lookup

### Financial Calculations

Dashboard totals, budgets, profit/loss, reports, category spending, and other aggregate calculations must continue to operate in the user's main currency.

Do not repeatedly recalculate historical transactions using today's exchange rate. Historical transaction values must remain reproducible using the rate associated with that transaction.

### Exchange Rates

Design the exchange-rate integration so rates are fetched centrally by the backend rather than independently by browser clients.

Target behavior:

* retrieve updated exchange rates approximately once per day
* cache/store rates so transaction creation does not require unnecessary external requests
* avoid fetching the same rate repeatedly for individual transactions
* handle provider/network failure without corrupting transaction data
* make the external exchange-rate provider replaceable rather than spreading provider-specific code throughout the application

Do not expose provider API secrets to the frontend.

### Existing Data

Provide a safe migration path for existing transactions.

Existing transactions should continue to behave as transactions in the user's current/base currency unless there is reliable existing currency information indicating otherwise.

### Currency Preference Changes

Inspect the existing main-currency preference behavior before deciding how transactions should behave when a user later changes their account-level base currency.

Do not silently reinterpret historical monetary values.

### Testing

Add focused backend coverage for:

* base-currency transactions
* foreign-currency conversion
* stored exchange-rate behavior
* aggregation using converted/base amounts
* existing transaction migration compatibility
* exchange-rate lookup/cache behavior
* failure handling

Add focused frontend coverage for transaction currency selection and conversion display/model behavior.

---

## Scope Control

Before implementing either feature, inspect the relevant existing implementation and tests.

Do not perform broad unrelated refactors.

Do not modify authentication, payday-period behavior, budget semantics, reporting-period semantics, or unrelated dashboard behavior except where currency conversion necessarily integrates with financial calculations.

Use existing repository conventions and preserve owner-scoped data access.

## Verification

Use targeted tests during development.

Before completion, run:

```bash
cd backend && python -m pytest && python -m ruff check . && python -m ruff format --check .
cd frontend && npm run check && npm run test && npm run build
```
