import { expect, it, vi } from 'vitest'
import { applyCellEdits, createBlankWorkbook, protectSheet } from '@sheets-web/xlsx-engine'
import { createWorkbookEditorView } from './workbook-main'
import { createNativeOfficeTransport } from './native-office-view'
import { NativeDraft, type NativeDraftIdentity, type NativeSaveRequest } from './native-draft'
import { createEditorShell } from './shell'

const grid = vi.hoisted(() => ({ api: undefined as any, ribbon: undefined as any, view: undefined as any, layers: [] as any[], inputs: [] as any[], printed: [] as any[], apply: vi.fn(() => false), instances: [] as any[], failNameImport: false as boolean | 'local' }))
vi.mock('@univerjs/preset-sheets-core', () => ({ UniverSheetsCorePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-note', () => ({ UniverSheetsNotePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-find-replace', () => ({ UniverSheetsFindReplacePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-drawing', () => ({ UniverSheetsDrawingPreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-table', () => ({ UniverSheetsTablePreset: () => ({ plugins: [] }) }))
vi.mock('@univerjs/preset-sheets-conditional-formatting', () => ({ UniverSheetsConditionalFormattingPreset: () => ({ plugins: [] }) }))
vi.mock('./workbook-ribbon', () => ({
  mountWorkbookRibbon: (_host: unknown, callback: unknown, view: unknown) => { grid.ribbon = callback; grid.view = view; return { dispose() {}, refreshState() {} } },
  applyWorkbookRibbonCommand: grid.apply,
}))
vi.mock('./workbook-vendor/grid/decimal-step', () => ({ stepSelectionDecimals() {} }))
vi.mock('./workbook-vendor/grid/sparkline-render', () => ({ setSparklines() {}, setSparklineWorkbookResolver() {} }))
vi.mock('./workbook-vendor/grid/chart-render', () => ({ setCharts() {} }))
vi.mock('./workbook-vendor/grid/create-univer', async () => {
  const { Univer, IUniverInstanceService, LocaleType, mergeLocales } = await import('@univerjs/core')
  const CoreZhCN = (await import('@univerjs/preset-sheets-core/locales/zh-CN')).default
  const NoteZhCN = (await import('@univerjs/preset-sheets-note/locales/zh-CN')).default
  const { FUniver } = await import('@univerjs/core/lib/facade')
  const { UniverSheetsPlugin } = await import('@univerjs/sheets')
  const { UniverSheetsNotePlugin } = await import('@univerjs/sheets-note')
  const { UniverSheetsSortPlugin } = await import('@univerjs/sheets-sort')
  const { UniverFormulaEnginePlugin } = await import('@univerjs/engine-formula')
  const { UniverSheetsFormulaPlugin } = await import('@univerjs/sheets-formula')
  const { UniverSheetsDataValidationPlugin } = await import('@univerjs/sheets-data-validation')
  const { UniverSheetsTablePlugin } = await import('@univerjs/sheets-table')
  const { UniverSheetsConditionalFormattingPlugin } = await import('@univerjs/sheets-conditional-formatting')
  await import('@univerjs/sheets/facade')
  await import('@univerjs/sheets-formula/facade')
  await import('@univerjs/sheets-note/facade')
  // mock的table preset不会执行其官方facade副作用，补齐实际运行时的表格接口。
  await import('@univerjs/sheets-table/facade')
  await import('@univerjs/sheets-conditional-formatting/facade')
  return { createUniver: () => {
    const univer = new Univer({ locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: mergeLocales(CoreZhCN, NoteZhCN) } })
    grid.instances.push(univer)
    univer.registerPlugin(UniverSheetsPlugin)
    univer.registerPlugin(UniverSheetsNotePlugin)
    univer.registerPlugin(UniverSheetsSortPlugin)
    univer.registerPlugin(UniverFormulaEnginePlugin)
    univer.registerPlugin(UniverSheetsFormulaPlugin)
    univer.registerPlugin(UniverSheetsDataValidationPlugin)
    univer.registerPlugin(UniverSheetsTablePlugin)
    univer.registerPlugin(UniverSheetsConditionalFormattingPlugin)
    const api = FUniver.newAPI(univer)
    const execute = api.syncExecuteCommand.bind(api)
    api.syncExecuteCommand = ((id: string, params: any) => grid.failNameImport && id === 'formula.mutation.set-defined-name' && params?.name === 'LostDependency'
      && (grid.failNameImport !== 'local' || params.localSheetId)
      ? false : execute(id, params)) as typeof api.syncExecuteCommand
    const create = api.createWorkbook.bind(api)
    api.createWorkbook = data => {
      const workbook = create(data)
      univer.__getInjector().get(IUniverInstanceService).focusUnit(workbook.getId())
      return workbook
    }
    grid.api = api
    return { univer, univerAPI: api }
  } }
})

const identity: NativeDraftIdentity = { documentId: 'main-calculation', revision: 1, sourceSha256: 'b'.repeat(64),
  scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } }
const store = () => { const data = new Map<string, string>(); return { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => { data.set(key, value) }, removeItem: (key: string) => { data.delete(key) } } }
async function fixture() {
  return applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 2 } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 6, formula: '=A1*3' } },
  ])
}
async function open(source: Uint8Array, draft: NativeDraft, save: (request: NativeSaveRequest) => Promise<unknown>, path?: string, editingEnabled = true) {
  document.body.innerHTML = '<main id="app"></main>'
  const shell = createEditorShell(document.querySelector('#app')!, 'full', 'xlsx')
  const context = { context: { ...identity, format: 'xlsx', sourceFile: { sha256: identity.sourceSha256 } }, editingEnabled }
  const transport = createNativeOfficeTransport({ api: { save } as never, context: context as never, draft })
  const view = await createWorkbookEditorView(shell, { native: true, draft, request: transport.workbook,
    file: async () => ({ bytes: source.slice().buffer as ArrayBuffer, sha256: identity.sourceSha256, path }) })
  return { shell, view }
}
const sheet = () => grid.api.getActiveWorkbook().getActiveSheet()


