/**
 * 表格样式写回请求的共享规格（桥接与前端共用，不依赖 Node/XML 库）：
 * 固定源 Ribbon.tsx TABLE_PRESETS 与 table-properties.ts TableLook / applyTablePreset 行取色规则。
 */
export interface DocxTableLook { firstRow: boolean; lastRow: boolean; firstColumn: boolean; lastColumn: boolean; bandedRows: boolean; bandedColumns: boolean }
export interface DocxTablePreset { headerFill: string | null; band1Fill: string | null; band2Fill: string | null; borderColor: string }
/** 固定源 Ribbon.tsx TABLE_PRESETS（顺序与取值一致）。 */
export const DOCX_TABLE_PRESETS: Record<'grid' | 'blueHeader' | 'blueBanded' | 'grayBanded' | 'greenHeader', DocxTablePreset> = {
  grid: { headerFill: null, band1Fill: null, band2Fill: null, borderColor: '808080' },
  blueHeader: { headerFill: 'D9EAF7', band1Fill: null, band2Fill: null, borderColor: '5B9BD5' },
  blueBanded: { headerFill: 'BDD7EE', band1Fill: 'DDEBF7', band2Fill: 'FFFFFF', borderColor: '9DC3E6' },
  grayBanded: { headerFill: 'D9E1F2', band1Fill: 'E7E6E6', band2Fill: 'FFFFFF', borderColor: 'A5A5A5' },
  greenHeader: { headerFill: 'E2F0D9', band1Fill: null, band2Fill: null, borderColor: '70AD47' },
}
export type DocxTablePresetName = keyof typeof DOCX_TABLE_PRESETS
export interface DocxTableStyleRequest { styleId?: string | null; look?: DocxTableLook; preset?: DocxTablePresetName }
export interface DocxTableStyleState { styleId: string | null; look: DocxTableLook; presetEditable: boolean }
export const DOCX_TABLE_LOOK_KEYS = ['firstRow', 'lastRow', 'firstColumn', 'lastColumn', 'bandedRows', 'bandedColumns'] as const
/** 固定源 table-properties.ts 未写 tblLook 时的默认值。 */
export const DOCX_DEFAULT_TABLE_LOOK: DocxTableLook = { firstRow: true, lastRow: false, firstColumn: true, lastColumn: false, bandedRows: true, bandedColumns: false }

function fail(reason: string): never { throw new Error(`docx_table_style_${reason}`) }
/** 固定源 applyTablePreset：首行 headerFill，其余行 rowIndex%2===0 → band2，否则 band1。 */
export const docxTablePresetRowFill = (preset: DocxTablePreset, row: number) => row === 0 ? preset.headerFill : row % 2 === 0 ? preset.band2Fill : preset.band1Fill

export function safeDocxTableLook(value: unknown): DocxTableLook {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).length !== DOCX_TABLE_LOOK_KEYS.length || DOCX_TABLE_LOOK_KEYS.some(key => typeof (value as Record<string, unknown>)[key] !== 'boolean')) fail('look_invalid')
  return Object.fromEntries(DOCX_TABLE_LOOK_KEYS.map(key => [key, (value as Record<string, boolean>)[key]])) as unknown as DocxTableLook
}

/** 请求形状校验：styleId 与 preset 互斥；styleId 必须是文档中已有的表格样式。 */
export function safeDocxTableStyleRequest(raw: unknown, tableStyles: ReadonlySet<string>): DocxTableStyleRequest {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw) || Object.keys(raw).some(key => !['styleId', 'look', 'preset'].includes(key)) || !Object.keys(raw).length) fail('request_invalid')
  const request = raw as Record<string, unknown>, result: DocxTableStyleRequest = {}
  if (request.preset !== undefined && request.styleId !== undefined) fail('request_invalid')
  if (request.preset !== undefined) {
    if (typeof request.preset !== 'string' || !Object.hasOwn(DOCX_TABLE_PRESETS, request.preset)) fail('preset_invalid')
    result.preset = request.preset as DocxTablePresetName
  }
  if (request.styleId !== undefined) {
    if (request.styleId !== null && (typeof request.styleId !== 'string' || !tableStyles.has(request.styleId))) fail('style_invalid')
    result.styleId = request.styleId as string | null
  }
  if (request.look !== undefined) result.look = safeDocxTableLook(request.look)
  return result
}
