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
const history = (direction: 'undo' | 'redo') => expect(grid.api.syncExecuteCommand(`univer.command.${direction}`)).toBe(true)

it('switches preview on a readonly sheet without history, snapshot or draft edits and clears its layer', async () => {
  const draft = new NativeDraft(identity, store()), current = await open(await fixture(), draft, async () => { throw Error('unexpected save') }, undefined, false)
  try {
    const workbook = grid.api.getActiveWorkbook(), before = workbook.getSnapshot()
    const { IUndoRedoService } = await import('@univerjs/core'), stack = grid.instances.at(-1).__getInjector().get(IUndoRedoService)
    const undo = stack.pitchTopUndoElement(), status = current.shell.statusLabel.textContent
    grid.ribbon('toggle-page-break-preview')
    await vi.waitFor(() => expect(grid.layers.length).toBeGreaterThan(0))
    expect(grid.view.pageBreakPreview().active).toBe(true)
    expect(workbook.getSnapshot()).toEqual(before); expect(draft.operations).toEqual([])
    expect(stack.pitchTopUndoElement()).toBe(undo); expect(current.shell.statusLabel.textContent).toBe(status)
    const layer = grid.layers.at(-1)
    grid.ribbon('normal-view')
    await vi.waitFor(() => expect(layer.dispose).toHaveBeenCalled())
    expect(grid.view.pageBreakPreview().active).toBe(false)
  } finally { current.view?.dispose(); grid.layers.length = 0 }
})

it('refreshes preview and prints the same replayed setup after row edits and Undo', async () => {
  const source = await applyPageSetups(await fixture(), [{ sheetName: 'Sheet1', printArea: 'A1:B8', printTitles: '$1:$1', rowBreaks: [4], scale: 85 }])
  const draft = new NativeDraft(identity, store()), current = await open(source, draft, async () => { throw Error('unexpected save') })
  try {
    grid.ribbon('toggle-page-break-preview')
    await vi.waitFor(() => expect(grid.inputs.at(-1)?.setup.rowBreaks).toEqual([4]))
    grid.ribbon('page-orientation:landscape')
    await vi.waitFor(() => expect(grid.inputs.at(-1)?.setup.orientation).toBe('landscape'))
    expect(sheet().insertRowsBefore(1, 2)).toBeTruthy()
    await vi.waitFor(() => expect(grid.inputs.at(-1)?.setup.rowBreaks).toEqual([6]))
    expect(grid.inputs.at(-1).setup.scale).toBe(85)
    expect(grid.inputs.at(-1).setup.printArea).toContain('10')
    grid.ribbon('print')
    await vi.waitFor(() => expect(grid.printed.length).toBeGreaterThan(0))
    expect(grid.printed.at(-1)).toEqual(grid.inputs.at(-1))
    history('undo')
    await vi.waitFor(() => expect(grid.inputs.at(-1)?.setup.rowBreaks).toEqual([4]))
  } finally { current.view?.dispose(); grid.layers.length = 0; grid.inputs.length = 0; grid.printed.length = 0 }
})
