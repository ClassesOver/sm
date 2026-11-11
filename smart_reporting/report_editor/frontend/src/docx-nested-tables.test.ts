import { describe, expect, it } from 'vitest'
import { docxOperations, replayDocxOperations, type DocxAnchor, type DocxPmNode } from './docx-operations'
import { getDocxNestedTableTargets } from './docx-nested-tables'

function fixture() {
  const model = { rows: [[{ paras: ['a', 'b'], richParas: [{ runs: [{ text: 'a' }] }], fill: 'FFFFFF' }, { paras: ['same'] }]], widths: [100, 100] }
  const original: DocxPmNode = { type: 'doc', content: [{ type: 'docTable', attrs: { docxIndex: 0 }, content: [{ type: 'docTableRow', content: [{ type: 'docTableCell', content: [{ type: 'docParagraph', content: [{ type: 'text', text: 'before' }] }, ...[0, 1].map(() => ({ type: 'docNestedTable', attrs: { model: structuredClone(model) } })), { type: 'docParagraph' }] }] }] }] }
  const anchor: DocxAnchor = { docxIndex: 0, blockId: 'root', expectedObjectSha256: 'root-hash', editable: false, cells: [[{ cellId: 'parent', expectedObjectSha256: 'parent-hash', editable: false }]], nestedTables: [0, 1].map(nestedOrdinal => ({ tableId: `table-${nestedOrdinal}`, expectedObjectSha256: 'table-hash', row: 0, column: 0, nestedOrdinal, cells: [model.rows[0].map((cell, column) => ({ cellId: `cell-${nestedOrdinal}-${column}`, expectedObjectSha256: `hash-${nestedOrdinal}-${column}`, editable: true, paragraphs: [...cell.paras] }))] })) }
  const current = structuredClone(original)
  const cell = (doc: DocxPmNode, ordinal = 1, column = 0) => (doc.content![0]!.content![0]!.content![0]!.content![ordinal + 1]!.attrs!.model as typeof model).rows[0][column]!
  const edit = (ordinal = 1, column = 0, paragraphs = ['changed', '', '中文😀$&']) => { const target = cell(current, ordinal, column); target.paras = paragraphs; delete (target as { richParas?: unknown }).richParas }
  const operation = (ordinal = 1, column = 0, paragraphs = ['changed', '', '中文😀$&']) => ({ kind: 'replaceNestedCellText', blockId: 'root', tableId: `table-${ordinal}`, cellId: `cell-${ordinal}-${column}`, expectedObjectSha256: `hash-${ordinal}-${column}`, paragraphs })
  return { original, current, anchor, cell, edit, operation }
}
describe('一层嵌套简单单元格的纯 diff/replay', () => {
  it('按父cell中的原子节点序号映射同胞，未修改时无操作', () => {
    const f = fixture()
    const targets = getDocxNestedTableTargets(f.original.content![0]!, f.anchor)
    expect(targets.map(target => target.anchor.tableId)).toEqual(['table-0', 'table-1'])
    expect(targets[1]!.node).toBe(f.original.content![0]!.content![0]!.content![0]!.content![2])
    expect(docxOperations(f.original, f.current, [f.anchor])).toEqual([])
  })
  it('只读不可靠cell允许空hash和空段落清单，但不授予编辑能力', () => {
    const f = fixture(), cell = f.anchor.nestedTables![1]!.cells[0]![0]!
    Object.assign(cell, { editable: false, expectedObjectSha256: '', paragraphs: [] })
    f.cell(f.original).paras = []
    expect(getDocxNestedTableTargets(f.original.content![0]!, f.anchor)).toHaveLength(2)
    expect(() => replayDocxOperations(f.original, [f.operation()], [f.anchor])).toThrow()
  })
  it.each(['path', 'table-id', 'cell-id', 'dimension', 'deep'])('拒绝失效或重复清单映射：%s', kind => {
    const f = fixture(), tables = f.anchor.nestedTables!
    if (kind === 'path') tables[1]!.nestedOrdinal = 0
    if (kind === 'table-id') tables[1]!.tableId = tables[0]!.tableId
    if (kind === 'cell-id') tables[1]!.cells[0]![0]!.cellId = tables[0]!.cells[0]![0]!.cellId
    if (kind === 'dimension') tables[1]!.cells[0]!.pop()
    if (kind === 'deep') Object.assign(f.cell(f.original), { nestedTables: [{ rows: [] }] })
    expect(() => getDocxNestedTableTargets(f.original.content![0]!, f.anchor)).toThrow()
  })
  it('只修改第二张相同表，回放完整模型并保留空段及其余属性', () => {
    const f = fixture(); f.edit()
    expect(docxOperations(f.original, f.current, [f.anchor])).toEqual([f.operation()])
    expect(replayDocxOperations(f.original, [f.operation()], [f.anchor])).toEqual(f.current)
    expect(f.cell(f.original).richParas).toBeDefined()
  })
  it('同根不同目标可组合，段落数组不能用join判断相同', () => {
    const f = fixture(); f.edit(1, 0, ['a', 'b', '']); f.edit(0, 1)
    const ops = docxOperations(f.original, f.current, [f.anchor])
    expect(ops).toEqual([f.operation(0, 1), f.operation(1, 0, ['a', 'b', ''])])
    expect(replayDocxOperations(f.original, ops, [f.anchor])).toEqual(f.current)
  })
  it.each(['a\nb', 'a\rb', 'a\tb'])('拒绝无法无损回读的段内字符：%j', text => {
    const f = fixture(); f.edit(1, 0, [text])
    expect(() => docxOperations(f.original, f.current, [f.anchor])).toThrow()
    expect(() => replayDocxOperations(f.original, [f.operation(1, 0, [text])], [f.anchor])).toThrow()
  })
  it.each(['ancestor', 'format', 'rich', 'readonly', 'unsigned', 'stale'])('拒绝额外变化或失效来源：%s', kind => {
    const f = fixture(); f.edit()
    if (kind === 'ancestor') f.current.content![0]!.attrs!.width = 999
    if (kind === 'format') f.cell(f.current).fill = '000000'
    if (kind === 'rich') f.cell(f.current).richParas = []
    if (kind === 'readonly') f.anchor.nestedTables![1]!.cells[0]![0]!.editable = false
    if (kind === 'unsigned') f.anchor.nestedTables = []
    if (kind === 'stale') f.anchor.nestedTables![1]!.cells[0]![0]!.paragraphs = ['old source']
    expect(() => docxOperations(f.original, f.current, [f.anchor])).toThrow()
  })
  it.each(['duplicate', 'hash', 'table', 'cell', 'block', 'field', 'paragraphs', 'mixed', 'stale'])('草稿拒绝篡改、重复及同根混批：%s', kind => {
    const f = fixture(); const op: Record<string, unknown> = f.operation(); const ops = [op] as ReturnType<typeof docxOperations>
    if (kind === 'duplicate') ops.push({ ...op } as typeof ops[number])
    if (kind === 'hash') op.expectedObjectSha256 = 'foreign'
    if (kind === 'table') op.tableId = 'table-0'
    if (kind === 'cell') op.cellId = 'foreign'
    if (kind === 'block') op.blockId = 'foreign'
    if (kind === 'field') op.row = 0
    if (kind === 'paragraphs') op.paragraphs = ['text', 1]
    if (kind === 'mixed') ops.push({ kind: 'setTableRepeatHeaders', blockId: 'root' })
    if (kind === 'stale') f.anchor.nestedTables![1]!.cells[0]![0]!.paragraphs = ['stale']
    expect(() => replayDocxOperations(f.original, ops, [f.anchor])).toThrow()
  })
})
