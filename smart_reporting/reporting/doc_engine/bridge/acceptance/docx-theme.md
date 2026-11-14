# Document theme acceptance

Source: GenOffice `f8c17004`, `apps/docs/src/renderer/ribbon-design-tab.tsx`, lines 28–198. Preset values are copied without changes into bridge and frontend `docx-theme-presets.ts`: **4** themes (Office, Facet, Ion, Retrospect), 6 font pairs, 6 color palettes. The initially described three-theme count does not match the pinned source.

Native operation: `setDocumentTheme`, `expectedThemeSha256`, optional `themePreset`, `fontPreset`, `colorPreset`. Values are fixed source `nameKey` identifiers. A theme supplies both components; independently selected font/color presets override that component. A subsequent complete theme selection clears prior component overrides. No caller-provided XML/font/color payload is accepted. The SHA binds the complete original theme part, and protected or missing/unsupported theme sources remain read-only. The outer bridge must verify the selected theme is the actual document relationship target before offering editing.

`inspectDocxTheme(xml, protectedSource)` provides the model. `validateDocxThemeOperations(ops, model)` supplies native `themeFonts` / `themeColors` save options. `assertDocxThemeWritten(savedThemeXml, options)` verifies every requested field independently after save. Tests use the real pinned engine, assert source `word/document.xml` remains byte-identical, and reject stale SHA, raw XML payload, and protected sources.

Frontend history: store `withDocxTheme` results through the existing document attribute / `commitDocxNativeOperations`; include the operation in native filters and restore validators. `effectiveDocxTheme` projects live preset values for the existing `docThemeCss`; recompute from document attributes on every transaction including undo/redo. A complete save/reparse resolves theme-referencing styles; direct body formatting must not be overwritten to simulate a theme. `DocxThemeControls` is the three-selector UI adapter.

Verification (2026-11-14): bridge isolated suite 2 passed; frontend isolated suite 3 passed; dedicated Python acceptance 2 passed, including default real python-docx theme inspection. Commands:

- `node --import tsx --test bridge/tests/docx-theme.test.ts` from doc_engine
- `npx vitest run src/docx-theme.test.ts` from frontend
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest smart_reporting/reporting/tests/test_docx_theme_native.py -q` from repository root

No repeated complete suites, budget changes, commits, or pushes were performed. Root owns end-to-end bridge/UI wiring and source manifest registration.
