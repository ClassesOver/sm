/** 固定源 f8c17004 editor/table-borders.ts；纯协议供浏览器与native桥接共用。 */
export const DOCX_CELL_BORDER_MODES = ['bottom', 'top', 'left', 'right', 'none', 'all', 'outer', 'inner', 'insideH', 'insideV', 'tl2br', 'tr2bl'] as const
export const DOCX_CELL_BORDER_STYLES = ['single', 'thick', 'double', 'triple', 'dotted', 'dashed', 'dotDash', 'dotDotDash'] as const
export const DOCX_CELL_BORDER_WIDTHS = [4, 8, 12, 18, 24] as const
export const DOCX_CELL_BORDER_SIDES = ['top', 'left', 'bottom', 'right', 'tl2br', 'tr2bl'] as const
export type DocxCellBorderMode = typeof DOCX_CELL_BORDER_MODES[number]
export type DocxCellBorderSide = typeof DOCX_CELL_BORDER_SIDES[number]
export interface DocxCellBorderLine { style: string; szEighths?: number; color?: string }
export interface DocxCellBorderPen extends DocxCellBorderLine { szEighths: number; color: string }
export interface DocxCellBorderStep { range: { fromCellId: string; toCellId: string } | null; mode: DocxCellBorderMode; pen: DocxCellBorderPen }
function fail(): never { throw new Error('docx_cell_borders_operation_invalid') }
function record(value: unknown, keys: string[]): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(key => !keys.includes(key))) fail()
  return value as Record<string, unknown>
}
export function safeDocxCellBorderSteps(value: unknown): DocxCellBorderStep[] {
  if (!Array.isArray(value) || !value.length) fail()
  return value.map(raw => {
    const step = record(raw, ['range', 'mode', 'pen']), pen = record(step.pen, ['style', 'szEighths', 'color'])
    if (!(DOCX_CELL_BORDER_MODES as readonly unknown[]).includes(step.mode) || !(DOCX_CELL_BORDER_STYLES as readonly unknown[]).includes(pen.style)
      || !(DOCX_CELL_BORDER_WIDTHS as readonly unknown[]).includes(pen.szEighths) || typeof pen.color !== 'string' || !/^[0-9a-fA-F]{6}$/.test(pen.color)) fail()
    let range: DocxCellBorderStep['range'] = null
    if (step.range !== null) {
      const ends = record(step.range, ['fromCellId', 'toCellId'])
      if (typeof ends.fromCellId !== 'string' || !ends.fromCellId || typeof ends.toCellId !== 'string' || !ends.toCellId) fail()
      range = { fromCellId: ends.fromCellId, toCellId: ends.toCellId }
    }
    return { range, mode: step.mode as DocxCellBorderMode, pen: { style: pen.style as string, szEighths: pen.szEighths as number, color: pen.color.toUpperCase() } }
  })
}
/** 源 sideLine：复合模式只改四边；none才同时清除斜线。 */
export function docxCellBorderSideLine(mode: DocxCellBorderMode, side: DocxCellBorderSide, edge: Record<'top' | 'bottom' | 'left' | 'right', boolean>, line: DocxCellBorderLine): DocxCellBorderLine | undefined {
  if (side === 'tl2br' || side === 'tr2bl') return mode === 'none' ? { style: 'none' } : mode === side ? line : undefined
  const horizontal = side === 'top' || side === 'bottom'
  switch (mode) {
    case 'all': return line
    case 'none': return { style: 'none' }
    case 'outer': return edge[side] ? line : undefined
    case 'inner': return edge[side] ? undefined : line
    case 'insideH': return horizontal && !edge[side] ? line : undefined
    case 'insideV': return !horizontal && !edge[side] ? line : undefined
    default: return mode === side && edge[side] ? line : undefined
  }
}
export function docxCellBorderRect(step: DocxCellBorderStep, cells: readonly (readonly { cellId: string }[])[]) {
  if (!cells.length || !cells[0]?.length || cells.some(row => row.length !== cells[0]!.length)) fail()
  const identities = new Set<string>()
  for (const row of cells) for (const cell of row) { if (!cell.cellId || identities.has(cell.cellId)) fail(); identities.add(cell.cellId) }
  if (step.range === null) return { top: 0, left: 0, bottom: cells.length, right: cells[0]!.length }
  const find = (id: string) => {
    for (let r = 0; r < cells.length; r++) for (let c = 0; c < cells[r]!.length; c++) if (cells[r]![c]!.cellId === id) return { r, c }
    fail()
  }
  const a = find(step.range.fromCellId), b = find(step.range.toCellId)
  return { top: Math.min(a.r, b.r), left: Math.min(a.c, b.c), bottom: Math.max(a.r, b.r) + 1, right: Math.max(a.c, b.c) + 1 }
}
