import { afterEach, expect, it } from 'vitest'
import { Editor, Extension, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { TableMap } from '@tiptap/pm/tables'
import { NativeTableStructure } from './docx-tables'
import { type DocxPmNode } from './docx-operations'
import { applyDocxTableStyle } from './docx-table-style'

const attrs = (v: Record<string, unknown>) => Object.fromEntries(Object.entries(v).map(([key, value]) => [key, { default: value }]))
const Doc = Node.create({ name: 'doc', topNode: true, content: 'block+' }), Text = Node.create({ name: 'text', group: 'inline' })
const Paragraph = Node.create({ name: 'docParagraph', group: 'block', content: 'text*', addAttributes: () => attrs({ docxIndex: null }), renderHTML: () => ['p', 0] })
const Table = Node.create({ name: 'docTable', group: 'block', content: 'docTableRow+', addAttributes: () => attrs({ docxIndex: null, tblStyleId: null, tblLook: null }), renderHTML: () => ['table', ['tbody', 0]] })
const Row = Node.create({ name: 'docTableRow', content: 'docTableCell+', renderHTML: () => ['tr', 0] })
const Cell = Node.create({ name: 'docTableCell', content: 'docParagraph+', addAttributes: () => attrs({ colspan: 1, rowspan: 1, colwidth: null, fill: null, borders: null }), renderHTML: () => ['td', 0] })
const Roles = Extension.create({ name: 'roles', extendNodeSchema: e => ({ tableRole: ({ docTable: 'table', docTableRow: 'row', docTableCell: 'cell' } as Record<string, string>)[e.name] }) })
const editors: Editor[] = []
afterEach(() => { editors.splice(0).forEach(e => e.destroy()); document.body.replaceChildren() })
const look = { firstRow: true, lastRow: false, firstColumn: true, lastColumn: false, bandedRows: true, bandedColumns: false }
const styles = [{ styleId: 'TableGrid', name: 'Table Grid' }, { styleId: 'LightShading', name: 'Light Shading' }]


const cell = (text: string, extra: Record<string, unknown>) => ({ type: 'docTableCell', attrs: extra, content: [{ type: 'docParagraph', content: [{ type: 'text', text }] }] })
const row = (...cells: any[]) => ({ type: 'docTableRow', content: cells })
const layouts = {
  colspan: [row(cell('A', { colspan: 2, fill: 'FF0000' }), cell('B', { fill: '0000FF' })), row(cell('C', { fill: '00FF00' }), cell('D', { fill: 'FFFF00' }), cell('E', { fill: '00FFFF' }))],
  rowspan: [row(cell('A', { rowspan: 2, fill: 'FF0000' }), cell('B', { fill: '0000FF' })), row(cell('C', { fill: '00FF00' }))],
  ordinary: [row(cell('A', { fill: 'FF0000' }), cell('B', { fill: '0000FF' })), row(cell('C', { fill: '00FF00' }), cell('D', { fill: 'FFFF00' }))],
}
for (const layout of ['colspan', 'rowspan', 'ordinary'] as const) for (const action of ['table-look-last-row', 'table-style-custom']) {
  it(`${layout} preserves physical cells when applying ${action}`, () => {
    const editor = new Editor({ extensions: [Doc, Paragraph, Text, Table, Row, Cell, Roles, NativeTableStructure, UndoRedo], content: {type:'doc',content:[{type:'docTable',attrs:{docxIndex:1,tblStyleId:'TableGrid',tblLook:look},content:layouts[layout]}]}, editorProps: { handleScrollToSelection: () => true } })
    editors.push(editor)
    const table = editor.state.doc.child(0)
    expect(TableMap.get(table).problems).toBeNull()
    const baseline = editor.getJSON() as DocxPmNode
    const originalCells = baseline.content![0]!.content
    const anchor = {docxIndex:1,blockId:'table',expectedObjectSha256:'sha',tableStyleEditable:true,tableStyleState:{styleId:'TableGrid',look,presetEditable:false},tableStyleOptions:styles}
    editor.commands.setTextSelection(3)
    expect(() => applyDocxTableStyle(editor,baseline,[anchor],action,action === 'table-style-custom' ? 'LightShading' : undefined)).not.toThrow()
    expect(editor.getJSON().content![0]!.content).toEqual(originalCells)
    if (action === 'table-look-last-row') expect(editor.state.doc.child(0).attrs.tblLook.lastRow).toBe(true)
    else expect(editor.state.doc.child(0).attrs.tblStyleId).toBe('LightShading')
  })
}
