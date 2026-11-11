/** 固定网格列宽：可信来源几何与宽度校验，原XML只替换三类宽度属性值。 */
import type { Block } from '@genoffice/docx-engine'
import { XMLValidator } from 'fast-xml-parser'
import { splitXmlChildren } from '../packages/docx-engine/src/generate.ts'
import { applyTableColumnWidthSteps, Schema, type TableColumnWidthStep } from '../../../report_editor/frontend/src/docx-table-column-width-core.ts'
export interface ColumnWidthCell { top: number; left: number; bottom: number; right: number; physicalRow: number; physicalColumn: number }
interface Element { name: string; xml: string; start: number }
function fail(reason = 'unsupported'): never { throw new Error(`docx_table_column_width_${reason}`) }
function children(node: Element): Element[] {
  const opening = /^<[\w:.-]+\b[^>]*>/.exec(node.xml)?.[0]
  if (!opening) fail('xml_invalid')
  if (opening.endsWith('/>')) return []
  const end = node.xml.lastIndexOf('</')
  if (end < opening.length) fail('xml_invalid')
  const inner = node.xml.slice(opening.length, end), parts = splitXmlChildren(inner)
  if (inner.replace(/\s/g, '') !== parts.map(p => p.xml).join('').replace(/\s/g, '')) fail('xml_invalid')
  let cursor = opening.length
  return parts.map(part => { const at = node.xml.indexOf(part.xml, cursor); if (at < 0) fail('xml_invalid'); cursor = at + part.xml.length; return { name: part.name, xml: part.xml, start: node.start + at } })
}
function single(parts: Element[], name: string): Element {
  const matches = parts.filter(p => p.name === name)
  if (matches.length !== 1) fail('grid_unsupported')
  return matches[0]
}
function attribute(node: Element, key: string): { value: string; start: number; end: number } {
  const opening = /^<[\w:.-]+\b[^>]*>/.exec(node.xml)?.[0] ?? ''
  const matches = [...opening.matchAll(/([^\s=<>]+)\s*=\s*(["'])([\s\S]*?)\2/g)].filter(m => m[1] === key)
  if (matches.length !== 1) fail('width_unsupported')
  const m = matches[0], start = node.start + m.index! + m[0].indexOf(m[2]) + 1
  return { value: m[3], start, end: start + m[3].length }
}
/** 几何叶元素只接受明确属性和空内容；未知属性不能靠原样保留冒充已解释。 */
function geometryLeaf(node: Element, allowed: string[], required: string[] = allowed): void {
  const opening = /^<[\w:.-]+\b[^>]*>/.exec(node.xml)?.[0]
  if (!opening) fail('grid_unsupported')
  const body = opening.endsWith('/>') ? '' : node.xml.slice(opening.length, node.xml.lastIndexOf('</'))
  if (body.trim()) fail('grid_unsupported')
  const attributes = [...opening.matchAll(/([^\s=<>]+)\s*=\s*(["'])([\s\S]*?)\2/g)].map(match => match[1])
  if (attributes.some(key => !allowed.includes(key)) || new Set(attributes).size !== attributes.length || required.some(key => !attributes.includes(key))) fail('grid_unsupported')
}
function geometryContainer(node: Element): Element[] {
  const opening = /^<[\w:.-]+\b[^>]*>/.exec(node.xml)?.[0] ?? ''
  if (/\s[^\s=<>]+\s*=/.test(opening)) fail('grid_unsupported')
  return children(node)
}
function geometryProperties(parts: Element[], allowed: string[]): void {
  if (parts.some(part => !allowed.includes(part.name)) || new Set(parts.map(part => part.name)).size !== parts.length) fail('grid_unsupported')
  for (const part of parts) {
    const opening = /^<[\w:.-]+\b[^>]*>/.exec(part.xml)?.[0] ?? ''
    const body = opening.endsWith('/>') ? '' : part.xml.slice(opening.length, part.xml.lastIndexOf('</'))
    if (/<w:(?:tblW|tblLayout|tblGrid|gridCol|tcW|gridSpan|vMerge|hMerge|gridBefore|gridAfter|tblInd|tblCellSpacing|tcFitText)\b/.test(body)) fail('grid_unsupported')
  }
}
function integerWidth(node: Element): number {
  const value = attribute(node, 'w:w').value
  if (!/^\d+$/.test(value) || !Number.isSafeInteger(Number(value)) || Number(value) < 1 || Number(value) > 31680) fail('width_unsupported')
  return Number(value)
}
function sourceOf(block: Block, max: number) {
  const xml = block.originalXml
  if (block.type !== 'table' || !block.table || !xml || xml.length > 1024 * 1024 || !Number.isSafeInteger(max) || max < 1 || max > 31680) fail()
  // 仅允许已解析的常规Word命名空间结构；拒绝会另设有效网格/宽度的布局与修订。
  if (!/^<w:tbl(?:\s|>)/.test(xml) || /<!DOCTYPE|<!ENTITY|\sxmlns(?::\w+)?\s*=|<w:(?:hMerge|gridBefore|gridAfter|tblPrChange|tblGridChange|trPrChange|tcPrChange|cellMerge|tblpPr|bidiVisual|tblPrEx)\b/.test(xml) || XMLValidator.validate(xml) !== true) fail('grid_unsupported')
  const root: Element = { name: 'w:tbl', xml, start: 0 }, parts = children(root)
  if (parts.some(p => !['w:tblPr', 'w:tblGrid', 'w:tr'].includes(p.name))) fail('grid_unsupported')
  const pr = geometryContainer(single(parts, 'w:tblPr')), tableWidth = single(pr, 'w:tblW'), layout = single(pr, 'w:tblLayout')
  geometryProperties(pr, ['w:tblW', 'w:tblLayout', 'w:tblBorders', 'w:tblCellMar', 'w:tblStyle', 'w:tblLook', 'w:jc', 'w:shd', 'w:tblCaption', 'w:tblDescription'])
  geometryLeaf(tableWidth, ['w:w', 'w:type']); geometryLeaf(layout, ['w:type'])
  if (attribute(tableWidth, 'w:type').value !== 'dxa' || attribute(layout, 'w:type').value !== 'fixed') fail('width_unsupported')
  const columns = geometryContainer(single(parts, 'w:tblGrid'))
  if (!columns.length || columns.length > 30 || columns.some(c => c.name !== 'w:gridCol')) fail('size_unsupported')
  columns.forEach(column => geometryLeaf(column, ['w:w']))
  const widths = columns.map(integerWidth)
  if (integerWidth(tableWidth) !== widths.reduce((a, b) => a + b, 0)) fail('width_unsupported')
  const rows = parts.filter(p => p.name === 'w:tr')
  if (!rows.length || rows.length > 100 || rows.length * widths.length > 1000 || rows.length !== block.table.rows.length) fail('size_unsupported')
  const cells: ColumnWidthCell[] = [], physical: { cell: ColumnWidthCell; width: Element }[] = []
  let active = new Map<number, ColumnWidthCell>()
  rows.forEach((row, r) => {
    const rowParts = children(row)
    if (rowParts.some(p => !['w:trPr', 'w:tc'].includes(p.name)) || rowParts.filter(p => p.name === 'w:trPr').length > 1) fail('grid_unsupported')
    const rowProps = rowParts.find(part => part.name === 'w:trPr')
    if (rowProps) geometryProperties(geometryContainer(rowProps), ['w:trHeight', 'w:tblHeader', 'w:cantSplit', 'w:hidden'])
    const sourceCells = rowParts.filter(p => p.name === 'w:tc')
    if (sourceCells.length !== block.table!.rows[r].length) fail('grid_unsupported')
    const next = new Map<number, ColumnWidthCell>()
    let col = 0
    sourceCells.forEach((item, c) => {
      const content = children(item), props = geometryContainer(single(content, 'w:tcPr'))
      geometryProperties(props, ['w:tcW', 'w:gridSpan', 'w:vMerge', 'w:tcBorders', 'w:shd', 'w:vAlign', 'w:textDirection', 'w:tcMar', 'w:noWrap', 'w:hideMark'])
      if (content.some(p => !['w:tcPr', 'w:p', 'w:tbl', 'w:sdt'].includes(p.name))) fail('grid_unsupported')
      const spans = props.filter(p => p.name === 'w:gridSpan'), merges = props.filter(p => p.name === 'w:vMerge')
      if (spans.length > 1 || merges.length > 1) fail('grid_unsupported')
      spans.forEach(node => geometryLeaf(node, ['w:val']))
      merges.forEach(node => geometryLeaf(node, ['w:val'], []))
      const spanValue = spans.length ? attribute(spans[0], 'w:val').value : '1'
      const span = /^\d+$/.test(spanValue) ? Number(spanValue) : 0
      let merge: string | undefined
      if (merges.length) { const opening = merges[0].xml; merge = /\bw:val\s*=/.test(opening) ? attribute(merges[0], 'w:val').value : 'continue' }
      if (!Number.isSafeInteger(span) || span < 1 || col + span > widths.length || merge && !['restart', 'continue'].includes(merge)) fail('grid_unsupported')
      const w = single(props, 'w:tcW')
      geometryLeaf(w, ['w:w', 'w:type'])
      if (attribute(w, 'w:type').value !== 'dxa' || integerWidth(w) !== widths.slice(col, col + span).reduce((a, b) => a + b, 0)) fail('width_unsupported')
      const model = block.table!.rows[r][c]
      if ((model.colSpan ?? 1) !== span || model.vMerge !== merge || model.gridGap) fail('grid_unsupported')
      const cell: ColumnWidthCell = { top: r, left: col, bottom: r + 1, right: col + span, physicalRow: r, physicalColumn: c }
      if (merge === 'continue') {
        const owner = active.get(col)
        if (!owner || owner.right !== cell.right) fail('grid_unsupported')
        owner.bottom = r + 1; next.set(col, owner)
      } else { cells.push(cell); if (merge === 'restart') next.set(col, cell) }
      physical.push({ cell, width: w }); col += span
    })
    if (col !== widths.length) fail('grid_unsupported')
    active = next
  })
  return { xml, widths, cells, physical, columns, tableWidth }
}
export function tableColumnWidthAvailability(block: Block, maxWidthTwips: number) {
  try { const s = sourceOf(block, maxWidthTwips); return { columnWidthEditable: true, columnWidthReadOnlyReason: null, columnWidthsTwips: s.widths, columnWidthMaxTwips: maxWidthTwips, columnWidthCells: s.cells } }
  catch (error) { return { columnWidthEditable: false, columnWidthReadOnlyReason: error instanceof Error ? error.message : 'docx_table_column_width_unsupported', columnWidthsTwips: [] as number[], columnWidthMaxTwips: maxWidthTwips, columnWidthCells: [] as ColumnWidthCell[] } }
}
export function editTableColumnWidths(block: Block, maxWidthTwips: number, steps: readonly TableColumnWidthStep[]) {
  const s = sourceOf(block, maxWidthTwips)
  const schema = new Schema({ nodes: { doc: { content: 'docTable+' }, text: {}, docParagraph: {}, docTable: { content: 'docTableRow+', tableRole: 'table', attrs: { colWidthsPct: { default: null }, widthPx: { default: null }, widthPct: { default: null } } }, docTableRow: { content: 'docTableCell*', tableRole: 'row' }, docTableCell: { content: 'docParagraph+', tableRole: 'cell', attrs: { colspan: { default: 1 }, rowspan: { default: 1 }, colwidth: { default: null } } } } })
  const table = schema.node('docTable', null, block.table!.rows.map((_, r) => schema.node('docTableRow', null, s.cells.filter(c => c.top === r).map(c => schema.node('docTableCell', { colspan: c.right - c.left, rowspan: c.bottom - c.top }, schema.node('docParagraph'))))))
  const { widthsTwips } = applyTableColumnWidthSteps(table, s.widths, maxWidthTwips, steps)
  const patches = [...s.columns.map((node, c) => ({ ...attribute(node, 'w:w'), width: widthsTwips[c] })), { ...attribute(s.tableWidth, 'w:w'), width: widthsTwips.reduce((a, b) => a + b, 0) }, ...s.physical.map(({ cell, width }) => ({ ...attribute(width, 'w:w'), width: widthsTwips.slice(cell.left, cell.right).reduce((a, b) => a + b, 0) }))]
  let xml = s.xml
  for (const patch of patches.sort((a, b) => b.start - a.start)) xml = xml.slice(0, patch.start) + patch.width + xml.slice(patch.end)
  return { xml, widthsTwips, cells: s.cells, maxWidthTwips }
}
export function verifyTableColumnWidthResult(block: Block, result: ReturnType<typeof editTableColumnWidths>): void {
  const s = sourceOf(block, result.maxWidthTwips)
  if (block.originalXml !== result.xml || JSON.stringify(s.widths) !== JSON.stringify(result.widthsTwips) || JSON.stringify(s.cells) !== JSON.stringify(result.cells)) fail('write_not_applied')
}
