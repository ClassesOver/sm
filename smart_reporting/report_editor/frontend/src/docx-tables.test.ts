import { afterEach, expect, it } from 'vitest'
import { Editor, Extension, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { Plugin } from '@tiptap/pm/state'
import { TableMap, selectedRect, addRowAfter, CellSelection } from '@tiptap/pm/tables'
import { NativeTableStructure, TABLE_ACTIONS, TABLE_KINDS, createDocxTableCommands, projectDocxTable } from './docx-tables'
import { docxOperations, replayDocxOperations, type DocxAnchor, type DocxPmNode } from './docx-operations'
import { createDocxRibbon } from './docx-ribbon'
import { NativeDraft } from './native-draft'
const defaults = (values: Record<string, unknown>) => Object.fromEntries(Object.entries(values).map(([key, value]) => [key, { default: value }]))
const Doc = Node.create({ name: 'doc', topNode: true, content: 'block+' })
const Paragraph = Node.create({ name: 'docParagraph', group: 'block', content: 'text*', addAttributes: () => defaults({ docxIndex: null }), renderHTML: () => ['p', 0] })
const Text = Node.create({ name: 'text', group: 'inline' })
const Table = Node.create({ name: 'docTable', group: 'block', content: 'docTableRow+', addAttributes: () => defaults({ docxIndex: null, colWidthsPct: null }), renderHTML: () => ['table', ['tbody', 0]] })
const Row = Node.create({ name: 'docTableRow', content: '(docTableCell|docTableHeader)+', addAttributes: () => defaults({ heightTwips: null, repeatHeader: false, rawTrPr: null }), renderHTML: () => ['tr', 0] })
const Cell = Node.create({ name: 'docTableCell', content: 'docParagraph+', addAttributes: () => defaults({ colspan: 1, rowspan: 1, colwidth: null, rawTcPr: null }), renderHTML: () => ['td', 0] })
const Header = Cell.extend({ name: 'docTableHeader', renderHTML: () => ['th', 0] })
const Roles = Extension.create({ name: 'testTableRoles', extendNodeSchema: extension => ({ tableRole: ({ docTable: 'table', docTableRow: 'row', docTableCell: 'cell', docTableHeader: 'header_cell' } as Record<string, string>)[extension.name] }) })
const editors: Editor[] = []
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })
function setup(followingTable = false) {
  let baseline: DocxPmNode, ready = false
  const errors: string[] = [], values = new Map<string, string>()
  const draft = new NativeDraft({ documentId: 'table-doc', revision: 1, sourceSha256: 'source', scope: { database: 'd', companyId: 'c', userId: 'u', threadId: 't' } }, { getItem: key => values.get(key) ?? null, setItem: (key, value) => { values.set(key, value) }, removeItem: key => { values.delete(key) } })
  const widths = [2401, 3000, 3599]
  const anchor: DocxAnchor = { docxIndex: 2, blockId: 'table', expectedObjectSha256: 'sha', editable: false, structureEditable: true, tableWidthsTwips: widths, tableHeaderCount: 1,
    cells: widths.map((_, r) => widths.map((_, c) => ({ cellId: `${r}:${c}`, expectedObjectSha256: `hash${r}:${c}`, editable: true }))) }
  const anchors: DocxAnchor[] = [{ docxIndex: 1, blockId: 'body', expectedObjectSha256: 'body-sha', editable: true }, anchor]
  const source = { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 1 }, content: [{ type: 'text', text: 'body' }] }, { type: 'docTable', attrs: { docxIndex: 2, colWidthsPct: widths.map(width => width / 90) },
    content: widths.map((_, r) => ({ type: 'docTableRow', attrs: { heightTwips: 300 + r, repeatHeader: r === 0, rawTrPr: `row${r}` }, content: widths.map((width, c) => ({ type: 'docTableCell', attrs: { colwidth: [Math.round(width / 15)], rawTcPr: `cell${r}:${c}` }, content: [{ type: 'docParagraph', content: [{ type: 'text', text: 'same' }] }] })) })) }] }
  if (followingTable) {
    const second = structuredClone(source.content[1]); second.attrs.docxIndex = 3
    source.content.push(second)
    anchors.push({ ...anchor, docxIndex: 3, blockId: 'second-table' })
  }
  const Guard = Extension.create({ name: 'testNativeGuard', addProseMirrorPlugins: () => [new Plugin({ filterTransaction(tr) { if (!ready || !tr.docChanged) return true; try { docxOperations(baseline, tr.doc.toJSON(), anchors, undefined, editor.schema); return true } catch (error) { errors.push(String(error)); return false } } })] })
  const editor = new Editor({ extensions: [Doc, Paragraph, Text, Table, Row, Cell, Header, Roles, NativeTableStructure, UndoRedo, Guard], content: source, editorProps: { handleScrollToSelection: () => true }, onUpdate: () => { if (ready) draft.setOperations(docxOperations(baseline, editor.getJSON(), anchors, undefined, editor.schema)) } })
  editors.push(editor); baseline = editor.getJSON(); ready = true
  const table = baseline.content![1]
  const commands = createDocxTableCommands(editor, baseline, anchors, error => errors.push(String(error)))
  const select = (row = 0, column = 0) => { const table = editor.state.doc.child(1), map = TableMap.get(table); editor.commands.setTextSelection(editor.state.doc.child(0).nodeSize + 1 + map.map[row * map.width + column] + 2) }
  return { editor, anchor, anchors, baseline, table, commands, select, errors, draft }
}
it.each(TABLE_KINDS.flatMap(kind => [0, 1, kind.startsWith('insert') ? 3 : 2].map(index => ({ kind, index }))))('projects and replays $kind at source index $index with duplicate texts', intent => {
  const f = setup(), projected = projectDocxTable(f.table, f.anchor, intent, f.editor.schema)
  const current = structuredClone(f.baseline); current.content![1] = projected
  const ops = docxOperations(f.baseline, current, f.anchors, undefined, f.editor.schema)
  expect(ops).toEqual([{ blockId: 'table', expectedObjectSha256: 'sha', ...intent }])
  expect(replayDocxOperations(f.baseline, ops, f.anchors, undefined, f.editor.schema)).toEqual(current)
  expect(f.table.content![0].content![0].attrs!.rawTcPr).toBe('cell0:0')
  const sourceCells = projected.content!.flatMap(row => row.content!).filter(cell => cell.attrs?.rawTcPr)
  expect(sourceCells.every(cell => cell.content![0].content![0].text === 'same')).toBe(true)
})
const restructure = (steps: { kind: string; index: number }[], texts?: { row: number; column: number; text: string }[]) =>
  ({ kind: 'restructureTable', blockId: 'table', expectedObjectSha256: 'sha', steps, ...(texts ? { texts } : {}) })
