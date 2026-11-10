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
const identity: NativeDraftIdentity = { documentId: 'cell-shading', revision: 1, sourceSha256: 'a'.repeat(64), scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } }
const context = { context: { ...identity, format: 'pptx', sourceFile: { sha256: identity.sourceSha256 } }, editingEnabled: true } as unknown as NativeContextResponse
const store = () => {
  const values = new Map<string, string>()
  return { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value) }, removeItem: (key: string) => { values.delete(key) } }
}
function model(presetEditable = true) {
  return { revision: 1, sha256: identity.sourceSha256, size: { cx: 9144000, cy: 5143500 }, slides: [{ slideIndex: 0, animations: [], transitionApplyAllSafe: true, elements: [
    { id: 'tbl_1', type: 'table', name: 'Table', text: '', editable: false, tableStructureEditable: true, tableCellShadingEditable: true, tableCellShadingReason: null as string | null, tableCells: [['a','b'],['c','d']], tablePresetEditable: presetEditable, tablePresetReason: presetEditable ? null : '来源样式定义冲突', tableStyleName: 'headerOrange', tableStyleFlags: { firstRow: false, bandRow: true, rtl: true, lastRow: false, firstCol: false, lastCol: false, bandCol: false } },
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

const cells = (root: ParentNode) => [...root.querySelectorAll<HTMLTextAreaElement>('[data-table-cell]')]
const focus = (root: ParentNode, index: number) => cells(root)[index]!.focus()
const target = (root: ParentNode) => root.querySelector('[data-table-shading-target]')!.textContent

it('targets only the focused source cell with the existing palette and sends exact per-cell overrides to the bridge',async()=>{
 const {shell,draft,view,api}=await open()
 expect(target(shell.editor)).toBe('底纹目标：整表')
 focus(shell.editor,3);expect(target(shell.editor)).toBe('底纹目标：第 2 行 2 列')
 selectValue(shell.editor,'tableShading','#FFF2CC')
 expect(patch(draft)).toEqual({slideIndex:0,elementId:'tbl_1',cellShadings:[{row:1,col:1,shadingColor:'#FFF2CC'}]})
 expect((control(shell.editor,'tableShading') as HTMLSelectElement).value).toBe('#FFF2CC')
 await vi.waitFor(()=>expect(api.renderTree.mock.calls.some(call=>JSON.stringify(call).includes('"cellShadings":[{"row":1,"col":1,"shadingColor":"#FFF2CC"}]'))).toBe(true))
 view.dispose()
})
it('folds repeated cell updates, retains noFill and canonical order while whole-table target changes no draft',async()=>{
 const {shell,draft,view}=await open()
 focus(shell.editor,3);selectValue(shell.editor,'tableShading','#FFF2CC')
 focus(shell.editor,0);selectValue(shell.editor,'tableShading','none')
 focus(shell.editor,3);selectValue(shell.editor,'tableShading','#D6E4F0')
 expect(patch(draft).cellShadings).toEqual([{row:0,col:0,shadingColor:'none'},{row:1,col:1,shadingColor:'#D6E4F0'}])
 const before=structuredClone(draft.operations);control(shell.editor,'tableShadingWholeTable').click()
 expect(target(shell.editor)).toBe('底纹目标：整表');expect(draft.operations).toEqual(before)
 selectValue(shell.editor,'tableShading','#FFFFFF')
 expect(patch(draft)).toEqual({slideIndex:0,elementId:'tbl_1',shadingColor:'#FFFFFF'})
 view.dispose()
})
it('choosing a preset clears old cell overrides; flags and whole borders preserve later cell overrides',async()=>{
 const {shell,draft,view}=await open()
 focus(shell.editor,1);selectValue(shell.editor,'tableShading','#FFF2CC')
 selectValue(shell.editor,'tableStyle','zebraBlue')
 expect(patch(draft)).toEqual({slideIndex:0,elementId:'tbl_1',styleName:'zebraBlue'})
 focus(shell.editor,2);selectValue(shell.editor,'tableShading','none')
 control(shell.editor,'tableBandRow').click();control(shell.editor,'tableAllBorders').click()
 expect(patch(draft)).toEqual({slideIndex:0,elementId:'tbl_1',styleName:'zebraBlue',bandRow:false,borderPreset:'all',cellShadings:[{row:1,col:0,shadingColor:'none'}]})
 view.dispose()
})
it('keeps cell overrides independent of source table-preset capability',async()=>{
 const {shell,draft,view}=await open(undefined,model(false))
 focus(shell.editor,0);selectValue(shell.editor,'tableShading','#FFF2CC')
 expect(patch(draft).cellShadings).toEqual([{row:0,col:0,shadingColor:'#FFF2CC'}])
 view.dispose()
})
it('unsafe cell shading is visibly disabled while whole-table shading remains available',async()=>{
 const source=model();source.slides[0]!.elements[0]!.tableCellShadingEditable=false;source.slides[0]!.elements[0]!.tableCellShadingReason='含合并或扩展'
 const {shell,draft,view}=await open(undefined,source)
 focus(shell.editor,0);expect(control(shell.editor,'tableShading').disabled).toBe(true);expect(control(shell.editor,'tableShading').title).toContain('合并')
 selectValue(shell.editor,'tableShading','#FFF2CC');expect(draft.operations).toEqual([])
 control(shell.editor,'tableShadingWholeTable').click();expect(control(shell.editor,'tableShading').disabled).toBe(false)
 selectValue(shell.editor,'tableShading','#FFF2CC');expect(patch(draft)).toMatchObject({shadingColor:'#FFF2CC'})
 view.dispose()
})
it('restores exact nested cell overrides through undo redo and reload without mutating previous snapshots',async()=>{
 const storage=store(),draft=new NativeDraft(identity,storage)
 let {shell,view}=await open(draft)
 focus(shell.editor,0);selectValue(shell.editor,'tableShading','#FFF2CC');const original=structuredClone(draft.operations)
 focus(shell.editor,3);selectValue(shell.editor,'tableShading','none');const final=structuredClone(draft.operations)
 shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onUndo"]')!.click();expect(draft.operations).toEqual(original)
 shell.editor.querySelector<HTMLButtonElement>('[data-source-action="onRedo"]')!.click();expect(draft.operations).toEqual(final)
 view.dispose();const recovered=new NativeDraft(identity,storage);({shell,view}=await open(recovered))
 expect(recovered.operations).toEqual(final);expect(target(shell.editor)).toBe('底纹目标：整表')
 focus(shell.editor,3);expect((control(shell.editor,'tableShading') as HTMLSelectElement).value).toBe('none')
 view.dispose()
})
it('refuses detached-cell focus and change callbacks, and forced shading while selection or saving changes',async()=>{
 const {shell,draft,view}=await open();const stale=cells(shell.editor)[0]!
 const select=shell.editor.querySelector<HTMLSelectElement>('#object-select')!;select.value='text_0';select.dispatchEvent(new Event('change'))
 stale.dispatchEvent(new Event('focus'));stale.value='forged';stale.dispatchEvent(new Event('change'));expect(draft.operations).toEqual([])
 select.value='tbl_1';select.dispatchEvent(new Event('change'));expect(target(shell.editor)).toBe('底纹目标：整表')
 focus(shell.editor,0);draft.beginSave();selectValue(shell.editor,'tableShading','#FFF2CC');expect(draft.operations).toEqual([])
 const detached=control(shell.editor,'tableShading');draft.saveFailed();view.dispose();detached.dispatchEvent(new Event('change'));expect(draft.operations).toEqual([])
})
it('blocks a cell-shading operation after same-table structure changes',async()=>{
 const {shell,draft,view}=await open()
 focus(shell.editor,0);control(shell.editor,'tableStructure').click()
 const dialog=shell.editor.querySelector<HTMLDialogElement>('dialog')!
 ;[...dialog.querySelectorAll<HTMLButtonElement>('button')].find(button=>button.textContent==='在下方插入行')!.click()
 const before=structuredClone(draft.operations);selectValue(shell.editor,'tableShading','#FFF2CC');expect(draft.operations).toEqual(before)
 expect(control(shell.editor,'tableShading').disabled).toBe(true)
 view.dispose()
})
it.each([
 null, [], [{row:0,col:0,shadingColor:'#000000'}], [{row:0,col:0,shadingColor:'#FFF2CC',cells:[]}],
 [{row:-1,col:0,shadingColor:'none'}], [{row:0,col:2,shadingColor:'none'}], [{row:0,col:0,shadingColor:'none'},{row:0,col:0,shadingColor:'#FFF2CC'}],
 Array.from({length:501},(_,row)=>({row,col:0,shadingColor:'none'})),
])('retains malformed nested cell drafts before any view mutation %j',async cellShadings=>{
 const storage=store(),draft=new NativeDraft(identity,storage),operations=[{kind:'editSlides',tableStyles:[{slideIndex:0,elementId:'tbl_1',cellShadings}]}]
 draft.setOperations(operations);await expect(open(draft)).rejects.toThrow(/原草稿已保留/);expect(new NativeDraft(identity,storage).operations).toEqual(operations)
})
it('refuses restored cell edits when source safety changed and retains its stored draft',async()=>{
 const storage=store(),draft=new NativeDraft(identity,storage),operations=[{kind:'editSlides',tableStyles:[{slideIndex:0,elementId:'tbl_1',cellShadings:[{row:0,col:0,shadingColor:'none'}]}]}]
 const source=model();source.slides[0]!.elements[0]!.tableCellShadingEditable=false
 draft.setOperations(operations);await expect(open(draft,source)).rejects.toThrow(/原草稿已保留/);expect(new NativeDraft(identity,storage).operations).toEqual(operations)
})

it('allows updating one of 500 table records but refuses the 501st whole, cell or border record',async()=>{
 const source=model(),table=source.slides[0]!.elements[0]!
 source.slides[0]!.elements=Array.from({length:501},(_,i)=>({...table,id:`tbl_${i}`,name:`Table ${i}`}))
 const draft=new NativeDraft(identity,store());draft.setOperations([{kind:'editSlides',tableStyles:Array.from({length:500},(_,i)=>({slideIndex:0,elementId:`tbl_${i}`,borderPreset:'none'}))}])
 const {shell,view}=await open(draft,source)
 selectValue(shell.editor,'tableShading','#FFF2CC');expect(patch(draft)).toMatchObject({elementId:'tbl_0',shadingColor:'#FFF2CC'})
 const previous=structuredClone(draft.operations),select=shell.editor.querySelector<HTMLSelectElement>('#object-select')!
 select.value='tbl_500';select.dispatchEvent(new Event('change'))
 expect(control(shell.editor,'tableShading').disabled).toBe(true);expect(control(shell.editor,'tableShading').title).toContain('500')
 selectValue(shell.editor,'tableShading','#D6E4F0');expect(draft.operations).toEqual(previous)
 focus(shell.editor,0);selectValue(shell.editor,'tableShading','#D6E4F0');expect(draft.operations).toEqual(previous)
 control(shell.editor,'tableAllBorders').dispatchEvent(new Event('click'));expect(draft.operations).toEqual(previous)
 view.dispose()
})
