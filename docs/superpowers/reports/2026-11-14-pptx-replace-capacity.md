# PPTX Replace All capacity verification

Base: `origin/code` b29f8d8. Independent branch `dot/pptx-parity`.
Astra reviewed/approved the design before product/test code changes.

## Change and evidence

`planSlidesReplace` now rejects a final planned edits array above 500 before it
can reach `onReplace`/native draft history. It does not count occurrences or
truncate results. The existing dialog catch reports the concrete Chinese warning
and leaves query/replacement text intact. Visual layout and CSS are untouched.

- Effective RED: `/tmp/pptx-capacity-red.log`, 3 failed / 2 passed. Failure shows
  501 edits returned and a dialog controller commit occurring instead of rejection.
- GREEN: `/tmp/pptx-capacity-green.log`, 24 passed in two focused files (new 5,
  existing 19). Covers 500 objects, 501 occurrences in one object, pending geometry,
  cross-slide identity, final-draft total, repeated overflow and query recovery.
- Directed strict TypeScript check on `src/slides-find-replace.ts`: exit 0,
  `/tmp/pptx-capacity-tsc.log`. `git diff --check`: exit 0.
- Isolated temporary dependencies from official npm registry, outside checkout:
  vitest 3.2.7, jsdom 27.4.0, TypeScript 5.9.3, vite 7.3.6. Versions and integrity
  hashes for these four direct packages match project package-lock. This is not
  a claim that every transitive dependency matches the entire application lock.
  No project lock, shared dependency tree or production static was modified.

## Corrections and limits

An initial test command used a wrong working-directory-relative output path and
found no tests; it was not counted as RED. The first GREEN attempt exposed a test
fixture problem: pending text intentionally overrides source text, so it had
removed the unique recovery query. Corrected the fixture's pending text; no extra
product change was needed. The successful run above includes that correction.

Not run: full frontend/application suite, complete project typecheck/build,
real browser, HTTP save/download, exported PPTX round trip. No claim that actual
Undo/Redo is independently exercised: the dialog's zero/one controller calls are
verified, and unchanged native commit wiring was inspected. No push, PR, merge,
deployment or Codex integration.

Final independent Astra code review: no code blocker found; reviewer read guard and
five tests and ran diff-check, but did not rerun the reported 24 tests.
