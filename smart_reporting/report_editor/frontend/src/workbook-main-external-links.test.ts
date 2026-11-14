import JSZip from '../../../reporting/workbook_engine/node_modules/jszip'
import {sha256Hex} from '@sheets-web/xlsx-engine/sha256'
import {applyWorkbookOperations} from '../../../reporting/workbook_engine/bridge/operations'
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
  const { UniverSheetsFilterPlugin } = await import('@univerjs/sheets-filter')
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
    file: async () => ({ bytes: source.slice().buffer as ArrayBuffer, sha256: draft.identity.sourceSha256, path }) })
  return { shell, view }
}
const sheet = () => grid.api.getActiveWorkbook().getActiveSheet()


it('runs full external links through native draft update undo redo save and package reopen',async()=>{
 const zip=await JSZip.loadAsync(await createBlankWorkbook())
 zip.file('xl/workbook.xml',(await zip.file('xl/workbook.xml')!.async('string')).replace('</workbook>','<externalReferences><externalReference r:id="ext1"/></externalReferences></workbook>'))
 zip.file('xl/_rels/workbook.xml.rels',(await zip.file('xl/_rels/workbook.xml.rels')!.async('string')).replace('</Relationships>','<Relationship Id="ext1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/externalLink" Target="externalLinks/externalLink1.xml"/></Relationships>'))
 zip.file('xl/externalLinks/externalLink1.xml','<externalLink xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><externalBook r:id="rId1"><sheetNames><sheetName val="Data"/></sheetNames></externalBook></externalLink>')
 zip.file('xl/externalLinks/_rels/externalLink1.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/externalLinkPath" Target="source.xlsx" TargetMode="External"/></Relationships>')
 zip.file('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><f>[1]Data!A1*2</f><v>6</v></c></row></sheetData></worksheet>')
 const source=await zip.generateAsync({type:'uint8array'}),external=await applyCellEdits(await createBlankWorkbook('Data'),[{sheetName:'Data',row:0,column:0,writeValue:true,cell:{value:12}}]),draft=new NativeDraft(identity,store())
 draft.setOperations([{kind:'bindExternalLinkSource',index:1,expectedTarget:'source.xlsx',name:'source.xlsx',mediaType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',size:external.length,sha256:await sha256Hex(external),bytesBase64:Buffer.from(external).toString('base64')}])
 let savedBytes:Uint8Array|undefined
 const save=vi.fn(async(request:NativeSaveRequest)=>{savedBytes=await applyWorkbookOperations(source,request.operations);return {documentId:identity.documentId,revision:2,parentRevision:1,revisionRegistered:true,validation:{ok:false,issues:[{code:'native_source_review_pending'}]},artifacts:{xlsx:{downloadUrl:'/saved.xlsx',sha256:await sha256Hex(savedBytes)}}}})
 const current=await open(source,draft,save)
 try{
  await vi.waitFor(()=>expect(sheet().getRange('A1').getValue()).toBe(6))
  grid.ribbon('external-links-panel');await vi.waitFor(()=>expect(current.shell.editor.querySelector('[data-external-update]')).not.toBeNull())
  ;(current.shell.editor.querySelector('[data-external-update]') as HTMLButtonElement).click()
  await vi.waitFor(()=>expect(current.shell.editor.querySelector('.workbook-external-links [role=status]')?.textContent).toContain('已更新 1 个值'),{timeout:5000})
  expect(sheet().getRange('A1').getValue()).toBe(24);expect(draft.operations.map(op=>op.kind)).toEqual(['bindExternalLinkSource','updateExternalLinkCaches'])
  grid.ribbon('undo');await vi.waitFor(()=>expect(sheet().getRange('A1').getValue()).toBe(6));grid.ribbon('redo');await vi.waitFor(()=>expect(sheet().getRange('A1').getValue()).toBe(24))
  current.shell.save.click();await vi.waitFor(()=>expect(save).toHaveBeenCalledTimes(1),{timeout:5000});await vi.waitFor(()=>expect(savedBytes).toBeDefined())
  const output=await JSZip.loadAsync(savedBytes!);expect(await output.file('xl/worksheets/sheet1.xml')!.async('string')).toContain('<f>[1]Data!A1*2</f><v>24</v>')
  await vi.waitFor(()=>expect(document.querySelector('a[href="/saved.xlsx"]')).not.toBeNull())
 }finally{current.view?.dispose()}
 const reopened=await open(savedBytes!,new NativeDraft({...identity,revision:2,sourceSha256:await sha256Hex(savedBytes!)},store()),vi.fn(async()=>{throw Error('unexpected')}))
 try{await vi.waitFor(()=>expect(sheet().getRange('A1').getValue()).toBe(24));expect(sheet().getRange('A1').getFormula()).toBe('=[1]Data!A1*2')}finally{reopened.view?.dispose()}
},20000)
