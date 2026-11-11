import { afterEach, expect, it } from 'vitest'
import { Editor, Extension, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { Plugin, NodeSelection } from '@tiptap/pm/state'
import { TableMap, selectedRect, addRowAfter, CellSelection } from '@tiptap/pm/tables'
import { NativeTableStructure, createDocxTableCommands } from './docx-tables'
import { docxOperations, replayDocxOperations, type DocxAnchor, type DocxPmNode } from './docx-operations'
import { createDocxRibbon } from './docx-ribbon'
import { DocTableRow, editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { NativeDraft } from './native-draft'
const defaults = (values: Record<string, unknown>) => Object.fromEntries(Object.entries(values).map(([key, value]) => [key, { default: value }]))
const Doc = Node.create({ name: 'doc', topNode: true, content: 'block+' })
const Paragraph = Node.create({ name: 'docParagraph', group: 'block', content: 'text*', addAttributes: () => defaults({ docxIndex: null }), renderHTML: () => ['p', 0] })
const Text = Node.create({ name: 'text', group: 'inline' })
const Table = Node.create({ name: 'docTable', group: 'block', content: 'docTableRow+', addAttributes: () => defaults({ docxIndex: null, colWidthsPct: null }), renderHTML: () => ['table', ['tbody', 0]] })
const Row = Node.create({ name: 'docTableRow', content: '(docTableCell|docTableHeader)+', addAttributes: () => defaults({ heightTwips: null, repeatHeader: false, repeatHeaderEdited: false, rawTrPr: null }), renderHTML: () => ['tr', 0] })
const Cell = Node.create({ name: 'docTableCell', content: 'docParagraph+', addAttributes: () => defaults({ colspan: 1, rowspan: 1, colwidth: null, rawTcPr: null }), renderHTML: () => ['td', 0] })
const Header = Cell.extend({ name: 'docTableHeader', renderHTML: () => ['th', 0] })
const Roles = Extension.create({ name: 'testTableRoles', extendNodeSchema: extension => ({ tableRole: ({ docTable: 'table', docTableRow: 'row', docTableCell: 'cell', docTableHeader: 'header_cell' } as Record<string, string>)[extension.name] }) })
const editors: Editor[] = []
afterEach(() => { editors.splice(0).forEach(editor => editor.destroy()); document.body.replaceChildren() })
function setup(followingTable = false, merged = false, fullWidth = false) {
  let baseline: DocxPmNode, ready = false
  const errors: string[] = [], values = new Map<string, string>()
  const draft = new NativeDraft({ documentId: 'table-doc', revision: 1, sourceSha256: 'source', scope: { database: 'd', companyId: 'c', userId: 'u', threadId: 't' } }, { getItem: key => values.get(key) ?? null, setItem: (key, value) => { values.set(key, value) }, removeItem: key => { values.delete(key) } })
  const widths = fullWidth ? [2401, 3001] : [2401, 3000, 3599]
  const anchor: DocxAnchor = { docxIndex: 2, blockId: 'table', expectedObjectSha256: 'sha', editable: false, structureEditable: true, tableWidthsTwips: widths, tableHeaderCount: 1,
    cells: widths.map((_, r) => widths.map((_, c) => ({ cellId: `${r}:${c}`, expectedObjectSha256: `hash${r}:${c}`, editable: true }))) }
  anchor.cellShapeEditable = true; anchor.cellShapeWidthsTwips = widths
  const anchors: DocxAnchor[] = [{ docxIndex: 1, blockId: 'body', expectedObjectSha256: 'body-sha', editable: true }, anchor]
  const source = { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 1 }, content: [{ type: 'text', text: 'body' }] }, { type: 'docTable', attrs: { docxIndex: 2, colWidthsPct: widths.map(width => width / 90) },
    content: widths.map((_, r) => ({ type: 'docTableRow', attrs: { heightTwips: 300 + r, repeatHeader: r === 0, rawTrPr: `row${r}` }, content: widths.map((width, c) => ({ type: 'docTableCell', attrs: { colwidth: [Math.round(width / 15)], rawTcPr: `cell${r}:${c}` }, content: [{ type: 'docParagraph', content: [{ type: 'text', text: 'same' }] }] })) })) }] }
  if (followingTable) {
    const second = structuredClone(source.content[1]); second.attrs.docxIndex = 3
    source.content.push(second)
    anchors.push({ ...anchor, docxIndex: 3, blockId: 'second-table' })
  }
  if(merged){const row=(source.content[1] as DocxPmNode).content![0]!;row.content![0]!.attrs={...row.content![0]!.attrs,colspan:2,colwidth:[160,200]};row.content!.splice(1,1)}
  const Guard = Extension.create({ name: 'testNativeGuard', addProseMirrorPlugins: () => [new Plugin({ filterTransaction(tr) { if (!ready || !tr.docChanged) return true; try { docxOperations(baseline, tr.doc.toJSON(), anchors, undefined, editor.schema); return true } catch (error) { errors.push(String(error)); return false } } })] })
  const editor = new Editor({ extensions: fullWidth ? [...editorExtensions.map(extension => extension.name === 'docTableRow' ? DocTableRow.extend({content:'(docTableCell | docTableHeader)*'}) : extension), NativeTableStructure, Guard] : [Doc, Paragraph, Text, Table, Row, Cell, Header, Roles, NativeTableStructure, UndoRedo, Guard], content: source, editorProps: { handleScrollToSelection: () => true }, onUpdate: () => { if (ready) draft.setOperations(docxOperations(baseline, editor.getJSON(), anchors, undefined, editor.schema)) } })
  editors.push(editor); baseline = editor.getJSON(); ready = true
  const table = baseline.content![1]
  const pmTable=editor.state.doc.child(1), sourceMap=TableMap.get(pmTable)
  anchor.cellShapeCells=[]
  pmTable.forEach((row,rowOffset,physicalRow)=>row.forEach((_cell,offset,physicalColumn)=>anchor.cellShapeCells!.push({...sourceMap.findCell(rowOffset+1+offset),physicalRow,physicalColumn})))
  const commands = createDocxTableCommands(editor, baseline, anchors, error => errors.push(String(error)))
  const select = (row = 0, column = 0) => { const table = editor.state.doc.child(1), map = TableMap.get(table); editor.commands.setTextSelection(editor.state.doc.child(0).nodeSize + 1 + map.map[row * map.width + column] + 2) }
  const cells=(headRow=1,headColumn=1)=>{const table=editor.state.doc.child(1),map=TableMap.get(table),start=editor.state.doc.child(0).nodeSize+1;editor.view.dispatch(editor.state.tr.setSelection(CellSelection.create(editor.state.doc,start+map.map[0]!,start+map.map[headRow*map.width+headColumn]!)))}
  return { editor, anchor, anchors, baseline, table, commands, select, cells, errors, draft, values }
}
const merge = { kind: 'mergeTableCells', rect: { top: 0, left: 0, bottom: 2, right: 2 } }
const operation = (steps: unknown[]) => ({ kind: 'reshapeTableCells', blockId: 'table', expectedObjectSha256: 'sha', steps })
const dialog = () => document.querySelector<HTMLElement>('[role="dialog"][aria-label="拆分单元格"]')!
const split = (rows = '1', columns = '2', mergeFirst = true) => {
  const modal = dialog()
  modal.querySelector<HTMLInputElement>('[aria-label="行数"]')!.value = rows
  modal.querySelector<HTMLInputElement>('[aria-label="列数"]')!.value = columns
  modal.querySelector<HTMLInputElement>('[type="checkbox"]')!.checked = mergeFirst
  modal.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
}
it('merges an exact CellSelection, undoes/redoes and replays a persisted shape draft', () => {
  const f = setup(); f.cells()
  expect(f.commands.reason('table-merge-cells')).toBeNull()
  f.commands.run('table-merge-cells')
  expect(f.errors).toEqual([])
  expect(f.draft.operations).toEqual([operation([merge])])
  expect(f.editor.state.doc.child(1).child(0).child(0).attrs).toMatchObject({ colspan: 2, rowspan: 2 })
  const pending = f.editor.getJSON()
  expect(f.editor.commands.undo()).toBe(true); expect(f.editor.getJSON()).toEqual(f.baseline)
  expect(f.editor.commands.redo()).toBe(true); expect(f.editor.getJSON()).toEqual(pending)
  const restoredDraft = new NativeDraft(f.draft.identity, { getItem: key => f.values.get(key) ?? null, setItem: (key, value) => { f.values.set(key, value) }, removeItem: key => { f.values.delete(key) } })
  expect(replayDocxOperations(f.baseline, restoredDraft.operations, f.anchors, undefined, f.editor.schema)).toEqual(pending)
  expect(f.editor.getHTML()).not.toContain('nativeTableCellShape')
})
it('splits a source merged cell without row/column capability and keeps default 1x2 source semantics', () => {
  const f = setup(false, true); f.anchor.structureEditable = false; f.select()
  expect(f.commands.reason('table-split-cells')).toBeNull()
  f.commands.run('table-split-cells')
  expect(dialog().hidden).toBe(false)
  expect(dialog().querySelector<HTMLInputElement>('[aria-label="行数"]')!.value).toBe('1')
  expect(dialog().querySelector<HTMLInputElement>('[aria-label="列数"]')!.value).toBe('2')
  expect(dialog().querySelector<HTMLInputElement>('[type="checkbox"]')!.checked).toBe(true)
  split()
  expect(f.errors).toEqual([])
  expect(f.draft.operations).toEqual([operation([{ kind: 'splitTableCells', rect: { top: 0, left: 0, bottom: 1, right: 2 }, rows: 1, columns: 2, mergeFirst: true }])])
  expect(f.editor.state.doc.child(1).child(0).childCount).toBe(3)
})
it('chains merge and explicit 2x2 split with baseline projection, history and draft replay', () => {
  const f = setup(); f.cells(); f.commands.run('table-merge-cells'); f.select()
  f.commands.run('table-split-cells'); split('2', '2')
  expect(f.errors).toEqual([])
  expect(f.draft.operations).toEqual([operation([merge, { kind: 'splitTableCells', rect: merge.rect, rows: 2, columns: 2, mergeFirst: true }])])
  const final = f.editor.getJSON()
  expect(replayDocxOperations(f.baseline, f.draft.operations, f.anchors, undefined, f.editor.schema)).toEqual(final)
  f.editor.commands.undo(); expect(f.draft.operations[0]!.steps).toHaveLength(1)
  f.editor.commands.redo(); expect(f.editor.getJSON()).toEqual(final)
})
it('validates split integers and 1x1 without changing draft or document, and rechecks the save lock', () => {
  const f = setup(); f.select(); f.commands.run('table-split-cells')
  const before = f.editor.getJSON()
  for (const [rows, columns] of [['1','1'], ['0','2'], ['1.5','2'], ['1','51'], ['','2']]) {
    split(rows, columns)
    expect(dialog().querySelector('[role="alert"]')!.textContent).not.toBe('')
    expect(f.editor.getJSON()).toEqual(before); expect(f.draft.operations).toEqual([])
  }
  f.editor.setEditable(false); split()
  expect(dialog().querySelector('[role="alert"]')!.textContent).toMatch(/正在保存|不可编辑/)
  expect(f.editor.getJSON()).toEqual(before)
})
it('keeps multi-select split mergeFirst=false distinct and requires a rectangle for merge', () => {
  const f = setup(); f.select()
  expect(f.commands.reason('table-merge-cells')).toMatch(/选中|选择/)
  f.cells(0, 1); f.commands.run('table-split-cells'); split('1','2',false)
  expect(f.errors).toEqual([])
  expect(f.draft.operations).toEqual([operation([{ kind: 'splitTableCells', rect: { top: 0, left: 0, bottom: 1, right: 2 }, rows: 1, columns: 2, mergeFirst: false }])])
  expect(TableMap.get(f.editor.state.doc.child(1)).width).toBe(5)
})
it('gates shape independently and refuses nested input, node/text ranges and mixed edits', () => {
  const f = setup(); f.cells(); f.anchor.structureEditable = false
  expect(f.commands.reason('table-merge-cells')).toBeNull()
  f.anchor.cellShapeEditable = false; f.anchor.cellShapeReadOnlyReason = '复杂 continuation'
  expect(f.commands.reason('table-merge-cells')).toContain('复杂 continuation')
  f.anchor.cellShapeEditable = true
  const nested = createDocxTableCommands(f.editor, f.baseline, f.anchors, error => f.errors.push(String(error)), () => true)
  expect(nested.reason('table-merge-cells')).toContain('嵌套')
  f.editor.view.dispatch(f.editor.state.tr.setSelection(NodeSelection.create(f.editor.state.doc, f.editor.state.doc.child(0).nodeSize)))
  expect(f.commands.reason('table-split-cells')).toMatch(/单元格|选择/)
  f.select(); f.editor.commands.insertContent('changed'); f.cells()
  expect(f.commands.reason('table-merge-cells')).toMatch(/同表|先保存/)
})
it('disables row/column and header mutation after shape edits and preserves the shape draft', () => {
  const f = setup(); f.cells(); f.commands.run('table-merge-cells'); f.select()
  const pending = f.editor.getJSON(), draft = structuredClone(f.draft.operations)
  for (const action of ['table-insert-row-before', 'table-repeat-header-rows']) {
    expect(f.commands.reason(action)).toMatch(/合并|拆分|先保存/)
    f.commands.run(action); expect(f.editor.getJSON()).toEqual(pending); expect(f.draft.operations).toEqual(draft)
  }
})
it('routes Ribbon merge/split controls with selection and save-lock refresh', () => {
  const f = setup(); f.cells()
  const ribbon = createDocxRibbon(f.editor, true, undefined, undefined, undefined, f.anchors, f.commands)
  document.body.append(ribbon); ribbon.querySelector<HTMLButtonElement>('[data-tab-id="tableLayout"]')!.click()
  const button = (action: string) => ribbon.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)!
  expect(button('table-merge-cells').disabled).toBe(false)
  button('table-merge-cells').click(); expect(f.draft.operations).toEqual([operation([merge])])
  expect(button('table-split-cells').disabled).toBe(false)
  button('table-split-cells').click(); split('2','2')
  expect(f.draft.operations[0]!.steps).toHaveLength(2)
  f.editor.setEditable(false); f.editor.commands.setMeta('saving',true)
  expect(button('table-split-cells').disabled).toBe(true)
})

it('merges a full-width 2x2 using the actual host schema without creating phantom cells, with undo/replay', () => {
  const f=setup(false,false,true);f.cells()
  expect(f.commands.reason('table-merge-cells')).toBeNull()
  f.commands.run('table-merge-cells')
  expect(f.errors).toEqual([])
  const table=f.editor.state.doc.child(1),map=TableMap.get(table)
  expect(map.problems).toBeNull();expect(map.width).toBe(2);expect(map.height).toBe(2)
  expect(table.child(1).childCount).toBe(0)
  expect(table.child(0).child(0).attrs).toMatchObject({colspan:2,rowspan:2})
  const pending=f.editor.getJSON()
  expect(replayDocxOperations(f.baseline,f.draft.operations,f.anchors,undefined,f.editor.schema)).toEqual(pending)
  f.editor.commands.undo();expect(f.editor.getJSON()).toEqual(f.baseline)
  f.editor.commands.redo();expect(f.editor.getJSON()).toEqual(pending)
})
