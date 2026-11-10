/** Fixed GenOffice f8c17004 table gallery keys/order/zh labels and tblPr flags.
 * Source: apps/slides/src/renderer/components/Ribbon.tsx TABLE_STYLE_PRESETS_UI,
 * renderer/i18n/ribbon/zh.ts, packages/pptx-engine/src/table-edit.ts.
 * Web uses a named select; it does not synthesize gallery-preview thumbnails.
 */
export const SLIDES_TABLE_PRESETS = [
  { name: 'none', label: '无样式', firstRow: false, bandRow: false },
  { name: 'lightGrid', label: '浅色网格', firstRow: false, bandRow: false },
  { name: 'zebraBlue', label: '斑马纹蓝', firstRow: true, bandRow: true },
  { name: 'zebraGray', label: '斑马纹灰', firstRow: true, bandRow: true },
  { name: 'headerDarkBlue', label: '表头深蓝', firstRow: true, bandRow: false },
  { name: 'headerOrange', label: '表头橙色', firstRow: true, bandRow: false },
  { name: 'noBorder', label: '无边框', firstRow: true, bandRow: true },
  { name: 'fullBorder', label: '全边框', firstRow: false, bandRow: false },
] as const
export type SlidesTablePresetName = (typeof SLIDES_TABLE_PRESETS)[number]['name']
export const SLIDES_TABLE_FLAG_FIELDS = ['firstRow', 'lastRow', 'firstCol', 'lastCol', 'bandRow', 'bandCol', 'rtl'] as const
export type SlidesTableFlags = Record<(typeof SLIDES_TABLE_FLAG_FIELDS)[number], boolean>
