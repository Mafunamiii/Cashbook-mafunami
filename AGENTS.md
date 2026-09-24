# AGENTS.md

## Purpose

Work efficiently on this repository with minimal unnecessary token usage.

Prioritize:

1. Correctness
2. Minimal, targeted changes
3. Preservation of existing behavior
4. Low token/output overhead

Avoid broad rewrites, speculative refactors, and verbose explanations unless explicitly requested.

---

## Repository Workflow

Before changing code:

1. Inspect only the files relevant to the requested task.
2. Use targeted search (`rg`, `git grep`, specific file reads) before broad repository exploration.
3. Follow existing architecture, naming, patterns, and conventions.
4. Identify the smallest safe implementation surface.
5. Check existing tests and nearby behavior before introducing new abstractions.

Do not scan or summarize the entire repository unless the task genuinely requires it.

Prefer targeted file/symbol inspection over dumping large files into context.

---

## Change Policy

Make the smallest change that fully solves the task.

Do not:

* Refactor unrelated code.
* Rename unrelated symbols.
* Reformat entire files.
* Change architecture without a concrete need.
* Add dependencies when existing tools can solve the problem.
* Introduce abstractions for hypothetical future use.
* Remove existing behavior unless explicitly requested.
* Modify public/API behavior unless required by the task.

Preserve backward compatibility whenever practical.

If the task can be solved locally, keep it local.

---

## Existing Behavior

Treat current repository behavior as intentional unless there is clear evidence otherwise.

Before modifying an existing flow:

* Identify its callers.
* Identify relevant tests.
* Check whether compatibility behavior or fallback logic exists.
* Preserve existing semantics unless the task explicitly changes them.

When optimizing performance, do not silently change functional behavior.

---

## Investigation Strategy

Use the narrowest useful investigation.

Preferred order:

1. `rg` / `git grep` for relevant terms and symbols.
2. Inspect the directly related functions/files.
3. Inspect callers/callees only when necessary.
4. Inspect tests covering the path.
5. Expand scope only if the initial investigation is insufficient.

Avoid repeatedly rereading unchanged files.

Do not generate repository-wide maps unless requested or genuinely necessary.

---

## Implementation

When implementing:

* Prefer editing existing functions over creating parallel implementations.
* Reuse existing helpers and utilities.
* Match existing error-handling patterns.
* Keep functions focused.
* Avoid unnecessary indirection.
* Avoid premature optimization.
* Avoid duplicated logic.
* Validate input at existing trust boundaries.
* Preserve security controls already present.

For backend/API work, pay particular attention to:

* Authentication
* Authorization
* User/data isolation
* Input validation
* CSRF where applicable
* Rate limiting where applicable
* Error leakage
* Network exposure
* Database consistency

---

## Testing

Run the narrowest relevant validation first.

Preferred order:

1. Existing targeted test(s).
2. Relevant test file/module.
3. Lint/typecheck/build for affected code.
4. Broader test suite only when justified.

Do not run expensive unrelated test suites unnecessarily.

When fixing a bug, add or update a regression test when practical.

Do not claim something is verified unless it was actually tested or directly inspected.

---

## Git Discipline

Before changes:

* Inspect `git status`.
* Do not overwrite unrelated user changes.

During changes:

* Keep the patch narrowly scoped.
* Do not modify generated or unrelated files unless required.

After changes:

* Review the diff.
* Confirm no unrelated modifications were introduced.

Do not commit, push, reset, rebase, or discard user changes unless explicitly instructed.

---

## Dependencies

Do not add a new package or service unless:

* Existing dependencies cannot reasonably solve the problem.
* The benefit clearly outweighs the maintenance cost.

If adding a dependency is necessary, prefer established and actively maintained options.

Do not upgrade unrelated dependencies during a task.

---

## Performance Work

For optimization tasks:

1. Identify the actual hot path first.
2. Preserve current functional semantics.
3. Prefer measurable improvements over theoretical rewrites.
4. Avoid introducing caches unless invalidation and consistency are understood.
5. Avoid optimization that significantly increases complexity for negligible benefit.

When benchmarks are available, compare before/after behavior.

---

## Security-Sensitive Changes

Use extra scrutiny for:

* Authentication
* Sessions
* Permissions
* Public endpoints
* File access
* Uploads
* Reverse proxies
* Network exposure
* Secrets
* Database migrations
* Destructive operations

Do not weaken existing security controls for convenience.

Never print, commit, or expose secrets, tokens, passwords, private keys, or sensitive environment values.

Use placeholders when referencing secrets.

---

## Output / Token Budget

Minimize output tokens aggressively.

Do not narrate routine exploration, shell commands, repository navigation, or obvious reasoning.

Do not:

* Restate the user's request.
* Dump large source snippets.
* Quote entire files.
* Explain every command executed.
* Produce long implementation diaries.
* Repeat findings in multiple sections.
* Generate lengthy summaries after straightforward changes.

Prefer:

* `file:line` or file/symbol references.
* Short descriptions.
* Concise findings.
* Small diffs.
* Actionable information only.

Exploration may be extensive internally, but the final response should contain only information useful to the user.

Stop once the requested task has been completed.

---

## Default Output Format

For inspection or assessment tasks, use:

### Status

`ready` / `needs-prep` / `blocked`

### Findings

* Only material findings.
* Prefer `file:line — finding`.

### Recommended Action

* One concise next action.

Target: **≤400 words** unless more detail is required for correctness.

---

For implementation tasks, use:

### Changed

* `file — concise description`

### Verification

* Tests/checks actually performed.

### Notes

* Only unresolved risks, assumptions, or follow-up items.

Do not provide a full walkthrough unless explicitly requested.

---

## Planning

Do not create a lengthy plan for small or obvious tasks.

For larger tasks, produce only a short implementation outline covering:

* Scope
* Files/components likely affected
* Material risks

Then proceed if the task is sufficiently defined.

Do not repeatedly ask for confirmation for routine implementation details that can be safely inferred from the repository and task.

---

## Ambiguity

Resolve minor ambiguity from:

1. Existing repository behavior
2. Existing tests
3. Existing conventions
4. The smallest behavior-preserving interpretation

Ask the user only when the ambiguity materially changes expected behavior, security, architecture, or destructive impact.

---

## Completion Criteria

A task is complete when:

* The requested behavior is implemented or assessed.
* Existing relevant behavior remains intact.
* Relevant validation has been performed where practical.
* The diff contains no unrelated changes.
* Any remaining material limitation is stated concisely.

Do not continue polishing beyond the requested scope.
