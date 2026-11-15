# PR #240 bounded review follow-up

Base published head: c6c61531317a8ac985791da35bff4bafa3c6cb38; code remained 2ed02513b5fbc3ae1fadc98be38df0661fe649bc during source validation. Default remains off; no real Codex/provider, DSH/permission probe, deployment or broader capability enablement.

## Minor 1: late start cleanup retry

Source 557bc030dc975495f7cd7a52d514bc8cfb52694e, tree25b74079aad574adf0fb0085a8f00ce2ec73ab91. Controller-only transports may provide cancel(id) without cancelRequest. A start returned after cancellation, and its first ID cancellation failed; the old implementation swallowed the error without keeping retry identity. Three unchanged behavioral regressions failed before the fix (three failed, one passed, thirteen filtered out), then controller/native-ai 29 passed. Test SHA256 was 01c2562d51fb36667243581d398efb2071a42f34c64593a84e1748fdeb53dc57 in both runs. The independent late-cleanup set retains failed handles, coalesces in-flight cleanup and never restores stale identity over a replacement. Retry failures remain observable.

On this source tree, actual native-main closure had 4763 files/zero diagnostics; Chromium seven checks passed, including cancel-only retry/error propagation. Those source-tree results do not claim the later combined tree reran types/browser, and do not lift or bypass the separately reported PPTX socket EPERM restriction.

## Minor 2: unsupported trusted Word selection

Word source c2b65c25be759b4fcbd139c40b3ff57ff5851708, tree8d1d0ff84603b7c94356cabf9fee4928b328b780. A table selection legal in the generic Word validator is unsupported by this trusted paragraph-only builder. The real HTTP regression observed 500 before repair; after minimal dispatcher boundary translation it requires 422/native_ai_selection_invalid, no internal marker, no task/job/provider activity. The same function SHA256 before/after is 0fe139463ff287efa9e48a93a0e65befe30a94da5c431fd76a89f9568bccec3b. Only exact builtin ValueError with the known marker is translated; unknown ValueError and authorization ReportingError remain the identical original exception in additional guards. No selection expansion or legacy fallback was added; builder normalization is unchanged.

Directed source verification: 50 passed, zero skip, exit0: new API3, dispatcher8, MCP5, native_ai31, actual PG/HTTP/authenticated-MCP/DOCX chain smoke3. Only those final three are actual PG chain cases. Ruff and diff-check passed, one existing imghdr pytest warning; synthetic configuration/runtime links/PG containers and anonymous volumes cleaned.

## Accept authority test addition

Includes ffcfc9ac6b358d933598314355a0291e2651712b and its existing report. Six unique preview/receipt-wait cases cumulatively passed, not one six-green execution and not a production repair. First run four passed/two test injection failures; overwrite=True was missing in actual source replacement and cleanup. Only those two were rerun after correcting the test calls, two passed/four deselected. Domain rejection assertions and production code were not changed. Registered sessions use the existing in-memory fixture repository, while task receipts use actual disposable PG18 and Node DOCX. Coverage is bounded re-observation across two waits, not cross-service linearizable revocation. Accepted remains false, no revision2 is created, and accept does not write source bytes.

## Exact combination and independent review

Both fixes and tests combined without conflicts into ef11bc46038976f69876041c41b51a8afa756f4c, tree8853c8b0e5f59ee92e312b097e4f149f10f87000. Backend/test projection equals c2b65c25; frontend equals557bc030. Bundle parts and final SHA were checked before execution.

- Backend exact-tree smoke: six passed, zero skipped, exit0, 62.57s; API3 plus actual PG chain3. Ruff/diff-check passed, worktree clean, one existing imghdr warning; PG18/volume/config/link cleanup verified. Source 50 and accept6 were not repeated.
- Frontend exact-tree controller/native-ai: 29 passed, zero skipped, exit0. Source projection equals557bc030. No type closure or Chromium rerun in this combination; source-tree results stay separately attributed.

Astra independently inspected actual source/test diffs, matching function hashes and cloud acceptance records. No new code blocker in this bounded combination; this does not claim independent reruns or parsing all raw JUnit. Existing initial full-suite/resource failures and earlier type/interface/fixture failures in the main stage report remain open historical evidence; no full suite or whole build was repeated. No PPTX feature code is included here.
