/// Excel Insert Cells / Delete Cells with shift (本地新增，GenOffice f8c17004 的
/// `insert-delete-cells.ts` 走 Univer 整模型序列化，无引擎操作可移植).
///
/// The shift is a banded structural op: only the selected rows (horizontal
/// shift) or columns (vertical shift) move, so it reuses the structural
/// formula/notes machinery through `ShiftSpec.band`. Cells, same-sheet
/// formulas, other sheets' qualified formulas, defined names, chart series and
/// notes follow; merges shift when they lie wholly inside the band. Anything
/// this build cannot move cell-by-cell fails closed when it touches the
/// shifted region: tables, autoFilter, validations, conditional formats,
/// hyperlinks, drawings/OLE anchors, shared/array formula groups and merges
/// straddling the band — Excel refuses most of these too.

import { columnIndex, columnLabel, parseRange } from './cell-address'
import { shiftSheetNotes } from './notes'
import { sheetPartsOf } from './sheet-ops'
import {
  assertShiftable,
  shiftCellIndex,
  shiftChartSeriesReferences,
  shiftDefinedNames,
  shiftFormulaText,
  shiftIndex,
  StructuralShiftError,
  type ShiftSpec,
} from './structural'
import { decodeXmlText, escapeXmlText } from './xml'
import { assemblePackage, createBufferEntrySource, type MutationPlan } from './zip'

export type CellShiftDirection = 'right' | 'down' | 'left' | 'up'
export interface CellShift {
  /// A1 range of the inserted / deleted cells
  readonly range: string
  readonly shift: CellShiftDirection
}

const MAX_ROW = 1048575
const MAX_COLUMN = 16383

interface Area { readonly startRow: number; readonly endRow: number; readonly startColumn: number; readonly endColumn: number }

export function cellShiftSpec(area: Area, shift: CellShiftDirection): ShiftSpec {
  const horizontal = shift === 'right' || shift === 'left'
  const size = horizontal ? area.endColumn - area.startColumn + 1 : area.endRow - area.startRow + 1
  return horizontal
    ? { axis: 'column', start: area.startColumn, delta: shift === 'right' ? size : -size, band: { start: area.startRow, end: area.endRow } }
    : { axis: 'row', start: area.startRow, delta: shift === 'down' ? size : -size, band: { start: area.startColumn, end: area.endColumn } }
}

/// The cells a banded shift moves or deletes: the band × [start, ∞).
function affectedArea(spec: ShiftSpec): Area {
  const band = spec.band!
  return spec.axis === 'column'
    ? { startRow: band.start, endRow: band.end, startColumn: spec.start, endColumn: MAX_COLUMN }
    : { startRow: spec.start, endRow: MAX_ROW, startColumn: band.start, endColumn: band.end }
}

const intersects = (a: Area, b: Area) =>
  a.startRow <= b.endRow && b.startRow <= a.endRow && a.startColumn <= b.endColumn && b.startColumn <= a.endColumn

function areaOf(reference: string): Area | null {
  const token = reference.replace(/\$/g, '').trim()
  if (!token) return null
  try {
    const range = parseRange(token.includes(':') ? token : `${token}:${token}`)
    return { startRow: range.startRow, endRow: range.endRow, startColumn: range.startColumn, endColumn: range.endColumn }
  } catch { return null }
}

function refuse(reason: string): never {
  throw new StructuralShiftError(`插入/删除单元格已拒绝：${reason}。`)
}

/// Ranged features that would need cell-by-cell rewriting refuse when they
/// touch the shifted region; elsewhere they are untouched by the shift.
function assertRangedFeaturesClear(worksheetXml: string, region: Area): void {
  const checks: [RegExp, string][] = [
    [/<autoFilter\b[^>]*\bref="([^"]+)"/g, '筛选范围位于移位区域'],
    [/<dataValidation\b[^>]*\bsqref="([^"]+)"/g, '数据验证位于移位区域'],
    [/<conditionalFormatting\b[^>]*\bsqref="([^"]+)"/g, '条件格式位于移位区域'],
    [/<hyperlink\b[^>]*\bref="([^"]+)"/g, '超链接位于移位区域'],
    [/<(?:x14:)?sqref>([^<]+)<\/(?:x14:)?sqref>/g, '扩展条件格式/数据验证位于移位区域'],
  ]
  for (const [pattern, reason] of checks) {
    for (const match of worksheetXml.matchAll(pattern)) {
      for (const reference of match[1]!.split(/\s+/)) {
        const area = areaOf(reference)
        if (!area || intersects(area, region)) refuse(reason)
      }
    }
  }
  for (const match of worksheetXml.matchAll(/<f\b([^>]*)>/g)) {
    const attributes = match[1]!
    if (!/\bt="(?:shared|array)"/.test(attributes)) continue
    const reference = attributes.match(/\bref="([^"]+)"/)?.[1]
    if (!reference) continue
    const area = areaOf(reference)
    if (!area || intersects(area, region)) refuse('共享公式或数组公式位于移位区域')
  }
}

