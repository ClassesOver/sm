import { afterEach, expect, it } from 'vitest'
import { Editor, Extension, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { Plugin, NodeSelection } from '@tiptap/pm/state'
import { TableMap, selectedRect, addRowAfter, CellSelection } from '@tiptap/pm/tables'
import { NativeTableStructure, createDocxTableCommands } from './docx-tables'
import { docxOperations, replayDocxOperations, type DocxAnchor, type DocxPmNode } from './docx-operations'
import { createDocxRibbon } from './docx-ribbon'
import { DocTableRow, editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { projectDocxColumnWidths, normalizeDocxColumnWidthSources } from './docx-table-column-width'
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
function setup(followingTable = false, merged = false, fullWidth = false, vertical = false) {
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
  if(vertical){const table=source.content[1] as DocxPmNode;table.content![0]!.content![0]!.attrs={...table.content![0]!.content![0]!.attrs,colspan:2,rowspan:2,colwidth:[160,200]};table.content![0]!.content!.splice(1,1);table.content![1]!.content=[]}
  const Guard = Extension.create({ name: 'testNativeGuard', addProseMirrorPlugins: () => [new Plugin({ filterTransaction(tr) { if (!ready || !tr.docChanged) return true; try { docxOperations(baseline, tr.doc.toJSON(), anchors, undefined, editor.schema); return true } catch (error) { errors.push(String(error)); return false } } })] })
  const editor = new Editor({ extensions: fullWidth ? [...editorExtensions.map(extension => extension.name === 'docTableRow' ? DocTableRow.extend({content:'(docTableCell | docTableHeader)*'}) : extension), NativeTableStructure, Guard] : [Doc, Paragraph, Text, Table, Row, Cell, Header, Roles, NativeTableStructure, UndoRedo, Guard], content: source, editorProps: { handleScrollToSelection: () => true }, onUpdate: () => { if (ready) draft.setOperations(docxOperations(baseline, editor.getJSON(), anchors, undefined, editor.schema)) } })
  editors.push(editor); baseline = editor.getJSON(); ready = true
  const table = baseline.content![1]
  const pmTable=editor.state.doc.child(1), sourceMap=TableMap.get(pmTable)
  anchor.cellShapeCells=[]
  pmTable.forEach((row,rowOffset,physicalRow)=>row.forEach((_cell,offset,physicalColumn)=>anchor.cellShapeCells!.push({...sourceMap.findCell(rowOffset+1+offset),physicalRow,physicalColumn})))
  Object.assign(anchor, { columnWidthEditable:true, columnWidthsTwips:widths, columnWidthMaxTwips:12000, columnWidthCells:anchor.cellShapeCells })
  const commands = createDocxTableCommands(editor, baseline, anchors, error => errors.push(String(error)))
  const select = (row = 0, column = 0) => { const table = editor.state.doc.child(1), map = TableMap.get(table); editor.commands.setTextSelection(editor.state.doc.child(0).nodeSize + 1 + map.map[row * map.width + column] + 2) }
  const cells=(headRow=1,headColumn=1)=>{const table=editor.state.doc.child(1),map=TableMap.get(table),start=editor.state.doc.child(0).nodeSize+1;editor.view.dispatch(editor.state.tr.setSelection(CellSelection.create(editor.state.doc,start+map.map[0]!,start+map.map[headRow*map.width+headColumn]!)))}
  return { editor, anchor, anchors, baseline, table, commands, select, cells, errors, draft, values }
}
const dialog = () => document.querySelector<HTMLElement>('[role="dialog"][aria-label="列宽"]')!
const setWidth = (value: string) => {
  dialog().querySelector<HTMLInputElement>('[aria-label="列宽（twip）"]')!.value=value
  dialog().querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))
}
const operation = (steps: unknown[]) => ({kind:'resizeTableColumns',blockId:'table',expectedObjectSha256:'sha',steps})
const widths = (editor: Editor) => {
  const table=editor.state.doc.child(1),map=TableMap.get(table)
  return Array.from({length:map.width},(_,column)=>{const rect=map.findCell(map.map[column]!);return Math.round(table.nodeAt(map.map[column]!)!.attrs.colwidth[column-rect.left]*15)})
}
it('sets a selected logical column through the twip dialog, chains distribution and replays persisted history',()=>{
  const f=setup();f.select(0,1)
  expect(f.commands.reason('table-column-width')).toBeNull()
  f.commands.run('table-column-width');setWidth('3010')
  expect(f.errors).toEqual([])
  expect(f.draft.operations).toEqual([operation([{kind:'setTableColumnWidth',left:1,right:2,widthTwips:3010}])])
  // 来源输入先round(twip/15)到整px，未选奇数twip原列不漂移。
  expect(widths(f.editor)).toEqual([2401,3015,3599])
  const once=f.editor.getJSON()
  f.commands.run('table-distribute-columns')
  expect(widths(f.editor)).toEqual([3005,3005,3005])
  const final=f.editor.getJSON()
  expect(replayDocxOperations(f.baseline,f.draft.operations,f.anchors,undefined,f.editor.schema)).toEqual(final)
  f.editor.commands.undo();expect(f.editor.getJSON()).toEqual(once)
  f.editor.commands.redo();expect(f.editor.getJSON()).toEqual(final)
  const restored=new NativeDraft(f.draft.identity,{getItem:key=>f.values.get(key)??null,setItem:(key,value)=>{f.values.set(key,value)},removeItem:key=>{f.values.delete(key)}})
  expect(replayDocxOperations(f.baseline,restored.operations,f.anchors,undefined,f.editor.schema)).toEqual(final)
  expect(f.editor.getHTML()).not.toContain('nativeTableColumnWidths')
})
it('uses merged caret span for set and distribution without structural capability',()=>{
  const f=setup(false,true);f.anchor.structureEditable=false;f.select()
  expect(f.commands.reason('table-column-width')).toBeNull()
  f.commands.run('table-column-width');setWidth('3000')
  expect(widths(f.editor)).toEqual([3000,3000,3599])
  expect(f.draft.operations).toEqual([operation([{kind:'setTableColumnWidth',left:0,right:2,widthTwips:3000}])])
  f.editor.commands.undo();f.select();f.commands.run('table-distribute-columns')
  expect(widths(f.editor)).toEqual([2701,2700,3599])
  expect(f.editor.state.doc.child(1).child(0).child(0).attrs.colspan).toBe(2)
})
it('supports whole-table NodeSelection and keeps multicolumn distribution limited to the selected band',()=>{
  const f=setup();f.cells(1,1);f.commands.run('table-distribute-columns')
  expect(widths(f.editor)).toEqual([2701,2700,3599])
  f.editor.commands.undo()
  f.editor.view.dispatch(f.editor.state.tr.setSelection(NodeSelection.create(f.editor.state.doc,f.editor.state.doc.child(0).nodeSize)))
  expect(f.commands.reason('table-column-width')).toBeNull()
  f.commands.run('table-column-width');setWidth('3000')
  expect(widths(f.editor)).toEqual([3000,3000,3000])
  expect(f.draft.operations).toEqual([operation([{kind:'setTableColumnWidth',left:0,right:3,widthTwips:3000}])])
})
it('rejects invalid width, frozen selection changes and save locks without changing document or draft',()=>{
  const f=setup();f.select();f.commands.run('table-column-width')
  for(const value of ['', '0','-1','1.5','9007199254740992']){
    setWidth(value);expect(dialog().querySelector('[role="alert"]')!.textContent).not.toBe('')
    expect(f.editor.getJSON()).toEqual(f.baseline);expect(f.draft.operations).toEqual([])
  }
  f.select(0,1);setWidth('3000')
  expect(dialog().querySelector('[role="alert"]')!.textContent).toMatch(/选择|选区/)
  expect(f.editor.getJSON()).toEqual(f.baseline)
  dialog().querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click()
  f.commands.run('table-column-width');f.editor.setEditable(false);setWidth('3000')
  expect(dialog().querySelector('[role="alert"]')!.textContent).toMatch(/正在保存|不可编辑/)
  expect(f.draft.operations).toEqual([])
})
it('rejects capability mismatch, nested inputs and mixed text/shape/header/row edits in both directions',()=>{
  const f=setup();f.select()
  Object.assign(f.anchor,{columnWidthEditable:false,columnWidthReadOnlyReason:'非固定dxa来源'})
  expect(f.commands.reason('table-column-width')).toContain('非固定dxa来源')
  Object.assign(f.anchor,{columnWidthEditable:true})
  const nested=createDocxTableCommands(f.editor,f.baseline,f.anchors,()=>{},()=>true)
  expect(nested.reason('table-column-width')).toContain('嵌套')
  f.editor.commands.insertContent('changed');expect(f.commands.reason('table-column-width')).toMatch(/先保存|同表/)
  f.editor.commands.undo();f.cells();f.commands.run('table-merge-cells')
  expect(f.commands.reason('table-column-width')).toMatch(/先保存|同表/)
  f.editor.commands.undo();f.select();f.commands.run('table-column-width');setWidth('3000')
  for(const action of ['table-merge-cells','table-split-cells','table-insert-row-before','table-repeat-header-rows']){
    if(action==='table-merge-cells')f.cells()
    expect(f.commands.reason(action)).toMatch(/先保存|列宽/)
  }
})
it('exposes only the two supported sizing Ribbon controls and refreshes their save lock',()=>{
  const f=setup();f.select()
  const ribbon=createDocxRibbon(f.editor,true,undefined,undefined,undefined,f.anchors,f.commands)
  document.body.append(ribbon);ribbon.querySelector<HTMLButtonElement>('[data-tab-id="tableLayout"]')!.click()
  const button=(action:string)=>ribbon.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)!
  expect(button('table-column-width').disabled).toBe(false);expect(button('table-distribute-columns').disabled).toBe(false)
  expect(button('table-row-height').disabled).toBe(true);expect(button('table-distribute-rows').disabled).toBe(true)
  button('table-column-width').click();setWidth('3000')
  expect(f.draft.operations[0]!.kind).toBe('resizeTableColumns')
  f.editor.setEditable(false);f.editor.commands.setMeta('saving',true)
  expect(button('table-column-width').disabled).toBe(true);expect(button('table-distribute-columns').disabled).toBe(true)
})

