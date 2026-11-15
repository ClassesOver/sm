# Reporting Redundancy Helpers Design

## Goal

Remove four confirmed duplication points without changing public behavior:
duplicate compression delegation, elapsed-time calculation, sandbox binding
digest calculation, and non-negative integer normalization.

## Scope

- Delete `ContextBudgetController.ashould_compress`; inherit the existing
  implementation from `ProtectedCompressionManager`.
- Add one runtime helper for elapsed milliseconds and replace the five identical
  private implementations.
- Add one sandbox helper for canonical `WorkspaceBinding` HMAC digests and use
  it from Daytona and local providers.
- Add one Reporting phase helper for non-negative integer values and replace the
  repeated local `count` closures.

No protocol fields, error codes, persistence formats, or business rules change.
Existing provider secret-length checks remain in each provider.

## Testing

Add focused unit tests for helper boundaries and provider digest equivalence,
plus a regression test proving the context-budget manager still dispatches its
overridden synchronous compression predicate through the inherited async method.
Run only the focused tests and Ruff checks needed for the touched modules.
