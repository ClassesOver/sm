# GenOffice Native Ribbon Implementation Plan

> For agentic workers: Use subagent-driven development for independent format tracks. Steps use checkbox syntax; review each track against NATIVE_RIBBON_DESIGN.md before integration.

**Goal:** Bring the complete fixed-version GenOffice DOCX, XLSX, PPTX, and PDF ribbon UI into the native editor and connect each action to the existing Web editor, authorized API, or an explicit unavailable state.

**Architecture:** Keep one editor state and one immutable revision/publication path per native document. Migrate upstream ribbon UI and only its required browser-safe dependencies; adapt command callbacks to NativeDraft and current format engines/API. Desktop-only commands remain visibly unavailable until a reviewed server capability exists.

**Tech Stack:** TypeScript, React, Tiptap/ProseMirror, Univer 0.25.1, Konva, PDF.js, native FastAPI API, GenOffice revision f8c17004fb730df11f0f743164ffd8b4281bb38c.

**Spec:** NATIVE_RIBBON_DESIGN.md

## Global Constraints

- Preserve the Markdown authoritative content model and all current report routes.
- Use the existing NativeDraft, NativeEditorService, file identities, CSRF, publication, and download grants.
- Keep gate, validation, and lineage faults nonblocking for generated files whose identities can be verified.
- Register new signing-chain failure injections and static signing functions as required by repository AGENTS.md.
- Do not add Plotly, .plotly.json, or interactiveCharts support.
- Keep editing features off by default; do not deploy during implementation.
- Retain GenOffice license/NOTICE/SOURCE and refresh local-adaptation SHA manifests for vendored upstream code.
- Browser tests must verify command effect, save, actual download, and independent reopen; screenshots alone do not establish command support.
- Do not use browser or LibreOffice output as Microsoft Office desktop certification.

## Files and Boundaries