vi.mock('./workbook-goto-reveal',()=>({createWorkbookReveal:()=>({cancel(){},dispose(){},reveal:vi.fn(async(_sheet:unknown,_row:number,_column:number,current:()=>boolean)=>current()?true:null)})}))
it('checks current sheet on readonly facades through official selection without draft history requests or content changes',async()=>{
 const source=await applyCellEdits(await fixture(),[
  {sheetName:'Sheet1',row:2,column:1,writeValue:true,cell:{value:'#FIELD!'}},
  {sheetName:'Sheet1',row:50,column:2,writeValue:true,cell:{value:'#REF!'}},
  {sheetName:'Sheet1',row:1,column:1,writeValue:true,cell:{value:'#REF!suffix'}},
 ])
 const draft=new NativeDraft(identity,store()),save=vi.fn(async()=>{throw Error('unexpected save')}),current=await open(source,draft,save,undefined,false)
 try{
  const workbook=grid.api.getActiveWorkbook(),sheet=workbook.getActiveSheet();sheet.setActiveRange(sheet.getRange('A1'))
  await vi.waitFor(()=>expect(sheet.getRange('B1').getValue()).toBe(6))
  const before=workbook.getSnapshot(),status=current.shell.statusLabel.textContent
  const {IUndoRedoService}=await import('@univerjs/core'),stack=grid.instances.at(-1).__getInjector().get(IUndoRedoService),undo=stack.pitchTopUndoElement()
  expect(grid.view.errorChecking().available).toBe(true)
  for(const address of ['B3','C51','B3']){
   grid.ribbon('error-checking');await vi.waitFor(()=>expect(current.shell.editor.querySelector('.workbook-feedback')!.textContent).toContain(address))
   expect(workbook.getActiveRange().getA1Notation()).toBe(address)
  }
  expect(current.shell.editor.querySelector('.workbook-feedback')!.textContent).toMatch(/当前工作表.*2 个错误/)
  expect(workbook.getSnapshot()).toEqual(before);expect(draft.operations).toEqual([]);expect(stack.pitchTopUndoElement()).toBe(undo);expect(current.shell.statusLabel.textContent).toBe(status);expect(save).not.toHaveBeenCalled()
 }finally{current.view?.dispose()}
})
it('blocks error checking during save and supports saved non-native navigation',async()=>{
 document.body.innerHTML='<main id="app"></main>';const shell=createEditorShell(document.querySelector('#app')!,'full','xlsx')
 const source=await applyCellEdits(await fixture(),[{sheetName:'Sheet1',row:2,column:1,writeValue:true,cell:{value:'#REF!'}}])
 let finish!:(result:unknown)=>void;const request=vi.fn(()=>new Promise(resolve=>{finish=resolve}))
 const view=await createWorkbookEditorView(shell,{file:async()=>({bytes:source.slice().buffer as ArrayBuffer,sha256:identity.sourceSha256}),request:request as never})
 try{
  const workbook=grid.api.getActiveWorkbook(),sheet=workbook.getActiveSheet();sheet.setActiveRange(sheet.getRange('A1'))
  shell.save.click();await vi.waitFor(()=>expect(request).toHaveBeenCalledTimes(1));expect(grid.view.errorChecking().available).toBe(false)
  grid.ribbon('error-checking');await Promise.resolve();expect(workbook.getActiveRange().getA1Notation()).toBe('A1')
  finish({revisionRegistered:true,revision:2,xlsx:{downloadUrl:'/saved.xlsx'},validation:{ok:true,issues:[]}})
  await vi.waitFor(()=>expect(shell.statusLabel.textContent).not.toContain('正在保存'));expect(grid.view.errorChecking().available).toBe(true)
  const before=workbook.getSnapshot();grid.ribbon('error-checking');await vi.waitFor(()=>expect(shell.editor.querySelector('.workbook-feedback')!.textContent).toContain('B3'))
  expect(workbook.getActiveRange().getA1Notation()).toBe('B3');expect(workbook.getSnapshot()).toEqual(before);expect(request).toHaveBeenCalledTimes(1)
 }finally{view?.dispose()}
})

