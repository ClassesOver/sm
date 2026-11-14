import { expect, it, vi } from 'vitest'
import { ICommandService } from '@univerjs/core'
import { applyCellEdits, applyPageSetups, applySheetEdits, applySparklines, createBlankWorkbook, readWorkbook, protectSheet } from '@sheets-web/xlsx-engine'
import { assemblePackage, createBufferEntrySource } from '@sheets-web/xlsx-engine/zip'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { chartAdditionFromGrid } from './workbook-chart-add'
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
// 此无画布宿主未注册 HoverManagerService；线程浮层由专属浏览器测试覆盖。
vi.mock('./workbook-threaded-comments-host', () => ({ mountWorkbookThreads: () => ({ load() {}, dispose() {} }) }))
vi.mock('./workbook-note-pictures-host', async original => ({ ...await original<typeof import('./workbook-note-pictures-host')>(), installNotePictureHover: () => ({ dispose() {} }) }))
vi.mock('./workbook-vendor/grid/create-univer', async () => {
  const { Univer, IUniverInstanceService, LocaleType, mergeLocales } = await import('@univerjs/core')
  const CoreZhCN = (await import('@univerjs/preset-sheets-core/locales/zh-CN')).default
  const NoteZhCN = (await import('@univerjs/preset-sheets-note/locales/zh-CN')).default
  const { FUniver } = await import('@univerjs/core/lib/facade')
  const { UniverSheetsPlugin } = await import('@univerjs/sheets')
  const { UniverSheetsFilterPlugin } = await import('@univerjs/sheets-filter')
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
  await import('@univerjs/sheets-filter/facade')
  // mock的table preset不会执行其官方facade副作用，补齐实际运行时的表格接口。
  await import('@univerjs/sheets-table/facade')
  await import('@univerjs/sheets-conditional-formatting/facade')
  return { createUniver: () => {
    const univer = new Univer({ locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: mergeLocales(CoreZhCN, NoteZhCN) } })
    grid.instances.push(univer)
    univer.registerPlugin(UniverSheetsPlugin)
    univer.registerPlugin(UniverSheetsNotePlugin)
    univer.registerPlugin(UniverSheetsFilterPlugin)
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
const history = (direction: 'undo' | 'redo') => expect(grid.api.syncExecuteCommand(`univer.command.${direction}`)).toBe(true)

it('collects a real sparkline addition once through draft, Undo/Redo, save and reloaded draft', async () => {
 const restoredDraft=new NativeDraft(identity,store())
 const source=await fixture(),draft=new NativeDraft(identity,store()),save=vi.fn(async(_request:NativeSaveRequest)=>({documentId:identity.documentId,revision:2,parentRevision:1,revisionRegistered:true,editor:{openUrl:'/saved'},artifacts:{xlsx:{downloadUrl:'/saved.xlsx'}},validation:{ok:true,issues:[]}})),current=await open(source,draft,save)
 try {
  sheet().getRange('A1:B1').activate()
  grid.ribbon('sparkline:line')
  await vi.waitFor(()=>expect(draft.operations.filter(op=>op.kind==='appendSheetSparklines')).toHaveLength(1))
  const operation=draft.operations.find(op=>op.kind==='appendSheetSparklines')!
  expect(operation).toEqual({kind:'appendSheetSparklines',sheetName:'Sheet1',groups:[{type:'line',cells:[{cell:'C1',sourceRef:'Sheet1!$A$1:$B$1'}]}]})
  history('undo');await vi.waitFor(()=>expect(draft.operations).toEqual([]))
  history('redo');await vi.waitFor(()=>expect(draft.operations.filter(op=>op.kind==='appendSheetSparklines')).toEqual([operation]))
  const bytes=await applyWorkbookOperations(source,draft.operations)
  const reopened=await readWorkbook(bytes)
  expect(reopened.sheets[0]!.sparklines).toHaveLength(1)
  restoredDraft.setOperations(draft.operations)
  current.shell.save.click();await vi.waitFor(()=>expect(save).toHaveBeenCalledTimes(1))
  expect(save.mock.calls[0]![0].operations.filter(op=>op.kind==='appendSheetSparklines')).toEqual([operation])
 } finally {current.view?.dispose()}
 const restored=await open(source,restoredDraft,async()=>{throw Error('no save')})
 try {
  sheet().getRange('A2:B2').activate();grid.ribbon('sparkline:column')
  await vi.waitFor(()=>expect(restoredDraft.operations.filter(op=>op.kind==='appendSheetSparklines')).toHaveLength(2))
  const reopened=await readWorkbook(await applyWorkbookOperations(source,restoredDraft.operations))
  expect(reopened.sheets[0]!.sparklines).toHaveLength(2)
 } finally {restored.view?.dispose()}
})

it('rejects protected and readonly sparkline commands without drafts', async()=>{
 for(const protectedSheet of [false,true]) {
  const source=protectedSheet?await protectSheet(await fixture(),'Sheet1',true):await fixture()
  const draft=new NativeDraft(identity,store()),current=await open(source,draft,async()=>{throw Error('no save')},undefined,protectedSheet)
  try {sheet().getRange('A1:B1').activate();grid.ribbon('sparkline:line');expect(draft.operations).toEqual([])}finally{current.view?.dispose()}
 }
})

it('keeps renamed additions bound to the sheet and rejects structure before changing the grid', async()=>{
 const source=await fixture(),draft=new NativeDraft(identity,store()),current=await open(source,draft,async()=>{throw Error('no save')})
 try {
  sheet().getRange('A1:B1').activate();grid.ribbon('sparkline:stacked')
  await vi.waitFor(()=>expect(draft.operations).toHaveLength(1))
  const rows=sheet().getMaxRows(),value=sheet().getRange('A1').getValue()
  const commands=grid.instances.at(-1).__getInjector().get(ICommandService) as any
  const stackSize=commands._commandExecutionStack.length
  sheet().insertRowsBefore(0,1)
  expect(commands._commandExecutionStack).toHaveLength(stackSize)
  expect(sheet().getMaxRows()).toBe(rows)
  expect(sheet().getRange('A1').getValue()).toBe(value)
  expect(current.shell.editor.querySelector('.workbook-feedback')!.textContent).toMatch(/迷你图/)
  expect(sheet().setName("中文 '数据")).toBeTruthy()
  await vi.waitFor(()=>expect(draft.operations.find(op=>op.kind==='appendSheetSparklines')?.sheetName).toBe("中文 '数据"))
  const result=await readWorkbook(await applyWorkbookOperations(source,draft.operations))
  expect(result.sheets[0]!.name).toBe("中文 '数据")
  expect(result.sheets[0]!.sparklines).toHaveLength(1)
 } finally {current.view?.dispose()}
})

it('rejects cross-sheet source moves after rename without leaving a command on the stack', async()=>{
 let source=await applySheetEdits(await fixture(),{renames:[],additions:[{name:'Source'}],removals:[],order:['Sheet1','Source']})
 source=await applySparklines(source,'Sheet1',[{kind:'line',source:'A1:B1',target:'C1'}])
 const archive=await createBufferEntrySource(source),path='xl/worksheets/sheet1.xml'
 const xml=(await archive.readText(path)).replace('<xm:f>A1:B1</xm:f>','<xm:f>Source!$A$1:$B$1</xm:f>')
 source=(await assemblePackage(source,{replaced:new Map([[path,xml]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer
 const draft=new NativeDraft(identity,store()),current=await open(source,draft,async()=>{throw Error('no save')})
 try {
  const target=grid.api.getActiveWorkbook().getSheetBySheetId('sheet-1')
  expect(target.setName('Renamed Source')).toBeTruthy()
  grid.api.getActiveWorkbook().setActiveSheet(target)
  const rows=target.getMaxRows(),commands=grid.instances.at(-1).__getInjector().get(ICommandService) as any,depth=commands._commandExecutionStack.length
  target.insertRowsBefore(0,1)
  expect(target.getMaxRows()).toBe(rows)
  expect(commands._commandExecutionStack).toHaveLength(depth)
  expect(current.shell.editor.querySelector('.workbook-feedback')!.textContent).toMatch(/迷你图/)
 }finally{current.view?.dispose()}
})

it('keeps the full format pane bound across real doughnut edits, history and save', async()=>{
 const source=await applyWorkbookOperations(await fixture(),[{kind:'applyChartAdditions',additions:[chartAdditionFromGrid({sheetName:'Sheet1',chartType:'doughnut',title:'收入',range:{startRow:0,endRow:1,startColumn:0,endColumn:1},values:[['分类','收入'],['甲',2]]})]}])
 const draft=new NativeDraft(identity,store()),save=vi.fn(async(_request:NativeSaveRequest)=>({documentId:identity.documentId,revision:2,parentRevision:1,revisionRegistered:true,editor:{openUrl:'/saved'},artifacts:{xlsx:{downloadUrl:'/saved.xlsx'}},validation:{ok:true,issues:[]}})),current=await open(source,draft,save)
 try {
  grid.ribbon('chart-format-pane')
  const release=(name:string,value:string)=>{const input=document.querySelector<HTMLInputElement>(`[aria-label="${name}"]`)!;expect(input).not.toBeNull();input.value=value;input.dispatchEvent(new Event('pointerup',{bubbles:true}))}
  release('圆环内径','70');await vi.waitFor(()=>expect(draft.operations.filter(op=>op.kind==='applyChartEdits')).toHaveLength(1))
  release('饼图分离度','25');await vi.waitFor(()=>expect(draft.operations.filter(op=>op.kind==='applyChartEdits')).toHaveLength(2))
  const reread=async()=> (await readWorkbook(await applyWorkbookOperations(source,draft.operations))).sheets[0]!.charts![0]!
  expect(await reread()).toMatchObject({holeSizePct:70,series:[{explosionPct:25}]})
  await vi.waitFor(()=>expect(document.querySelector('.workbook-chart-format-pane')?.getAttribute('aria-busy')).toBeNull())
  grid.ribbon('undo');await vi.waitFor(()=>expect(draft.operations.filter(op=>op.kind==='applyChartEdits')).toHaveLength(1))
  await vi.waitFor(()=>expect(current.shell.editor.inert).not.toBe(true));grid.ribbon('redo');await vi.waitFor(()=>expect(draft.operations.filter(op=>op.kind==='applyChartEdits')).toHaveLength(2))
  await vi.waitFor(()=>expect(current.shell.editor.inert).not.toBe(true));current.shell.save.click();await vi.waitFor(()=>expect(save).toHaveBeenCalledOnce());expect((await readWorkbook(await applyWorkbookOperations(source,save.mock.calls[0]![0].operations))).sheets[0]!.charts![0]).toMatchObject({holeSizePct:70,series:[{explosionPct:25}]})
 } finally {current.view?.dispose()}
})

it('edits chart axis titles and data labels through Chart Design and saves the OOXML parts', async()=>{
 let source=await applyWorkbookOperations(await fixture(),[{kind:'applyChartAdditions',additions:[chartAdditionFromGrid({
  sheetName:'Sheet1',chartType:'column',range:{startRow:0,endRow:1,startColumn:0,endColumn:1},values:[['Quarter','Sales'],['Q1',2]]
 })]}])
 const draft=new NativeDraft(identity,store()),current=await open(source,draft,async()=>{throw Error('no save')})
 try {
  grid.ribbon('chart-axis-cat')
  document.querySelector<HTMLInputElement>('[aria-label="分类轴标题"]')!.value='季度'
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  await vi.waitFor(()=>expect(draft.operations.some(op=>op.kind==='applyChartEdits')).toBe(true))
  grid.ribbon('chart-labels')
  document.querySelector<HTMLSelectElement>('[aria-label="数据标签"]')!.value='value'
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  await vi.waitFor(()=>expect(draft.operations.filter(op=>op.kind==='applyChartEdits').flatMap(op=>op.edits)).toHaveLength(2))
  grid.ribbon('chart-format-pane')
  document.querySelector<HTMLSelectElement>('.workbook-chart-format-pane [aria-label="图表分组"]')!.value='stacked'
  document.querySelector<HTMLSelectElement>('.workbook-chart-format-pane [aria-label="图表分组"]')!.dispatchEvent(new Event('change',{bubbles:true}))
  await vi.waitFor(()=>expect(draft.operations.filter(op=>op.kind==='applyChartEdits').flatMap(op=>op.edits)).toHaveLength(3))
  const gridlines=document.querySelector<HTMLInputElement>('.workbook-chart-format-pane [aria-label="显示主网格线"]')!;gridlines.checked=true;gridlines.dispatchEvent(new Event('change',{bubbles:true}))
  await vi.waitFor(()=>expect(draft.operations.filter(op=>op.kind==='applyChartEdits').flatMap(op=>op.edits)).toHaveLength(4))
  const saved=await applyWorkbookOperations(source,draft.operations)
  const archive=await createBufferEntrySource(saved),xml=await archive.readText('xl/charts/chart1.xml')
  expect(xml).toContain('<c:tx><c:rich>')
  expect(xml).toContain('季度')
  expect(xml).toContain('<c:dLbls>')
  expect(xml).toContain('<c:showVal val="1"/>')
  expect(xml).toContain('<c:grouping val="stacked"/>')
  expect(xml).toContain('<c:majorGridlines/>')
 } finally {current.view?.dispose()}
})

it('routes Scatter axis-title dialogs and the value pane to the same native X/Y identities',async()=>{
 const source=await applyWorkbookOperations(await fixture(),[{kind:'applyChartAdditions',additions:[chartAdditionFromGrid({
  sheetName:'Sheet1',chartType:'scatter',range:{startRow:0,endRow:2,startColumn:0,endColumn:1},values:[['X','Y'],[1,2],[3,4]],
 })]}])
 const draft=new NativeDraft(identity,store()),current=await open(source,draft,async()=>{throw Error('no save')})
 try{
  for(const [command,label,value]of [['chart-axis-cat','分类轴标题','Elapsed'],['chart-axis-val','数值轴标题','Revenue']] as const){
   grid.ribbon(command)
   const input=document.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)
   expect(input).not.toBeNull();input!.value=value
   document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
   await vi.waitFor(()=>expect(current.shell.editor.querySelector('[data-chart-design-submit]')?.closest('[role="dialog"]')?.hasAttribute('hidden')).toBe(true))
  }
  grid.ribbon('chart-format-pane')
  const maximum=document.querySelector<HTMLInputElement>('.workbook-chart-format-pane [aria-label="最大值"]')!
  maximum.value='10';maximum.dispatchEvent(new Event('blur'))
  await vi.waitFor(()=>expect(draft.operations.filter(op=>op.kind==='applyChartEdits')).toHaveLength(3))
  const chart=(await readWorkbook(await applyWorkbookOperations(source,draft.operations))).sheets[0]!.charts![0]!
  expect(chart.axes).toMatchObject({category:{title:'Elapsed'},value:{title:'Revenue',scaling:{max:10}}})
  expect(chart.axes!.category.scaling?.max).toBeUndefined()
  expect(chart.design?.axisTitles).toEqual({category:'Elapsed',value:'Revenue'})
 }finally{current.view?.dispose()}
})

it('format pane rejects replaced workbook, protected and readonly targets without a chart draft',async()=>{
 const bytes=await applyWorkbookOperations(await fixture(),[{kind:'applyChartAdditions',additions:[chartAdditionFromGrid({sheetName:'Sheet1',chartType:'doughnut',range:{startRow:0,endRow:1,startColumn:0,endColumn:1},values:[['分类','收入'],['甲',2]]})]}])
 for(const mode of ['replaced','protected','readonly']){const source=mode==='protected'?await protectSheet(bytes,'Sheet1',true):bytes,draft=new NativeDraft(identity,store()),current=await open(source,draft,async()=>{throw Error('no save')},undefined,mode!=='readonly');try{if(mode==='readonly')current.shell.editor.inert=true;grid.ribbon('chart-format-pane');if(mode==='replaced'){const original=grid.api.getActiveWorkbook.bind(grid.api),actual=original();grid.api.getActiveWorkbook=()=>new Proxy(actual,{get:(target,key)=>key==='getWorkbook'?()=>({}):Reflect.get(target,key,target)});const range=document.querySelector<HTMLInputElement>('.workbook-chart-format-pane [aria-label=圆环内径]')!;range.value='70';range.dispatchEvent(new Event('pointerup',{bubbles:true}));await vi.waitFor(()=>expect(document.querySelector('.workbook-chart-format-pane [role=alert]')!.textContent).toContain('变化'));grid.api.getActiveWorkbook=original}else expect(document.querySelector('.workbook-chart-format-pane:not([hidden])')).toBeNull();expect(draft.operations.filter(op=>op.kind==='applyChartEdits')).toEqual([])}finally{current.view?.dispose()}}
})

it('edits a user chart title and legend position only after confirmation', async()=>{
 const source=await applyWorkbookOperations(await fixture(),[{kind:'applyChartAdditions',additions:[chartAdditionFromGrid({
  sheetName:'Sheet1',chartType:'column',title:'原始标题',range:{startRow:0,endRow:1,startColumn:0,endColumn:1},values:[['Quarter','Sales'],['Q1',2]]
 })]}])
 const draft=new NativeDraft(identity,store()),current=await open(source,draft,async()=>{throw Error('no save')})
 try {
  grid.ribbon('chart-title')
  const input=document.querySelector<HTMLInputElement>('[aria-label="图表标题"]')!
  expect(input.value).toBe('原始标题')
  input.value='取消的标题'
  document.querySelector<HTMLButtonElement>('[data-chart-design-cancel]')!.click()
  expect(draft.operations).toEqual([])
  sheet().getRange('J2').setValue(77)
  grid.ribbon('chart-title')
  document.querySelector<HTMLInputElement>('[aria-label="图表标题"]')!.value='销售 & 订单'
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  await vi.waitFor(()=>expect(draft.operations.filter(op=>op.kind==='applyChartEdits')).toHaveLength(1))
  grid.ribbon('chart-legend')
  document.querySelector<HTMLSelectElement>('[aria-label="图例位置"]')!.value='bottom'
  document.querySelector<HTMLButtonElement>('[data-chart-design-submit]')!.click()
  await vi.waitFor(()=>expect(draft.operations.filter(op=>op.kind==='applyChartEdits')).toHaveLength(2))
  const bytes=await applyWorkbookOperations(source,draft.operations)
  expect(sheet().getRange('J2').getValue()).toBe(77)
  expect((await readWorkbook(bytes)).sheets[0]!.charts![0]!.title).toBe('销售 & 订单')
  expect(await (await createBufferEntrySource(bytes)).readText('xl/charts/chart1.xml')).toContain('<c:legendPos val="b"/>')
 } finally {current.view?.dispose()}
})

it('switches chart rows and columns using source references rather than the active selection', async()=>{
 const values=[['', 'North', 'South'], ['Q1',10,20], ['Q2',30,40]]
 let source=await applyCellEdits(await createBlankWorkbook(),values.flatMap((row,r)=>row.map((value,c)=>({sheetName:'Sheet1',row:r,column:c,writeValue:true,cell:{value}}))))
 source=await applyWorkbookOperations(source,[{kind:'applyChartAdditions',additions:[{
  worksheetSheetName:'Sheet1',anchor:{fromRow:0,fromColumn:4,fromRowOffset:0,fromColumnOffset:0,toRow:15,toColumn:10,toRowOffset:0,toColumnOffset:0},
  chart:{chartType:'column',title:'Sales',series:[1,2].map(c=>({name:String(values[0]![c]),categories:['Q1','Q2'],values:[Number(values[1]![c]),Number(values[2]![c])],categoriesRef:"'Sheet1'!$A$2:$A$3",valuesRef:`'Sheet1'!$${c===1?'B':'C'}$2:$${c===1?'B':'C'}$3`}))}
 }]}])
 const draft=new NativeDraft(identity,store()),current=await open(source,draft,async()=>{throw Error('no save')})
 try {
  sheet().getRange('B2').setValue(99)
  sheet().getRange('J10').activate();grid.ribbon('chart-switch-row-col')
  await vi.waitFor(()=>expect(draft.operations.filter(op=>op.kind==='applyChartEdits')).toHaveLength(1))
  const saved=await applyWorkbookOperations(source,draft.operations),chart=(await readWorkbook(saved)).sheets[0]!.charts![0]!
  expect(chart.series).toMatchObject([{name:'Q1',valuesRef:"'Sheet1'!$B$2:$C$2"},{name:'Q2',valuesRef:"'Sheet1'!$B$3:$C$3"}])
  expect(sheet().getRange('B2').getValue()).toBe(99)
  grid.ribbon('chart-switch-row-col')
  await vi.waitFor(()=>expect(draft.operations.filter(op=>op.kind==='applyChartEdits')).toHaveLength(2))
  const restored=(await readWorkbook(await applyWorkbookOperations(source,draft.operations))).sheets[0]!.charts![0]!
  expect(restored.series).toMatchObject([{name:'North',valuesRef:"'Sheet1'!$B$2:$B$3"},{name:'South',valuesRef:"'Sheet1'!$C$2:$C$3"}])
 } finally {current.view?.dispose()}
})

it('combo Select Data preserves manual draft through cancel UndoRedo replay and native save', async()=>{
 const values=[['Quarter','North','Rate'],['Q1',10,200],['Q2',20,400]]
 let source=await applyCellEdits(await createBlankWorkbook(),values.flatMap((row,r)=>row.map((value,c)=>({sheetName:'Sheet1',row:r,column:c,writeValue:true,cell:{value}}))))
 source=await applyWorkbookOperations(source,[{kind:'applyChartAdditions',additions:[{
  worksheetSheetName:'Sheet1',anchor:{fromRow:4,fromColumn:4,toRow:19,toColumn:12,fromRowOffset:0,fromColumnOffset:0,toRowOffset:0,toColumnOffset:0},
  chart:{chartType:'combo',title:'Native combo',series:['North','Rate'].map((name,index)=>({name,values:index?[200,400]:[10,20],categories:['Q1','Q2'],valuesRef:`'Sheet1'!$${index?'C':'B'}$2:$${index?'C':'B'}$3`,categoriesRef:"'Sheet1'!$A$2:$A$3"}))}
 }]}])
 const storage=store(),draft=new NativeDraft(identity,storage),current=await open(source,draft,async()=>{throw Error('no save')})
 try{
  sheet().getRange('J2').setValue('Keep combo manual')
  await vi.waitFor(()=>expect(draft.operations.length).toBeGreaterThan(0))
  grid.ribbon('chart-select-data');expect(current.shell.editor.querySelector('.workbook-feedback')!.textContent).not.toContain('组合图暂不支持');await vi.waitFor(()=>expect(document.querySelector('[role=dialog]:not([hidden]) [data-chart-data-plot]')).not.toBeNull(),{timeout:10000})
  const before=structuredClone(draft.operations)
  document.querySelector<HTMLButtonElement>('[data-chart-data-cancel]')!.click();expect(draft.operations).toEqual(before)
  grid.ribbon('chart-select-data');await vi.waitFor(()=>expect(document.querySelector('[role=dialog]:not([hidden]) [data-chart-data-plot]')).not.toBeNull(),{timeout:10000})
  const rows=document.querySelectorAll('[data-chart-data-row]')
  const first=rows[0]!.querySelector<HTMLSelectElement>('[data-chart-data-plot]')!;first.value='lineChart';first.dispatchEvent(new Event('change'))
  const second=rows[1]!.querySelector<HTMLSelectElement>('[data-chart-data-plot]')!;second.value='barChart';second.dispatchEvent(new Event('change'))
  document.querySelector<HTMLFormElement>('.workbook-chart-data-dialog form')!.dispatchEvent(new Event('submit',{cancelable:true}))
  await vi.waitFor(()=>{if(draft.operations.filter(op=>op.kind==='applyChartEdits').length!==1)throw Error(`等待组合图: ${document.querySelector('.workbook-chart-data-dialog [role=alert]')?.textContent}; ${document.querySelector('.workbook-feedback')?.textContent}`)},{timeout:10000})
  await vi.waitFor(()=>expect(document.querySelector('[role=dialog]:not([hidden]) [data-chart-data-plot]')).toBeNull(),{timeout:10000})
  grid.ribbon('undo');await vi.waitFor(()=>expect(draft.operations.filter(op=>op.kind==='applyChartEdits')).toHaveLength(0),{timeout:10000});expect(sheet().getRange('J2').getValue()).toBe('Keep combo manual')
  await vi.waitFor(()=>expect(current.shell.editor.inert).not.toBe(true),{timeout:10000})
  grid.ribbon('redo');await vi.waitFor(()=>expect(draft.operations.filter(op=>op.kind==='applyChartEdits')).toHaveLength(1),{timeout:10000});expect(sheet().getRange('J2').getValue()).toBe('Keep combo manual')
  await vi.waitFor(()=>expect(current.shell.editor.inert).not.toBe(true),{timeout:10000})
 }finally{current.view?.dispose()}
 const restored=new NativeDraft(identity,storage);let saved:Uint8Array|undefined
 const save=vi.fn(async(request:NativeSaveRequest)=>{saved=await applyWorkbookOperations(source,request.operations);return {documentId:identity.documentId,revision:2,parentRevision:1,revisionRegistered:true,editor:{openUrl:'/saved'},artifacts:{xlsx:{downloadUrl:'/saved.xlsx'}},validation:{ok:false,issues:[{code:'native_source_review_pending'}]}}})
 const reopened=await open(source,restored,save)
 try{
  expect(sheet().getRange('J2').getValue()).toBe('Keep combo manual')
  grid.ribbon('chart-select-data');await vi.waitFor(()=>expect(document.querySelector('[role=dialog]:not([hidden]) [data-chart-data-plot]')).not.toBeNull(),{timeout:10000})
  expect([...document.querySelectorAll<HTMLSelectElement>('[data-chart-data-plot]')].map(node=>node.value)).toEqual(['lineChart','barChart'])
  expect([...document.querySelectorAll<HTMLInputElement>('[data-chart-data-secondary]')].map(node=>node.checked)).toEqual([false,true])
  document.querySelector<HTMLButtonElement>('[data-chart-data-cancel]')!.click();reopened.shell.save.click()
  await vi.waitFor(()=>expect(saved).toBeDefined(),{timeout:10000});expect(save).toHaveBeenCalledTimes(1)
  const model=await readWorkbook(saved!);expect(model.sheets[0]!.cells.J2!.value).toBe('Keep combo manual')
  expect(model.sheets[0]!.charts![0]!.series).toMatchObject([{name:'North',plot:'lineChart',secondaryAxis:false},{name:'Rate',plot:'barChart',secondaryAxis:true}])
 }finally{reopened.view?.dispose()}
}, 30000)

it('opens Select Data without mutating and applies named series vectors through the existing writer', async()=>{
 let source=await applyCellEdits(await fixture(),[
  {sheetName:'Sheet1',row:0,column:2,writeValue:true,cell:{value:'Period'}},
  {sheetName:'Sheet1',row:0,column:3,writeValue:true,cell:{value:'Orders'}},
  {sheetName:'Sheet1',row:1,column:2,writeValue:true,cell:{value:'Q2'}},
  {sheetName:'Sheet1',row:1,column:3,writeValue:true,cell:{value:12}},
 ])
 source=await applyWorkbookOperations(source,[{kind:'applyChartAdditions',additions:[chartAdditionFromGrid({
  sheetName:'Sheet1',chartType:'column',range:{startRow:0,endRow:1,startColumn:0,endColumn:1},values:[['Quarter','Sales'],['Q1',2]]
 })]}])
 const draft=new NativeDraft(identity,store()),current=await open(source,draft,async()=>{throw Error('no save')})
 try {
  grid.api.getActiveWorkbook().setActiveRange(sheet().getRange('C1:D2'))
  const selected=sheet().getSelection().getActiveRange()!
  expect([selected.getRow(),selected.getColumn(),selected.getHeight(),selected.getWidth()]).toEqual([0,2,2,2])
  expect(selected.getRange()).toMatchObject({startRow:0,endRow:1,startColumn:2,endColumn:3})
  grid.ribbon('chart-select-data')
  await vi.waitFor(()=>expect(document.querySelector('[data-chart-data-name]')).not.toBeNull())
  expect(draft.operations.filter(op=>op.kind==='applyChartEdits')).toHaveLength(0)
  const set=(field:string,value:string)=>{const input=document.querySelector<HTMLInputElement>(`[data-chart-data-${field}]`)!;input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}))}
  set('name','Orders');set('values','D2');set('categories','C2')
  document.querySelector<HTMLFormElement>('.workbook-chart-data-dialog form')!.dispatchEvent(new Event('submit',{cancelable:true}))
  await vi.waitFor(()=>{
   const edits=draft.operations.filter(op=>op.kind==='applyChartEdits').flatMap(op=>op.edits)
   if(edits.length!==1)throw Error(`等待系列应用: ${document.querySelector('.workbook-chart-data-dialog [role=alert]')?.textContent}; ${document.querySelector('.workbook-feedback')?.textContent}`)
  },{timeout:10000})
  const saved=await applyWorkbookOperations(source,draft.operations)
  const xml=await (await createBufferEntrySource(saved)).readText('xl/charts/chart1.xml')
  expect(draft.operations.find(op=>op.kind==='applyChartEdits')!.edits).toEqual([expect.objectContaining({
   seriesSet: [expect.objectContaining({name:'Orders',categoriesRef: "'Sheet1'!$C$2:$C$2", valuesRef: "'Sheet1'!$D$2:$D$2"})],
  })])
  expect(xml).toContain('<c:v>Q2</c:v>')
  expect(xml).toContain('<c:v>12</c:v>')
 } finally {current.view?.dispose()}
})

it('Select Data rejects replaced workbook identity while keeping the existing manual draft',async()=>{
 const source=await applyWorkbookOperations(await fixture(),[{kind:'applyChartAdditions',additions:[chartAdditionFromGrid({sheetName:'Sheet1',chartType:'column',range:{startRow:0,endRow:0,startColumn:0,endColumn:1},values:[[2,6]]})]}])
 const draft=new NativeDraft(identity,store()),current=await open(source,draft,async()=>{throw Error('no save')})
 try{
  sheet().getRange('J2').setValue('Keep manual')
  await vi.waitFor(()=>expect(draft.operations.length).toBeGreaterThan(0))
  grid.ribbon('chart-select-data');await vi.waitFor(()=>expect(document.querySelector('[data-chart-data-name]')).not.toBeNull(),{timeout:10000})
  const before=structuredClone(draft.operations),original=grid.api.getActiveWorkbook.bind(grid.api),actual=original()
  grid.api.getActiveWorkbook=()=>new Proxy(actual,{get:(target,key)=>key==='getWorkbook'?()=>({}):Reflect.get(target,key,target)})
  document.querySelector<HTMLFormElement>('.workbook-chart-data-dialog form')!.dispatchEvent(new Event('submit',{cancelable:true}))
  await vi.waitFor(()=>expect(document.querySelector('.workbook-chart-data-dialog [role=alert]')!.textContent).toContain('变化'))
  expect(draft.operations).toEqual(before);grid.api.getActiveWorkbook=original
 }finally{current.view?.dispose()}
})

it('Select Data transposes cached series, saves literal values and reopens the same data',async()=>{
 const source=await applyWorkbookOperations(await fixture(),[{kind:'applyChartAdditions',additions:[chartAdditionFromGrid({sheetName:'Sheet1',chartType:'column',range:{startRow:0,endRow:0,startColumn:0,endColumn:1},values:[[2,6]]})]}])
 const draft=new NativeDraft(identity,store()),current=await open(source,draft,async()=>{throw Error('no save')})
 try{
  grid.ribbon('chart-select-data');await vi.waitFor(()=>expect(document.querySelector('[data-chart-data-switch]')).not.toBeNull(),{timeout:10000})
  document.querySelector<HTMLButtonElement>('[data-chart-data-switch]')!.click()
  await vi.waitFor(()=>expect(draft.operations.some(op=>op.kind==='applyChartEdits')).toBe(true),{timeout:10000})
  const saved=(await readWorkbook(await applyWorkbookOperations(source,draft.operations))).sheets[0]!.charts![0]!
  expect(saved.series.length).toBeGreaterThan(0);expect(saved.series.every(entry=>entry.valuesRef===''&&entry.values!==undefined)).toBe(true)
  grid.ribbon('chart-select-data');await vi.waitFor(()=>expect(document.querySelector('[data-chart-data-name]')).not.toBeNull(),{timeout:10000})
  const before=structuredClone(draft.operations);document.querySelector<HTMLButtonElement>('[data-chart-data-cancel]')!.click();expect(draft.operations).toEqual(before)
 }finally{current.view?.dispose()}
})

it('edits an existing sparkline through the actual FRange facade and rejects moved selection',async()=>{
 const source=await applySparklines(await fixture(),'Sheet1',[{kind:'line',source:'A1:B1',target:'C1'}])
 const draft=new NativeDraft(identity,store()),current=await open(source,draft,async()=>{throw Error('no save')})
 try{
  grid.api.getActiveWorkbook().setActiveRange(sheet().getRange('C1'))
  expect(sheet().getSelection().getActiveRange().getRange()).toMatchObject({startRow:0,startColumn:2})
  grid.ribbon('sparkline:edit')
  const type=document.querySelector<HTMLSelectElement>('[aria-label="迷你图类型"]')
  expect(type).not.toBeNull();type!.value='column'
  type!.closest('form')!.dispatchEvent(new Event('submit',{cancelable:true}))
  await vi.waitFor(()=>expect(draft.operations.some(op=>op.kind==='editSheetSparklineGroup')).toBe(true))
  const saved=await readWorkbook(await applyWorkbookOperations(source,draft.operations))
  expect(saved.sheets[0]!.sparklines?.[0]?.kind).toBe('column')
  grid.ribbon('sparkline:edit')
  const next=document.querySelector<HTMLSelectElement>('[aria-label="迷你图类型"]')!
  grid.api.getActiveWorkbook().setActiveRange(sheet().getRange('D1'))
  const before=JSON.stringify(draft.operations);next.value='stacked';next.closest('form')!.dispatchEvent(new Event('submit',{cancelable:true}))
  expect(next.closest('form')!.textContent).toContain('迷你图目标已变化')
  expect(JSON.stringify(draft.operations)).toBe(before)
 }finally{current.view?.dispose()}
})