- frontend/src/native-ribbon/: shared command availability, status messages, tab integration helpers and format-specific native adapters; no editor business state.
- frontend/src/docx-main.tsx: existing Tiptap-backed Word state and save-operation translation.
- frontend/src/workbook-main.ts: existing Univer-backed workbook shell and plugin registration.
- frontend/src/slides-main.ts and native-office-view.ts: existing Konva slide state and editSlides translation.
- frontend/src/pdf-main.ts and pdf-operations.ts: PDF.js state and PDFium operation translation.
- frontend/src/vendor/genoffice-*: pinned upstream component files and exact adapted dependency closure only.
- frontend/src/*-native-ribbon.test.ts and per-format browser fixtures: command contract and actual browser checks.
- reporting/tests/test_http_publication_lineage.py and test_publication_nonblocking.py: required signing fault/static registrations only when server signing code changes.
- reporting/slides_engine/UPGRADE.md: upstream revision, selected source closure, omitted desktop dependencies, tests and known gaps.

## Execution Order

The command inventory tasks run concurrently. The shared host contract is reviewed before format integration; then Word, Excel, PowerPoint, and PDF tracks can run concurrently because they own separate adapters/views. Each worker edits only the files in its assignment and must not change the shared shell or another format's code.

### Task 0: Four-Format Upstream Command Inventory

**Files:** modify NATIVE_RIBBON_DESIGN.md; add command inventory section to NATIVE_RIBBON_PLAN.md.

- [x] Enumerated the fixed-revision top-level/contextual tabs and command families for all four formats in NATIVE_RIBBON_DESIGN.md. The per-tab command IDs/callback fields and engine mapping remain mandatory in each format's implementation brief before that tab is migrated.
- [x] Read the Docs Ribbon and tab props, Slides Ribbon plus ribbon-actions boundary, Sheets ExcelShell and Univer command registration, and PDF App ribbon sections.
- [x] Traced currently advertised operations to native editor/bridge schemas; documented unconnected families and the PPTX animation direction mismatch.
- [x] Confirmed upstream command-bearing components have desktop boundaries: Docs Ribbon has pickImage; PDF App owns file/print/signing handlers; ExcelShell and Slides Ribbon delegate through callbacks to desktop-aware App. No such source is safe to import as an unadapted Web module.
- [x] Added command families, current Web mapping and known gaps to the design. Per-tab implementation briefs will record exact command IDs and final status.
- [x] git diff --check passes.

### Task 1: Shared Native Ribbon Host Contract

**Files:** create frontend/src/native-ribbon/host.ts, frontend/src/native-ribbon/status.ts, and focused unit tests; modify native-main.ts only to provide shared shell state.

**Interface:** NativeRibbonCommandState contains enabled:boolean and optional reason:string. NativeRibbonHost exposes format as docx/xlsx/pptx/pdf, commandState(command) and reportCommand(command, result), where result status is applied/unavailable/failed and code is an optional safe public code.

- [x] Rejected a global NativeRibbonHost object: each ribbon is natively coupled to a distinct editor/state owner. Format adapters call their existing editor APIs directly; add only a shared helper if two completed format migrations demonstrate actual identical behavior.

### Task 2: Word Ribbon

**Files:** pinned Docs Ribbon support under vendor/genoffice-docs; modify docx-main.tsx, docx.css, and targeted tests.

- [ ] Port the ribbon's required browser components, icons, palettes, formatting helpers and localization from the fixed upstream revision; refresh SHA/source metadata and preserve license headers.
- [ ] Bind ribbon format state to the active Tiptap selection and existing parsed DOCX styles/sections; update on selection and transactions without stale state.
- [ ] Connect supported character/paragraph/list/table/page-layout commands to current Tiptap transactions and docxOperations; ensure undo/redo is existing ProseMirror history.
- [ ] Map save/export/open to current Native API and publication flow. Keep filename/path, OS print dialog and unsupported document features explicit and non-executable.
- [ ] Replace OS print with browser print/downloadable output and system font enumeration with browser/document fonts. Leave certificate signing behind the separate security design gate; do not access host certificate stores.
- [ ] Add component tests for tab visibility/state and command mapping; browser tests for each command family, undo, actual DOCX save/download/reopen.
- [ ] Scope Markdown CSS to Markdown editor roots so it cannot distort Word canvas or pagination measurements; verify the long Chinese/67-row table fixture has no empty trailing pages.
- [ ] Run affected Word/Vitest and browser fixture checks, then production frontend build/budget once after the track stabilizes.

### Task 3: Excel Ribbon

**Files:** modify workbook-main.ts, Univer runtime/preset registration, native workbook adapters/tests; add only source wrappers required by GenOffice.

- [ ] Port GenOffice self-drawn ExcelShell tabs (Home, Insert, Page Layout, Formulas, Data, Review, View, contextual Chart Design) and ribbon-actions semantics; Univer supplies grid/presets, not this ribbon.
- [ ] Reuse existing Univer selection, command, history, locale and rendering state. Register the minimum upstream-compatible FindReplace, Drawing and Table UI presets/plugins after checking their APIs against Univer 0.25.1.
- [ ] Map each enabled ribbon command to a supported Univer command and NativeDraft operation; disable commands without safe XLSX writeback and explain their state.
- [ ] Ensure edits serialize through existing workbook operations and engine bridge; preserve formulas/styles/merged ranges and source identities.
- [ ] Add tests per command family plus a browser edit-save-download-reopen check for values/formulas and workbook structure.
- [ ] Check chunk budget and license/source manifest; do not bundle desktop file, shell or external-link gateway code.

Task 3 progress (2026-11-05): the historical brief path `.superpowers/sdd/NATIVE_RIBBON_PLAN/task-3-brief.md` is absent in this checkout and is not reviewable evidence. The current bounded, tracked source inventory is in `NATIVE_RIBBON_COMMAND_AUDIT.md`; full inventory remains open. Univer 0.25.1 FindReplace, Drawing and Table presets are registered in the existing runtime. Browser XLSX readback covers font/size/color, bold, number format/decimal increment and now source `autofn:*` SUM/AVERAGE/COUNT/MAX/MIN; the AutoSum smoke saves, downloads and independently reopens the workbook with openpyxl to verify `=SUM(A1:A2)`. The complete upstream ribbon is still not ported: most source action groups remain incomplete or unavailable and contextual Chart Design does not yet track chart selection/edit state. Do not mark Task 3 complete until remaining parity and command gaps are addressed.

Task progress (2026-11-05 continuation):

- Task 2 adds anchored paragraph insertion/deletion, source-derived Home/Insert controls, symbol insertion, paragraph alignment and non-list paragraph/heading left indentation, with browser save/download/reopen. Table, links, list-level indentation and full tab parity remain open.
- Task 3 adds source glyphs, formatting controls, numeric-format and decimal increment, with browser save/download/openpyxl readback for values, formula, style, number format and sheet structure. Most upstream command families and exact source Ribbon parity remain open.
- Task 4 adds selected-object text formatting with strict operation validation and PPTX inspect readback. The browser save/download/reopen smoke passes; full source tab/group/control parity remains open.
- Task 5 adds validated AcroForm value editing with independent value readback, source-derived icon/label/color controls, saved-page browser printing, and browser form save/download/reopen. A signed-PDF fixture, full command parity, Form Design and static-form editing remain open.
- Unified standard and Slides builds, TypeScript checks, chunk budget and its contract passed after the format slices stabilized. Existing third-party bundler warnings and >500 KiB chunk notices remain visible; the repository budget contract passes.
- No format task is complete. Browser smoke now covers Word edits/download/reopen (including nonblocking validation failure), PPTX selected-text formatting/save/download/independent inspect, and PDF AcroForm save/download/readback. XLSX has browser readback for supported style/number commands. Full upstream tab/control parity, clean-image/offline readiness and remaining command families are still required.
- 2026-11-05 continuation: DOCX now mounts a source-derived Home React component backed by fixed-upstream SVG glyph and Chinese Ribbon label resources; XLSX uses its byte-identical source glyph module and browser readback now covers font/size/color and decimal increment; PPTX uses byte-identical source icons on native controls; PDF uses a source-derived icon/palette subset and implements isolated printing of saved PDF pages. See the format briefs for exact hashes and test evidence. These are partial UI closures, not completion: DOCX/PPTX source Ribbon groups and control parity remain incomplete, ExcelShell remains an adapted group model, and PDF's original controls/locales are only partially represented.
- 2026-11-05 parallel continuation: Word now maps all four source paragraph alignments through an anchored operation and independently reopened DOCX; Excel maps five source `autofn:*` actions and verifies the formula in a downloaded/reopened XLSX; PPTX has button-dispatch coverage for the source font-size ladder with existing strict bridge/readback path; PDF Fill Form has previous/next focus navigation across actual editable fields. Merged TypeScript and 54 focused frontend tests pass. Standard and Slides builds pass, as does the budget contract; the actual chunk budget currently fails on the 425 KiB `lazy-react` chunk versus the 250 KiB ordinary limit. The full command inventories, feature parity and offline acceptance remain open.
- 2026-11-05 Word indent continuation: Home increase/decrease indentation follows GenOffice's 720-twip half-inch stops for anchored paragraphs and headings; list items stay disabled because list-level writeback is not implemented. A Chromium save/download/reopen smoke independently reads 720 twips from the downloaded DOCX and checks the reopened browser's 48px paragraph inset. Forty focused DOCX/ribbon/draft tests, TypeScript, and nine paragraph-indent bridge cases pass.
- 2026-11-05 parallel command-group continuation: PDF Pages now follows the pinned source's four command groups and semantic IDs; left/right rotate and delete stay enabled on the verified bridge, while unsupported extract/insert/replace/crop/size/reverse/split/merge actions have individual disabled reasons. PDF View adds source IDs for thumbnails, outline, search, page jump in Home and View, single/two-page layout, zoom and fit; only night mode remains unavailable in this source group. Two-page Chromium coverage verifies outline destination navigation, spread toggling, View zoom and Home page jump before PDF save/download/form readback. Word Home/Layout exposes source IDs for line spacing and before/after spacing as disabled because DOCX operation and bridge allowlists do not support those paragraph attributes; Table Design/Layout commands are inventoried and disabled except anchored cell text editing. Insert link/edit/remove link remain disabled until anchored DOCX link operations are supported. Excel Review Comments/Notes and Data filter/clear/reapply/advanced actions remain disabled because current runtime/engine lack persisted filter state and readable comment state; Data ascending/descending sort is enabled using public Univer 0.25.1 `getValues()` plus `getFormulas()` and the shared stable sort engine, rejecting formulas before grid writes. Browser save/download/openpyxl readback verifies sorting `alpha, zeta` in A1:A2. PPTX Review Comments remain disabled without comment writeback/state; Home paragraph alignment and layout selection bind to strict native operations and verified inspect state. New slide, slide-with-layout, reset-layout and section commands remain disabled without bridge operations. Combined focused PDF/Word/XLSX/PPTX tests pass 83/83, merged TypeScript checking and `git diff --check` pass. The standard frontend production build passed before these final command group additions and will be rerun. Build output reports existing third-party chunk/circular-chunk warnings. These are command-group increments only; Tasks 2-5 and final acceptance remain open.
- 2026-11-05 continuation: PDF View outline now resolves PDF.js named/direct destinations to source page indexes and exposes a navigable nested sidebar; a two-page Chromium fixture with a real outline verifies bookmark navigation to page 2, zoom and Home/View page inputs, then PDF form save/download/readback. Word list indentation now uses a strict `setParagraphListLevel` operation with source numbering identity and compatible adjacent-level checks; bridge validates level 0-8 and preserves `numId`, with a real DOCX multilevel roundtrip. Excel View adds source-ordered controls and binds gridline visibility to Univer's worksheet view API; other unsupported view commands remain individually disabled. PPTX Home layout selection is enabled on the existing inspectable layout operation; unsupported slide add/reset/sections and Insert table/image/shape/SmartArt/chart commands are present with source IDs and explicit reasons. The combined focused ribbon/operation selection passes 87/87, merged TypeScript and `git diff --check` pass. Build and full acceptance remain to be rerun; all four format tasks remain open.
- 2026-11-05 source parity continuation: PDF View's single/two-page command now toggles the renderer's page grid; actual outline destination, spread state, zoom, Home/View page navigation and PDF form save/readback all pass the two-page Chromium smoke. Word Home list controls now map legal existing numbering levels to strict `setParagraphListLevel`; list style galleries, new definitions, numbering values and restart semantics remain explicitly disabled. The DOCX bridge roundtrip preserves `numId` and is covered by a focused pytest. Excel Data Tools now includes source-ordered text-to-columns choices, Flash Fill, Remove Duplicates, Validation, Consolidate and a separate Outline subtotal placement; these remain disabled where the XLSX bridge lacks equivalent persistent operation/readback. PPTX Insert Text Box maps to the existing addText operation; its browser smoke saves revision 2, downloads it, and independently reads text/type/geometry with `inspect_office` and python-pptx. WordArt/header-footer/dynamic fields/equation remain unavailable. Merged focused ribbon/operation tests pass 89/89; TypeScript and `git diff --check` pass. Four-format full source parity and final acceptance remain incomplete.
- 2026-11-05 continued source parity: PDF Home Document Properties now opens a read-only panel sourced from PDF.js Info/XMP with missing-XMP fallback; the AcroForm browser smoke verifies title/author while also checking outline, spread, zoom, Home/View page navigation, save/download and field readback. PPTX native-office strict validation now accepts optional animation `append` only as a boolean, matching the existing bridge contract. API tests cover invalid types and ordered append readback. The transitions/animations browser smoke saves and independently reopens the downloaded revision, confirming `wipe` and `flyIn/right/afterPrev/1250ms/300ms`. Cross-format focused frontend tests pass 95/95, native-office pytest passes 31, merged TypeScript and `git diff --check` pass. Standard build must be rerun after these latest PDF/PPTX edits. Tasks 2-5 and full four-format source parity remain open.
- 2026-11-05 Word Layout/Header/Footer continuation: DOCX Layout now writes the anchored trailing section's orientation, paper size, margins, column count, and header/footer distances through `setSectionLayout`; unsafe section-break and independent header/footer part controls retain stable source IDs with explicit unavailable reasons. Focused frontend ribbon/operation tests pass 93/93, section bridge tests pass 2, `git diff --check` and the standard production build pass. The build still reports existing circular/dynamic chunk and >500 KiB chunk warnings. Full source parity, browser end-to-end acceptance for this layout slice, build-budget compliance, offline/image readiness, and four-format HTTP acceptance remain open.
- 2026-11-06 integration continuation: PDF source Reverse Pages now stages the existing identity-bound `reorderPages` operation from the surviving draft order. Browser save/download plus independent pypdf readback verifies two distinct page sizes in reverse order while retaining all four AcroForm values and unchanged source bytes. Word Home spacing now supports source multiplier presets and before/after 0/240-twip toggles; 16 real bridge cases cover raw OOXML group preservation, inherited before=0, automatic spacing cleanup and invalid inputs. The browser smoke saves/downloads/reopens spacing alongside prior alignment/list/indent commands. Review found and fixed the section-aware Layout replacing paragraph right-indent controls and losing section controls on selection refresh; both section/no-section right-indent tests pass. Home uses the pinned UI popover-dismiss hook; editor destruction now unmounts React roots/listeners. XLSX row deletion capture now uses actual Univer `sheet.mutation.remove-rows`; browser save contains four structural operations without compensating cell edits, and openpyxl verifies deletion, formula and number format preservation. PPTX Design 16:9/4:3 saves and reopens real size/geometry, but review found a pending-size draft-restoration gap, which remains in progress before accepting that command. The last stable integrated selection passed 106 frontend tests, standard/Slides builds and both budget checks; subsequent review fixes still require final integrated verification. Complete fixed-source parity, latest clean-image/offline and four-format HTTP acceptance remain open. No format is complete.

### Task 4: PowerPoint Ribbon

2026-11-06 acceptance update: Word's section Layout slice now passes `DOCX_SMOKE_MODE=section-layout node smoke/docx-native-save-smoke.mjs`. Independent python-docx confirms A4 landscape, two columns, custom margins and header/footer distances from the downloaded file; browser revision-2 controls retain the values. Source bytes and nonblocking validation download behavior remain intact. This closes the earlier missing browser/file check for this slice only. DOCX draft refresh/undo restoration remains under repair; full source parity and HTTP/production acceptance are not complete.

**Files:** create focused vendored ribbon adapter components; modify slides-main.ts, slide editor view styles, native-office-view.ts, and format-specific tests.

- [ ] Port upstream Ribbon, tab subcomponents, icons, palettes, and only browser-safe helpers at the pinned commit; regenerate SHA/source manifests.
- [ ] Bind hasSelection, hasTextSelection, font/alignment, layout, animation, transition, theme, zoom and undo/redo state to the current Konva model and render tree.
- [ ] Map commands onto the existing strict editSlides operation schema and real bridge. For a missing operation, add schema validation, bridge writeback, roundtrip test and failure injection before exposing its button.
- [ ] Replace Electron open/save/save-as/print/image export with Native API behavior or a clear unavailable state; keep existing revision and download chain.
- [ ] Replace system printing with browser print or a downloadable rendered PDF; map image picking to the existing safe upload/import path.
- [ ] Add tests for tab/state updates and each operation family; browser tests edit text/geometry/layout, save, download and reopen with independent python-pptx readback.
- [ ] Run affected slide tests and source/module typecheck; do not claim the known broken upstream full-package test toolchain is fixed by this task.

### Task 5: PDF Ribbon

**Files:** add isolated PDF ribbon components under frontend/src/pdf-ribbon/; modify pdf-main.ts, pdf-operations.ts, pdf.css, and focused tests.

- [ ] Extract upstream tab/control components and command definitions for Home, Annotate, Edit, Page, View, Fill Form and Form Design without importing GenOffice's full Electron App.
- [ ] Bind commands to existing PDF.js document, stable page/object selection, annotations, form state, PDF operation stack and actual PDF preview; preserve explicit PDF text preview confirmation.
- [ ] Add server operation/schema/bridge and tests before enabling commands not yet in the current PDF operation contract.
- [ ] Map open/save/export/download to authorized Native API endpoints. Keep certificate-store signing, OS printer dialogs, local file paths and desktop windows disabled with explicit explanations unless a separately reviewed server service exists.
- [ ] Implement browser print and server-side PDF/page operations as Web equivalents. Before certificate signing, write a separate key-custody/authorization/recovery security design and validate it; this ribbon plan must not store private keys or passwords.
- [ ] Add tab and selection-state tests; browser-test each enabled command family, preview confirmation for text changes, save/sign/download and pypdf/poppler readback.
- [ ] Keep PDF.js assets same-origin, lazy loaded and within the fixed chunk budget.

### Task 6: Cross-Format Review and Final Acceptance

2026-11-06 PR checkpoint: section Layout and DOCX draft recovery now pass real browser/file readback; XLSX draft recovery and structural Undo preserve formulas/defined names/merges; PPTX A4/A3 portrait presets pass save/download/readback/reopen. Four new HTTP integration cases cover real authorization, file engines, nonblocking failed validation, signing/download and reopen with explicit repository test doubles. Both production builds and budget checks pass after the structural-Undo repair. The work is being submitted as a draft PR: complete source-command parity, a fresh clean/offline image, production database/host acceptance and deployment remain outstanding. No format is marked complete.

- [ ] Run command inventory against all delivered ribbons: every source action is executable, implemented server-side, or explicitly unavailable with a reason.
- [ ] Run format tests independently; run required nonblocking publication contracts once if server publishing code changed.
- [ ] Run npm test only for affected ribbon/editor test files, then once each npm run build, npm run build:slides, npm run check:budget, and npm run test:budget.
- [ ] Verify no Electron imports, Node filesystem paths, CDN loads, or unlicensed assets enter browser output.
- [ ] Build a clean app image, compare native module and vendored-source hashes, and test offline readiness and actual four-format HTTP upload/edit/save/download/reopen.
- [ ] Keep user upload mount/integration and real production-scope database acceptance distinct from fixtures and image tests.
- [ ] Update NATIVE_EDITING.md and slides_engine/UPGRADE.md with exact commands supported/unavailable, evidence, feature flags, rollback and remaining desktop-only checks.


### PR #190 follow-up (2026-11-05): custom PPTX dimensions

- Bounded independent review of NativeDraft/PPTX identity, retry and revision locking found no confirmed blocking defect in the reviewed paths; this is not a full review of all 495 changed files. GitHub returned no commit statuses or PR-triggered workflow runs for `0017ff7a`.
- Design now provides custom dimensions with cm/mm/in using the unchanged pinned source conversion helpers. Applying both axes creates one NativeDraft edit, supports Undo/Redo and refresh restoration, and refreshes the preset/orientation state immediately. Cancel leaves the draft unchanged.
- Native API and file bridge require integer dimensions within ECMA-376's 914400–51206400 EMU per axis; malformed fields, booleans, fractions and out-of-range dimensions are rejected. Real PPTX roundtrips include a custom size and the minimum/maximum boundary pair.
- New-presentation defaults remain explicitly unavailable because this host has no blank-presentation creation flow. Full source parity, fresh offline image and production-scope acceptance remain open; all four format tasks remain incomplete and feature flags stay off.
- Validation: 45 focused frontend tests plus the added portrait-state regression passed separately; 28 backend size/schema/bridge cases passed. No full repository suite was run. Browser/build results are recorded below after completion.

- Final build evidence: restored the separate frontend, slides-engine and workbook-engine npm dependencies; `npm run build`, `npm run build:slides`, `npm run check:budget` and `npm run test:budget` all passed. Existing third-party/chunk warnings remain.
- **Browser acceptance NOT passed:** `PPTX_SMOKE_MODE=slide-size-custom node smoke/pptx-native-save-smoke.mjs` exposes a real interaction failure: after Playwright fills width 25 cm, the focused input still reports the source 25.4 cm; saving consequently retains source dimensions. Explicit click/keyboard input also reproduced it. Unit, bridge and build results do not close this gap. The smoke retains an input-value assertion before applying so this cannot be misreported as a successful save. Next step is to resolve the real modal input path, then rerun this affected smoke, independent python-pptx download readback and reopen checks. Custom dimensions are implementation-in-progress and must not be marked accepted or deployed.


### Follow-up closure: evidence-led diagnosis and parallel acceptance

The earlier browser failure checkpoint above is superseded: a bare-HTML control reproduces the failed input on managed Chromium 140 without any editor code, while system Chromium 154 passes native input/event checks. No speculative editor fix was retained. The smoke now gates on a checked-in input baseline and accepts an explicit executable path; it never bypasses native input or silently changes browsers.

- Chromium 154 custom-size acceptance passed: 25×20 cm native input, custom orientation changes, Undo/Redo, save/download, SHA identity/source immutability, independent python-pptx dimensions and scaled geometry, and revision-2 browser reopen. See `NATIVE_RIBBON_INPUT_DIAGNOSIS.md` for original evidence and reproducer.
- Fixed-source command audit found and closed three product discrepancies: custom/default source entry identities, disabled custom orientation despite legal bridge sizes, and ratio-only false preset labels. Native state/source-identity regressions pass; source matching now follows the fixed upstream helper.
- Parallel inventory and HTTP evidence are recorded in `NATIVE_RIBBON_COMMAND_AUDIT.md` and `NATIVE_RIBBON_HTTP_EVIDENCE.md`. Missing historical `.superpowers` briefs are not treated as available evidence. ASGI routes, actual engines and independent file readback are distinguished from in-memory repository substitutes and production deployment.
- Tasks 2–6 remain incomplete globally. Next acceptance work: close remaining source inventory gaps and execute fresh image/offline acceptance; real production database/host checks stay separate. No default-new-deck preference is enabled without a creation flow. Feature flags remain off.


Final verification for this closure:

- Backend dimensions/schema/bridge: 28 passed in the preceding implementation checkpoint; no subsequent backend product changes.
- Updated frontend selection initially had 46 passes and one obsolete ratio-label expectation; after correcting it, the four affected size/state regressions passed, followed by the exact custom/default source-entry regression (1 passed). No complete repository suite was repeated.
- Final standard and Slides production builds, actual chunk budget and budget contract all passed after the orientation/preset fixes; existing third-party chunk warnings remain.
- The four-format ASGI roundtrip cases passed individually (three initial + PDF after restoring its missing engine dependency), plus three scoped negative cases. The modified PPTX custom-dimension HTTP case then passed separately with independent dimension/text/geometry readback and the existing identity/retry/reopen assertions (1 passed, 10.84s).
- Native Chromium 154 browser custom-size smoke passed independently; command audit was independently reviewed against pinned upstream source. Browser route substitutes, ASGI repository substitutes and the still-open production/clean-image boundaries remain documented separately.


### Next planned slice: packaged/offline acceptance and Home state

- Continued Task 6 rather than adding another feature family. Added `scripts/verify_native_offline.py` and two fail-closed negative checks. Freshly packaged all three engines, then verified four-format edit/independent file readback in an actual read-only `--network none` container (only loopback). Static entry/PDF.js identities and all-disabled flags passed; report provenance is explicitly `mounted-runtime-probe`.
- The same packaged runtimes then passed all four ASGI upload/save/download/retry/reopen cases under network isolation (4 passed, 8.74s). Repository substitutions and the absence of production DB/TCP/TLS evidence remain explicit.
- Attempted a fresh complete application Docker build. It failed on the managed 8 GB `vfs` workspace with ENOSPC, before any completed app image existed. Recovered space by removing this attempt's build cache. Complete-image acceptance stays unchecked; the smaller probe is not a substitute. Dockerfile now accepts optional ephemeral CA secret mounts while retaining TLS checks. Two obsolete Dockerfile contracts were corrected for the third PDF engine and passed.
- Independent Home Font/Paragraph source audit found enabled font-step buttons without a text target. Added them to the existing target/lock predicate; the focused selection/lock-transition case passed (1 passed, 15 skipped). Both production builds and budget checks passed after the change. The source Paragraph inventory now records missing bullets/numbering/indent/direction/spacing actions as missing, rather than claiming they are all explicitly disabled.
- Evidence, exact probe commands, runtime identity, artifacts and still-open boundaries: `NATIVE_RIBBON_OFFLINE_ACCEPTANCE.md`. The authoritative Paragraph slice inventory is in `NATIVE_RIBBON_COMMAND_AUDIT.md`.
- Next: complete the application-image boundary in adequate build storage, and use the tracked source inventory to connect or visibly explain the remaining Paragraph commands. Global Tasks 2–6 remain incomplete. Feature flags remain off; no deployment/merge/push.


### Word range links: implementation and independent acceptance

- [x] Connect Insert/Edit/Remove Link to an actual anchored text range using the existing pinned Tiptap link mark and GenOffice relationship allocator; strict UTF16/current-text ranges and URL validation are shared across diff/replay and backend.
- [x] Preserve mixed styles, untouched same-paragraph links and tooltips, source file identity, Undo/Redo and refresh; reject unsupported metadata/selection/restored fields explicitly.
- [x] Close an independently reproduced preservation defect: partial edit of unstyled external link ABC had injected Hyperlink style on untouched A/C. The bridge now preserves all original unstyled link runs during regeneration; independent re-probe and targeted regression passed without modifying vendor code.
- [x] Verify actual browser insert/edit/remove across revisions 2/3/4, file download and independent python-docx relationship/style readback. Verify the composed DOCX HTTP path separately with the production-packed bridge in Node 22 and a read-only network-disabled container (1 passed, 12.72s). Repository/route substitute boundaries remain explicit.
- [ ] Support body-text changes while a source paragraph still contains links; currently explicitly rejected. New paragraphs, table cells and complex/unsupported source links also stay unavailable for range-link editing.

Exact source/protocol boundaries, commands, tests and generated artifacts are in `NATIVE_WORD_LINK_ACCEPTANCE.md`. No full repository suite was repeated. This closes the bounded Word range-link slice only; Task 2/full ribbon parity, table/header/footer work, complete application-image and production-database/host acceptance remain open. Features remain disabled; no deployment/merge/push.


### PPTX Paragraph spacing continuation

- [x] Connect six pinned-source line-spacing presets plus before/after point spacing to strict native API/bridge fields and unchanged `setElementParagraphFormat`; require a nonempty patch and preserve all unspecified properties.
- [x] Inspect per-paragraph actual values and alternative units; present mixed/unset/unsupported source units without fabricated defaults. Merge pending alignment/spacing and same-object restored records; validate Enter input, selection and saving locks.
- [x] Validate 52 backend/native cases, 43 frontend cases plus 3 affected restore checks, and an independent reorder/multi-record/font-preservation probe. Real browser mixed-value/input/Undo/refresh/download/reopen and independent python-pptx/ZIP checks passed. The combined PPTX ASGI path passed with the production-packed bridge in a read-only Node22 network-disabled container (1 passed, 9.86s).
- [x] Complete the bounded source bullet/numbering, indent and direction families (2026-11-06); picture upload explicitly disabled. This does not complete PPTX or Task 6.

Source/format boundaries, exact commands and retained samples: `NATIVE_PPTX_SPACING_ACCEPTANCE.md`. Full application-image acceptance remains blocked by the previously documented 8GB/vfs build storage limit; mounted probes are not substituted for it. Feature flags remain off.

Final spacing checkpoint: both production builds and both budget checks passed after adding visible line/before/after unit labels. No full repository suite was repeated.


### Overall continuation: ordered Paragraph commands and real SQL evidence

- [x] Connect the remaining supported PPTX Paragraph list/number/indent/direction controls, including full source option inventories and strict API/bridge validation. Preserve ordered records rather than merging relative operations; independently reproduced Undo, record-budget and overflow defects are fixed. See `NATIVE_PPTX_LISTS_ACCEPTANCE.md`.
- [x] Run real PostgreSQL 18 repository isolation, transaction, retry, immutable completion and concurrency checks, including independent engines/processes; connect all four existing HTTP/file roundtrips to actual SQL persistence. 18 distinct checks passed across selected runs. Disposable schemas and container removed. See `NATIVE_POSTGRES_ACCEPTANCE.md`.
- [x] Trace Word table structure serializer and original XML, row-property ownership, column-width and anchor contracts. Found unmodeled paragraph-property loss even for nonmerged tables; enabling structural buttons now would overstate preservation. See `NATIVE_WORD_TABLE_PLAN.md`.
- [x] Execute original-XML preservation probes and prove the structural allowlist; the later backend/frontend checkpoints deliver the bounded table operations. The original investigation itself did not deliver a feature.
- [ ] Complete clean application-image acceptance with sufficient build storage; mounted runtime evidence does not close the recorded 8GB/vfs failure.
- [ ] Complete source parity and production host/tenant/grant persistence checks. Real native SQL tests do not establish production permissions; ASGI artifact/grant repositories still use doubles.

Global Tasks 2–6 remain incomplete. Feature flags remain off; this batch updates PR #190 without merging or deploying.

### Word table executable preservation checkpoint

- [x] Execute 14 real-DOCX serializer scenarios: original save, unchanged-model regeneration, four structure operations at first/middle/last positions. Python-docx/lxml independently verify matrices, widths, row ownership, rich text and untouched package members.
- [x] Confirm original save is byte-identical, while all 13 regenerated scenarios lose surviving paragraph `mirrorIndents` and `rsidR`. Record per-cell differences and hashes; do not treat modeled-content checks as structural preservation acceptance.
- [x] Preserve original surviving-cell paragraph XML through the bounded backend adapter (frontend structure commands remain open). Original-source anchors and unsupported combinations still require their planned tests. See the executed-probe section of `NATIVE_WORD_TABLE_PLAN.md`.


### Word table bounded backend continuation

- [x] Reuse pinned table generation and restore original surviving cells/paragraph XML by source coordinates; independent 13-case preservation probe has zero property loss. Raw vendor serializer baseline remains separately reproducible.
- [x] Admit strict insert/delete row/column operations for fixed-width rectangular sources; expose separate structure availability/reasons, dimension budgets, width policy and contiguous repeating-header handling.
- [x] Reject same-table mixed/second structural operations; invalidate old table/cell anchors and permit fresh revision cell editing. Validate actual output matrix/width/XML before emitting bytes; injected silent failure is rejected.
- [x] 44 distinct new backend checks, five affected regressions, expanded DOCX ASGI case and production-packed Node22 read-only/offline case passed. Details: `NATIVE_WORD_TABLE_ACCEPTANCE.md`. No full repository suite was repeated.
- [x] Capture bounded frontend table transactions against source coordinates, implement draft/Undo/replay and connect six Ribbon controls only for the inspectable safe subset (frontend checkpoint below).
- [ ] Desktop, native SQL combined with these new operations, full application image and deployed host acceptance remain open. Global Tasks 2–6 remain incomplete; flags off.


### Word table bounded frontend continuation

- [x] Connect six Table Layout controls through upstream PM commands and canonical source projection; preserve source coordinates even with duplicate text. Guard whole-table/multi-cell selections, locks, readonly sources, same-table dirty text, dimensions and minimum widths.
- [x] Persist/replay strict structure intentions with source hash validation; retain pending-cell identity safety and block mixed/second same-table operations until save/reopen. PM and NativeDraft Undo/Redo restore the same protocol.
- [x] Repair real-browser caret escape into an adjacent table and merged quick-action Undo groups. Keep table buttons stable during selection/transaction refresh.
- [x] 26 new frontend checks and 70 affected existing checks passed across focused selections. Chromium clicks all six controls, restores across reload, saves four independent structural operations, downloads and independently reads original paragraph XML/widths, then reopens revision 2. Exact evidence: `NATIVE_WORD_TABLE_ACCEPTANCE.md`.
- [ ] Broader same-table structural sequences, merged/complex source support, remaining source command groups, desktop checks, this combined flow against actual SQL/production grants and full application-image acceptance remain open. Global Tasks 2–6 remain incomplete; flags off.


### Parallel Tasks 2–5 and SQL delivery continuation (2026-11-06)

- [x] Task 2 bounded slice: whole anchored nonempty paragraph superscript/subscript/baseline with mixed-run/link preservation, strict source replay/history and explicit baseline overriding inherited file styles. 11 new frontend + 60 affected existing checks, 18 distinct backend cases and actual browser revisions 2/3/4 passed. Three affected baseline cases also pass with production-packed Node22 read-only/offline runtime. Details: `NATIVE_WORD_VERTICAL_ACCEPTANCE.md`. Caret/cell/new-paragraph and full inherited-style canvas parity remain open.
- [x] Task 3 bounded slice: six source text-rotation commands, exact OOXML↔Univer mapping, native history/replay and downloaded-file proof. Fixed the real reader bug that always dropped direct textRotation/indent; conservatively disable rotation for unmodeled inherited source styles. 14 new frontend + 26 affected existing checks, 13 reader/gate cases and actual Chromium/openpyxl revision-2 acceptance passed; adaptation SHA manifests verified. Details: `NATIVE_XLSX_ROTATION_ACCEPTANCE.md`.
- [x] Task 4 bounded slice: transition Apply to All expands source indices into strict existing operations, keeps per-slide auto-advance and one Undo/Redo step, validates full restored order and rejects unsafe source transition metadata. 13 new frontend + one affected button check, 20 actual-file cases and real Chromium save/download/XML/reopen passed. The original upstream formatter's metadata-loss probe is retained; the native single-page gap is closed by the preservation follow-up below. The bulk control still refuses these sources, including AlternateContent. Details: `NATIVE_PPTX_TRANSITION_ALL_ACCEPTANCE.md`.
- [x] Task 5 bounded slice: clockwise +90 for all surviving source pages, one draft action, 500-record budget, text-preview invalidation/lock/history/recovery guards. 18 distinct targeted checks passed across focused selections without summing reruns. Final production-static Chromium fixture passes strict console/page checks, PDF download/pypdf readback, fields/radio mapping/annotation/CropBox preservation and reopen. Details: `NATIVE_PDF_ROTATE_ALL_ACCEPTANCE.md`.
- [x] Word table SQL gap: actual four-table HTTP failure/retry/concurrent save/revision-3 chain; final dedicated case uses production SQL native, artifact bytes/chunks, download grants and editor grants/sessions. Independently verified bytes, SQL counters, revocation and scope. Disposable schema/container removed. Earlier generic fixture and memory-delivery scope are kept distinct. Details: `NATIVE_WORD_TABLE_SQL_ACCEPTANCE.md`.
- [x] Root integration: two affected existing Word-table/history regressions pass after Word changes; final standard/Slides builds, actual budget/contract, strict bridge typecheck, packaged runtimes, Ruff/diff and workbook SHA manifests pass. No complete frontend/repository test suite repeated.
- [x] Removed inactive/regenerable tool caches and superseded runtimes with explicit receipt; preserved current dependencies, Playwright revision referenced by installed tooling, all acceptance artifacts and existing user Docker volumes/containers.
- [ ] Tasks 2–5 still lack full source tabs/groups/controls/context parity. Remaining advanced objects, inherited rendering contexts, distributed/deployed tenant authorization and Office desktop acceptance are not closed by these slices.
- [ ] Task 6 full clean application image is still open: the earlier 8GB/vfs ENOSPC build failure is not replaced by mounted runtime or static preview evidence. The new all-SQL table fixture is in-process/synthetic scope, not production identity or deployed network proof. Feature flags remain off; do not merge or deploy.


### PPTX native single-page preservation follow-up (2026-11-06)

- [x] Replace native effect-only writeback with a thin preservation adapter retaining source speed, advance-click/time, p14 duration, sound/extensions, namespaces and related WAV bytes. Keep the pinned generator and dirty hook; vendor unchanged.
- [x] Inspect and UI/draft/backend gates refuse unsupported compatibility sources; pinned Morph branches retain individual metadata. Keep the separate conservative bulk gate.
- [x] 29 distinct new actual-file cases, 20 affected existing cases, four new frontend checks plus one affected check, strict types, browser history/reload/save/download/reopen and three production-packed Node22 readonly/offline checks pass. Both production builds and budget checks pass. Evidence: `NATIVE_PPTX_TRANSITION_PRESERVATION_ACCEPTANCE.md`.
- [ ] Arbitrary compatibility markup, playback/audio/desktop, remaining source command/context parity and full application image/deployed acceptance remain open. Tasks 2–6 remain incomplete; flags off.


### PDF current-page crop continuation (2026-11-06)

- [x] Connect source page.crop with display-relative margins, immutable source ID and unrotated bounds; use PDF.js transforms and pdf-lib CropBox primitive. Repeated crop/rotation/reorder/delete remain ordered; one draft history step, reload, no-op/budget/readonly/source guards. Canvas/text/overlays/thumbnails/fit share the cropped viewport.
- [x] Preserve MediaBox/content/UserUnit/forms/annotations; dialog explains hidden content remains and shows invalid input inside the modal. Old engines need an explicit crop capability. Vendor unchanged.
- [x] 27 distinct new file cases, 13 affected existing file cases, 18 new frontend checks and 18 affected inventory/operation checks pass across focused runs. Production-static Chromium four rotations/UserUnit2/save/download/reopen, one actual-engine ASGI crop combination and two Node22 readonly/offline cases pass. Final builds/budgets and 32-item local SHA audit pass; standalone bridge tsc retains identical baseline desktop-type diagnostics. Details: `NATIVE_PDF_CROP_ACCEPTANCE.md`.
- [ ] Crop-all/image handles, size, extraction/insertion/replacement, splitting/merging and Form Design remain open. This closes one bounded command, not Task 5 or deployment/desktop/full-image acceptance. Flags off.


### PDF crop-all source option closure (2026-11-06)

- [x] Connect the pinned CropDialog all-visible-pages checkbox as all surviving original IDs, preserving individual CropBoxes/rotations/UserUnit and earlier drafts. Prepare before one history commit; retain no-op/budget/error/cancel/source/readonly guards and prevent reopening during pending preparation.
- [x] Ten new frontend cases and 18 affected crop cases pass across focused runs; production-static Chromium mixed-size/mixed-direction/UserUnit1/2/3 batch, cancellation/forced reopen, actual download/pypdf and revision2 reopen pass, as do final builds/budget checks. Evidence: `NATIVE_PDF_CROP_ALL_ACCEPTANCE.md`. This supersedes the crop-all open item in the preceding checkpoint.
- [ ] Image drag handles, Page Size, extract/insert/replace, split/merge, Form Design, full source/context parity and desktop/deployed/full-image acceptance remain open. Backend and flags unchanged; Tasks 2–6 remain incomplete.
