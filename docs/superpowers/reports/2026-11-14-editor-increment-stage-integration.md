# Editor incremental stage: PDF reading, PPTX capacity, XLSX candidate reliability

This is the final integration record for this limited stage. It supersedes the
local-only `pending` verification statements in the historical PDF navigation
plan; it does not erase that plan's rejected browser results or claim that the
initial implementation had passed them.

## Scope and provenance

Base: `code` at `b29f8d8b9f2c136e1d97cab83cfb54e3042bc67d`.
Tested integration HEAD: `9de556d3d1b6ce1f014c45281d66b78ce40f7be4`.
Tested tree: `ba146197b16c81172bf9517b0f3f65569650c2af`.

Each source commit was replayed without conflicts using `git cherry-pick -x`:

| Source | Integration replay | Slice |
| --- | --- | --- |
| `5710b55` | `04b4047` | PDF keyboard guards and reading navigation |
| `f5d567e` | `7f3fd3e` | Live reading anchor and boundaries |
| `79e9076` | `415423f` | Actual spread-row navigation |
| `815dfa8` | `6b77345` | Interruptible intent, rapid keys and short tails |
| `283a381` | `e1eac48` | Atomic PPTX final-draft capacity rejection |
| `aa081150` | `9de556d` | XLSX preview receipt and submission protection |

All seven changed source/test blobs exactly match their independently reviewed
source commits. The XLSX source was originally based on `82b3583`; its independent
replay on `b29f8d8` had tree `45b92a37350ac9575ce22a7202296c82a8a7699b`.
Only these PDF/PPTX/XLSX increments and their documentation are included. No
`task_execution` or `native_word` file is changed; Word identity binding/Codex work
belongs to a different stage and PR.

## Evidence on the exact integration tree

These are separate directed executions, not a single full-product pass:

- Local isolated frontend run: six suites, **83 passed** (PDF navigation 35,
  fit-state 7, NativeDraft 8, focus trap 9, slides find/replace 19, capacity 5).
  A seventh `pdf-page-layout.test.ts` suite failed collection because the minimal
  temporary dependency set lacked `pdfjs-dist/legacy/build/pdf.mjs`. The original
  combined command exited **1**. This was a dependency/import failure, not a
  behavioral assertion failure, and is retained rather than counted as RED or green.
- Independent cloud rerun of that layout suite with existing complete dependencies:
  **2 passed**. This closes only that collection gap; it does not rewrite the
  original command as successful. The other 83 were not unnecessarily rerun.
- Independent cloud XLSX four-file directed suite, once: **89 passed**, no failures
  or skips, 39.39 seconds; one existing third-party `imghdr` deprecation warning.
- Actual `pdf-main.ts` import closure noEmit check: **1,044 files, zero diagnostics**.
  Slides replacement import closure: **304 files / 3 project sources, zero diagnostics**.
  TypeScript 5.9.3 retained strict/noEmit and the existing skipLibCheck; old-worktree
  source references were zero. These are directed
  closures, not a full-frontend typecheck or production build.
- Actual Chromium smoke on this integration tree: **4/4 passed**, zero page errors.
  It checks the rapid-key/short-tail/zoom/wheel/native-key-interruption seam, not
  the complete historical browser matrix. The exact scenarios were
  `final-rapid-40ms`, `final-short-tail-scale-boundary`,
  `final-wheel-interrupts-intent`, and `final-native-space-clears-intent`
  (Chromium 154.0.8037.57, total exit 0). The existing localhost Vite HMR warning
  is retained separately from page errors: Chromium Local Network Access blocked
  the development HMR WebSocket and Vite reported failed WebSocket connection.
  This is not suppressed or reported as a warning-free browser run.
- Local strict TypeScript check of the two changed helpers, two-file Python Ruff,
  and local/cloud diff checks passed. No dependency installation or lock update
  was needed for integration; cloud runs reused the existing locked environment.

The transferred integration bundle was 21,041 bytes, SHA256
`dc10933eb87007214942e5094f1c4f38a8f5d1d5749806b43cb3ce14c132cfcd`.
Cloud checked all 24 chunks, bundle identity, exact HEAD/tree and the evidence
manifest. Its 74-entry SHA256 manifest was rechecked successfully; manifest digest:
`f6cce76995ca4780983b94c27a1657aacb30a0fc2b90df8e8feadbf9009d4696`.
All seven changed source/test SHA256 values were independently compared between
cloud identity evidence and this local tree, with exact equality.
Exact commands, exit codes, diagnostics and browser trajectories remain in the
integration acceptance evidence. The final publication follow-up changes only
this record and its link from the historical PDF plan; all executable/test/config
content must remain identical to the tested integration commit.

## Source-history evidence, not a repeated final-tree matrix

The unchanged PDF content from `815dfa8` had already passed independent real-browser
navigation verification, focused Vitest and the actual pdf-main type closure.
Earlier `79e9076` had failed rapid keys and short-tail browser cases; those failures
were fixed before the later source acceptance and are retained in the historical
plan. Final-tree smoke above is additional integration evidence, not a claim that
that entire earlier matrix was rerun on the integration tree.

PPTX capacity had real behavioral RED (3 failed, 2 passed) before the final
`result.length > 500` guard, then 24 focused tests passed. The guard counts final
edit objects, not text occurrences, preserves incoming drafts, and rejects before
one native draft commit. XLSX's standalone replay had 89 passing tests before this
stage; its final-tree 89-case execution is separately recorded above.

## Review, exclusions and release boundary

Independent Astra integration review checked exact HEAD/tree, all six stable
patch-ids and the 11-file pre-record scope, finding no code-level blocker. Final
acceptance is for this bounded editor increment only.

Not run or claimed: full frontend/application suite or production build, all-format
AI acceptance, true Codex/provider connection, production MCP authentication,
complete HTTP save/download/export round trips, or a complete four-format product.
No business credentials, business database or actual user document was used. No
Word binding behavior is inferred from these tests. There is no automatic save,
merge, deployment or production feature enablement in this stage.
