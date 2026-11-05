# GenOffice Slides Ribbon Sources

Upstream repository: `https://github.com/genspark-ai/genoffice`
Pinned commit: `f8c17004fb730df11f0f743164ffd8b4281bb38c`

`slide-size.ts` is copied unchanged from
`apps/slides/src/renderer/slide-size.ts`; its matching and preset-orientation
helpers drive Design's 16:9, 4:3, A4 and A3 choices. Both source and local hashes
are recorded in `SOURCE-SHA256.json`. Preset selection preserves orientation;
the orientation control only swaps the current dimensions. Custom source
sizes remain unchanged and explain why orientation requires an explicit preset
selection until custom-size writes are supported by the native schema.

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
A4 and A3. Only the strict supported dimensions can be saved. A source with
other dimensions keeps its original size and receives an unavailable reason
for orientation until an explicit standard preset is chosen. The imported
custom-unit/default-size helpers do not expose additional native commands;
custom size entry and new-presentation defaults remain unimplemented.
