# Office desktop UI

Private frontend workspace package: `@smart-reporting/office-desktop-ui`.

The package owns presentation migrated from GenOffice desktop, pinned to
`f8c17004fb730df11f0f743164ffd8b4281bb38c`. Each app keeps its source provenance,
original styles and scoped browser adapter together. Document content styles
are separate from interface theme tokens.

Entries: `theme.css`, `docs.css`, `sheets.css`, `slides.css`, `pdf.css`.
PDF, sheets and slides also expose presentation helpers through matching
TypeScript entries. Entries load independently; opening PDF must not import
Word, sheets or slides UI.

Host applications retain file transport, authentication, capability checks,
editing controllers, saving and Agno tool execution. This package must not import
host `src` modules or Electron. Model selection is not exposed.

Migration policy:

1. Migrate desktop appearance into this package with source attribution.
2. Switch one existing editor at a time through a small compatibility adapter.
3. Remove superseded UI overrides after that editor's behavior and appearance
   are verified. Existing document styles and business code remain until their
   replacements are verified independently.

`frontend/src/office-ui-theme.css` is a deprecated compatibility import. New UI
imports this package directly. The retired smart-report toolbar is not part of
this package; native Office ribbons remain the editing interface.
