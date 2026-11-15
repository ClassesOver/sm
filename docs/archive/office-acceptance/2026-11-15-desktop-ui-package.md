# Desktop appearance migration into a separate UI package

User scope: directly migrate GenOffice desktop appearance into a new package,
then gradually retire the previous UI. Remove the smart-report toolbar and keep
Office ribbons. User model selection remains unavailable.

Package: `frontend/packages/office-desktop-ui`, npm workspace
`@smart-reporting/office-desktop-ui`. Source revision:
`genspark-ai/genoffice@f8c17004fb730df11f0f743164ffd8b4281bb38c`.

The theme and four ribbon entries load separately. Original styles, license,
source hashes and selector adapters live with each entry. Host controllers
retain permissions, commands, file transport, saving and Agno tool execution.
Package boundary checks reject host/Electron imports in presentation helpers.

The first cutover covers shared theme and the Word, Excel, Slides and PDF
ribbons. Superseded Word/Excel ribbon overrides are removed. PDF/Slides keep
scoped compatibility resets while the old shared structural CSS is retired.
The old `office-ui-theme.css` entry is now a deprecated package import.

This is a staged migration, not a claim that every dialog is pixel-identical.
Native font/layout controls, additional protocol commands, specialized
existing galleries and parts of contextual dialogs remain adapters. PDF
conversion popup, quick access and compact/collapse controls are not yet moved.
Each app documents its exact remaining boundaries alongside source provenance.

Existing scoped baseline failures were independently reproduced before changing
assertions: three Word fake table fixtures lack valid table metadata; two Slides
expectations disagree with existing presenter/bitmap-icon behavior. They are
not counted as passing validation of this migration. Tests intentionally
changed here cover canonical source markup/group order and retain behavior
assertions.

Verification for the package cutover:

- 44 package/theme migration checks passed across scoped runs; the repaired
  explicit theme switch is checked for Word/PDF/Excel.
- Existing command, keyboard and protection tests were run by editor; the five
  reproduced baseline failures described above remain documented separately.
- TypeScript no-emit check and production Vite build passed after merging
  remote PR245 changes. Build asset budgets passed without raising thresholds.
- New UI runtime chunks are separated by app. PDF source SVG strings are
  generated ahead of time; the UI package does not run a React server renderer
  in the browser.
- Chromium PDF smoke passed against the final built assets, including source
  asset hashes, ribbon visibility, no model picker, real Agno read calls,
  page-two navigation, close/reopen follow behavior and unchanged source/draft.
  Evidence: `/workspace/scratch/pr245-desktop-isolated-browser/`.
- Chromium Sheets sweep checked nine ribbon tabs at 1280px: every band is 80px,
  controls remain visible, and horizontal overflow scrolls.
