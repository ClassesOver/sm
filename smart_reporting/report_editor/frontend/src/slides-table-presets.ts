/** Fixed GenOffice f8c17004 table gallery keys/order/zh labels and tblPr flags.
 * Source: apps/slides/src/renderer/components/Ribbon.tsx TABLE_STYLE_PRESETS_UI,
 * renderer/i18n/ribbon/zh.ts, packages/pptx-engine/src/table-edit.ts.
 */
export const SLIDES_TABLE_PRESETS = [
  { name: 'none', label: '无样式', english: 'No Style', firstRow: false, bandRow: false, preview: {} },
  { name: 'lightGrid', label: '浅色网格', english: 'Light Grid', firstRow: false, bandRow: false, preview: { gridLine: '#BFBFBF', outline: '#BFBFBF' } },
  { name: 'zebraBlue', label: '斑马纹蓝', english: 'Banded Blue', firstRow: true, bandRow: true, preview: { header: '#4472C4', band: '#D6E4F0', outline: '#C9D8EA' } },
  { name: 'zebraGray', label: '斑马纹灰', english: 'Banded Gray', firstRow: true, bandRow: true, preview: { header: '#595959', band: '#EDEDED', outline: '#D0D0D0' } },
  { name: 'headerDarkBlue', label: '表头深蓝', english: 'Dark Blue Header', firstRow: true, bandRow: false, preview: { header: '#1F3864', rowLine: '#D9D9D9', outline: '#D0D0D0' } },
  { name: 'headerOrange', label: '表头橙色', english: 'Orange Header', firstRow: true, bandRow: false, preview: { header: '#ED7D31', rowLine: '#D9D9D9', outline: '#D0D0D0' } },
  { name: 'noBorder', label: '无边框', english: 'No Borders', firstRow: true, bandRow: true, preview: { band: '#F2F2F2' } },
  { name: 'fullBorder', label: '全边框', english: 'All Borders', firstRow: false, bandRow: false, preview: { gridLine: '#595959', outline: '#595959' } },
] as const
export type SlidesTablePresetName = (typeof SLIDES_TABLE_PRESETS)[number]['name']
export const SLIDES_TABLE_FLAG_FIELDS = ['firstRow', 'lastRow', 'firstCol', 'lastCol', 'bandRow', 'bandCol', 'rtl'] as const
export type SlidesTableFlags = Record<(typeof SLIDES_TABLE_FLAG_FIELDS)[number], boolean>