it('navigates real protected sheets and blocks commands retained after disposal',async()=>{
 const source=await protectSheet(await applyCellEdits(await fixture(),[{sheetName:'Sheet1',row:2,column:1,writeValue:true,cell:{value:'#REF!'}}]),'Sheet1',true)
 const draft=new NativeDraft(identity,store()),save=vi.fn(async()=>{throw Error('unexpected save')}),current=await open(source,draft,save)
 try{
  const workbook=grid.api.getActiveWorkbook(),sheet=workbook.getActiveSheet();sheet.setActiveRange(sheet.getRange('A1'));await vi.waitFor(()=>expect(sheet.getRange('B1').getValue()).toBe(6))
  const before=workbook.getSnapshot();expect(grid.view.protection().sheet.protected).toBe(true);expect(grid.view.errorChecking().available).toBe(true)
  grid.ribbon('error-checking');await vi.waitFor(()=>expect(current.shell.editor.querySelector('.workbook-feedback')!.textContent).toContain('B3'))
  expect(workbook.getActiveRange().getA1Notation()).toBe('B3');expect(workbook.getSnapshot()).toEqual(before);expect(draft.operations).toEqual([]);expect(save).not.toHaveBeenCalled()
 }finally{current.view?.dispose()}
 const feedback=current.shell.editor.querySelector('.workbook-feedback')!.textContent;grid.ribbon('error-checking');await Promise.resolve();expect(current.shell.editor.querySelector('.workbook-feedback')!.textContent).toBe(feedback)
})
