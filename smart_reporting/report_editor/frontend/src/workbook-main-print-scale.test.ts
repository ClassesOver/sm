import { expect, it, vi } from 'vitest'
import { applyCellEdits, applyPageSetups, createBlankWorkbook, readWorkbook, protectSheet } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
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
vi.mock('./workbook-print', async original => {
  const actual = await original<typeof import('./workbook-print')>()
  return { ...actual, buildSheetPrintHtml: (source: any, setup: any) => { grid.printed.push({ source, setup }); return '<html></html>' }, printDocument: () => true }
})
vi.mock('./workbook-page-break-preview', async original => {
  const actual = await original<typeof import('./workbook-page-break-preview')>()
  return { ...actual, planPageBreakPreview: (source: any, setup: any) => { grid.inputs.push({ source, setup }); return actual.planPageBreakPreview(source, setup) }, installPageBreakOverlay: (_runtime: unknown, _sheet: unknown, plan: unknown) => { const layer = { plan, dispose: vi.fn() }; grid.layers.push(layer); return layer } }
})
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
  const { UniverSheetsFilterPlugin } = await import('@univerjs/sheets-filter')
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
    univer.registerPlugin(UniverSheetsFilterPlugin)
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
const history = (direction: 'undo' | 'redo') => expect(grid.api.syncExecuteCommand(`univer.command.${direction}`)).toBe(true)

const scaleInput=()=>document.querySelector<HTMLInputElement>('[data-print-scale-input]')!
const confirm=(value:number)=>{scaleInput().value=String(value);document.querySelector<HTMLFormElement>('.workbook-print-scale-dialog form')!.dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}))}
it('initializes trusted print state and saves only scale/fit changes through the existing draft and page setup protocol',async()=>{
 const source=await applyPageSetups(await fixture(),[{sheetName:'Sheet1',scale:85,fitToPage:true,fitToWidth:2,fitToHeight:3,orientation:'landscape'}]),draft=new NativeDraft(identity,store()),save=vi.fn(async(_request:NativeSaveRequest)=>({documentId:identity.documentId,revision:2,parentRevision:1,revisionRegistered:true,editor:{openUrl:'/saved'},artifacts:{xlsx:{downloadUrl:'/saved.xlsx'}},validation:{ok:true,issues:[]}})),current=await open(source,draft,save)
 try{
  const baseline=current.shell.statusLabel.textContent
  grid.ribbon('print-scale-open');expect(scaleInput().value).toBe('85');expect(document.querySelector('[data-print-scale-mode]')!.textContent).toMatch(/暂未生效/);confirm(85)
  await vi.waitFor(()=>expect(draft.operations).toEqual([{kind:'applyPageSetups',setups:[{sheetName:'Sheet1',fitToPage:false}]}]))
  expect(current.shell.statusLabel.textContent).not.toBe(baseline)
  grid.ribbon('print-scale-open');expect(scaleInput().value).toBe('85');const stable=JSON.stringify(draft.operations),status=current.shell.statusLabel.textContent;confirm(85);await new Promise(r=>setTimeout(r,150));expect(JSON.stringify(draft.operations)).toBe(stable);expect(current.shell.statusLabel.textContent).toBe(status)
  grid.ribbon('print-scale-open');confirm(125)
  await vi.waitFor(()=>expect(draft.operations).toEqual([{kind:'applyPageSetups',setups:[{sheetName:'Sheet1',scale:125,fitToPage:false}]}]))
  current.shell.save.click();await vi.waitFor(()=>expect(save).toHaveBeenCalledTimes(1));expect(save.mock.calls[0]![0].operations).toEqual([{kind:'applyPageSetups',setups:[{sheetName:'Sheet1',scale:125,fitToPage:false}]}])
 }finally{current.view?.dispose()}
})
it('rejects replaced workbook identity and readonly callbacks without creating a draft',async()=>{
 const source=await fixture(),draft=new NativeDraft(identity,store()),current=await open(source,draft,async()=>{throw Error('no save')})
 try{grid.ribbon('print-scale-open');expect(scaleInput()).not.toBeNull();const original=grid.api.getActiveWorkbook.bind(grid.api);const actual=original();grid.api.getActiveWorkbook=()=>new Proxy(actual,{get:(target,key)=>key==='getWorkbook'?()=>({}):Reflect.get(target,key,target)});confirm(125);expect(document.querySelector('.workbook-print-scale-dialog [role="alert"]')!.textContent).toMatch(/变化/);expect(draft.operations).toEqual([]);grid.api.getActiveWorkbook=original
 }finally{current.view?.dispose()}
 const readonlyDraft=new NativeDraft(identity,store()),readonly=await open(source,readonlyDraft,async()=>{throw Error('no save')},undefined,false)
 try{readonly.shell.editor.inert=true;grid.ribbon('print-scale-open');expect(document.querySelector<HTMLElement>('.workbook-print-scale-overlay')!.hidden).toBe(true);expect(readonlyDraft.operations).toEqual([])}finally{readonly.view?.dispose()}
})

it('retains original print baseline by stable sheet identity after rename and saves against the renamed sheet',async()=>{
 const source=await applyPageSetups(await fixture(),[{sheetName:'Sheet1',scale:85,fitToPage:true,fitToWidth:2,fitToHeight:3}]),draft=new NativeDraft(identity,store()),current=await open(source,draft,async()=>{throw Error('no save')})
 try{expect(sheet().setName('Renamed')).toBeTruthy();grid.ribbon('print-scale-open');expect(scaleInput().value).toBe('85');expect(document.querySelector('[data-print-scale-mode]')!.textContent).toMatch(/暂未生效/);confirm(125);await vi.waitFor(()=>expect(draft.operations.find(op=>op.kind==='applyPageSetups')).toEqual({kind:'applyPageSetups',setups:[{sheetName:'Renamed',scale:125,fitToPage:false}]}));const reopened=await readWorkbook(await applyWorkbookOperations(source,draft.operations));expect(reopened.sheets[0]!.name).toBe('Renamed');expect(reopened.sheets[0]!.pageSetup).toMatchObject({scale:125,fitToWidth:2,fitToHeight:3});expect(reopened.sheets[0]!.pageSetup?.fitToPage??false).toBe(false)}finally{current.view?.dispose()}
})

it('blocks protected sheets before opening print scale without writes',async()=>{const source=await protectSheet(await fixture(),'Sheet1',true),draft=new NativeDraft(identity,store()),current=await open(source,draft,async()=>{throw Error('no save')});try{grid.ribbon('print-scale-open');expect(document.querySelector<HTMLElement>('.workbook-print-scale-overlay')!.hidden).toBe(true);expect(current.shell.editor.querySelector('.workbook-feedback')!.textContent).toMatch(/保护/);expect(draft.operations).toEqual([])}finally{current.view?.dispose()}})
