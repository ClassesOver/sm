# GenOffice Sheets desktop ribbon source

Upstream: https://github.com/genspark-ai/genoffice
Pinned commit: `f8c17004fb730df11f0f743164ffd8b4281bb38c`
License: Apache-2.0 (see LICENSE).

Unmodified source files:

- `styles.css`: `apps/sheets/src/renderer/styles.css`
- `ExcelShell.tsx.source`: `apps/sheets/src/renderer/ExcelShell.tsx`

`ribbon.css` directly extracts the contiguous `.ribbon-tabs` through
`.cover-select` section of styles.css, plus `.check-column` through
`button.check-item:hover`. It retains the upstream declarations and comments.
`ribbon.scoped.css` is mechanically generated from ribbon.css with PostCSS:
every selector is prefixed with `.workbook-ribbon`; declarations are unchanged.
No grid, canvas, dialog, model picker, backend or source application code runs.

The package's index.ts implements the source RibbonGroup DOM contract
(`section.ribbon-group[aria-label] > .ribbon-group-content`, no captions),
`.ribbon-rows > .inline-tools`, clipboard `.tool-stack`, and
`.ribbon-tool.large > .tool-icon-row`. It moves host elements without recreating
them, preserving selection handlers, command callbacks, menus, and permissions.
Additional host commands expand along two rows with horizontal scrolling.
Native input/select, mixed-format and permission state adaptations are isolated
in adapter.css. Host view menus retain their existing popover lifecycle.

The source is vendored as evidence and maintenance input; only the extracted,
scoped ribbon stylesheet is imported by the application.
