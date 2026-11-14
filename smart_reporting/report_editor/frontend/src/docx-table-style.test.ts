import { afterEach, expect, it } from 'vitest'
import { Editor, Extension, Node } from '@tiptap/core'
import { UndoRedo } from '@tiptap/extensions'
import { TableMap } from '@tiptap/pm/tables'
import { NativeTableStructure, createDocxTableCommands } from './docx-tables'
import { createDocxRibbon } from './docx-ribbon'
import { docxOperations, replayDocxOperations, type DocxAnchor, type DocxPmNode } from './docx-operations'
import { mergeDocxTableStyleRequest, safeDocxTableStyleOptions } from './docx-table-style'
import { DOCX_TABLE_PRESETS } from '../../../reporting/doc_engine/bridge/docx-table-style-spec'

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

function setup(state: Record<string, unknown> = {}) {
  const content: DocxPmNode = { type: 'doc', content: [{ type: 'docParagraph', attrs: { docxIndex: 0 }, content: [{ type: 'text', text: 'body' }] }, {
    type: 'docTable', attrs: { docxIndex: 1, tblStyleId: 'TableGrid', tblLook: look },
    content: [0, 1, 2].map(r => ({ type: 'docTableRow', content: [0, 1].map(c => ({ type: 'docTableCell', content: [{ type: 'docParagraph', content: [{ type: 'text', text: `${r}${c}` }] }] })) })),
  }] }
  const editor = new Editor({ extensions: [Doc, Paragraph, Text, Table, Row, Cell, Roles, NativeTableStructure, UndoRedo], content, editorProps: { handleScrollToSelection: () => true } })
  editors.push(editor)
  const baseline = editor.getJSON() as DocxPmNode
  const anchor = { docxIndex: 1, blockId: 'table', expectedObjectSha256: 'sha', editable: true, tableStyleEditable: true, tableStyleReadOnlyReason: null, tableStyleState: { styleId: 'TableGrid', look, presetEditable: true, ...state }, tableStyleOptions: styles, cells: [0, 1, 2].map(r => [0, 1].map(c => ({ cellId: `${r}${c}`, expectedObjectSha256: 'c', editable: true }))) } as unknown as DocxAnchor
  const errors: string[] = [], commands = createDocxTableCommands(editor, baseline, [anchor], e => errors.push(String(e)))
  const start = editor.state.doc.child(0).nodeSize + 1
  editor.commands.setTextSelection(start + 2 + TableMap.get(editor.state.doc.child(1)).map[0]!)
  const table = () => editor.state.doc.child(1)
  const paragraph = { docxIndex: 0, blockId: 'p', expectedObjectSha256: 'p', editable: true } as DocxAnchor
  const ops = () => docxOperations(baseline, editor.getJSON() as DocxPmNode, [paragraph, anchor])
  return { editor, baseline, anchor, paragraph, commands, errors, table, ops }
}

it('style options from inspect are validated', () => {
  expect(safeDocxTableStyleOptions([{ styleId: 'A', name: '' }])).toEqual([{ styleId: 'A', name: 'A' }])
  expect(safeDocxTableStyleOptions(undefined)).toEqual([])
  for (const bad of [{}, [{ styleId: '' }], [{ styleId: 1 }]]) expect(() => safeDocxTableStyleOptions(bad)).toThrow()
})

it('look toggles preview tblLook and save as one setTableStyle; toggling back clears the intent', () => {
  const { commands, table, ops, errors } = setup()
  expect(commands.reason('table-look-last-row')).toBeNull()
  expect(commands.active!('table-look-first-row')).toBe(true)
  commands.run('table-look-last-row'); commands.run('table-look-banded-rows')
  expect(errors).toEqual([])
  expect(table().attrs.tblLook).toEqual({ ...look, lastRow: true, bandedRows: false })
  expect(commands.active!('table-look-last-row')).toBe(true)
  expect(ops()).toEqual([{ kind: 'setTableStyle', blockId: 'table', expectedObjectSha256: 'sha', look: { ...look, lastRow: true, bandedRows: false } }])
  commands.run('table-look-last-row'); commands.run('table-look-banded-rows')
  expect(table().attrs.nativeTableStyle).toBeNull()
  expect(ops()).toEqual([])
})

it('no style and gallery styles change tblStyleId and merge with look', () => {
  const { commands, table, ops, editor } = setup()
  commands.run('table-style-none')
  expect(table().attrs.tblStyleId).toBeNull()
  expect(commands.active!('table-style-none')).toBe(true)
  commands.run('table-look-first-column')
  expect(ops()).toEqual([{ kind: 'setTableStyle', blockId: 'table', expectedObjectSha256: 'sha', styleId: null, look: { ...look, firstColumn: false } }])
  commands.run('table-style-custom')
  const select = document.querySelector<HTMLSelectElement>('select[aria-label="文档表格样式"]')!
  expect([...select.options].map(option => option.value)).toEqual(['TableGrid', 'LightShading'])
  select.value = 'LightShading'
  select.form!.requestSubmit()
  expect(table().attrs.tblStyleId).toBe('LightShading')
  const operations = ops()
  expect(operations).toEqual([{ kind: 'setTableStyle', blockId: 'table', expectedObjectSha256: 'sha', styleId: 'LightShading', look: { ...look, firstColumn: false } }])
  // 草稿恢复得到同一预览
  const { baseline, anchor, paragraph } = setup()
  expect(replayDocxOperations(baseline, operations, [paragraph, anchor]).content![1]).toEqual(editor.getJSON().content![1])
})

