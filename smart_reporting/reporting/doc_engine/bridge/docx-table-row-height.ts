/** 来源行高只补直属trHeight；不移动格/段落或重建table XML。 */
import type { Block } from '@genoffice/docx-engine'
import { XMLValidator } from 'fast-xml-parser'
import { splitXmlChildren } from '../packages/docx-engine/src/generate.ts'
import { applyTableRowHeightSteps, Schema, type TableRowHeightStep } from '../../../report_editor/frontend/src/docx-table-row-height-core.ts'
interface Element { name: string; xml: string; start: number }
export interface RowHeightCell { top: number; left: number; bottom: number; right: number; physicalRow: number; physicalColumn: number }
function fail(): never { throw new Error('docx_table_row_height_unsupported') }
function children(node: Element): Element[] {
  const open = /^<[\w:.-]+\b[^>]*>/.exec(node.xml)?.[0]
  if (!open) fail()
  if (open.endsWith('/>')) return []
  const inner = node.xml.slice(open.length, node.xml.lastIndexOf('</')), parts = splitXmlChildren(inner)
  if (inner.replace(/\s/g, '') !== parts.map(p => p.xml).join('').replace(/\s/g, '')) fail()
  let cursor = open.length
  return parts.map(p => { const at = node.xml.indexOf(p.xml, cursor); cursor = at + p.xml.length; return { ...p, start: node.start + at } })
}
function attr(node: Element, key: string) {
  const open = /^<[\w:.-]+\b[^>]*>/.exec(node.xml)?.[0] ?? ''
  const m = [...open.matchAll(/([^\s=<>]+)\s*=\s*(["'])([\s\S]*?)\2/g)].filter(a => a[1] === key)
  if (m.length > 1) fail()
  if (!m.length) return undefined
  const start = node.start + m[0].index! + m[0][0].indexOf(m[0][2]) + 1
  return { value: m[0][3], start, end: start + m[0][3].length }
}
function leaf(node: Element, fields: string[], required: string[] = fields) {
  const open = /^<[\w:.-]+\b[^>]*>/.exec(node.xml)?.[0] ?? ''
  const attrs = [...open.matchAll(/([^\s=<>]+)\s*=\s*(["'])([\s\S]*?)\2/g)].map(m => m[1])
  if (attrs.some(a => !fields.includes(a)) || new Set(attrs).size !== attrs.length || required.some(a => !attrs.includes(a)) || !open.endsWith('/>') && node.xml.slice(open.length, node.xml.lastIndexOf('</')).trim()) fail()
}
function one(parts: Element[], name: string, required = true) { const matches = parts.filter(p => p.name === name); if (matches.length > 1 || required && !matches.length) fail(); return matches[0] }
function sourceOf(block: Block, max: number) {
  const xml = block.originalXml
  if (block.type !== 'table' || !block.table || !xml || xml.length > 1024 * 1024 || !Number.isSafeInteger(max) || max < 1 || max > 31680 || XMLValidator.validate(xml) !== true || !/^<w:tbl(?:\s|>)/.test(xml) || /<!DOCTYPE|<!ENTITY|\sxmlns(?::\w+)?\s*=|<w:(?:hMerge|gridBefore|gridAfter|trPrChange|tblPrChange|tblGridChange|tcPrChange|cellMerge|tblPrEx)\b/.test(xml)) fail()
  const root: Element = { name: 'w:tbl', xml, start: 0 }, parts = children(root)
  if (parts.some(p => !['w:tblPr', 'w:tblGrid', 'w:tr'].includes(p.name))) fail()
  one(parts, 'w:tblPr', false)
  const grid = children(one(parts, 'w:tblGrid')!)
  if (!grid.length || grid.length > 30 || grid.some(p => p.name !== 'w:gridCol')) fail()
  grid.forEach(p => { leaf(p, ['w:w']); const w = attr(p, 'w:w')!.value; if (!/^\d+$/.test(w) || Number(w) < 1 || Number(w) > 31680) fail() })
  const rows = parts.filter(p => p.name === 'w:tr')
  if (!rows.length || rows.length > 100 || rows.length * grid.length > 1000 || block.table.rows.length !== rows.length) fail()
  const heights: (number | null)[] = [], rules: ('exact' | 'atLeast' | null)[] = [], cells: RowHeightCell[] = []
  const rowInfo: { row: Element; props?: Element; height?: Element }[] = []
  let active = new Map<number, RowHeightCell>()
  rows.forEach((row, r) => {
    const parts = children(row)
    if (parts.some(p => !['w:trPr', 'w:tc'].includes(p.name))) fail()
    const props = one(parts, 'w:trPr', false), propParts = props ? children(props) : []
    if (props && /\s[^\s=<>]+\s*=/.test(/^<[\w:.-]+\b[^>]*>/.exec(props.xml)?.[0] ?? '')) fail()
    // 不解释未知行几何或修订；段落及格内容不在此白名单中，仍原样保留。
    if (propParts.some(p => !['w:trHeight', 'w:cantSplit', 'w:tblHeader', 'w:hidden'].includes(p.name)) || new Set(propParts.map(p => p.name)).size !== propParts.length) fail()
    const height = one(propParts, 'w:trHeight', false)
    let h: number | null = null, rule: 'exact' | 'atLeast' | null = null
    if (height) {
      leaf(height, ['w:val', 'w:hRule'], ['w:val'])
      const raw = attr(height, 'w:val')!.value, declared = attr(height, 'w:hRule')?.value
      if (!/^\d+$/.test(raw) || Number(raw) < 0 || Number(raw) > 31680 || declared !== undefined && !['exact', 'atLeast', 'auto'].includes(declared)) fail()
      h = Number(raw) > 0 ? Number(raw) : null; rule = h === null ? null : declared === 'exact' ? 'exact' : 'atLeast'
    }
    for (const prop of propParts.filter(p => p !== height)) if (/<w:trHeight\b/.test(prop.xml)) fail()
    heights.push(h); rules.push(rule); rowInfo.push({ row, props, height })
    const sourceCells = parts.filter(p => p.name === 'w:tc'), next = new Map<number, RowHeightCell>()
    if (!sourceCells.length || sourceCells.length !== block.table!.rows[r].length) fail()
    let col = 0
    sourceCells.forEach((cell, c) => {
      const content = children(cell), tcPr = one(content, 'w:tcPr', false), tcProps = tcPr ? children(tcPr) : []
      if (content.some(p => !['w:tcPr', 'w:p', 'w:tbl', 'w:sdt'].includes(p.name))) fail()
      const spanEl = one(tcProps, 'w:gridSpan', false), mergeEl = one(tcProps, 'w:vMerge', false)
      if (spanEl) leaf(spanEl, ['w:val']); if (mergeEl) leaf(mergeEl, ['w:val'], [])
      const rawSpan = spanEl ? attr(spanEl, 'w:val')!.value : '1', span = /^\d+$/.test(rawSpan) ? Number(rawSpan) : 0, merge = mergeEl ? attr(mergeEl, 'w:val')?.value ?? 'continue' : undefined
      if (!Number.isSafeInteger(span) || span < 1 || col + span > grid.length || merge && !['restart', 'continue'].includes(merge)) fail()
      const model = block.table!.rows[r][c]
      if ((model.colSpan ?? 1) !== span || model.vMerge !== merge || model.gridGap) fail()
      const record: RowHeightCell = { top: r, left: col, bottom: r + 1, right: col + span, physicalRow: r, physicalColumn: c }
      if (merge === 'continue') { const owner = active.get(col); if (!owner || owner.right !== record.right) fail(); owner.bottom = r + 1; next.set(col, owner) }
      else { cells.push(record); if (merge === 'restart') next.set(col, record) }
      col += span
    })
    if (col !== grid.length) fail()
    active = next
  })
  return { xml, cells, heights, rules, rowInfo }
}
export function tableRowHeightAvailability(block: Block, maxHeightTwips: number) {
  try { const s = sourceOf(block, maxHeightTwips); return { rowHeightEditable: true, rowHeightReadOnlyReason: null, rowHeightMaxTwips: maxHeightTwips, rowHeightsTwips: s.heights, rowHeightRules: s.rules, rowHeightCells: s.cells } }
  catch (error) { return { rowHeightEditable: false, rowHeightReadOnlyReason: error instanceof Error ? error.message : 'docx_table_row_height_unsupported', rowHeightMaxTwips: maxHeightTwips, rowHeightsTwips: [] as (number | null)[], rowHeightRules: [] as ('exact' | 'atLeast' | null)[], rowHeightCells: [] as RowHeightCell[] } }
}
export function editTableRowHeights(block: Block, maxHeightTwips: number, steps: readonly TableRowHeightStep[]) {
  const s = sourceOf(block, maxHeightTwips)
  const schema = new Schema({ nodes: { doc: { content: 'table' }, text: {}, p: {}, table: { content: 'row+', tableRole: 'table' }, row: { content: 'cell*', tableRole: 'row', attrs: { heightTwips: { default: null }, heightRule: { default: null } } }, cell: { content: 'p', tableRole: 'cell', attrs: { colspan: { default: 1 }, rowspan: { default: 1 } } } } })
  const table = schema.node('table', null, s.heights.map((h, r) => schema.node('row', { heightTwips: h, heightRule: s.rules[r] }, s.cells.filter(c => c.top === r).map(c => schema.node('cell', { colspan: c.right - c.left, rowspan: c.bottom - c.top }, schema.node('p'))))))
  const result = applyTableRowHeightSteps(table, maxHeightTwips, steps)
  // 顺序在XML上回放，保留set前clear带来的rule重置，也保留未清除height的原始属性字节。
  const replacements: { start: number; end: number; value: string }[] = []
  s.rowInfo.forEach((info, r) => {
    const relevant = steps.filter(step => step.top <= r && r < step.bottom)
    if (!relevant.length) return
    let heightXml = info.height?.xml ?? ''
    for (const step of relevant) {
      if (step.heightTwips === null) { heightXml = ''; continue }
      const value = 'kind' in step && step.kind === 'distributeTableRows' ? step.heightTwips : Math.min(step.heightTwips, maxHeightTwips)
      if (heightXml) {
        const node = { name: 'w:trHeight', xml: heightXml, start: 0 }, field = attr(node, 'w:val')!
        const requiresRule = Number(field.value) === 0 || attr(node, 'w:hRule')?.value === 'auto' || 'kind' in step && step.kind === 'distributeTableRows' && attr(node, 'w:hRule')?.value === 'exact'
        heightXml = heightXml.slice(0, field.start) + value + heightXml.slice(field.end)
        if (requiresRule) {
          const ruleField = attr({ ...node, xml: heightXml }, 'w:hRule')
          if (ruleField) heightXml = heightXml.slice(0, ruleField.start) + 'atLeast' + heightXml.slice(ruleField.end)
          else { const at = heightXml.indexOf('>') - (heightXml[heightXml.indexOf('>') - 1] === '/' ? 1 : 0); heightXml = heightXml.slice(0, at) + ' w:hRule="atLeast"' + heightXml.slice(at) }
        }
      }
      else { heightXml = `<w:trHeight w:val="${value}" w:hRule="atLeast"/>` }
    }
    if (info.height) replacements.push({ start: info.height.start, end: info.height.start + info.height.xml.length, value: heightXml })
    else if (heightXml) {
      if (!info.props) { const at = info.row.start + info.row.xml.indexOf('>') + 1; replacements.push({ start: at, end: at, value: `<w:trPr>${heightXml}</w:trPr>` }) }
      else if (info.props.xml.endsWith('/>')) replacements.push({ start: info.props.start + info.props.xml.length - 2, end: info.props.start + info.props.xml.length, value: `>${heightXml}</w:trPr>` })
      else { const props = children(info.props), next = props.find(p => ['w:tblHeader', 'w:hidden'].includes(p.name)), at = next?.start ?? info.props.start + info.props.xml.lastIndexOf('</'); replacements.push({ start: at, end: at, value: heightXml }) }
    }
  })
  let xml = s.xml
  for (const edit of replacements.sort((a, b) => b.start - a.start)) xml = xml.slice(0, edit.start) + edit.value + xml.slice(edit.end)
  return { xml, rowHeightsTwips: result.rowHeightsTwips, rowHeightRules: result.rowHeightRules, cells: s.cells, maxHeightTwips }
}
export function verifyTableRowHeightResult(block: Block, result: ReturnType<typeof editTableRowHeights>) {
  const s = sourceOf(block, result.maxHeightTwips)
  if (block.originalXml !== result.xml || JSON.stringify(s.heights) !== JSON.stringify(result.rowHeightsTwips) || JSON.stringify(s.rules) !== JSON.stringify(result.rowHeightRules) || JSON.stringify(s.cells) !== JSON.stringify(result.cells)) fail()
}
