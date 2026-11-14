import { expect, it, vi } from 'vitest'
import { applyCellEdits, applyPageSetups, createBlankWorkbook } from '@sheets-web/xlsx-engine'
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
vi.mock('./workbook-formula-trace', async original => {
  const actual = await original<typeof import('./workbook-formula-trace')>()
  return { ...actual, installFormulaTraceOverlay: (_runtime: unknown, _sheet: unknown, plan: unknown) => { const layer = { plan, dispose: vi.fn() }; grid.layers.push(layer); return layer } }
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

it('runs trace and remove arrows on readonly sheets without draft/history edits and clears on worksheet edits', async () => {
  const draft = new NativeDraft(identity, store()), current = await open(await fixture(), draft, async () => { throw Error('unexpected save') }, undefined, false)
  try {
    const workbook = grid.api.getActiveWorkbook(), sheet = workbook.getActiveSheet()
    sheet.setActiveRange(sheet.getRange('B1'))
    const before = workbook.getSnapshot(), status = current.shell.statusLabel.textContent
    const { IUndoRedoService } = await import('@univerjs/core'), stack = grid.instances.at(-1).__getInjector().get(IUndoRedoService), undo = stack.pitchTopUndoElement()
    grid.ribbon('trace-precedents')
    expect(grid.layers).toHaveLength(1)
    expect(grid.layers[0].plan.highlights).toEqual([{startRow: 0,endRow: 0,startColumn: 0,endColumn: 0}])
    expect(grid.view.formulaTrace().active).toBe(true)
    expect(workbook.getSnapshot()).toEqual(before); expect(draft.operations).toEqual([]); expect(stack.pitchTopUndoElement()).toBe(undo); expect(current.shell.statusLabel.textContent).toBe(status)
    grid.ribbon('remove-arrows'); expect(grid.layers[0].dispose).toHaveBeenCalledTimes(1)
    expect(grid.view.formulaTrace().active).toBe(false)
    sheet.setActiveRange(sheet.getRange('A1'))
    grid.ribbon('trace-dependents')
    expect(grid.layers[1].plan.arrows).toEqual([{from:{row:0,column:0},to:{row:0,column:1}}])
    // 外部公式重算/视图变更也不能留下静态旧geometry，不产生额外文件操作。
    grid.api.syncExecuteCommand('sheet.mutation.set-worksheet-right-to-left', { unitId: workbook.getId(), subUnitId: sheet.getSheetId(), rightToLeft: 1 })
    expect(grid.layers[1].dispose).toHaveBeenCalledTimes(1)
  } finally { current.view?.dispose(); grid.layers.length = 0 }
})

it('opens watch window on readonly sheets without changing snapshot draft history or status', async()=>{
 const draft=new NativeDraft(identity,store()),current=await open(await fixture(),draft,async()=>{throw Error('unexpected save')},undefined,false)
 try{
  const workbook=grid.api.getActiveWorkbook(),sheet=workbook.getActiveSheet();sheet.setActiveRange(sheet.getRange('B1'))
  const before=workbook.getSnapshot(),status=current.shell.statusLabel.textContent
  const {IUndoRedoService}=await import('@univerjs/core'),stack=grid.instances.at(-1).__getInjector().get(IUndoRedoService),undo=stack.pitchTopUndoElement()
  grid.ribbon('watch-window');expect(document.querySelector('[data-watch-window]')).not.toBeNull()
  document.querySelector<HTMLButtonElement>('[data-watch-add]')!.click();expect(document.querySelector('[data-watch-row]')!.textContent).toContain('=A1*3')
  grid.ribbon('watch-window');grid.ribbon('watch-window');expect(document.querySelectorAll('[data-watch-row]')).toHaveLength(1)
  expect(workbook.getSnapshot()).toEqual(before);expect(draft.operations).toEqual([]);expect(stack.pitchTopUndoElement()).toBe(undo);expect(current.shell.statusLabel.textContent).toBe(status)
 }finally{current.view?.dispose()}
 expect(document.querySelector('[data-watch-window]')).toBeNull()
})

it('keeps watch controls and navigation outside the saved non-native grid lock without changing saved content', async () => {
  document.body.innerHTML = '<main id="app"></main>'
  const shell = createEditorShell(document.querySelector('#app')!, 'full', 'xlsx')
  const source = await fixture(), request = vi.fn(async () => ({
    revisionRegistered: true, revision: 2, xlsx: { downloadUrl: '/saved.xlsx' }, validation: { ok: true, issues: [] },
  }))
  const view = await createWorkbookEditorView(shell, {
    file: async () => ({ bytes: source.slice().buffer as ArrayBuffer, sha256: identity.sourceSha256 }),
    request: request as never,
  })
  try {
    shell.save.click()
    await vi.waitFor(() => expect(shell.save.disabled && shell.statusLabel.textContent?.includes('正在保存') === false).toBe(true))
    expect(shell.editor.inert).toBe(false)
    expect(shell.editor.querySelector<HTMLElement>('.workbook-grid')!.inert).toBe(true)
    expect(shell.editor.querySelector<HTMLFormElement>('form')!.inert).toBe(true)
    const workbook = grid.api.getActiveWorkbook(), sheet = workbook.getActiveSheet()
    sheet.setActiveRange(sheet.getRange('B1'))
    const before = workbook.getSnapshot(), status = shell.statusLabel.textContent
    grid.ribbon('watch-window')
    const panel = document.querySelector<HTMLElement>('[data-watch-window]')!
    // jsdom 不执行 inert 的浏览器交互屏蔽，逐级核对真实祖先属性和属性值。
    for (let element: HTMLElement | null = panel; element; element = element.parentElement) {
      expect(element.inert || element.hasAttribute('inert')).toBeFalsy()
    }
    panel.querySelector<HTMLButtonElement>('[data-watch-add]')!.click()
    expect(panel.querySelector('[data-watch-row]')!.textContent).toContain('=A1*3')
    panel.querySelector<HTMLButtonElement>('[data-watch-remove]')!.click()
    expect(panel.querySelector('[data-watch-row]')).toBeNull()
    panel.querySelector<HTMLButtonElement>('[data-watch-close]')!.click()
    expect(document.querySelector('[data-watch-window]')).toBeNull()
    expect(workbook.getSnapshot()).toEqual(before)
    expect(shell.statusLabel.textContent).toBe(status)
    expect(request).toHaveBeenCalledTimes(1)
  } finally { view?.dispose() }
})

it('marks watches gone after public facade sheet deletion and restores by real undo',async()=>{
 const current=await open(await fixture(),new NativeDraft(identity,store()),async()=>{throw Error('unexpected save')})
 try{
  const workbook=grid.api.getActiveWorkbook(),watched=workbook.getActiveSheet();watched.setActiveRange(watched.getRange('B1'))
  grid.ribbon('watch-window');document.querySelector<HTMLButtonElement>('[data-watch-add]')!.click()
  workbook.insertSheet('Other');await new Promise(resolve=>setTimeout(resolve,50));expect(workbook.deleteSheet(watched)).toBe(true)
  await new Promise(resolve=>setTimeout(resolve,850));expect(document.querySelector('[data-watch-row].watch-gone')).not.toBeNull()
  expect(grid.api.syncExecuteCommand('univer.command.undo')).toBe(true)
  await new Promise(resolve=>setTimeout(resolve,850));expect(document.querySelector('.watch-gone')).toBeNull();expect(document.querySelector('[data-watch-row]')!.textContent).toContain('=A1*3')
 }finally{current.view?.dispose()}
})