it('uses the actual host schema for a full-width rowspan source and preserves zero-cell rows/content',()=>{
  const f=setup(false,false,true,true);f.select()
  f.commands.run('table-column-width');setWidth('3000')
  expect(f.errors).toEqual([]);expect(widths(f.editor)).toEqual([3000,3000])
  const table=f.editor.state.doc.child(1)
  expect(TableMap.get(table).problems).toBeNull();expect(table.child(1).childCount).toBe(0)
  expect(table.child(0).child(0).attrs).toMatchObject({colspan:2,rowspan:2})
  expect(table.child(0).child(0).content.toJSON()).toEqual(f.editor.schema.nodeFromJSON(f.table).child(0).child(0).content.toJSON())
  expect(table.attrs.widthPx).toBe(400);expect(table.attrs.widthPct).toBeNull()
  const pending=f.editor.getJSON()
  expect(replayDocxOperations(f.baseline,f.draft.operations,f.anchors,undefined,f.editor.schema)).toEqual(pending)
  f.editor.commands.undo();expect(f.editor.getJSON()).toEqual(f.baseline)
  f.editor.commands.redo();expect(f.editor.getJSON()).toEqual(pending)
})
it('rejects stale logical source grids before producing a width projection',()=>{
  const f=setup(),step={kind:'setTableColumnWidth' as const,left:0,right:1,widthTwips:3000}
  const anchor={...f.anchor,columnWidthCells:[{top:0,left:0,bottom:3,right:3,physicalRow:0,physicalColumn:0}]}
  expect(()=>projectDocxColumnWidths(f.table,anchor,[step],f.editor.schema)).toThrow(/来源网格/)
  expect(f.editor.getJSON()).toEqual(f.baseline)
})
it('normalizes actual host load/reopen from rounded pixels to exact trusted odd twips without editing intent',()=>{
  const f=setup(false,false,true), trusted=[1801,2401,3001]
  const source=structuredClone(f.baseline), table=source.content![1]!
  table.content=Array.from({length:2},()=>({type:'docTableRow',content:trusted.map(width=>({type:'docTableCell',attrs:{colwidth:[Math.round(width/15)]},content:[{type:'docParagraph',content:[{type:'text',text:'source'}]}]}))}))
  const rounded=f.editor.schema.nodeFromJSON(source).toJSON() as DocxPmNode
  const node=f.editor.schema.nodeFromJSON(rounded).child(1),map=TableMap.get(node)
  const cells: NonNullable<DocxAnchor['columnWidthCells']>=[]
  node.forEach((row,rowOffset,physicalRow)=>row.forEach((_cell,offset,physicalColumn)=>cells.push({...map.findCell(rowOffset+1+offset),physicalRow,physicalColumn})))
  const anchor={...f.anchor,columnWidthsTwips:trusted,columnWidthCells:cells}
  for(let reopen=0;reopen<2;reopen++){
    const normalized=normalizeDocxColumnWidthSources(rounded,[anchor],f.editor.schema)
    const table=f.editor.schema.nodeFromJSON(normalized).child(1)
    expect(table.child(0).content.content.map(cell=>cell.attrs.colwidth)).toEqual(trusted.map(width=>[width/15]))
    expect(table.attrs.widthPx).toBe(7203/15)
    expect(table.attrs.nativeTableColumnWidths).toBeNull()
    expect(table.child(0).child(0).textContent).toBe('source')
    expect(normalizeDocxColumnWidthSources(normalized,[anchor],f.editor.schema)).toEqual(normalized)
    expect(docxOperations(normalized,normalized,[f.anchors[0]!,anchor],undefined,f.editor.schema)).toEqual([])
    const loadEditor=new Editor({extensions:[...editorExtensions.map(extension=>extension.name==='docTableRow'?DocTableRow.extend({content:'(docTableCell | docTableHeader)*'}):extension),NativeTableStructure],content:rounded,onUpdate:()=>{throw new Error('source normalization must not emit an edit')}})
    editors.push(loadEditor)
    loadEditor.chain().setMeta('addToHistory',false).setContent(normalized,{emitUpdate:false}).run()
    expect(loadEditor.getJSON()).toEqual(normalized)
    expect(loadEditor.commands.undo()).toBe(false)
    const resized=structuredClone(normalized)
    resized.content![1]=projectDocxColumnWidths(normalized.content![1]!,anchor,[{kind:'setTableColumnWidth',left:0,right:1,widthTwips:3000}],f.editor.schema)
    expect(normalizeDocxColumnWidthSources(resized,[anchor],f.editor.schema)).toEqual(resized)
  }
  expect(normalizeDocxColumnWidthSources(rounded,[{...anchor,columnWidthEditable:false}],f.editor.schema)).toEqual(rounded)
  expect(f.draft.operations).toEqual([])
})