it('dispatches source commands, chains steps with typed text, supports real PM undo/redo and persisted draft replay', () => {
  const f = setup(); f.select(1, 1)
  expect(f.commands.reason('table-insert-column-before')).toBeNull()
  f.commands.run('table-insert-column-before')
  expect(f.draft.operations).toEqual([restructure([{ kind: 'insertTableColumn', index: 1 }])])
  // 新列空格子可直接输入；同表继续结构修改，文字随单元格迁移。
  f.editor.commands.insertContent('typed')
  expect(f.draft.operations).toEqual([restructure([{ kind: 'insertTableColumn', index: 1 }], [{ row: 1, column: 1, text: 'typed' }])])
  expect(f.commands.reason('table-insert-row-before')).toBeNull()
  f.select(0, 0); f.commands.run('table-insert-row-before')
  expect(f.draft.operations).toEqual([restructure([{ kind: 'insertTableColumn', index: 1 }, { kind: 'insertTableRow', index: 0 }], [{ row: 2, column: 1, text: 'typed' }])])
  const pending = f.editor.getJSON()
  // 格式与非文字修改仍被拒绝
  f.editor.commands.splitBlock()
  expect(f.editor.getJSON()).toEqual(pending)
  expect(f.editor.commands.undo()).toBe(true)
  expect(f.draft.operations).toEqual([restructure([{ kind: 'insertTableColumn', index: 1 }], [{ row: 1, column: 1, text: 'typed' }])])
  expect(f.editor.commands.redo()).toBe(true)
  expect(f.draft.operations[0].steps).toHaveLength(2)
  const restored = replayDocxOperations(f.baseline, f.draft.operations, f.anchors, undefined, f.editor.schema)
  expect(restored).toEqual(pending)
  let undone = 0
  while (f.draft.canUndo) { f.draft.undo(); undone++ }
  f.editor.commands.setContent(replayDocxOperations(f.baseline, f.draft.operations, f.anchors, undefined, f.editor.schema), { emitUpdate: false })
  expect(f.editor.getJSON()).toEqual(f.baseline)
  for (let i = 0; i < undone; i++) f.draft.redo()
  expect(replayDocxOperations(f.baseline, f.draft.operations, f.anchors, undefined, f.editor.schema)).toEqual(pending)
})
it('keeps raw upstream structure commands out of the save protocol and carries earlier text edits through structure', () => {
  const f = setup(); f.select(0, 0)
  addRowAfter(f.editor.state, f.editor.view.dispatch)
  expect(f.editor.getJSON()).toEqual(f.baseline)
  f.editor.commands.insertContent('text')
  expect(f.draft.operations[0].kind).toBe('replaceCellText')
  expect(f.commands.reason('table-insert-row-before')).toBeNull()
  f.commands.run('table-insert-row-before')
  expect(f.draft.operations).toEqual([restructure([{ kind: 'insertTableRow', index: 0 }], [{ row: 1, column: 0, text: 'textsame' }])])
  expect(replayDocxOperations(f.baseline, f.draft.operations, f.anchors, undefined, f.editor.schema)).toEqual(f.editor.getJSON())
})
it('exposes only six supported Ribbon controls and refreshes pending/read-only/selection/lock states', () => {
  const f = setup(); f.select()
  const ribbon = createDocxRibbon(f.editor, true, undefined, undefined, undefined, f.anchors, f.commands)
  document.body.append(ribbon)
  ribbon.querySelector<HTMLButtonElement>('[data-tab-id="tableLayout"]')!.click()
  const button = (action: string) => ribbon.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)!
  for (const action of Object.keys(TABLE_ACTIONS)) expect(button(action).disabled).toBe(false)
  expect(button('table-merge-cells').disabled).toBe(true)
  const stable = button('table-insert-row-before')
  f.editor.commands.setMeta('selection-refresh', true)
  expect(button('table-insert-row-before')).toBe(stable)
  stable.click()
  expect(button('table-delete-column').disabled).toBe(false)
  f.editor.commands.undo()
  expect(button('table-delete-column').disabled).toBe(false)
  f.editor.setEditable(false); f.editor.commands.setMeta('lock', true)
  expect(button('table-delete-column').disabled).toBe(true)
  f.editor.setEditable(true); f.anchor.structureEditable = false; f.anchor.structureReadOnlyReason = 'complex source'; f.editor.commands.setMeta('lock', false)
  expect(button('table-delete-column').title).toMatch(/complex source/)
})
it('rejects stale, forged, mixed and multiple source structural records without mutating the baseline', () => {
  const f = setup(), good = { kind: 'insertTableRow', blockId: 'table', expectedObjectSha256: 'sha', index: 1 }
  for (const op of [{ ...good, index: 4 }, { ...good, index: true }, { ...good, xml: '<w:tbl/>' }, { ...good, expectedObjectSha256: 'old' }]) expect(() => replayDocxOperations(f.baseline, [op], f.anchors, undefined, f.editor.schema)).toThrow()
  expect(() => replayDocxOperations(f.baseline, [good, good], f.anchors, undefined, f.editor.schema)).toThrow(/同表/)
  expect(() => replayDocxOperations(f.baseline, [good, { kind: 'replaceCellText', blockId: 'table', cellId: '0:0', text: 'x' }], f.anchors, undefined, f.editor.schema)).toThrow(/同表/)
  expect(f.editor.getJSON()).toEqual(f.baseline)
})
it('replays multi-step drafts and rejects forged steps or texts', () => {
  const f = setup(), op = restructure([{ kind: 'deleteTableColumn', index: 0 }, { kind: 'insertTableRow', index: 3 }], [{ row: 3, column: 1, text: '新' }])
  const restored = replayDocxOperations(f.baseline, [op], f.anchors, undefined, f.editor.schema)
  expect(restored.content![1].content!.map(row => row.content!.length)).toEqual([2, 2, 2, 2])
  expect(restored.content![1].content![3].content![1].content![0].content![0].text).toBe('新')
  expect(docxOperations(f.baseline, restored, f.anchors, undefined, f.editor.schema)).toEqual([op])
  for (const bad of [{ ...op, steps: [] }, { ...op, steps: [{ kind: 'mergeCells', index: 0 }] }, { ...op, texts: [{ row: 9, column: 0, text: 'x' }] }, { ...op, expectedObjectSha256: 'old' }, { ...op, xml: '<w:tbl/>' }])
    expect(() => replayDocxOperations(f.baseline, [bad], f.anchors, undefined, f.editor.schema)).toThrow()
  expect(() => replayDocxOperations(f.baseline, [op, op], f.anchors, undefined, f.editor.schema)).toThrow(/同表/)
})
it('rejects multi-cell selection and reflects the repeating-header and exact odd-width policy', () => {
  const f = setup(), projected = projectDocxTable(f.table, f.anchor, { kind: 'insertTableColumn', index: 0 }, f.editor.schema)
  ;(projected.attrs!.colWidthsPct as number[]).forEach((value, index) => expect(value).toBeCloseTo([1200, 1201, 3000, 3599][index] / 90, 10))
  const row = projectDocxTable(f.table, f.anchor, { kind: 'insertTableRow', index: 0 }, f.editor.schema)
  expect(row.content![0].attrs).toMatchObject({ repeatHeader: true, heightTwips: null })
  expect(row.content![0].content!.every(cell => !cell.content![0].content)).toBe(true)
  const table = f.editor.state.doc.child(1), map = TableMap.get(table), start = f.editor.state.doc.child(0).nodeSize + 1
  f.editor.view.dispatch(f.editor.state.tr.setSelection(new CellSelection(f.editor.state.doc.resolve(start + map.map[0]), f.editor.state.doc.resolve(start + map.map[1]))))
  expect(f.commands.reason('table-delete-column')).toMatch(/单个单元格/)
})