function assertAnchorsClear(xml: string, region: Area, reason: string): void {
  for (const match of xml.matchAll(/<((?:\w+:)?)from>([\s\S]*?)<\/\1from>(?:[\s\S]*?<\1to>([\s\S]*?)<\/\1to>)?/g)) {
    const marker = (inner: string | undefined) => {
      if (!inner) return null
      const column = inner.match(/<(?:\w+:)?col>([0-9]+)</)?.[1]
      const row = inner.match(/<(?:\w+:)?row>([0-9]+)</)?.[1]
      return column === undefined || row === undefined ? null : { row: Number(row), column: Number(column) }
    }
    const from = marker(match[2]), to = marker(match[3]) ?? from
    if (!from || !to) continue
    if (intersects({ startRow: from.row, endRow: to.row, startColumn: from.column, endColumn: to.column }, region)) refuse(reason)
  }
}

/// Merges wholly inside the band shift; merges clear of the moved cells stay;
/// a merge the shift would split, or one straddling the band, refuses.
function shiftBandedMerges(worksheetXml: string, spec: ShiftSpec): string {
  const band = spec.band!
  return worksheetXml.replace(/<mergeCell\b[^>]*\bref="([^"]+)"[^>]*\/>/g, (full, reference: string) => {
    const area = areaOf(reference)
    if (!area) refuse('合并单元格引用无法解析')
    const [crossStart, crossEnd, axisStart, axisEnd] = spec.axis === 'column'
      ? [area.startRow, area.endRow, area.startColumn, area.endColumn]
      : [area.startColumn, area.endColumn, area.startRow, area.endRow]
    if (axisEnd < spec.start || crossEnd < band.start || crossStart > band.end) return full
    if (crossStart < band.start || crossEnd > band.end) refuse('合并单元格跨越移位区域边界')
    if (spec.delta > 0) {
      if (axisStart < spec.start) refuse('插入位置位于合并单元格内部')
    } else {
      const deletedEnd = spec.start - spec.delta - 1
      if (axisStart >= spec.start && axisEnd <= deletedEnd) return ''
      if (axisStart <= deletedEnd) refuse('删除范围会拆分合并单元格')
    }
    const first = shiftIndex(axisStart, spec)!, last = shiftIndex(axisEnd, spec)!
    const [startRow, endRow, startColumn, endColumn] = spec.axis === 'column'
      ? [area.startRow, area.endRow, first, last] : [first, last, area.startColumn, area.endColumn]
    return `<mergeCell ref="${columnLabel(startColumn)}${startRow + 1}:${columnLabel(endColumn)}${endRow + 1}"/>`
  })
}

const CELL_RE = /<c\b[^>]*?(?:\/>|>[\s\S]*?<\/c>)/g
const ROW_RE = /<row\b[^>]*?(?:\/>|>[\s\S]*?<\/row>)/g