it('presets fill header/bands, draw single borders, drop the style reference and round-trip through drafts', () => {
  const { commands, table, ops, editor, errors } = setup()
  commands.run('table-style-blue-banded')
  expect(errors).toEqual([])
  const preset = DOCX_TABLE_PRESETS.blueBanded
  expect(table().attrs.tblStyleId).toBeNull()
  const fills: unknown[] = []
  table().forEach(row => row.forEach(cell => { fills.push(cell.attrs.fill); expect(cell.attrs.borders).toMatchObject({ top: { style: 'single', szEighths: 4, color: '9DC3E6' }, left: { style: 'single' }, bottom: { style: 'single' }, right: { style: 'single' } }) }))
  expect(fills).toEqual([preset.headerFill, preset.headerFill, preset.band1Fill, preset.band1Fill, preset.band2Fill, preset.band2Fill])
  expect(commands.active!('table-style-blue-banded')).toBe(true)
  const operations = ops()
  expect(operations).toEqual([{ kind: 'setTableStyle', blockId: 'table', expectedObjectSha256: 'sha', preset: 'blueBanded' }])
  const restored = setup()
  expect(replayDocxOperations(restored.baseline, operations, [restored.paragraph, restored.anchor]).content![1]).toEqual(editor.getJSON().content![1])
  // 预设之后再选文档样式：预设格式整体撤回为来源，只保留样式引用
  commands.run('table-style-custom')
  const select = document.querySelector<HTMLSelectElement>('select[aria-label="文档表格样式"]')!
  select.value = 'LightShading'; select.form!.requestSubmit()
  table().forEach(row => row.forEach(cell => expect(cell.attrs.fill).toBeNull()))
  expect(ops()).toEqual([{ kind: 'setTableStyle', blockId: 'table', expectedObjectSha256: 'sha', styleId: 'LightShading' }])
})

it('mixing with text edits, unsupported presets, read-only tables and forged drafts is refused', () => {
  const { commands, editor, ops, table } = setup()
  commands.run('table-look-last-row')
  const pos = editor.state.doc.child(0).nodeSize + 4
  editor.view.dispatch(editor.state.tr.insertText('X', pos))
  expect(() => ops()).toThrow(/表格样式修改不能与同表/)
  expect(commands.reason('table-look-first-row')).toMatch(/表格样式修改不能与同表/)
  expect(table().attrs.nativeTableStyle).not.toBeNull()

  const merged = setup({ presetEditable: false })
  expect(merged.commands.reason('table-style-grid')).toMatch(/内置样式暂不支持/)
  expect(merged.commands.reason('table-look-first-row')).toBeNull()

  const readOnly = setup()
  ;(readOnly.anchor as any).tableStyleEditable = false; (readOnly.anchor as any).tableStyleReadOnlyReason = 'docx_table_style_protected'
  expect(readOnly.commands.reason('table-style-none')).toBe('docx_table_style_protected')

  const forged = setup()
  for (const operations of [
    [{ kind: 'setTableStyle', blockId: 'table', expectedObjectSha256: 'stale', styleId: null }],
    [{ kind: 'setTableStyle', blockId: 'table', expectedObjectSha256: 'sha', styleId: 'Missing' }],
    [{ kind: 'setTableStyle', blockId: 'table', expectedObjectSha256: 'sha', preset: 'grid', styleId: null }],
    [{ kind: 'setTableStyle', blockId: 'table', expectedObjectSha256: 'sha', styleId: null }, { kind: 'replaceCellText', blockId: 'table', cellId: '00', expectedObjectSha256: 'c', text: 'x' }],
  ]) expect(() => replayDocxOperations(forged.baseline, operations as any, [forged.paragraph, forged.anchor])).toThrow()
})

it('merge keeps only fields that differ from the source', () => {
  const state = { styleId: 'TableGrid', look, presetEditable: true }
  expect(mergeDocxTableStyleRequest(null, { styleId: 'TableGrid' }, state)).toBeNull()
  expect(mergeDocxTableStyleRequest({ preset: 'grid' }, { styleId: 'TableGrid' }, state)).toBeNull()
  expect(mergeDocxTableStyleRequest({ styleId: null }, { preset: 'grid' }, state)).toEqual({ preset: 'grid' })
})

it('ribbon table design buttons are enabled, pressed and run the native commands', () => {
  const { editor, commands, table } = setup()
  const ribbon = createDocxRibbon(editor, true, undefined, undefined, undefined, [], commands)
  document.body.append(ribbon)
  ribbon.querySelector<HTMLButtonElement>('[data-tab-id="tableDesign"]')?.click()
  const button = (action: string) => ribbon.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)!
  expect(button('table-look-first-row').disabled).toBe(false)
  expect(button('table-look-first-row').getAttribute('aria-pressed')).toBe('true')
  button('table-look-banded-columns').click()
  expect(table().attrs.tblLook.bandedColumns).toBe(true)
  expect(button('table-look-banded-columns').getAttribute('aria-pressed')).toBe('true')
  expect(button('table-style-green-header').disabled).toBe(false)
})
