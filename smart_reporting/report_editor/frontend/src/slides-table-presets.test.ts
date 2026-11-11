import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createEditorShell } from './shell'
import { createNativeOfficeView } from './native-office-view'
import { NativeDraft, type NativeDraftIdentity } from './native-draft'
import type { NativeContextResponse } from './native-api'
import { SLIDES_TABLE_PRESETS } from './slides-table-presets'

vi.mock('./slides-canvas', () => ({ mountSlidesCanvas: () => ({ update() {}, destroy() {} }) }))
beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function (this: HTMLDialogElement) { this.open = true } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: function (this: HTMLDialogElement) { this.open = false; this.dispatchEvent(new Event('close')) } })
})
afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks() })
const identity: NativeDraftIdentity = { documentId: 'table-presets', revision: 1, sourceSha256: 'a'.repeat(64), scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } }
const context = { context: { ...identity, format: 'pptx', sourceFile: { sha256: identity.sourceSha256 } }, editingEnabled: true } as unknown as NativeContextResponse
const store = () => {
  const values = new Map<string, string>()
  return { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value) }, removeItem: (key: string) => { values.delete(key) } }
}
function model(presetEditable = true) {
  return { revision: 1, sha256: identity.sourceSha256, size: { cx: 9144000, cy: 5143500 }, slides: [{ slideIndex: 0, animations: [], transitionApplyAllSafe: true, elements: [
    { id: 'tbl_1', type: 'table', name: 'Table', text: '', editable: false, tableStructureEditable: true, tableCells: [['a','b'],['c','d']], tablePresetEditable: presetEditable, tablePresetReason: presetEditable ? null : '来源样式定义冲突', tableStyleName: 'headerOrange', tableStyleFlags: { firstRow: false, bandRow: true, rtl: true, lastRow: false, firstCol: false, lastCol: false, bandCol: false } },
    { id: 'text_0', type: 'text', name: 'Text', text: 'outside', editable: true },
  ] }] }
}
async function open(draft = new NativeDraft(identity, store()), source = model()) {
  document.body.innerHTML = '<main id="app"></main>'
  const shell = createEditorShell(document.querySelector('#app')!, 'full', 'pptx')
  const api = { preview: vi.fn(async () => ({ model: source })), renderTree: vi.fn(async () => ({ slides: [] })) }
  const view = await createNativeOfficeView(shell, { api: api as never, context, draft })
  if (!view) throw new Error('no view')
  return { shell, draft, view, api }
}
const control = (root: ParentNode, command: string) => root.querySelector<HTMLSelectElement | HTMLButtonElement>(`[data-command="${command}"]`)!
const selectValue = (root: ParentNode, command: string, value: string) => { const field = control(root,command) as HTMLSelectElement; field.value = value; field.dispatchEvent(new Event('change',{bubbles:true})) }
const patch = (draft: NativeDraft) => (draft.operations[0] as unknown as { tableStyles: Record<string, unknown>[] }).tableStyles[0]
const selected = (root: ParentNode, command: string) => control(root,command).getAttribute('aria-pressed')