/// Moves cell records inside the band; row elements (heights, row styles)
/// stay where they are, as in Excel.
function moveBandedCells(worksheetXml: string, spec: ShiftSpec): string {
  const match = worksheetXml.match(/([\s\S]*?<sheetData\b[^>]*>)([\s\S]*?)(<\/sheetData>[\s\S]*)/)
  if (!match) throw new StructuralShiftError('Worksheet has no sheetData element.')
  const rowOpen = new Map<number, string>()
  const cells = new Map<number, { column: number; xml: string }[]>()
  const touched = new Set<number>()
  for (const rowMatch of match[2]!.matchAll(ROW_RE)) {
    const rowXml = rowMatch[0]
    const row = Number(rowXml.match(/\br="([0-9]+)"/)?.[1] ?? '0') - 1
    if (row < 0) refuse('存在缺少行号的行记录')
    rowOpen.set(row, rowXml.match(/^<row\b[^>]*?(?=\/?>)/)![0])
    const inner = rowXml.match(/^<row\b[^>]*>([\s\S]*?)<\/row>$/)?.[1] ?? ''
    for (const cellMatch of inner.matchAll(CELL_RE)) {
      const cellXml = cellMatch[0]
      const address = cellXml.match(/\br="([A-Z]{1,3})([0-9]+)"/)
      if (!address) refuse('存在缺少地址的单元格记录')
      const column = columnIndex(address[1]!)
      const next = shiftCellIndex(row, column, spec)
      if (next === null) { touched.add(row); continue }
      if (next.row > MAX_ROW || next.column > MAX_COLUMN) {
        if (/<(?:v|f|is)\b/.test(cellXml)) refuse('移位会把非空单元格推出工作表边界')
        touched.add(row); continue
      }
      if (next.row !== row || next.column !== column) { touched.add(row); touched.add(next.row) }
      const moved = next.row === row && next.column === column ? cellXml
        : cellXml.replace(/\br="[A-Z]{1,3}[0-9]+"/, `r="${columnLabel(next.column)}${next.row + 1}"`)
      const list = cells.get(next.row) ?? []
      list.push({ column: next.column, xml: moved })
      cells.set(next.row, list)
    }
  }
  const rows = [...new Set([...rowOpen.keys(), ...cells.keys()])].sort((a, b) => a - b)
  const rebuilt = rows.map(row => {
    let open = rowOpen.get(row) ?? `<row r="${row + 1}"`
    // spans is an optimisation hint; drop it where the cell set changed.
    if (touched.has(row)) open = open.replace(/\s+spans="[^"]*"/, '')
    const list = (cells.get(row) ?? []).sort((a, b) => a.column - b.column)
    return list.length ? `${open}>${list.map(cell => cell.xml).join('')}</row>` : `${open}/>`
  })
  return `${match[1]}${rebuilt.join('')}${match[3]}`
}

