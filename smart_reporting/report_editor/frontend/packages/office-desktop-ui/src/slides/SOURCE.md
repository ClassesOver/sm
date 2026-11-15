# GenOffice Slides desktop ribbon migration

Source: https://github.com/genspark-ai/genoffice/tree/f8c17004fb730df11f0f743164ffd8b4281bb38c
License: Apache-2.0 (included in LICENSE). Source identity and copied line ranges are recorded in SOURCE.json.

`ribbon.source.css` contains unchanged CSS bytes from `apps/slides/src/renderer/styles.css`, ranges 438–1208 (desktop ribbon), 4566–4669 (font controls), and 4691–4710 (paragraph flyout). `ribbon.scoped.css` changes only selectors to scope them below the host ribbon and outrank the legacy host stylesheet. Regenerate using `node packages/office-desktop-ui/src/slides/scope-source.cjs` from the frontend workspace. It uses the workspace's PostCSS installation. Original React markup is retained for review in `Ribbon.tsx.source`, `RibbonHomeTab.tsx.source`, and `ribbon-shared.tsx.source`.

`index.ts` adopts the source Group/group-items/group-label hierarchy, big-button icon/label wrappers, Clipboard compact column, Slides rows, and Font two-row column. The host uses the source collapsed Paragraph pattern and preserves existing popover lifecycle. Source selectors retain their original declaration values, including the fixed 80px ribbon band, tab typography/underline, group spacing, button sizes, and icon hover plates.

`host-reset.css` neutralizes legacy three-row host rules before source styles apply. `host-adapter.css` is the explicit compatibility seam for existing native inputs, assistive labels, host gallery buttons and overflow. Host-owned business commands, model calls, lock state and persistence remain in `src/slides-native-ribbon.ts`; this package introduces no backend capability or model selector.

Fidelity limits: this migrates the desktop ribbon presentation, not Electron window controls or the complete upstream application. Native font/layout controls remain native inputs/selects rather than upstream React comboboxes. Additional supported host slide commands remain available in a compact extra column. Existing chart/table/animation galleries and specialized menus continue to use host controllers and their existing presentation beyond the copied desktop ribbon primitives. The AI entry uses the existing authorized host entry. No claim of a pixel-identical complete Slides application is made.