it.each(SLIDES_TABLE_PRESETS)('stages fixed $name preset and projects its source flags without inventing canvas colors', async preset => {
  const {shell,draft,view,api} = await open()
  selectValue(shell.editor,'tableStyle',preset.name)
  expect(patch(draft)).toEqual({slideIndex:0,elementId:'tbl_1',styleName:preset.name})
  expect(selected(shell.editor,'tableFirstRow')).toBe(String(preset.firstRow))
  expect(selected(shell.editor,'tableBandRow')).toBe(String(preset.bandRow))
  expect(selected(shell.editor,'tableRtl')).toBe('true')
  await vi.waitFor(()=>expect(api.renderTree.mock.calls.some(call=>JSON.stringify(call).includes(`"styleName":"${preset.name}"`))).toBe(true))
  expect(shell.editor.querySelectorAll('[data-table-cell]')).toHaveLength(4)
  view.dispose()
})
it('reads original flags independently of gallery name and leaves ambiguous source gallery unselected',async()=>{
 const source=model();source.slides[0]!.elements[0]!.tableStyleName=null as never
 const {shell,view}=await open(undefined,source)
 expect((control(shell.editor,'tableStyle') as HTMLSelectElement).value).toBe('')
 expect(selected(shell.editor,'tableFirstRow')).toBe('false');expect(selected(shell.editor,'tableBandRow')).toBe('true');expect(selected(shell.editor,'tableRtl')).toBe('true')
 view.dispose()
})
it('uses canonical preset then explicit overrides while choosing another preset clears prior direct formatting and ordinary flags',async()=>{
 const {shell,draft,view}=await open()
 selectValue(shell.editor,'tableShading','#FFF2CC');control(shell.editor,'tableAllBorders').click();control(shell.editor,'tableFirstRow').click()
 control(shell.editor,'tableRtl').click()
 expect(patch(draft)).toMatchObject({shadingColor:'#FFF2CC',borderPreset:'all',firstRow:true,rtl:false})
 selectValue(shell.editor,'tableStyle','zebraBlue')
 expect(patch(draft)).toEqual({slideIndex:0,elementId:'tbl_1',styleName:'zebraBlue',rtl:false})
 expect(selected(shell.editor,'tableFirstRow')).toBe('true');expect(selected(shell.editor,'tableBandRow')).toBe('true');expect(selected(shell.editor,'tableRtl')).toBe('false')
 control(shell.editor,'tableFirstRow').click();control(shell.editor,'tableBandRow').click();selectValue(shell.editor,'tableShading','#D6E4F0')
 expect(patch(draft)).toEqual({slideIndex:0,elementId:'tbl_1',styleName:'zebraBlue',rtl:false,firstRow:false,bandRow:false,shadingColor:'#D6E4F0'})
 selectValue(shell.editor,'tableStyle','headerOrange')
 expect(patch(draft)).toEqual({slideIndex:0,elementId:'tbl_1',styleName:'headerOrange',rtl:false})
 expect((control(shell.editor,'tableShading') as HTMLSelectElement).value).toBe('')
 view.dispose()
})
it('preserves source-scoped gallery/flag overrides through history and restored draft',async()=>{
 const storage=store(),draft=new NativeDraft(identity,storage)
 let {shell,view}=await open(draft)
 selectValue(shell.editor,'tableStyle','zebraGray');control(shell.editor,'tableBandRow').click()
 const expected=structuredClone(draft.operations)
 shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
 expect(patch(draft)).toEqual({slideIndex:0,elementId:'tbl_1',styleName:'zebraGray'})
 expect(selected(shell.editor,'tableBandRow')).toBe('true')
 shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click();expect(draft.operations).toEqual(expected)
 view.dispose();const recovered=new NativeDraft(identity,storage);({shell,view}=await open(recovered))
 expect(recovered.operations).toEqual(expected);expect((control(shell.editor,'tableStyle') as HTMLSelectElement).value).toBe('zebraGray');expect(selected(shell.editor,'tableBandRow')).toBe('false')
 view.dispose()
})
it('keeps preset-unsafe sources readonly for gallery and flags without disabling existing shading',async()=>{
 const {shell,draft,view}=await open(undefined,model(false))
 for(const command of ['tableStyle','tableFirstRow','tableBandRow','tableRtl']) {
  expect(control(shell.editor,command).disabled).toBe(true);expect(control(shell.editor,command).title).toContain('来源样式定义冲突')
  control(shell.editor,command).dispatchEvent(new Event(command==='tableStyle'?'change':'click',{bubbles:true}))
 }
 expect(draft.operations).toEqual([]);expect(control(shell.editor,'tableShading').disabled).toBe(false)
 view.dispose()
})
it('refuses forced gallery mutation after structure, selection change, save or disposal',async()=>{
 const {shell,draft,view}=await open()
 control(shell.editor,'tableStructure').click()
 const dialog=shell.editor.querySelector<HTMLDialogElement>('dialog')!
 ;[...dialog.querySelectorAll<HTMLButtonElement>('button')].find(button=>button.textContent==='在下方插入行')!.click()
 if(draft.operations.length) {
  const before=structuredClone(draft.operations);selectValue(shell.editor,'tableStyle','zebraBlue');expect(draft.operations).toEqual(before)
 } else throw new Error('structure not staged')
 shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click()
 const target=shell.editor.querySelector<HTMLSelectElement>('#object-select')!;target.value='text_0';target.dispatchEvent(new Event('change'))
 expect(control(shell.editor,'tableStyle').disabled).toBe(true);selectValue(shell.editor,'tableStyle','zebraBlue');expect(draft.operations).toEqual([])
 target.value='tbl_1';target.dispatchEvent(new Event('change'));draft.beginSave();selectValue(shell.editor,'tableStyle','zebraBlue');expect(draft.operations).toEqual([])
 const detached=control(shell.editor,'tableStyle');draft.saveFailed();view.dispose();detached.dispatchEvent(new Event('change'));expect(draft.operations).toEqual([])
})
it.each([
 null,
 [{slideIndex:0,elementId:'tbl_1',styleName:'made-up'}],
 [{slideIndex:0,elementId:'tbl_1',firstRow:'true'}],
 [{slideIndex:0,elementId:'tbl_1',rtl:null}],
 [{slideIndex:0,elementId:'text_0',styleName:'none'}],
 [{slideIndex:0,elementId:'tbl_1',styleName:'none',cells:[{row:0,col:0}]}],
])('retains malformed recovered table style without partially applying %j',async tableStyles=>{
 const storage=store(),draft=new NativeDraft(identity,storage),operations=[{kind:'editSlides',tableStyles}]
 draft.setOperations(operations);await expect(open(draft)).rejects.toThrow(/原草稿已保留/);expect(new NativeDraft(identity,storage).operations).toEqual(operations)
})
it('retains a recovered preset when changed source safety no longer permits it',async()=>{
 const storage=store(),draft=new NativeDraft(identity,storage),operations=[{kind:'editSlides',tableStyles:[{slideIndex:0,elementId:'tbl_1',styleName:'none'}]}]
 draft.setOperations(operations);await expect(open(draft,model(false))).rejects.toThrow(/原草稿已保留/);expect(new NativeDraft(identity,storage).operations).toEqual(operations)
})
