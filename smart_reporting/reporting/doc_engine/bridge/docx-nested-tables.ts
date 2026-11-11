// 第一层嵌套表的来源注册表。路径来自原文件；客户端只提交签发的身份。
import { createHash } from 'node:crypto'
import type { Block, TableModel } from '@genoffice/docx-engine'
import { patchTableCellTexts, splitXmlChildren, type CellTextsPatch } from '../packages/docx-engine/src/generate.ts'
import { childrenOf, nameOf, textOf, xmlParser } from '../packages/docx-engine/src/xml-utils.ts'

const hash = (value: string) => createHash('sha256').update(value).digest('hex')
const fail = (code: string): never => { throw new Error(`docx_nested_${code}`) }
const same = (left: unknown, right: unknown) => JSON.stringify(left) === JSON.stringify(right)
function validParagraphs(value: unknown): value is string[] {
  return Array.isArray(value) && value.length > 0 && value.length <= 1000
    && value.every(item => typeof item === 'string' && item.length <= 20000 && !/[\x00-\x1f\u007f\ufffe\uffff]/.test(item))
    && value.reduce((sum, item) => sum + item.length, 0) <= 20000
}
type Child = { name: string; xml: string; start: number; end: number }
/** splitXmlChildren 不验证未建模的缝隙；这里要求每个字节都是直属子项或空白。 */
function children(xml: string, tag: string): Child[] {
  const opening = new RegExp(`^<${tag}(?:\\s[^>]*)?>`).exec(xml)?.[0]
  const closing = `</${tag}>`
  if (!opening || !xml.endsWith(closing)) return fail('source_unsupported')
  const inner = xml.slice(opening.length, -closing.length)
  let cursor = 0
  const result = splitXmlChildren(inner).map(child => {
    cursor += /^\s*/.exec(inner.slice(cursor))![0].length
    if (!inner.startsWith(child.xml, cursor)) return fail('source_unsupported')
    const start = opening.length + cursor
    cursor += child.xml.length
    return { ...child, start, end: opening.length + cursor }
  })
  if (inner.slice(cursor).trim()) return fail('source_unsupported')
  return result
}
function only(items: Child[], names: string[]) {
  if (items.some(child => !names.includes(child.name))) fail('source_unsupported')
  for (const name of names.filter(name => name.endsWith('Pr') || name === 'w:tblGrid')) {
    if (items.filter(child => child.name === name).length > 1) fail('source_unsupported')
  }
}
function grid(xml: string, model: TableModel): Child[][] {
  const items = children(xml, 'w:tbl')
  only(items, ['w:tblPr', 'w:tblGrid', 'w:tr'])
  if (items.some(child => child.name !== 'w:tr' && /<w:(?:tbl|tr|tc)\b/.test(child.xml))) fail('source_unsupported')
  const rows = items.filter(child => child.name === 'w:tr').map(row => {
    const items = children(row.xml, 'w:tr')
    only(items, ['w:trPr', 'w:tc'])
    if (items.some(child => child.name !== 'w:tc' && /<w:(?:tbl|tr|tc)\b/.test(child.xml))) fail('source_unsupported')
    return items.filter(child => child.name === 'w:tc').map(cell => ({ ...cell, start: row.start + cell.start, end: row.start + cell.end }))
  })
  if (rows.length !== model.rows.length || rows.some((row, r) => row.length !== model.rows[r]!.length)) fail('source_unsupported')
  return rows
}
function paragraphs(xml: string): string[] {
  return children(xml, 'w:tc').filter(child => child.name === 'w:p').map(child => {
    const node = xmlParser.parse(child.xml)[0]
    const parts: string[] = []
    for (const run of childrenOf(node)) {
      if (nameOf(run) !== 'w:r') continue
      for (const item of childrenOf(run)) {
        const name = nameOf(item)
        if (name === 'w:t') parts.push(textOf(item))
        else if (name === 'w:tab') parts.push('\t')
        else if (name === 'w:br' || name === 'w:cr') parts.push('\n')
      }
    }
    return parts.join('')
  })
}
export type NestedCellAnchor = { cellId: string; expectedObjectSha256: string; editable: boolean; paragraphs: string[]; readOnlyReason?: string }
export type NestedTableAnchor = { tableId: string; expectedObjectSha256: string; row: number; column: number; nestedOrdinal: number; cells: NestedCellAnchor[][] }
export type NestedTarget = { anchor: NestedCellAnchor; tableId: string; row: number; column: number; nestedOrdinal: number; nestedRow: number; nestedColumn: number }
export function inspectNestedTables(block: Block, sourceSha256: string, rootBlockId: string, editableCell: (xml: string) => boolean, protectedDocument = false) {
  const anchors: NestedTableAnchor[] = [], targets = new Map<string, NestedTarget>()
  if (block.type !== 'table' || !block.table || !block.originalXml) return { anchors, targets }
  try {
    // 包装、修订、合并可能改变 parser 的网格投影；第一版整个根保持只读。
    if (/<w:(?:sdt|ins|del|moveFrom|moveTo|vMerge|hMerge|gridSpan|gridBefore|gridAfter|trPrChange|tblPrChange|tcPrChange|cellIns|cellDel)\b/.test(block.originalXml)) return { anchors, targets }
    const rows = grid(block.originalXml, block.table)
    for (let r = 0; r < rows.length; r++) for (let c = 0; c < rows[r]!.length; c++) {
      const parent = rows[r]![c]!, model = block.table.rows[r]![c]!
      const items = children(parent.xml, 'w:tc')
      only(items, ['w:tcPr', 'w:p', 'w:tbl'])
      if (items.some(child => child.name !== 'w:tbl' && /<w:(?:tbl|tr|tc)\b/.test(child.xml))) fail('source_unsupported')
      const tables = items.filter(item => item.name === 'w:tbl')
      if (tables.length !== (model.nestedTables?.length ?? 0) || !same(paragraphs(parent.xml), model.paras)) fail('source_unsupported')
      const positions = items.flatMap((item, i) => item.name === 'w:tbl' ? [items.slice(0, i).filter(child => child.name === 'w:p').length] : [])
      if (tables.length && !same(positions, model.nestedTableAnchors)) fail('source_unsupported')
      tables.forEach((table, nestedOrdinal) => {
        const inner = model.nestedTables![nestedOrdinal]!
        const identity = `${sourceSha256}:${rootBlockId}:${block.docxIndex}:${r}:${c}:${nestedOrdinal}`
        const tableId = hash(`${identity}:nested-table`)
        let cells: Child[][] = []
        try { cells = grid(table.xml, inner) } catch { /* 来源不可逆时仍显示 model，所有叶格只读。 */ }
        const anchor: NestedTableAnchor = { tableId, expectedObjectSha256: hash(table.xml), row: r, column: c, nestedOrdinal,
          cells: inner.rows.map((row, nr) => row.map((cell, nc) => {
            const xml = cells[nr]?.[nc]?.xml
            const editable = !protectedDocument && validParagraphs(cell.paras) && !!xml && editableCell(xml) && same(paragraphs(xml), cell.paras)
            const anchor: NestedCellAnchor = { cellId: hash(`${identity}:nested-cell:${nr}:${nc}`), expectedObjectSha256: hash(xml ?? ''), editable, paragraphs: [...cell.paras],
              ...(!editable ? { readOnlyReason: 'docx_nested_cell_unsupported' } : {}) }
            targets.set(anchor.cellId, { anchor, tableId, row: r, column: c, nestedOrdinal, nestedRow: nr, nestedColumn: nc })
            return anchor
          })) }
        anchors.push(anchor)
      })
    }
  } catch { return { anchors: [] as NestedTableAnchor[], targets: new Map<string, NestedTarget>() } }
  return { anchors, targets }
}
export function validateNestedCellOperation(op: Record<string, unknown>, targets: Map<string, NestedTarget>) {
  const fields = ['kind', 'blockId', 'tableId', 'cellId', 'expectedObjectSha256', 'paragraphs']
  if (Object.keys(op).length !== fields.length || Object.keys(op).some(key => !fields.includes(key))) fail('operation_invalid')
  const target = typeof op.cellId === 'string' ? targets.get(op.cellId) : undefined
  if (!target || target.tableId !== op.tableId || target.anchor.expectedObjectSha256 !== op.expectedObjectSha256) fail('anchor_invalid')
  if (!target.anchor.editable) fail('cell_unsupported')
  if (!validParagraphs(op.paragraphs)) fail('text_invalid')
  return { target, paragraphs: op.paragraphs as string[] }
}
function locate(xml: string, target: NestedTarget) {
  const row = children(xml, 'w:tbl').filter(child => child.name === 'w:tr')[target.row]!
  const parent = children(row.xml, 'w:tr').filter(child => child.name === 'w:tc')[target.column]!
  const table = children(parent.xml, 'w:tc').filter(child => child.name === 'w:tbl')[target.nestedOrdinal]!
  const innerRow = children(table.xml, 'w:tbl').filter(child => child.name === 'w:tr')[target.nestedRow]!
  const leaf = children(innerRow.xml, 'w:tr').filter(child => child.name === 'w:tc')[target.nestedColumn]!
  return { xml: leaf.xml, start: row.start + parent.start + table.start + innerRow.start + leaf.start,
    end: row.start + parent.start + table.start + innerRow.start + leaf.end }
}
export function patchNestedCellText(xml: string, target: NestedTarget, values: string[], patcher = patchTableCellTexts): string {
  const before = locate(xml, target), original = paragraphs(before.xml)
  const patches = values.map((value, i) => value === original[i] ? null : value)
  const inner: (null | (null | (string | null)[])[])[] = []
  inner[target.nestedRow] = []
  inner[target.nestedRow]![target.nestedColumn] = patches
  const nested = Array.from({ length: target.nestedOrdinal + 1 }, () => null) as (typeof inner | null)[]
  nested[target.nestedOrdinal] = inner
  const outer: (CellTextsPatch[] | null)[] = []
  outer[target.row] = []
  outer[target.row]![target.column] = { nested }
  const result = patcher(xml, outer)
  const after = locate(result, target)
  if (!same(paragraphs(after.xml), values) || xml.slice(0, before.start) !== result.slice(0, after.start)
    || xml.slice(before.end) !== result.slice(after.end)) fail('write_not_applied')
  return result
}
export function verifyNestedCellModel(table: TableModel | undefined, target: NestedTarget, values: string[]) {
  if (!same(table?.rows[target.row]?.[target.column]?.nestedTables?.[target.nestedOrdinal]?.rows[target.nestedRow]?.[target.nestedColumn]?.paras, values)) fail('write_not_applied')
}