function recomputeDimension(worksheetXml: string): string {
  if (!/<dimension\b/.test(worksheetXml)) return worksheetXml
  let minRow = Infinity, maxRow = -1, minColumn = Infinity, maxColumn = -1
  for (const match of worksheetXml.matchAll(/<c\b[^>]*?\br="([A-Z]{1,3})([0-9]+)"/g)) {
    const row = Number(match[2]) - 1, column = columnIndex(match[1]!)
    minRow = Math.min(minRow, row); maxRow = Math.max(maxRow, row)
    minColumn = Math.min(minColumn, column); maxColumn = Math.max(maxColumn, column)
  }
  if (maxRow < 0) return worksheetXml
  const first = `${columnLabel(minColumn)}${minRow + 1}`, last = `${columnLabel(maxColumn)}${maxRow + 1}`
  return worksheetXml.replace(/(<dimension\b[^>]*\bref=")[^"]*(")/, `$1${first === last ? first : `${first}:${last}`}$2`)
}

/// Shared-formula masters carry text their children reinterpret relatively;
/// a shift that rewrites one would silently re-target the whole group.
function shiftFormulasRefusingShared(partXml: string, rewrite: (formula: string) => string): string {
  return partXml.replace(/<f\b([^>]*[^/>])?>([\s\S]*?)<\/f>/g, (full, attributes: string | undefined, body: string) => {
    const before = decodeXmlText(body)
    const after = rewrite(before)
    if (after === before) return full
    if (/\bt="shared"/.test(attributes ?? '')) refuse('共享公式引用了移位区域')
    return `<f${attributes ?? ''}>${escapeXmlText(after)}</f>`
  })
}

/// Apply one Insert/Delete Cells shift to a sheet and the parts referencing it.
export async function applyCellShift(sourceBytes: Uint8Array, sheetName: string, change: CellShift): Promise<Uint8Array> {
  if (!['right', 'down', 'left', 'up'].includes(change.shift)) refuse('移位方向无效')
  const area = areaOf(change.range)
  if (!area || change.range.includes('!')) refuse('单元格范围无效')
  const spec = cellShiftSpec(area, change.shift)
  const region = affectedArea(spec)
  const source = await createBufferEntrySource(sourceBytes)
  const workbookXml = await source.readText('xl/workbook.xml')
  const parts = await sheetPartsOf(source, workbookXml)
  const target = parts.find(part => part.name === sheetName)
  if (!target) throw new Error(`workbook.xml 中找不到工作表 "${sheetName}"。`)
  const targetXml = await source.readText(target.path)
  assertShiftable(targetXml)
  if (/<tablePart\b/.test(targetXml)) {
    for (const tablePath of await relatedPaths(source, targetXml, target.path, 'tablePart')) {
      const reference = (await source.readText(tablePath)).match(/<table\b[^>]*\bref="([^"]+)"/)?.[1]
      const tableArea = reference ? areaOf(reference) : null
      if (!tableArea || intersects(tableArea, region)) refuse('表格位于移位区域')
    }
  }
  assertRangedFeaturesClear(targetXml, region)
  if (/<oleObjects\b|<controls\b/.test(targetXml)) assertAnchorsClear(targetXml, region, '嵌入对象或控件位于移位区域')
  for (const drawingPath of await relatedPaths(source, targetXml, target.path, 'drawing')) {
    assertAnchorsClear(await source.readText(drawingPath), region, '图表、图片或形状锚定在移位区域')
  }

  let xml = targetXml.replace(/<sheetData\b([^>]*)\/>/, '<sheetData$1></sheetData>')
  xml = moveBandedCells(xml, spec)
  xml = shiftFormulasRefusingShared(xml, formula => shiftFormulaText(formula, spec, true, sheetName))
  xml = shiftBandedMerges(xml, spec)
  xml = recomputeDimension(xml)

  const replaced = new Map<string, string>([[target.path, xml]])
  const touchedEntries = [target.path]
  const notePlan = await shiftSheetNotes(source, target.path, [spec], xml)
  for (const [path, content] of notePlan.replaced) replaced.set(path, content)
  touchedEntries.push(...notePlan.touchedEntries)
  // VML form controls behind <legacyDrawing> (not notes) cannot follow a band.
  for (const vmlPath of await relatedPaths(source, targetXml, target.path, 'legacyDrawing')) {
    if (notePlan.removedEntries.includes(vmlPath)) continue
    const vml = replaced.get(vmlPath) ?? await source.readText(vmlPath)
    for (const anchor of vml.matchAll(/<x:ClientData\b(?![^>]*ObjectType="Note")[\s\S]*?<x:Anchor>([^<]+)<\/x:Anchor>/g)) {
      const [column, , row, , column2, , row2] = anchor[1]!.split(',').map(value => Number(value.trim()))
      if (intersects({ startRow: row!, endRow: row2!, startColumn: column!, endColumn: column2! }, region)) refuse('表单控件位于移位区域')
    }
  }

  for (const part of parts) {
    if (part.name === sheetName) continue
    const otherXml = await source.readText(part.path)
    const shifted = shiftFormulasRefusingShared(otherXml, formula => shiftFormulaText(formula, spec, false, sheetName))
    if (shifted !== otherXml) { replaced.set(part.path, shifted); touchedEntries.push(part.path) }
  }
  for (const path of (await source.paths()).filter(path => /^xl\/charts\/chart[0-9]+\.xml$/.test(path)).sort()) {
    const chartXml = await source.readText(path)
    const shifted = shiftChartSeriesReferences(chartXml, spec, sheetName)
    if (shifted !== chartXml) { replaced.set(path, shifted); touchedEntries.push(path) }
  }
  const nextWorkbookXml = shiftDefinedNames(workbookXml, spec, sheetName)
  if (nextWorkbookXml !== workbookXml) { replaced.set('xl/workbook.xml', nextWorkbookXml); touchedEntries.push('xl/workbook.xml') }

  const plan: MutationPlan = { replaced, added: new Map(), addedBinary: new Map(), removedEntries: notePlan.removedEntries, addedEntries: [], touchedEntries }
  return (await assemblePackage(sourceBytes, plan)).buffer
}

async function relatedPaths(
  source: Awaited<ReturnType<typeof createBufferEntrySource>>,
  worksheetXml: string,
  worksheetPath: string,
  elementTag: 'drawing' | 'tablePart' | 'legacyDrawing',
): Promise<string[]> {
  const ids = [...worksheetXml.matchAll(new RegExp(`<${elementTag}\\b[^>]*\\br:id="([^"]+)"`, 'g'))].map(match => match[1]!)
  if (!ids.length) return []
  const relsPath = worksheetPath.replace(/([^/]+)$/, '_rels/$1.rels')
  if (!(await source.has(relsPath))) return []
  const rels = await source.readText(relsPath)
  const paths: string[] = []
  for (const id of ids) {
    const target = rels.match(new RegExp(`<Relationship\\b[^>]*\\bId="${id}"[^>]*/>`))?.[0].match(/\bTarget="([^"]+)"/)?.[1]
    if (!target) continue
    const resolved = new URL(target, 'http://pkg/xl/worksheets/').pathname.replace(/^\//, '')
    if ((await source.has(resolved)) && !paths.includes(resolved)) paths.push(resolved)
  }
  return paths
}
