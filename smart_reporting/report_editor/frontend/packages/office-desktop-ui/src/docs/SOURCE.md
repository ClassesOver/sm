# Word desktop UI

Source: [genspark-ai/genoffice](https://github.com/genspark-ai/genoffice/tree/f8c17004fb730df11f0f743164ffd8b4281bb38c), revision `f8c17004fb730df11f0f743164ffd8b4281bb38c`.

`ribbon.css` directly migrates `apps/docs/src/renderer/styles.css`, from the `ribbon` section through the end of Layout paragraph controls (original lines 434–2454). All declarations retain their original values. PostCSS scopes selectors under `.docx-native .docx-ribbon`; the original `.ribbon` selector targets that root. The `html.genoffice-popover-open` ancestor remains outside the scope so it can match the actual browser document. Only referenced Docs chrome tokens from original lines 1–96 are included, with the matching explicit and system dark theme token overrides from the same source. The package uses shared GenOffice UI chrome tokens supplied by its consumer.

`adapter.css` handles browser React mount wrappers, horizontal tab access, and native review controls that have no desktop JSX counterpart. It does not replace source button, tab, ribbon band, or gallery styling. Existing command handlers and DOCX persistence remain with the application. Existing contextual controls still depend on the legacy scoped stylesheet for contextual ribbon rules outside this extracted section; those can migrate into this package incrementally.

No document canvas, paper, pagination, editor, or backend styles are imported. The application's older vendor stylesheet remains temporarily for those separate content concerns.

Upstream license and attribution are preserved in `LICENSE.genoffice` and `NOTICE.genoffice`. `src/docx-desktop.test.ts` compares the principal packaged controls against the pinned original declarations.
