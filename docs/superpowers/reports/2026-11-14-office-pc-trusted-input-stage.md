# Office PC rail + trusted Word input precursor: bounded stage integration

## Candidate, scope and provenance

Base: code `0ce3aa10e975100fbbac7abf1ea1e85a925beeb6`.
Exact integration tested by both independent cloud sides:
HEAD `ba24ee2fbdaff343244d4fa3a25b780573fa3b37`, tree
`149736a372a02e1c3acba4268102afbf381d593b`.

The branch preserves independent commits for source-backed Scatter label/fallback
boundary documentation, Normal rail keyboard behavior, the rail verification ledger,
trusted Word builder, and its real-cloud history. Source replays use cherry-pick -x:
34ecf23→92a9d6a, 3202edb→a9d3d19, cad1f03→fef7309. Source/test blob equivalence
was checked individually for the four rail files and three Word builder files.
The whole frontend/scripts/project configuration/lock projection equals the tested
rail input; the Python/Node doc_engine/scripts/configuration/lock projection equals
the tested builder input. These checks support provenance, not a substitute for the
actual minimum integration smokes below.

This is a bounded Office PC interaction + trusted input precursor stage, not full
Office parity, all-format AI completion, a running Codex harness, production authority
transport, or a complete grant→preview→adopt→save workflow. No new production HTTP/MCP
listener, signed worker ticket, scheduler registration or Codex/provider run is enabled.

## Source evidence, kept separate from integration smokes

### Rail source and latest-code replay

The original 3202edb source and its a9d3d19 replay had 47 directed tests pass.
Actual slides-main import closure on the replay had 1190 files / 258 project sources,
zero diagnostics, strict/noEmit and original skipLibCheck, zero old-worktree sources.
Actual production-host Chromium six groups ran once on the replay and passed their
bounded assertions. The source ledger records these exact commits and evidence.
This was not full frontend tsc/build/budget or real PPTX import/save/export testing.

All earlier failures remain: invalid synthetic RenderSlide missing background caused
loading failure with zero behavior scenes; its first behavior round was 3 passed /
3 failed; only those three were rechecked after correcting canonical DOM-order and
localStorage isolation assumptions and introducing a 1px geometry tolerance. New
replay fixture separately added required scale:1. Products and repository tests were
not changed to obtain those results. The retained source/fixture analysis explains
why only the geometry assertion was deliberately relaxed, and the remaining limit:
Home still clips 0.5 CSS px, strict visible=false, only bounded-nearest=true. The 1px
acceptance-script tolerance is not a spec guarantee of strict complete visibility.

### Word trusted builder source

Exact cad1f039 / tree6d5f0fad source validation was three executions, not one green
suite: initial 123 nodes 62 passed / 11 failed / 50 setup errors, exit1; retry only
61 old failed/error nodes 45 passed / 16 errors, exit1; retry only those last PDF
nodes 16 passed, exit0. Latest per-node aggregation is 123 unique passed, zero skips.
The DOCX14 (including the real disposable-PG atomic create seam) actually passed in
the second run; controlled-service tests were not substituted for the engine chain.

The two failure rounds came from the isolated engine layout missing real frontend
and then sibling workbook_engine relative imports / original locked dependencies.
They are environment failures, not valid safety rejection or behavioral RED. Only the
isolated environment was repaired, with original versions/integrity and official npm
resolved mappings, disabled installation scripts, and no repository lock/source/test
change. Full prior output and manifests remain in the Word source ledger.

## Actual minimum smoke on the exact integration tree

The scope intentionally did not repeat 47 tests, 123 tests, the whole browser matrix,
or typecheck every frontend entry again. Both cloud sides checked the exact HEAD/tree
above and their respective source/engine/artifact binding before executing:

| Side | Actual selected execution | Result |
| --- | --- | --- |
| Word / actual DOCX + disposable PG18 | Authorized source/paragraph preservation; atomic task creation; final-context natural expiry; deletion | 4 passed, 0 failed/errors/skips, exit0 |
| Rail / actual host DOM | Two selected normal-rail navigation + notes-flush/veto cases | 2 passed, 5 unselected by name filter; not all seven rerun |
| Rail / first browser attempt | Source entry/helper/canvas binding verified but loading/optimizer failure before scenarios | 0 scenarios completed; failure retained |
| Rail / only affected browser retry | long-rail-repeat-and-nearest; notes-ime-veto-and-error-focus, each once | 2 passed, exit0, pageerrors=[] |

The browser retry changed only temporary /tmp Vite acceptance configuration:
pre-optimize the existing three and GLTFLoader dependencies and use an independent
cache. It did not modify product code, locks or assertions. No dynamic optimizer
reload or HTTP504 occurred during this retry. **The concrete historical 504 failure
URL was not captured, and a later loading probe did not reproduce it.** The passing
retry is evidence that this preoptimization setup mitigated the observed validation
problem, not proof of a fully established root cause or elimination of every race.
Original zero-scenario failure records were preserved, not relabeled as first-pass
success. No extra unit/type suites were rerun for that environment repair.

The Word side used its already corrected complete relative layout and locked actual
Node engine, rebound to this integration tree, with no old candidate source links.
Its four tests are fresh combination evidence, not the source-stage 123 repeated.
No behavioral PG or engine seam was skipped. Ruff for three new Python files and
incremental diff-check passed. Both working trees were clean; Word PG container,
anonymous volume and runtime links, and frontend temporary services/links were
removed and checked. No business database, credentials or actual user document used.

## Warnings, review level and remaining limits

All pytest runs retain the existing visions/imghdr DeprecationWarning (Python3.13
removal); source Word negative cases retain expected native_ai_failed ReportingError
WARNING logs. Browser records retain localhost Vite HMR console errors, download icon
warnings and invalid empty CSS color warnings; pageerrors=[] is not a claim of an
empty console. Exact levels/counts belong to their respective source or integration
records, not transferred from one matrix to another.

Astra independently read the cloud validation records and local source/diff/hash
boundaries. This describes reading cloud records/summaries, not downloading and
independently parsing every original JUnit/node JSON file. The final branch review
uses this bounded evidence and does not promote unexecuted paths to passed ones.
Only documentation follows the tested integration; executable/test/configuration
content must remain byte-identical to the tested tree.

Not verified or enabled: OS-native IME (only composition event boundaries), real PPTX
file rendering/import/save fidelity, strict pixel-complete Home visibility, complete
frontend build/budget, full application suite, all-format AI, real Codex/provider,
production MCP authentication/tickets, worker isolation or full editor adoption.
Word's final re-observation is not linearizable cross-service revocation; tools,
commit and adoption must reauthorize. Historical 780 full-project collection errors
remain a separate unresolved report, not replaced by these directed passes. No
push, PR, merge, deployment or production switch is authorized by validation alone.
