# GenOffice Slides Ribbon Sources

Upstream repository: `https://github.com/genspark-ai/genoffice`
Pinned commit: `f8c17004fb730df11f0f743164ffd8b4281bb38c`

`slide-size.ts` is copied unchanged from
`apps/slides/src/renderer/slide-size.ts`; its matching and preset-orientation
helpers drive Design's 16:9, 4:3, A4 and A3 choices. Both source and local hashes
are recorded in `SOURCE-SHA256.json`. Preset selection preserves orientation;
the orientation control only swaps the current dimensions. Custom source
sizes within the native schema's 1–56 inch bounds can also swap orientation
without replacing their dimensions with a preset.

`components/icons.tsx` is adapted from
`apps/slides/src/renderer/components/icons.tsx` (upstream SHA-256
`191d76ff69a597f140b4841b232f51ee4409c408fd24b0ad9e0aaf2c8c984975`). Its
only external type import (`AnimEffectKind` from the desktop app's shared IPC
types) was replaced with the same string union locally. All icon definitions
and SVG paths are retained unchanged; the React UI imports this browser-safe,
self-contained module for native Ribbon SVG glyphs. SHA-256 of the adapted file
is recorded in `components/SOURCE-SHA256.json`.

The Home Clipboard group in `slides-native-ribbon.ts` follows the pinned
`Ribbon.tsx` source order and callbacks: `onPaste`, `onCut`, `onCopy`, and
`onFormatBrushClick`. It uses the source `IconPaste`, `IconCut`, `IconCopy`,
and `IconFormatPainter` glyphs. Since those callbacks require GenOffice's
desktop clipboard bridge or format-painter selection state, all four controls
carry their source callback identity and remain disabled in the browser editor.
The English and Simplified Chinese labels in
`components/ribbon-home-clipboard-locales.ts` are adapted from the pinned
`apps/slides/src/renderer/i18n/ribbon/en.ts` and `zh.ts` entries; hashes for the
source Ribbon and locale files are recorded in `components/SOURCE-SHA256.json`.

The upstream application license and notice are retained in
`smart_reporting/reporting/slides_engine/LICENSE` and `NOTICE`.

2026-11-06: `slide-size.ts` is copied byte-for-byte from the same fixed
commit's `apps/slides/src/renderer/slide-size.ts`; root `SOURCE-SHA256.json`
records its upstream and local SHA-256. The native Design controls reuse
`SLIDE_SIZE_PRESETS`, `presetSize` and orientation helpers for 16:9, 4:3,
A4 and A3. This historical preset-only checkpoint is superseded by the custom-size
follow-up below. The unchanged imported conversion helpers now drive custom
size entry; new-presentation defaults still have no creation consumer.

2026-11-05 PR #190 continuation: the Web adapter now reuses the unchanged
`lengthToEmu`/`emuToLength` helpers for a custom-size dialog (cm/mm/in).
Both native API and bridge validate integer EMU coordinates in the ECMA-376
1–56 inch range. Draft history and restore use the existing slideSize operation.
New-presentation defaults remain explicitly disabled because this host has no
blank-presentation creation path. This supersedes the earlier preset-only
writeback limitation; the pinned upstream files and hashes are unchanged.

The follow-up also aligns source identities with fixed `Ribbon.tsx`: custom
size calls `onCustomSlideSize`, whereas the disabled new-deck default action
directly invokes the upstream local helper `saveDefaultNewSlideSize`. Preset
state uses the source matching helper without an aspect-ratio fallback.

2026-11-09: `components/shape-gallery-data.ts` adapts the pinned `packages/ui/src/shape-gallery.tsx`
`SHAPE_GALLERY_GROUPS` (7 groups, 109 presets, unchanged order) with Simplified Chinese labels from
`packages/i18n/src/common-ribbon.ts` (`ribbonCommonZh`) and `apps/slides/src/renderer/i18n/ribbon/zh.ts`.
Only the data is taken; the React previews depend on the renderer's preset geometry. Insert ▸ Shapes
uses it with the pinned insert defaults (`default-shape.ts` factory fill `#C43E1C`; line presets get a
1pt black stroke per `insert-actions.ts`). Hashes are in `components/SOURCE-SHA256.json`.

2026-11-10: `components/chart-gallery-data.ts` adapts the pinned `apps/slides/src/renderer/insert-presets.ts`
`CHART_GALLERY` and `chartSampleData` (13 kinds, unchanged order and sample values) with Simplified Chinese
strings substituted for the i18n keys. Insert ▸ Chart uses it with the pinned frame
(`insert-defaults.ts` `graphicFrameInsertFrame`: 2/3 slide width, 3:2, centred) and `barH` → `bar` +
`barDir: 'bar'` as in the pinned main process. Hashes are in `components/SOURCE-SHA256.json`.

2026-11-10: `components/smartart-gallery-data.ts` adapts the same pinned `insert-presets.ts` `SMARTART_GALLERY`
(7 layouts, unchanged order and default items) with Simplified Chinese strings; inserted with the same
`graphicFrameInsertFrame` placement through the pinned engine's `addSmartArt` (1–8 nodes).
