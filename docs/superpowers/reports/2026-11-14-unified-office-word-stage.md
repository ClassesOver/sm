# Unified Office controller + trusted Word task chain: stage evidence

## Scope and exact inputs

This is one bounded stage, not four independent assistants or a complete production Codex integration. The frontend has one view-free task controller with typed format adapters; the optional Word dispatcher projects repository receipts through the existing start/status/cancel/accept routes. Explicit accept enters NativeDraft; save is independent. The dispatcher uses an injected synthetic transport in these tests. Real Codex/provider startup, worker permissions/isolation and production enablement are not validated.

- Controller source: `1e7688ff3ba5fe1c0da17215230403db486ef186`, tree `88636d1ceeb74afdd9db9cb5d1fd956b82a493ba`.
- Word source: `3d976588d3c76175577b04b5940501e594789cad`, tree `c055c5981f80b5e7803aec455169cd9719adb349`.
- First no-conflict combination on code `1e4a0a34`: `21eaad1eeabe3c2cfe26bedc43610397d2196d75`, tree `f5f034602c7acb874e238f84a57458e18c7d4746`.
- After #238 merged, no-conflict integration on code `2ed02513b5fbc3ae1fadc98be38df0661fe649bc`: **tested HEAD `7396981c8c8492ebc5402fcdd7d8bb735abc2bf5`, tree `d630693fd41247ade1699ff150af841f250d66fe`**. Stage diff excludes #238's already-merged implementation.

## TDD, failures and source-tree evidence

Controller review found status-network failure followed by read-adapter release could lose cancellation identity. Regression RED preceded cleanup/identity retention. A second review found repeated cancellation could lose failed-cleanup retry identity; its regression was observed RED before generation-scoped cancellation coalescing. Final source-directed run was 79 passing tests, not a full suite.

The first combined controller tree `5034b363` had 79 directed passes and 24 synthetic-transport Chromium checks, but actual native-main type closure failed TS2774 (4759 files, one diagnostic, exit 2). The same baseline closure had 4758 files, zero diagnostics. Minimal source correction removed a required-method existence conjunct; its local actual-import TypeScript reproduction changed RED to GREEN. Subsequent combined `dd0dd108` had 26 directed passes, native-main 4759 files / 1126 project sources with zero diagnostics/old-tree references, and 24 Chromium checks. Those results are not attributed to later trees.

Word's original fixture used a save-only repository: `create_from_source` AttributeError was a fixture/interface error, **not RED**. Earlier missing configuration/engine layout failures were likewise not business RED. Test-only `214ae81a` used the real native repository and disposable PG. Fixture import/context/preview/source-readback passed (one test); then the takeover node failed with the exact business assertion `old executor cancellation terminated new claim`: actual CANCELLED, expected ACTIVE. No setup error or skip. Its extracted function SHA256 `794dcd07b7223faa0d33074d1abd202f3919beaf4fdfc0afdc4c2a46e538a9e0` is unchanged in the GREEN candidate.

Word source `3d976588` then passed **106 tests, zero failure/error/skip, exit 0** across the seven explicit files: MCP, dispatcher, actual chain DOCX, native_ai, Word wiring, Word contracts and Word repository. This included 13 real PG18/HTTP/authenticated-MCP/DOCX chain cases and 20 repository cases; remaining specified cases use controlled services. Original RED now passes; cancellation isolation, failed-attempt closure/no rerun, commit-ack/finish recovery, parallel exact retry/changed409, prepare cancellation and accept/save readback are covered. Seven Python files Ruff and incremental diff-check passed. This is not a full-project test result.

## Exact integration verification (separate executions, not one aggregate suite)

At `21eaad1e`, three actual PG/HTTP/authenticated-MCP/DOCX smoke nodes passed, zero skip; controller/native-ai 26 passed; actual Word adapter + NativeDraft Chromium six checks passed with synthetic transport. No type closure was rerun there. Frontend equals the previously tested `dd0dd108` projection, not the raw source candidate (which predates merged rail files). Backend/tests equal Word source. Transfer padding/SHA errors were retained and repaired by numbered hash-verified subchunks before testing; corrupted bundles were never treated as tested input.

At final tested `7396981c` / tree `d630693f`:

- Backend: **3 passed, zero failures/errors/skips, exit 0**, in a new disposable PG18, real HTTP/authenticated MCP/DOCX: start-to-candidate, explicit accept/save with independent DOCX readback; old-executor cancellation cannot terminate the new claim; late swallowed candidate after cancellation is rejected. Ruff and diff-check passed.
- Frontend: controller/native-ai **26 passed**, merged-cell regressions **6 passed**, both exit 0 and no skip.
- Actual native-main import closure: **4763 files / 1130 project files, zero diagnostics, exit 0**, no old-tree source references. This is not full frontend build/budget validation.
- Chromium actual Word adapter + NativeDraft: **6/6 passed**, synthetic transport, no browser warning/error, pageerror or failed network request in this run. It does not call a real provider or show real Codex output.
- New PG containers/anonymous volumes, temporary synthetic secrets/environment and runtime links, browser services/links were cleaned and checked. Worktrees stayed clean; source/tests/locks were not repaired in the cloud.

The source 106/79 runs were not repeated wholesale after integration. Only the above exact-tree minimal checks were run; no aggregate all-green suite claim is made.

## Warnings and unresolved coverage

Preserve one pytest third-party imghdr deprecation warning per relevant invocation, duplicate execute registration, absent management schema, native_refresh_capability_unavailable and fault-injected native_ai_failed logs. Their presence was not suppressed. Earlier frontend temporary entry 404 and baseline-script path failures remain separate environment evidence.

The single historical full frontend-suite attempt ended exit 130 when /tmp filled; partial output had 52 slides-native failures with ResizeObserver undefined and two slides-native-ribbon availability assertion failures. Those were not closed by these focused results and are not all proven baseline failures. Full TypeScript attempts had heap/resource termination. Neither full suite nor full build was repeated. Earlier whole-project 780 collection errors remain a separate unresolved historical report.

No real Codex/provider, production worker runtime/permissions, production auth/deployment, full four-format end-to-end AI, or complete save/export publication chain is claimed. Real HTTP and authenticated MCP here use complete synthetic configuration and actual format engines in disposable environments; transport/model behavior is injected. Default legacy path remains, while selecting the new Word backend without its configured transport fails explicitly rather than silently falling back.

## Readable evidence locations

- Word cloud thread `6af7e66b-08fc-8191-a00e-42126edf60f5`: source GREEN turn `01a1d9a5-9fc1-71cb-82c8-da1f94bdd834`, final integration turn `01a1d9de-dbcf-7744-be95-721a72ff4610`; final logs/JUnit/source hashes under `/workspace/word-chain-code238`.
- Frontend cloud thread `6af7d167-7eb0-8191-90c4-0d4a9abe40c6`: final integration turn `01a1d9df-0bef-7290-9093-48eb2c51b1e4`; final acceptance manifest SHA256 `f4b14111e9c63c076cc994706cfbbcd1c9593121458685384c36b53826bbe038` under `/tmp/office-stage-7396981c-20261114/acceptance`.

These execution-local paths identify audit evidence, not public artifact download links. Independent review reads cloud acceptance records and checks code/diffs/hashes; it must not be described as downloading/parsing every raw JUnit entry unless actually done.