it('keeps the caret in the edited table when another table follows it', () => {
  const f = setup(true); f.select(1, 1)
  f.commands.run('table-insert-row-before')
  expect(selectedRect(f.editor.state).table.attrs.docxIndex).toBe(2)
  expect(f.commands.reason('table-delete-row')).toBeNull()
  expect(f.editor.getJSON().content![2]).toEqual(f.baseline.content![2])
  expect(f.draft.operations).toHaveLength(1)
})

it.each(Object.entries(TABLE_ACTIONS))('routes Ribbon %s using the selected source cell coordinate', (action, spec) => {
  const f = setup(true); f.select(1, 1)
  f.commands.run(action)
  expect(f.draft.operations).toEqual([restructure([{ kind: spec.kind, index: spec.after ? 2 : 1 }])])
  expect(selectedRect(f.editor.state).table.attrs.docxIndex).toBe(2)
})

it('undoes one structural action at a time across adjacent tables without waiting', () => {
  const f = setup(true); f.select(1, 1); f.commands.run('table-delete-row')
  const table = f.editor.state.doc.child(2), map = TableMap.get(table)
  const start = f.editor.state.doc.child(0).nodeSize + f.editor.state.doc.child(1).nodeSize + 1
  f.editor.commands.setTextSelection(start + map.map[4] + 2)
  f.commands.run('table-insert-column-before')
  const steps = () => f.draft.operations.map(op => [op.blockId, (op.steps as { kind: string }[]).map(step => step.kind)])
  expect(steps()).toEqual([['table', ['deleteTableRow']], ['second-table', ['insertTableColumn']]])
  f.editor.commands.undo()
  expect(steps()).toEqual([['table', ['deleteTableRow']]])
  expect(f.editor.getJSON().content![2]).toEqual(f.baseline.content![2])
  f.editor.commands.redo()
  expect(steps()).toEqual([['table', ['deleteTableRow']], ['second-table', ['insertTableColumn']]])
})
it('requires an actual single cell and checks final dimensions and minimum column widths', () => {
  const f = setup(), start = f.editor.state.doc.child(0).nodeSize
  f.editor.commands.setNodeSelection(start)
  expect(f.commands.reason('table-delete-row')).toMatch(/单个单元格/)
  const table = f.editor.state.doc.child(1), map = TableMap.get(table)
  f.editor.commands.setTextSelection({ from: start + map.map[0] + 3, to: start + map.map[1] + 3 })
  expect(f.commands.reason('table-delete-column')).toMatch(/单个单元格/)
  const single = structuredClone(f.table); single.content = single.content!.slice(0, 1)
  expect(() => projectDocxTable(single, { ...f.anchor, cells: f.anchor.cells!.slice(0, 1) }, { kind: 'deleteTableRow', index: 0 }, f.editor.schema)).toThrow(/最后一行/)
  expect(() => projectDocxTable(f.table, { ...f.anchor, tableWidthsTwips: [1, 3000, 5999] }, { kind: 'insertTableColumn', index: 0 }, f.editor.schema)).toThrow(/太小/)
})
