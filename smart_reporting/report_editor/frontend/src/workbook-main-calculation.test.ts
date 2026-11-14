import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { afterEach, expect, it, vi } from 'vitest'
import { applyCellEdits, applyPageSetups, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { assemblePackage, createBufferEntrySource } from '../../../reporting/workbook_engine/packages/xlsx-engine/src/zip'
import { createWorkbookEditorView } from './workbook-main'
import { createNativeOfficeTransport } from './native-office-view'
import { NativeDraft, type NativeDraftIdentity, type NativeSaveRequest } from './native-draft'
import { createEditorShell } from './shell'

const grid = vi.hoisted(() => ({ api: undefined as any, ribbon: undefined as any, ribbonView: undefined as any, chartObjects: undefined as any, apply: vi.fn(() => false), instances: [] as any[], failNameImport: false as boolean | 'local', realRibbon: false }))
const reloadFault = vi.hoisted(() => ({ stage: '' as '' | 'read' | 'create' | 'loaded' | 'render' | 'hold-read', remaining: 1, release: undefined as (() => void) | undefined }))
vi.mock('./workbook-theme', async original => {
  const actual = await original<typeof import('./workbook-theme')>()
  return { ...actual, readWorkbookThemeSource: (...args: Parameters<typeof actual.readWorkbookThemeSource>) => {
    if (reloadFault.stage === 'read') { reloadFault.stage = ''; throw Error('fixture reload read failed') }
    if (reloadFault.stage === 'hold-read') {
      reloadFault.stage = ''
      return new Promise<void>(resolve => { reloadFault.release = resolve }).then(() => actual.readWorkbookThemeSource(...args))
    }
    return actual.readWorkbookThemeSource(...args)
  } }
})
vi.mock('./workbook-vendor/grid/sync', async original => {
  const actual = await original<typeof import('./workbook-vendor/grid/sync')>()
  return { ...actual, loadWorkbookData: (...args: Parameters<typeof actual.loadWorkbookData>) => {
    actual.loadWorkbookData(...args)
    if (reloadFault.stage === 'loaded') { reloadFault.stage = ''; throw Error('fixture reload loaded failed') }
  } }
})
vi.mock('./workbook-render-ready', async original => {
  const actual = await original<typeof import('./workbook-render-ready')>()
  return { ...actual, waitForWorkbookRendered: (...args: Parameters<typeof actual.waitForWorkbookRendered>) => {
    if (reloadFault.stage === 'render') { reloadFault.stage = ''; throw Error('fixture reload render failed') }
    return actual.waitForWorkbookRendered(...args)
  } }
})
vi.mock('@univerjs/preset-sheets-core', () => ({ UniverSheetsCorePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-note', () => ({ UniverSheetsNotePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-find-replace', () => ({ UniverSheetsFindReplacePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-drawing', () => ({ UniverSheetsDrawingPreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-table', () => ({ UniverSheetsTablePreset: () => ({ plugins: [] }) }))
vi.mock('@univerjs/preset-sheets-conditional-formatting', () => ({ UniverSheetsConditionalFormattingPreset: () => ({ plugins: [] }) }))
vi.mock('./workbook-ribbon', async original => {
  const actual = await original<typeof import('./workbook-ribbon')>()
  return { ...actual,
    mountWorkbookRibbon: (...args: Parameters<typeof actual.mountWorkbookRibbon>) => { grid.ribbon = args[1]; grid.ribbonView = args[2]; return grid.realRibbon ? actual.mountWorkbookRibbon(...args) : { dispose() {}, refreshState() {} } },
    applyWorkbookRibbonCommand: grid.apply,
  }
})
vi.mock('./workbook-vendor/grid/decimal-step', () => ({ stepSelectionDecimals() {} }))
vi.mock('./workbook-vendor/grid/sparkline-render', () => ({ setSparklines() {}, setSparklineWorkbookResolver() {} }))
vi.mock('./workbook-vendor/grid/chart-render', () => ({ setCharts() {} }))
vi.mock('./workbook-chart-object-interaction', async importOriginal => {
  const actual = await importOriginal<typeof import('./workbook-chart-object-interaction')>()
  return { ...actual, installWorkbookChartObjectInteraction: (root: HTMLElement, runtime: any, options: any) => {
    grid.chartObjects = options
    return actual.installWorkbookChartObjectInteraction(root, runtime, options)
  } }
})
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
      if (reloadFault.stage === 'create') { if (--reloadFault.remaining <= 0) reloadFault.stage = ''; throw Error('fixture reload create failed') }
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

it('inserts static date and time from the selected grid cell through native draft history and OOXML readback', async () => {
  const source = await fixture(), draft = new NativeDraft(identity, store())
  const current = await open(source, draft, async () => { throw Error('unexpected save') })
  try {
    const press = (shiftKey = false) => {
      const target = current.shell.editor.querySelector<HTMLElement>('#workbook-grid')!
      const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, code: 'Semicolon', ctrlKey: true, shiftKey })
      target.dispatchEvent(event)
      expect(event.defaultPrevented).toBe(true)
    }
    sheet().getRange('C3').activate()
    press()
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyCellEdits')).toBe(true))
    expect(sheet().getRange('C3').getValue()).toBeGreaterThan(45000)
    expect(sheet().getRange('C3').getValue()).toBeLessThan(70000)
    expect((draft.operations.find(op => op.kind === 'applyCellEdits') as any).edits[0]).toMatchObject({ row: 2, column: 2, style: { numberFormat: 'yyyy/m/d' } })
    grid.ribbon('undo')
    await vi.waitFor(() => expect(draft.operations).toEqual([]))
    grid.ribbon('redo')
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyCellEdits')).toBe(true))

    sheet().getRange('D4').activate()
    press(true)
    const cellEdits = () => draft.operations.filter(op => op.kind === 'applyCellEdits').flatMap(op => (op as any).edits)
    await vi.waitFor(() => expect(cellEdits()).toHaveLength(2))
    expect(sheet().getRange('D4').getValue()).toBeGreaterThanOrEqual(0)
    expect(sheet().getRange('D4').getValue()).toBeLessThan(1)
    expect(cellEdits()[1]).toMatchObject({ row: 3, column: 3, style: { numberFormat: 'h:mm' } })

    const saved = await applyWorkbookOperations(source, draft.operations)
    const model = await readWorkbook(saved)
    const { importedStyleOf } = await import('./workbook-vendor/core/session-core')
    expect(model.sheets[0]!.cells.C3?.value).toBe(sheet().getRange('C3').getValue())
    expect(importedStyleOf(model, 'Sheet1', 'C3')?.numberFormat).toBe('yyyy/m/d')
    expect(model.sheets[0]!.cells.D4?.value).toBe(sheet().getRange('D4').getValue())
    expect(importedStyleOf(model, 'Sheet1', 'D4')?.numberFormat).toBe('h:mm')
  } finally { current.view?.dispose() }
})

it('deletes the selected chart through the real Ribbon and restores it with Ribbon UndoRedo without dropping manual data', async () => {
  grid.realRibbon = true
  const source = await applyWorkbookOperations(await fixture(), [{ kind: 'applyChartAdditions', additions: [{ worksheetSheetName: 'Sheet1',
    anchor: { fromRow: 4, fromColumn: 4, toRow: 16, toColumn: 12, fromRowOffset: 0, fromColumnOffset: 0, toRowOffset: 0, toColumnOffset: 0 },
    chart: { chartType: 'column', title: 'Delete me', series: [{ name: 'Amount', values: [2], categories: ['Q1'], valuesRef: 'Sheet1!A1:A1' }] } }] }])
  const draft = new NativeDraft(identity, store()), current = await open(source, draft, async () => { throw Error('unexpected save') })
  const click = (tab: string, command: string) => {
    document.querySelector<HTMLButtonElement>(`[data-ribbon-tab="${tab}"]`)!.click()
    const button = document.querySelector<HTMLButtonElement>(`[data-ribbon-command="${command}"]`)!
    expect(button.disabled, button.title).toBe(false); button.click()
  }
  try {
    sheet().getRange('J2').setValue('Keep delete manual'); sheet().getRange('J2').activate()
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyCellEdits')).toBe(true))
    click('Chart Design', 'chart-delete')
    await vi.waitFor(() => expect(draft.operations.filter(op => op.kind === 'applyChartDeletions')).toHaveLength(1))
    await vi.waitFor(() => expect(current.shell.editor.inert).not.toBe(true))
    expect((await readWorkbook(await applyWorkbookOperations(source, draft.operations))).sheets[0]!.charts ?? []).toHaveLength(0)
    click('File', 'undo')
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyChartDeletions')).toBe(false))
    await vi.waitFor(() => expect(current.shell.editor.inert).not.toBe(true))
    expect(sheet().getRange('J2').getValue()).toBe('Keep delete manual')
    expect((await readWorkbook(await applyWorkbookOperations(source, draft.operations))).sheets[0]!.charts).toHaveLength(1)
    click('File', 'redo')
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyChartDeletions')).toBe(true))
    await vi.waitFor(() => expect(current.shell.editor.inert).not.toBe(true))
    expect(sheet().getRange('J2').getValue()).toBe('Keep delete manual')
  } finally { current.view?.dispose() }
}, 30000)

it('merges a file through the real Ribbon with cancel manual draft UndoRedo recovery and native save', async () => {
  grid.realRibbon = true
  const source = await fixture(), imported = await applyCellEdits(await createBlankWorkbook(), [{ sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Imported literal' }, style: { bold: true } }])
  const storage = store(), draft = new NativeDraft(identity, storage), current = await open(source, draft, async () => { throw Error('unexpected save') })
  const click = (tab: string, command: string) => {
    document.querySelector<HTMLButtonElement>(`[data-ribbon-tab="${tab}"]`)!.click()
    const button = document.querySelector<HTMLButtonElement>(`[data-ribbon-command="${command}"]`)!
    expect(button.disabled, button.title).toBe(false); button.click()
  }
  try {
    sheet().getRange('J2').setValue('Keep merge manual'); sheet().getRange('J2').activate()
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyCellEdits')).toBe(true))
    const manual = structuredClone(draft.operations)
    click('Data', 'merge-workbooks')
    await vi.waitFor(() => expect(document.querySelector('input[type=file]'), current.shell.editor.querySelector('.workbook-feedback')?.textContent ?? '').not.toBeNull(), { timeout: 10000 })
    document.querySelector<HTMLInputElement>('input[type=file]')!.dispatchEvent(new Event('cancel'))
    expect(draft.operations).toEqual(manual); expect(grid.api.getActiveWorkbook().getSheets()).toHaveLength(1)
    click('Data', 'merge-workbooks')
    await vi.waitFor(() => expect(document.querySelector('input[type=file]'), current.shell.editor.querySelector('.workbook-feedback')?.textContent ?? '').not.toBeNull(), { timeout: 10000 })
    const input = document.querySelector<HTMLInputElement>('input[type=file]')!
    Object.defineProperty(input, 'files', { value: [{ name: 'import.xlsx', size: imported.length, arrayBuffer: async () => imported.slice().buffer }] })
    input.dispatchEvent(new Event('change'))
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applySheetEdits'), current.shell.editor.querySelector('.workbook-feedback')?.textContent ?? '').toBe(true), { timeout: 10000 })
    await vi.waitFor(() => expect(current.shell.editor.inert).not.toBe(true))
    expect(grid.api.getActiveWorkbook().getSheets().map((item: any) => item.getSheetName())).toEqual(['Sheet1', 'Sheet1 (2)'])
    click('File', 'undo')
    await vi.waitFor(() => expect(grid.api.getActiveWorkbook().getSheets()).toHaveLength(1), { timeout: 10000 })
    await vi.waitFor(() => expect(current.shell.editor.inert).not.toBe(true))
    expect(sheet().getRange('J2').getValue()).toBe('Keep merge manual')
    click('File', 'redo')
    await vi.waitFor(() => expect(grid.api.getActiveWorkbook().getSheets()).toHaveLength(2), { timeout: 10000 })
    await vi.waitFor(() => expect(current.shell.editor.inert).not.toBe(true))
  } finally { current.view?.dispose() }
  const recovered = new NativeDraft(identity, storage); let saved: Uint8Array | undefined, saves = 0
  const reopened = await open(source, recovered, async request => {
    saves++; saved = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/merged.xlsx' } }, validation: { ok: false, issues: [{ code: 'native_source_review_pending' }] } }
  })
  try {
    expect(grid.api.getActiveWorkbook().getSheets()).toHaveLength(2)
    expect(grid.api.getActiveWorkbook().getSheetByName('Sheet1').getRange('J2').getValue()).toBe('Keep merge manual')
    expect(grid.api.getActiveWorkbook().getSheetByName('Sheet1 (2)').getRange('A1').getValue()).toBe('Imported literal')
    expect(reopened.shell.save.disabled).toBe(false)
    reopened.shell.save.click(); await vi.waitFor(() => expect(saved, reopened.shell.editor.querySelector('.workbook-feedback')?.textContent ?? '').toBeDefined(), { timeout: 10000 })
    expect(saves).toBe(1)
    const model = await readWorkbook(saved!)
    expect(model.sheets.map(item => item.name)).toEqual(['Sheet1', 'Sheet1 (2)'])
    expect(model.sheets[0]!.cells.J2?.value).toBe('Keep merge manual')
    expect(model.sheets[1]!.cells.A1?.value).toBe('Imported literal')
    expect(model.styles.fonts[model.styles.cellXfs[model.sheets[1]!.cells.A1!.styleIndex!]!.fontId]!.bold).toBe(true)
  } finally { reopened.view?.dispose() }
}, 30000)

it.each(['column', 'bar', 'line', 'area', 'pie', 'scatter', 'radar', 'doughnut', 'combo'] as const)('preserves manual data when directly inserting a %s chart with one native undo/redo and save', async kind => {
  const source = await fixture(), draft = new NativeDraft(identity, store()); let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations as any)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/direct-chart.xlsx' } }, validation: { issues: [] } }
  })
  try {
    sheet().getRange('D1:F4').setValues([['X', 'Sales', 'Cost'], [1, 10, 5], [2, 20, 8], [3, 30, 12]])
    sheet().getRange('D20').setValue(77); sheet().getRange('D1:F4').activate()
    grid.ribbon(`insert-chart:${kind}`)
    await vi.waitFor(() => expect(draft.operations.filter(op => op.kind === 'applyChartAdditions')).toHaveLength(1))
    expect(sheet().getRange('D20').getValue()).toBe(77)
    expect(sheet().getRange('E2').getValue()).toBe(10)
    grid.ribbon('undo')
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyChartAdditions')).toBe(false))
    await vi.waitFor(() => expect(current.shell.editor.inert).toBeFalsy())
    expect(sheet().getRange('D20').getValue()).toBe(77)
    grid.ribbon('redo')
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyChartAdditions')).toBe(true))
    await vi.waitFor(() => expect(current.shell.editor.inert).toBeFalsy())
    expect(sheet().getRange('D20').getValue()).toBe(77)
    current.shell.save.click(); await vi.waitFor(() => expect(downloaded).toBeDefined())
    const model = await readWorkbook(downloaded!)
    expect(model.sheets[0]!.cells.D20?.value).toBe(77)
    expect(model.sheets[0]!.cells.E2?.value).toBe(10)
    expect(model.sheets[0]!.charts).toHaveLength(1)
    expect(model.sheets[0]!.charts![0]!.kind).toBe(kind)
  } finally { current.view?.dispose() }
})

it.each(['read', 'create', 'loaded', 'render'] as const)('retains manual data after a direct insertion %s failure and supports ribbon retry', async stage => {
  const draft = new NativeDraft(identity, store()), current = await open(await fixture(), draft, async () => { throw Error('unexpected save') })
  try {
    sheet().getRange('D1:E3').setValues([['Quarter', 'Sales'], ['Q1', 10], ['Q2', 20]])
    sheet().getRange('D20').setValue(77)
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyCellEdits')).toBe(true))
    const before = structuredClone(draft.operations)
    sheet().getRange('D1:E3').activate(); reloadFault.stage = stage; reloadFault.remaining = 1
    grid.ribbon('insert-chart:column')
    await vi.waitFor(() => expect(document.querySelector('.workbook-feedback')!.textContent).toContain(`fixture reload ${stage} failed`))
    expect(document.querySelector<HTMLElement>('.workbook-feedback')!.hidden).toBe(false)
    expect(sheet().getRange('D20').getValue()).toBe(77); expect(draft.operations).toEqual(before)
    expect(current.shell.editor.inert).toBeFalsy()
    expect(sheet().getSelection().getActiveRange().getRange()).toMatchObject({ startRow: 0, endRow: 2, startColumn: 3, endColumn: 4 })
    grid.ribbon('insert-chart:column')
    await vi.waitFor(() => expect(draft.operations.filter(op => op.kind === 'applyChartAdditions')).toHaveLength(1))
    expect(sheet().getRange('D20').getValue()).toBe(77)
  } finally { reloadFault.stage = ''; current.view?.dispose() }
})

it('rejects direct insertion when the selected data changes during async preflight', async () => {
  const draft = new NativeDraft(identity, store()), current = await open(await fixture(), draft, async () => { throw Error('unexpected save') })
  try {
    sheet().getRange('A1:B1').activate(); grid.ribbon('insert-chart:column')
    sheet().getRange('A1').setValue(91)
    await vi.waitFor(() => expect(document.querySelector('.workbook-feedback')!.textContent).toContain('图表数据已变化，请重新选择数据并插入图表'))
    expect(document.querySelector<HTMLElement>('.workbook-feedback')!.hidden).toBe(false)
    expect(draft.operations.some(op => op.kind === 'applyChartAdditions')).toBe(false)
    expect(sheet().getRange('A1').getValue()).toBe(91)
    expect(current.shell.editor.inert).toBeFalsy()
  } finally { current.view?.dispose() }
})

it('rejects direct insertion on a protected sheet without replacing the workbook', async () => {
  const draft = new NativeDraft(identity, store()), current = await open(await fixture(), draft, async () => { throw Error('unexpected save') })
  try {
    sheet().getRange('A1:B1').activate(); grid.ribbon('sheet-protect')
    const book = grid.api.getActiveWorkbook().getWorkbook(), before = structuredClone(draft.operations)
    grid.ribbon('insert-chart:column')
    await vi.waitFor(() => expect(document.querySelector('.workbook-feedback')!.textContent).toContain('工作表受保护'))
    expect(document.querySelector<HTMLElement>('.workbook-feedback')!.hidden).toBe(false)
    expect(grid.api.getActiveWorkbook().getWorkbook()).toBe(book)
    expect(draft.operations).toEqual(before)
  } finally { current.view?.dispose() }
})

it('blocks grid input while replacement inputs are still being read', async () => {
  const draft = new NativeDraft(identity, store()), current = await open(await fixture(), draft, async () => { throw Error('unexpected save') })
  try {
    sheet().getRange('A1:B1').activate(); reloadFault.stage = 'hold-read'
    grid.ribbon('insert-chart:column')
    await vi.waitFor(() => expect(reloadFault.release).toBeTypeOf('function'))
    const key = new KeyboardEvent('keydown', { key: 'x', bubbles: true, cancelable: true })
    document.querySelector('.workbook-grid')!.dispatchEvent(key)
    expect(key.defaultPrevented).toBe(true)
    reloadFault.release!(); reloadFault.release = undefined
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyChartAdditions')).toBe(true))
  } finally { reloadFault.release?.(); reloadFault.release = undefined; reloadFault.stage = ''; current.view?.dispose() }
})

it.each(['read', 'create', 'loaded', 'render'] as const)('recovers a chart reload %s failure without losing manual data and retries the same dialog', async stage => {
  const { applyChartAdditions } = await import('@sheets-web/xlsx-engine')
  const source = await applyChartAdditions(await fixture(), [{ worksheetSheetName: 'Sheet1',
    anchor: { fromRow: 2, fromColumn: 3, toRow: 10, toColumn: 9, fromRowOffset: 0, fromColumnOffset: 0, toRowOffset: 0, toColumnOffset: 0 },
    chart: { chartType: 'column', title: 'Original', series: [{ name: 'Amount', values: [2], categories: ['Q1'], valuesRef: 'Sheet1!A1:A1' }] } }])
  const draft = new NativeDraft(identity, store()), current = await open(source, draft, async () => { throw Error('unexpected save') })
  try {
    sheet().getRange('D20').setValue(77)
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyCellEdits')).toBe(true))
    const before = structuredClone(draft.operations)
    grid.ribbon('chart-title')
    const input = document.querySelector<HTMLInputElement>('[aria-label="图表标题"]')!
    const form = input.closest('form')!, dialog = form.closest<HTMLElement>('[role="dialog"]')!
    input.value = 'Retry retained'
    reloadFault.stage = stage; reloadFault.remaining = 1
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await vi.waitFor(() => expect(form.querySelector('[role="alert"]')!.textContent).toContain(`fixture reload ${stage} failed`))
    expect(dialog.hidden).toBe(false); expect(input.value).toBe('Retry retained')
    expect(sheet().getRange('D20').getValue()).toBe(77); expect(draft.operations).toEqual(before)
    expect(current.shell.editor.inert).toBeFalsy()
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await vi.waitFor(() => expect(dialog.hidden).toBe(true))
    expect(sheet().getRange('D20').getValue()).toBe(77)
    expect(draft.operations.some(op => op.kind === 'applyChartEdits')).toBe(true)
    grid.ribbon('undo')
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyChartEdits')).toBe(false))
    await vi.waitFor(() => expect(current.shell.editor.inert).toBeFalsy())
    expect(sheet().getRange('D20').getValue()).toBe(77)
    grid.ribbon('redo')
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyChartEdits')).toBe(true))
    await vi.waitFor(() => expect(current.shell.editor.inert).toBeFalsy())
    expect(sheet().getRange('D20').getValue()).toBe(77)
  } finally { reloadFault.stage = ''; current.view?.dispose() }
})

it('retains the native manual undo/redo journal after a failed destructive chart reload', async () => {
  const { applyChartAdditions } = await import('@sheets-web/xlsx-engine')
  const source = await applyChartAdditions(await fixture(), [{ worksheetSheetName: 'Sheet1',
    anchor: { fromRow: 2, fromColumn: 3, toRow: 10, toColumn: 9, fromRowOffset: 0, fromColumnOffset: 0, toRowOffset: 0, toColumnOffset: 0 },
    chart: { chartType: 'column', title: 'Original', series: [{ name: 'Amount', values: [2], categories: ['Q1'], valuesRef: 'Sheet1!A1:A1' }] } }])
  const draft = new NativeDraft(identity, store()), current = await open(source, draft, async () => { throw Error('unexpected save') })
  try {
    sheet().getRange('D20').setValue(77)
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyCellEdits')).toBe(true))
    grid.ribbon('chart-title')
    const input = document.querySelector<HTMLInputElement>('[aria-label="图表标题"]')!
    input.value = 'Must not commit'; reloadFault.stage = 'render'
    input.closest('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await vi.waitFor(() => expect(input.closest('form')!.querySelector('[role="alert"]')!.textContent).toContain('fixture reload render failed'))
    grid.ribbon('undo')
    await vi.waitFor(() => expect(sheet().getRange('D20').getValue()).toBeNull())
    await vi.waitFor(() => expect(current.shell.editor.inert).toBeFalsy())
    grid.ribbon('redo')
    await vi.waitFor(() => expect(sheet().getRange('D20').getValue()).toBe(77))
    expect(draft.operations.some(op => op.kind === 'applyChartEdits')).toBe(false)
  } finally { reloadFault.stage = ''; current.view?.dispose() }
})

it('keeps the draft and disables editing with an explicit reopen reason when rollback also fails', async () => {
  const { applyChartAdditions } = await import('@sheets-web/xlsx-engine')
  const source = await applyChartAdditions(await fixture(), [{ worksheetSheetName: 'Sheet1',
    anchor: { fromRow: 2, fromColumn: 3, toRow: 10, toColumn: 9, fromRowOffset: 0, fromColumnOffset: 0, toRowOffset: 0, toColumnOffset: 0 },
    chart: { chartType: 'column', title: 'Original', series: [{ name: 'Amount', values: [2], categories: ['Q1'], valuesRef: 'Sheet1!A1:A1' }] } }])
  const draft = new NativeDraft(identity, store()), current = await open(source, draft, async () => { throw Error('unexpected save') })
  try {
    sheet().getRange('D20').setValue(77)
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyCellEdits')).toBe(true))
    const before = structuredClone(draft.operations)
    grid.ribbon('chart-title')
    const input = document.querySelector<HTMLInputElement>('[aria-label="图表标题"]')!
    input.value = 'Must not commit'; reloadFault.stage = 'create'; reloadFault.remaining = 2
    input.closest('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await vi.waitFor(() => expect(input.closest('form')!.querySelector('[role="alert"]')!.textContent).toContain('本地草稿已保留，请重新打开文档'))
    expect(draft.operations).toEqual(before); expect(current.shell.save.disabled).toBe(true)
    expect(input.value).toBe('Must not commit'); expect(current.shell.editor.inert).toBeFalsy()
  } finally { reloadFault.stage = ''; reloadFault.remaining = 1; current.view?.dispose() }
})

it('inserts the actual ranked recommendation through native draft history and restores it before save', async () => {
  const source = await fixture(), draft = new NativeDraft(identity, store()); let downloaded: Uint8Array | undefined
  const save = async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations as any)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/recommended.xlsx' } }, validation: { issues: [] } }
  }
  let current = await open(source, draft, save)
  try {
    sheet().getRange('D1:E4').setValues([['Quarter', 'Sales'], ['Q1', 10], ['Q2', 20], ['Q3', 30]])
    sheet().getRange('A1').setValue(9); sheet().getRange('D1:E4').activate()
    grid.ribbon('recommended-charts-open')
    await vi.waitFor(() => expect(document.querySelector('[data-recommended-chart="line"]')).not.toBeNull())
    expect(document.querySelector('[data-recommended-chart]')?.getAttribute('data-recommended-chart')).toBe('line')
    expect(document.querySelector('[data-recommended-chart="line"] svg path')).not.toBeNull()
    document.querySelector<HTMLButtonElement>('[data-recommended-close]')!.click()
    expect(draft.operations.some(op => op.kind === 'applyChartAdditions')).toBe(false)
    grid.ribbon('recommended-charts-open')
    document.querySelector<HTMLButtonElement>('[data-recommended-chart="line"]')!.click()
    await vi.waitFor(() => expect(draft.operations.filter(op => op.kind === 'applyChartAdditions')).toHaveLength(1))
    expect(sheet().getRange('A1').getValue()).toBe(9)
    grid.ribbon('undo'); await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyChartAdditions')).toBe(false))
    await vi.waitFor(() => expect(!!current.shell.editor.inert).toBe(false))
    expect(sheet().getRange('A1').getValue()).toBe(9)
    grid.ribbon('redo'); await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyChartAdditions')).toBe(true))
    await vi.waitFor(() => expect(!!current.shell.editor.inert).toBe(false))
    current.view?.dispose(); current = await open(source, draft, save)
    current.shell.save.click(); await vi.waitFor(() => expect(downloaded).toBeDefined())
    const model = await readWorkbook(downloaded!)
    expect(model.sheets[0]!.cells.A1?.value).toBe(9)
    expect(model.sheets[0]!.charts).toHaveLength(1)
    expect(model.sheets[0]!.charts![0]).toMatchObject({ kind: 'line', series: [{ name: 'Sales', categories: ['Q1', 'Q2', 'Q3'], valuesRef: "'Sheet1'!$E$2:$E$4" }] })
  } finally { current.view?.dispose() }
})

it.each(['data', 'protection', 'replacement'] as const)('rejects a stale recommendation after %s changes without dropping manual draft', async guard => {
  const source = await fixture(), draft = new NativeDraft(identity, store()), current = await open(source, draft, async () => { throw Error('unexpected save') })
  try {
    sheet().getRange('D1:E4').setValues([['Quarter', 'Sales'], ['Q1', 10], ['Q2', 20], ['Q3', 30]])
    sheet().getRange('A1').setValue(9); sheet().getRange('D1:E4').activate()
    grid.ribbon('recommended-charts-open')
    await vi.waitFor(() => expect(document.querySelector('[data-recommended-chart="line"]')).not.toBeNull())
    if (guard === 'data') sheet().getRange('E2').setValue(99)
    else if (guard === 'protection') grid.ribbon('sheet-protect')
    else { const book = grid.api.getActiveWorkbook(); grid.api.createWorkbook({ ...book.getSnapshot(), id: 'recommendation-replacement' }) }
    document.querySelector<HTMLButtonElement>('[data-recommended-chart="line"]')!.click()
    await vi.waitFor(() => expect(document.querySelector('.workbook-feedback')!.textContent).toMatch(/图表数据.*变化|工作表受保护/))
    expect(draft.operations.some(op => op.kind === 'applyChartAdditions')).toBe(false)
    expect(!!current.shell.editor.inert).toBe(false)
    expect(draft.operations.some(op => op.kind === 'applyCellEdits')).toBe(true)
  } finally { current.view?.dispose() }
})

it('rejects a recommendation for an empty selection without opening a fake chart picker', async () => {
  const current = await open(await fixture(), new NativeDraft(identity, store()), async () => { throw Error('unexpected save') })
  try {
    sheet().getRange('D1:E4').activate(); grid.ribbon('recommended-charts-open')
    expect(document.querySelector('.workbook-recommended-charts-overlay')).toBeNull()
    expect(document.querySelector('.workbook-feedback')!.textContent).toContain('至少一列数值')
  } finally { current.view?.dispose() }
})

it('targets the selected same-title chart in a multi-chart sheet and retains manual edits through save', async () => {
  const {applyChartAdditions}=await import('@sheets-web/xlsx-engine')
  const addition={worksheetSheetName:'Sheet1',anchor:{fromRow:2,fromColumn:3,toRow:10,toColumn:9,fromRowOffset:0,fromColumnOffset:0,toRowOffset:0,toColumnOffset:0},chart:{chartType:'column' as const,title:'Same',series:[{name:'Amount',values:[2],categories:['Q1'],valuesRef:'Sheet1!A1:A1'}]}}
  const source=await applyChartAdditions(await fixture(),[addition,{...addition,anchor:{...addition.anchor,fromColumn:10,toColumn:16}}])
  const draft=new NativeDraft(identity,store());let downloaded:Uint8Array|undefined
  const current=await open(source,draft,async request=>{
    downloaded=await applyWorkbookOperations(source,request.operations as any)
    return {revision:2,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/selected-chart.xlsx'}},validation:{issues:[]}}
  })
  try {
    sheet().getRange('A1').setValue(9)
    await vi.waitFor(()=>expect(draft.operations.some(op=>op.kind==='applyCellEdits')).toBe(true))
    grid.ribbon('chart-delete')
    expect(draft.operations.some(op=>op.kind==='applyChartDeletions')).toBe(false)
    grid.ribbon('chart-descriptions')
    const choose=document.querySelector<HTMLButtonElement>('[data-select-chart="xl/charts/chart2.xml"]')
    expect(choose).not.toBeNull();choose!.click()
    grid.ribbon('chart-title')
    const title=document.querySelector<HTMLInputElement>('[aria-label="图表标题"]')!
    title.value='Chosen second';title.closest('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))
    await vi.waitFor(()=>expect(draft.operations.some(op=>op.kind==='applyChartEdits')).toBe(true))
    expect((draft.operations.find(op=>op.kind==='applyChartEdits') as any).edits).toEqual([{chartPath:'xl/charts/chart2.xml',title:'Chosen second'}])
    grid.ribbon('chart-delete')
    await vi.waitFor(()=>expect(draft.operations.some(op=>op.kind==='applyChartDeletions')).toBe(true))
    current.shell.save.click();await vi.waitFor(()=>expect(downloaded).toBeDefined())
    const model=await readWorkbook(downloaded!)
    expect(model.sheets[0]!.charts?.map(chart=>[chart.chartPath,chart.title])).toEqual([['xl/charts/chart1.xml','Same']])
    expect(model.sheets[0]!.cells['A1']?.value).toBe(9)
  } finally {current.view?.dispose()}
})

it('applies layout and point colors to the selected pie chart across reloads without dropping manual edits', async () => {
  const { applyChartAdditions } = await import('@sheets-web/xlsx-engine')
  const addition = { worksheetSheetName: 'Sheet1', anchor: { fromRow: 2, fromColumn: 3, toRow: 10, toColumn: 9, fromRowOffset: 0, fromColumnOffset: 0, toRowOffset: 0, toColumnOffset: 0 },
    chart: { chartType: 'pie' as const, title: 'Same', series: [{ name: 'Amount', values: [2, 6], categories: ['Q1', 'Q2'], valuesRef: 'Sheet1!A1:A2' }] } }
  const source = await applyChartAdditions(await fixture(), [addition, { ...addition, anchor: { ...addition.anchor, fromColumn: 10, toColumn: 16 } }])
  const draft = new NativeDraft(identity, store()); let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations as any)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/chart-presets.xlsx' } }, validation: { issues: [] } }
  })
  try {
    expect(grid.ribbonView.chart()).toBeNull()
    grid.ribbon('chart-descriptions')
    document.querySelector<HTMLButtonElement>('[data-select-chart="xl/charts/chart2.xml"]')!.click()
    expect(grid.ribbonView.chart()).toEqual({ isPie: true, canLabel: true, seriesCount: 1, categoryCount: 2 })
    sheet().getRange('A1').setValue(9)
    grid.ribbon('chart-colors:green')
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyChartEdits' && (op as any).edits.some((edit: any) => edit.pointColors))).toBe(true))
    expect(document.querySelector<HTMLElement>('.workbook-grid')!.dataset.selectedChart).toBe('xl/charts/chart2.xml')
    grid.ribbon('chart-layout:1')
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyChartEdits' && (op as any).edits.some((edit: any) => edit.dataLabels === 'category-percent'))).toBe(true))
    current.shell.save.click(); await vi.waitFor(() => expect(downloaded).toBeDefined())
    const model = await readWorkbook(downloaded!), charts = model.sheets[0]!.charts!
    expect(charts[0]!.legend).toMatchObject({ position: 'bottom' })
    expect(charts[0]!.dataLabels).toBeUndefined()
    expect(charts[1]).toMatchObject({ chartPath: 'xl/charts/chart2.xml', legend: { position: 'right' }, dataLabels: { showCategory: true, showPercent: true } })
    expect(charts[1]!.series[0]!.pointColors).toMatchObject({ 0: '#375623', 1: '#548235' })
    expect(model.sheets[0]!.cells['A1']?.value).toBe(9)
  } finally { current.view?.dispose() }
})

it('undoes and redoes a chart palette through File commands while retaining the manual cell draft', async () => {
  const { applyChartAdditions } = await import('@sheets-web/xlsx-engine')
  const source = await applyChartAdditions(await fixture(), [{ worksheetSheetName: 'Sheet1',
    anchor: { fromRow: 2, fromColumn: 3, toRow: 10, toColumn: 9, fromRowOffset: 0, fromColumnOffset: 0, toRowOffset: 0, toColumnOffset: 0 },
    chart: { chartType: 'pie', title: 'Palette', series: [{ name: 'Amount', values: [2, 6], categories: ['Q1', 'Q2'], valuesRef: 'Sheet1!A1:A2' }] } }])
  const originalPointColors = (await readWorkbook(source)).sheets[0]!.charts![0]!.series[0]!.pointColors
  const draft = new NativeDraft(identity, store()); let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations as any)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/chart-history.xlsx' } }, validation: { issues: [] } }
  })
  try {
    sheet().getRange('A1').setValue(9)
    grid.ribbon('chart-colors:green')
    await vi.waitFor(() => expect(document.querySelector('.workbook-feedback')!.textContent).toContain('图表预设已应用'))
    const colored = await readWorkbook(await applyWorkbookOperations(source, draft.operations as any))
    expect(colored.sheets[0]!.charts![0]!.series[0]!.pointColors).toMatchObject({ 0: '#375623', 1: '#548235' })
    grid.ribbon('undo')
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyChartEdits')).toBe(false))
    await vi.waitFor(() => expect(!!current.shell.editor.inert).toBe(false))
    const undone = await readWorkbook(await applyWorkbookOperations(source, draft.operations as any))
    expect(undone.sheets[0]!.charts![0]!.series[0]!.pointColors).toEqual(originalPointColors)
    expect(undone.sheets[0]!.cells['A1']?.value).toBe(9)
    expect(sheet().getRange('A1').getValue()).toBe(9)
    grid.ribbon('redo')
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyChartEdits')).toBe(true))
    await vi.waitFor(() => expect(!!current.shell.editor.inert).toBe(false))
    current.shell.save.click(); await vi.waitFor(() => expect(downloaded).toBeDefined())
    const redone = await readWorkbook(downloaded!)
    expect(redone.sheets[0]!.charts![0]!.series[0]!.pointColors).toMatchObject({ 0: '#375623', 1: '#548235' })
    expect(redone.sheets[0]!.cells['A1']?.value).toBe(9)
  } finally { current.view?.dispose() }
})

it('saves exact chart geometry through the real host draft and File history without losing manual cells', async () => {
  const { applyChartAdditions } = await import('@sheets-web/xlsx-engine')
  const anchor = { fromRow: 2, fromColumn: 3, toRow: 10, toColumn: 9, fromRowOffset: 0, fromColumnOffset: 0, toRowOffset: 0, toColumnOffset: 0 }
  const source = await applyChartAdditions(await fixture(), [0, 1].map(index => ({ worksheetSheetName: 'Sheet1', anchor,
    chart: { chartType: 'column' as const, title: `Same ${index}`, series: [{ name: 'Amount', values: [2], valuesRef: 'Sheet1!A1:A1', categories: ['Q1'] }] } })))
  const draft = new NativeDraft(identity, store()); let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations as any)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/chart-geometry.xlsx' } }, validation: { issues: [] } }
  })
  try {
    sheet().getRange('A1').setValue(9)
    grid.ribbon('chart-descriptions'); document.querySelector<HTMLButtonElement>('[data-select-chart="xl/charts/chart2.xml"]')!.click()
    expect(grid.chartObjects).toBeDefined()
    const chart = grid.chartObjects.charts('Sheet1')[1], target = grid.chartObjects.capture(chart, 'Sheet1')
    const next = { ...anchor, fromRow: 1004, toRow: 1012, fromColumn: 30, toColumn: 36, fromColumnOffset: 9525, toColumnOffset: 9525 }
    await grid.chartObjects.commit(target, 'move', next)
    expect(draft.operations.filter(op => op.kind === 'applyChartAnchors')).toEqual([{ kind: 'applyChartAnchors', edits: [{ sheetName: 'Sheet1', chartPath: 'xl/charts/chart2.xml', before: anchor, anchor: next, mode: 'move' }] }])
    expect(sheet().getRange('A1').getValue()).toBe(9)
    expect(sheet().getMaxRows()).toBeGreaterThan(next.toRow)
    expect(sheet().getMaxColumns()).toBeGreaterThan(next.toColumn)
    grid.ribbon('undo')
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyChartAnchors')).toBe(false))
    await vi.waitFor(() => expect(!!current.shell.editor.inert).toBe(false))
    expect((await readWorkbook(await applyWorkbookOperations(source, draft.operations as any))).sheets[0]!.cells['A1']?.value).toBe(9)
    grid.ribbon('redo')
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyChartAnchors')).toBe(true))
    await vi.waitFor(() => expect(!!current.shell.editor.inert).toBe(false))
    current.shell.save.click(); await vi.waitFor(() => expect(downloaded).toBeDefined())
    const model = await readWorkbook(downloaded!)
    expect(model.sheets[0]!.charts![0]!.anchor).toMatchObject({ fromRow: 2, toRow: 10 })
    expect(model.sheets[0]!.charts![1]!.anchor).toMatchObject({ fromRow: 1004, toRow: 1012, fromColumn: 30, toColumn: 36, fromColumnOffset: 9525, toColumnOffset: 9525 })
    expect(model.sheets[0]!.cells['A1']?.value).toBe(9)
  } finally { current.view?.dispose() }
})

it.each(['protection', 'replacement'] as const)('rechecks chart geometry after async capture against %s changes', async guard => {
  const { applyChartAdditions } = await import('@sheets-web/xlsx-engine')
  const anchor = { fromRow: 2, fromColumn: 3, toRow: 10, toColumn: 9, fromRowOffset: 0, fromColumnOffset: 0, toRowOffset: 0, toColumnOffset: 0 }
  const source = await applyChartAdditions(await fixture(), [{ worksheetSheetName: 'Sheet1', anchor,
    chart: { chartType: 'column', title: 'Guarded', series: [{ name: 'Amount', values: [2], valuesRef: 'Sheet1!A1:A1', categories: ['Q1'] }] } }])
  const draft = new NativeDraft(identity, store()), current = await open(source, draft, async () => { throw Error('unexpected save') })
  try {
    expect(grid.chartObjects).toBeDefined()
    const target = grid.chartObjects.capture(grid.chartObjects.charts('Sheet1')[0], 'Sheet1')
    const commit = grid.chartObjects.commit(target, 'move', { ...anchor, fromRow: 4, toRow: 12 })
    if (guard === 'protection') grid.ribbon('sheet-protect')
    else { const book = grid.api.getActiveWorkbook(); grid.api.createWorkbook({ ...book.getSnapshot(), id: 'replacement-workbook' }) }
    await expect(commit).rejects.toThrow(guard === 'protection' ? '受保护' : '图表目标已变化')
    expect(draft.operations.some(op => op.kind === 'applyChartAnchors')).toBe(false)
  } finally { current.view?.dispose() }
})

it('rejects a stale chart anchor after native row insertion without locking the editor or losing the draft', async () => {
  const { applyChartAdditions } = await import('@sheets-web/xlsx-engine')
  const anchor = { fromRow: 2, fromColumn: 3, toRow: 10, toColumn: 9, fromRowOffset: 0, fromColumnOffset: 0, toRowOffset: 0, toColumnOffset: 0 }
  const source = await applyChartAdditions(await fixture(), [{ worksheetSheetName: 'Sheet1', anchor,
    chart: { chartType: 'column', title: 'Shifted', series: [{ name: 'Amount', values: [2], valuesRef: 'Sheet1!A1:A1', categories: ['Q1'] }] } }])
  const draft = new NativeDraft(identity, store()); let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations as any)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/chart-stale.xlsx' } }, validation: { issues: [] } }
  })
  try {
    const target = grid.chartObjects.capture(grid.chartObjects.charts('Sheet1')[0], 'Sheet1')
    expect(grid.api.syncExecuteCommand('sheet.command.insert-row-by-range', { unitId: grid.api.getActiveWorkbook().getId(), subUnitId: sheet().getSheetId(), range: { startRow: 1, endRow: 1, startColumn: 0, endColumn: 9 }, direction: 0 })).toBe(true)
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyRowColumnOps')).toBe(true))
    await expect(grid.chartObjects.commit(target, 'move', { ...anchor, fromRow: 4, toRow: 12 })).rejects.toThrow('图表锚点身份已变化')
    expect(grid.chartObjects.available()).toBe(true)
    sheet().getRange('A1').setValue(9)
    current.shell.save.click(); await vi.waitFor(() => expect(downloaded).toBeDefined())
    const model = await readWorkbook(downloaded!)
    expect(model.sheets[0]!.cells['A1']?.value).toBe(9)
    expect(model.sheets[0]!.charts![0]!.anchor).toMatchObject({ fromRow: 3, toRow: 11 })
    expect(draft.operations.some(op => op.kind === 'applyChartAnchors')).toBe(false)
  } finally { current.view?.dispose() }
})

it('rejects chart dialog edits when the actual worksheet is replaced despite an identical sheet id and chart path', async () => {
  const { applyChartAdditions } = await import('@sheets-web/xlsx-engine')
  const source = await applyChartAdditions(await fixture(), [{ worksheetSheetName: 'Sheet1',
    anchor: { fromRow: 2, fromColumn: 3, toRow: 10, toColumn: 9, fromRowOffset: 0, fromColumnOffset: 0, toRowOffset: 0, toColumnOffset: 0 },
    chart: { chartType: 'column', title: 'Original', series: [{ name: 'Amount', values: [2], categories: ['Q1'], valuesRef: 'Sheet1!A1:A1' }] } }])
  const draft = new NativeDraft(identity, store()), current = await open(source, draft, async () => { throw Error('unexpected save') })
  try {
    grid.ribbon('chart-title')
    const input = document.querySelector<HTMLInputElement>('[aria-label="图表标题"]')!
    input.value = 'Must not apply'
    const book = grid.api.getActiveWorkbook(), snapshot = book.getSnapshot()
    grid.api.createWorkbook({ ...snapshot, id: 'replacement-workbook' })
    expect(sheet().getSheetId()).toBe(book.getActiveSheet().getSheetId())
    input.closest('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    expect(input.closest('form')!.querySelector('[role="alert"]')!.textContent).toContain('图表目标已变化')
    expect(draft.operations.some(op => op.kind === 'applyChartEdits')).toBe(false)
  } finally { current.view?.dispose() }
})

it('rechecks protection after async chart capture and routes the grid Delete key through the same guarded deletion', async () => {
  const { applyChartAdditions } = await import('@sheets-web/xlsx-engine')
  const source = await applyChartAdditions(await fixture(), [{ worksheetSheetName: 'Sheet1',
    anchor: { fromRow: 2, fromColumn: 3, toRow: 10, toColumn: 9, fromRowOffset: 0, fromColumnOffset: 0, toRowOffset: 0, toColumnOffset: 0 },
    chart: { chartType: 'column', title: 'Guarded', series: [{ name: 'Amount', values: [2], categories: ['Q1'], valuesRef: 'Sheet1!A1:A1' }] } }])
  const draft = new NativeDraft(identity, store()), current = await open(source, draft, async () => { throw Error('unexpected save') })
  try {
    grid.ribbon('chart-descriptions')
    document.querySelector<HTMLButtonElement>('[data-select-chart="xl/charts/chart1.xml"]')!.click()
    grid.ribbon('chart-type-bar')
    grid.ribbon('sheet-protect')
    await vi.waitFor(() => expect(document.querySelector('.workbook-feedback')!.textContent).toContain('工作表受保护'))
    expect(draft.operations.some(op => op.kind === 'applyChartEdits')).toBe(false)
    const canvasHost = document.querySelector<HTMLElement>('.workbook-grid')!
    canvasHost.dispatchEvent(new KeyboardEvent('keydown', { key: 'Delete', bubbles: true, cancelable: true }))
    expect(draft.operations.some(op => op.kind === 'applyChartDeletions')).toBe(false)
    grid.ribbon('sheet-protect')
    canvasHost.dispatchEvent(new KeyboardEvent('keydown', { key: 'Delete', bubbles: true, cancelable: true }))
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyChartDeletions')).toBe(true))
    expect(canvasHost.dataset.selectedChart).toBeUndefined()
  } finally { current.view?.dispose() }
})

it('toggles cross highlight as a persisted reading preference without snapshot, history or draft edits', async () => {
  localStorage.removeItem('report-editor-cross-highlight')
  const source=await fixture(),draft=new NativeDraft(identity,store()),current=await open(source,draft,async()=>{throw Error('unexpected save')})
  try {
    const workbook=grid.api.getActiveWorkbook(),before=workbook.getSnapshot(),label=current.shell.statusLabel.textContent
    const {IUndoRedoService}=await import('@univerjs/core'),stack=grid.instances.at(-1).__getInjector().get(IUndoRedoService)
    const undo=stack.pitchTopUndoElement(),redo=stack.pitchTopRedoElement()
    grid.ribbon('toggle-cross-highlight')
    expect(localStorage.getItem('report-editor-cross-highlight')).toBe('1')
    expect(document.querySelector('.workbook-feedback')?.textContent).toBe('已开启活动行列突出显示。')
    expect(workbook.getSnapshot()).toEqual(before);expect(draft.operations).toEqual([])
    expect(stack.pitchTopUndoElement()).toBe(undo);expect(stack.pitchTopRedoElement()).toBe(redo)
    expect(current.shell.statusLabel.textContent).toBe(label)
    grid.ribbon('toggle-cross-highlight');expect(localStorage.getItem('report-editor-cross-highlight')).toBe('0')
  } finally {current.view?.dispose();localStorage.removeItem('report-editor-cross-highlight')}
})

it('restores cross-highlight preference in a reopened readonly workbook without creating edits', async()=>{
  localStorage.setItem('report-editor-cross-highlight','1')
  const draft=new NativeDraft(identity,store()),current=await open(await fixture(),draft,async()=>{throw Error('unexpected save')},undefined,false)
  try{
    const before=grid.api.getActiveWorkbook().getSnapshot(),label=current.shell.statusLabel.textContent
    expect(localStorage.getItem('report-editor-cross-highlight')).toBe('1')
    grid.ribbon('toggle-cross-highlight')
    expect(localStorage.getItem('report-editor-cross-highlight')).toBe('0')
    expect(grid.api.getActiveWorkbook().getSnapshot()).toEqual(before)
    expect(draft.operations).toEqual([]);expect(current.shell.statusLabel.textContent).toBe(label)
  }finally{current.view?.dispose();localStorage.removeItem('report-editor-cross-highlight')}
})

it('preserves unknown imported conditional formatting while saving an ordinary cell edit', async () => {
  const original = await fixture(), packageSource = await createBufferEntrySource(original)
  const path = 'xl/worksheets/sheet1.xml'
  const unknown = '<conditionalFormatting sqref="A1"><cfRule type="future" priority="1"><alien/></cfRule></conditionalFormatting>'
  const xml = (await packageSource.readText(path)).replace('</worksheet>', `${unknown}</worksheet>`)
  const source = (await assemblePackage(original, { replaced: new Map([[path, xml]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
  const draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const save = vi.fn(async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/unknown-cf.xlsx' } }, validation: { issues: [] } }
  })
  const current = await open(source, draft, save)
  try {
    sheet().getRange('A1').setValue(7)
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyCellEdits')).toBe(true))
    expect(draft.operations.some(op => op.kind === 'replaceSheetConditionalFormats')).toBe(false)
    current.shell.save.click()
    await vi.waitFor(() => expect(downloaded).toBeDefined())
    expect(await (await createBufferEntrySource(downloaded!)).readText(path)).toContain(unknown)
    expect((await readWorkbook(downloaded!)).sheets[0]!.cells.A1!.value).toBe(7)
  } finally { current.view?.dispose() }
})

it('imports full conditional formatting and persists native rule edits through draft recovery and save', async () => {
  const wire = { ranges: [{ startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 }], stopIfTrue: false,
    rule: { type: 'highlightCell', subType: 'number', operator: 'greaterThan', value: [5], style: { bg: { rgb: '#C6EFCE' } } } }
  const source = await applyWorkbookOperations(await fixture(), [{ kind: 'replaceSheetConditionalFormats', sheetName: 'Sheet1', rules: [wire] }])
  const storage = store(), draft = new NativeDraft(identity, storage)
  let downloaded: Uint8Array | undefined
  const save = vi.fn(async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/cf.xlsx' } }, validation: { issues: [] } }
  })
  let current = await open(source, draft, save)
  try {
    expect(sheet().getConditionalFormattingRules()).toHaveLength(1)
    expect(draft.operations).toEqual([])
    const rule = sheet().getConditionalFormattingRules()[0]
    expect(grid.api.syncExecuteCommand('sheet.command.set-conditional-rule', {
      unitId: grid.api.getActiveWorkbook().getId(), subUnitId: sheet().getSheetId(), cfId: rule.cfId,
      rule: { ...rule, rule: { ...rule.rule, value: 9 } },
    })).toBe(true)
    await vi.waitFor(() => expect(draft.operations.find(op => op.kind === 'replaceSheetConditionalFormats')).toMatchObject({ rules: [{ rule: { value: [9] } }] }))
    history('undo')
    await vi.waitFor(() => expect(draft.operations.filter(op => op.kind === 'replaceSheetConditionalFormats')).toEqual([]))
    history('redo')
    await vi.waitFor(() => expect(draft.operations.find(op => op.kind === 'replaceSheetConditionalFormats')).toBeDefined())
    current.view?.dispose()
    current = await open(source, new NativeDraft(identity, storage), save)
    expect(sheet().getConditionalFormattingRules()[0].rule.value).toBe(9)
    current.shell.save.click()
    await vi.waitFor(() => expect(downloaded).toBeDefined())
    const saved = await readWorkbook(downloaded!)
    expect(saved.sheets[0]!.conditionalFormatting!.rules[0]!.rule.value).toEqual([9])
    expect(saved.sheets[0]!.cells.B1!.formula).toBe('=A1*3')
    expect(save).toHaveBeenCalledTimes(1)
  } finally { current.view?.dispose() }
})

it('persists worksheet direction through native undo, redo, draft recovery and save', async () => {
  const source = await fixture(), storage = store(), draft = new NativeDraft(identity, storage)
  let downloaded: Uint8Array | undefined
  const save = vi.fn(async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/rtl.xlsx' } }, validation: { issues: [] } }
  })
  let current = await open(source, draft, save)
  try {
    grid.ribbon('toggle-right-to-left')
    await vi.waitFor(() => expect(sheet().getSheet().getConfig().rightToLeft).toBe(1))
    await vi.waitFor(() => expect(draft.operations.find(op => op.kind === 'applyPageSetups')).toMatchObject({ setups: [{ sheetName: 'Sheet1', rightToLeft: true }] }))
    history('undo')
    await vi.waitFor(() => expect(sheet().getSheet().getConfig().rightToLeft).not.toBe(1))
    await vi.waitFor(() => expect(draft.operations.filter(op => op.kind === 'applyPageSetups')).toEqual([]))
    history('redo')
    await vi.waitFor(() => expect(draft.operations.find(op => op.kind === 'applyPageSetups')).toMatchObject({ setups: [{ sheetName: 'Sheet1', rightToLeft: true }] }))
    current.view?.dispose()
    current = await open(source, new NativeDraft(identity, storage), save)
    expect(sheet().getSheet().getConfig().rightToLeft).toBe(1)
    current.shell.save.click()
    await vi.waitFor(() => expect(downloaded).toBeDefined())
    const saved = await readWorkbook(downloaded!)
    expect(saved.sheets[0]!.rightToLeft).toBe(true)
    expect(saved.sheets[0]!.cells.B1!.formula).toBe('=A1*3')
    expect(save).toHaveBeenCalledTimes(1)
  } finally { current.view?.dispose() }
})

it('preserves imported hidden headings through a native cell edit, draft and save', async () => {
  const source = await applyPageSetups(await fixture(), [{ sheetName: 'Sheet1', showHeadings: false }])
  const draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const save = vi.fn(async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/headings.xlsx' } }, validation: { issues: [] } }
  })
  const current = await open(source, draft, save)
  try {
    expect(sheet().getSheet().getConfig().rowHeader.hidden).toBe(1)
    sheet().getRange('A1').setValue(9)
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyCellEdits')).toBe(true))
    expect(draft.operations.filter(op => op.kind === 'applyPageSetups')).toEqual([])
    current.shell.save.click()
    await vi.waitFor(() => expect(downloaded).toBeDefined())
    const model = await readWorkbook(downloaded!)
    expect(model.sheets[0]!.showHeadings).toBe(false)
    expect(model.sheets[0]!.cells.A1?.value).toBe(9)
  } finally { current.view?.dispose() }
})

it('persists row outline grouping through draft recovery and the native save bridge', async () => {
  const source = await fixture(), storage = store(), draft = new NativeDraft(identity, storage)
  let downloaded: Uint8Array | undefined
  const save = vi.fn(async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/outline.xlsx' } }, validation: { issues: [] } }
  })
  let current = await open(source, draft, save)
  sheet().getRange('A1:B2').activate(); grid.ribbon('outline-group:rows')
  await vi.waitFor(() => expect(draft.operations.some(operation => operation.kind === 'applySheetOutline')).toBe(true))
  expect(draft.operations.find(operation => operation.kind === 'applySheetOutline')).toMatchObject({
    sheetName: 'Sheet1', rows: [{ index: 0, level: 1, collapsed: false }, { index: 1, level: 1, collapsed: false }],
  })
  current.view?.dispose()
  current = await open(source, new NativeDraft(identity, storage), save)
  await vi.waitFor(() => expect(current.shell.save.disabled).toBe(false))
  current.shell.save.click()
  await vi.waitFor(() => expect(downloaded).toBeDefined())
  const saved = await readWorkbook(downloaded!)
  expect(saved.sheets[0]!.cells.B1!.formula).toBe('=A1*3')
  expect(saved.sheets[0]!.rows.filter(row => row.row <= 2).map(row => [row.row, row.outlineLevel])).toEqual([[1, 1], [2, 1]])
  expect(save).toHaveBeenCalledTimes(1)
  current.view?.dispose()
})

it('retains grouping across a row insertion and persists the inserted detail level', async () => {
  const source = await fixture(), draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const save = vi.fn(async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/outline-insert.xlsx' } }, validation: { issues: [] } }
  })
  const current = await open(source, draft, save)
  sheet().getRange('A1:B3').activate(); grid.ribbon('outline-group:rows')
  await vi.waitFor(() => expect(draft.operations.some(operation => operation.kind === 'applySheetOutline')).toBe(true))
  sheet().getRange('A2').activate()
  expect(grid.api.syncExecuteCommand('sheet.command.insert-row-by-range', { unitId: grid.api.getActiveWorkbook().getId(), subUnitId: sheet().getSheetId(), range: { startRow: 1, endRow: 1, startColumn: 0, endColumn: 9 }, direction: 0 })).toBe(true)
  await vi.waitFor(() => expect(draft.operations.some(operation => operation.kind === 'applyRowColumnOps')).toBe(true))
  current.shell.save.click()
  await vi.waitFor(() => expect(downloaded).toBeDefined())
  const saved = await readWorkbook(downloaded!)
  expect(saved.sheets[0]!.rows.filter(row => row.outlineLevel).map(row => [row.row, row.outlineLevel])).toEqual([[1, 1], [2, 1], [3, 1], [4, 1]])
  expect(saved.sheets[0]!.cells.B1!.formula).toBe('=A1*3')
  current.view?.dispose()
})

it('saves folded detail rows on a worksheet without any auto filter', async () => {
  const source = await fixture(), draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const save = vi.fn(async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/outline-hidden.xlsx' } }, validation: { issues: [] } }
  })
  const current = await open(source, draft, save)
  sheet().getRange('A1:B2').activate(); grid.ribbon('outline-group:rows'); grid.ribbon('outline-hide-detail')
  await vi.waitFor(() => expect(draft.operations.some(operation => operation.kind === 'applySheetOutline')).toBe(true))
  current.shell.save.click()
  await vi.waitFor(() => expect(downloaded).toBeDefined())
  const saved = await readWorkbook(downloaded!)
  expect(saved.sheets[0]!.rows.find(row => row.row === 1)).toMatchObject({ outlineLevel: 1, hidden: true })
  expect(saved.sheets[0]!.rows.find(row => row.row === 2)).toMatchObject({ outlineLevel: 1, hidden: true })
  expect(saved.sheets[0]!.rows.find(row => row.row === 3)).toMatchObject({ collapsed: true })
  current.view?.dispose()
})

it('groups by keyboard and preserves outline summary controls through native draft save', async () => {
  const source = await fixture(), storage = store(), draft = new NativeDraft(identity, storage)
  let downloaded: Uint8Array | undefined
  const save = vi.fn(async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/outline-summary.xlsx' } }, validation: { issues: [] } }
  })
  let current = await open(source, draft, save)
  sheet().getRange('A2:B3').activate()
  window.dispatchEvent(new KeyboardEvent('keydown', { code: 'ArrowRight', altKey: true, shiftKey: true, bubbles: true, cancelable: true }))
  grid.ribbon('outline-summary-below'); grid.ribbon('outline-summary-right')
  await vi.waitFor(() => expect(draft.operations.find(operation => operation.kind === 'applySheetOutline')).toMatchObject({ summaryBelow: false, summaryRight: false }))
  current.view?.dispose(); current = await open(source, new NativeDraft(identity, storage), save)
  current.shell.save.click()
  await vi.waitFor(() => expect(downloaded).toBeDefined())
  const saved = await readWorkbook(downloaded!)
  expect(saved.sheets[0]).toMatchObject({ outlineSummaryBelow: false, outlineSummaryRight: false })
  expect(saved.sheets[0]!.rows.find(row => row.row === 2)).toMatchObject({ outlineLevel: 1 })
  current.view?.dispose()
})

it('creates live consolidation formulas at the captured target with undo, draft recovery and real save', async () => {
  const source = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 2 } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 3 } },
    { sheetName: 'Sheet1', row: 0, column: 2, writeValue: true, cell: { value: 10 } },
    { sheetName: 'Sheet1', row: 1, column: 2, writeValue: true, cell: { value: 20 } },
  ])
  const storage = store(), draft = new NativeDraft(identity, storage)
  let downloaded: Uint8Array | undefined
  const save = vi.fn(async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/consolidate.xlsx' } }, validation: { issues: [] } }
  })
  let current = await open(source, draft, save)
  sheet().getRange('E1').activate(); grid.ribbon('consolidate-open')
  const dialog = document.querySelector<HTMLElement>('[aria-label="合并计算"]')
  expect(dialog).not.toBeNull()
  const reference = dialog!.querySelector<HTMLInputElement>('[aria-label="引用位置"]')!
  reference.value = 'A1:A2'; dialog!.querySelector<HTMLButtonElement>('[data-action="add"]')!.click()
  reference.value = 'C1:C2'
  sheet().getRange('F1').activate()
  dialog!.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(dialog!.querySelector('[role="alert"]')!.textContent).toContain('目标选区已变化')
  expect(sheet().getRange('F1').getValue()).toBeNull()
  sheet().getRange('E1').activate()
  dialog!.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(dialog!.hidden).toBe(true)
  expect(sheet().getRange('E1').getFormula()).toBe('=SUM(Sheet1!A1,Sheet1!C1)')
  await vi.waitFor(() => expect(sheet().getRange('E1:E2').getValues()).toEqual([[12], [23]]))
  history('undo'); expect(sheet().getRange('E1:E2').getValues()).toEqual([[null], [null]])
  history('redo')
  await vi.waitFor(() => expect(draft.operations).toHaveLength(1))
  expect((draft.operations[0] as any).edits.map((edit: any) => [edit.row, edit.column])).toEqual([[0, 4], [1, 4]])
  current.view?.dispose()
  current = await open(source, new NativeDraft(identity, storage), save)
  expect(sheet().getRange('E2').getFormula()).toBe('=SUM(Sheet1!A2,Sheet1!C2)')
  current.shell.save.click()
  await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const result = (await readWorkbook(downloaded!)).sheets[0]!
  expect(result.cells.E1?.formula).toBe('=SUM(Sheet1!A1,Sheet1!C1)')
  expect(result.cells.E2?.formula).toBe('=SUM(Sheet1!A2,Sheet1!C2)')
  expect(result.cells.A1?.value).toBe(2); expect(result.cells.C2?.value).toBe(20)
  current.view?.dispose()
}, 20000)

it('persists only the successful Goal Seek input after manual solving and draft recovery', async () => {
  const source = await fixture(), storage = store(), draft = new NativeDraft(identity, storage)
  let downloaded: Uint8Array | undefined
  const save = vi.fn(async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/goal.xlsx' } }, validation: { issues: [] } }
  })
  let current = await open(source, draft, save)
  await vi.waitFor(() => expect(sheet().getRange('B1').getValue()).toBe(6))
  sheet().getRange('B1').activate(); grid.ribbon('calc-mode:manual'); grid.ribbon('goal-seek-open')
  const dialog = document.querySelector<HTMLElement>('[aria-label="单变量求解"]')
  expect(dialog).not.toBeNull()
  expect(dialog!.querySelector<HTMLInputElement>('[aria-label="目标公式单元格"]')!.value).toBe('B1')
  dialog!.querySelector<HTMLInputElement>('[aria-label="目标值"]')!.value = '45'
  const byCell = dialog!.querySelector<HTMLInputElement>('[aria-label="可变单元格"]')!
  byCell.value = 'A1'; byCell.dispatchEvent(new Event('input'))
  dialog!.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  current.shell.save.click(); expect(save).not.toHaveBeenCalled()
  await vi.waitFor(() => expect(dialog!.textContent).toContain('找到解：15'), { timeout: 10000 })
  await vi.waitFor(() => expect(draft.operations).toHaveLength(1))
  expect((draft.operations[0] as any).edits.map((edit: any) => [edit.row, edit.column, edit.cell.value])).toEqual([[0, 0, 15]])
  current.view?.dispose()
  current = await open(source, new NativeDraft(identity, storage), save)
  expect(sheet().getRange('A1').getValue()).toBe(15)
  current.shell.save.click()
  await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const result = (await readWorkbook(downloaded!)).sheets[0]!
  expect(result.cells.A1?.value).toBe(15)
  expect(result.cells.B1?.formula).toBe('=A1*3')
  current.view?.dispose()
}, 20000)

it('restores a failed Goal Seek input without persisting intermediate guesses or marking a clean file dirty', async () => {
  const source = await applyCellEdits(await fixture(), [{ sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { formula: '=A1*0+5', value: 5 } }])
  const draft = new NativeDraft(identity, store()), current = await open(source, draft, vi.fn())
  const initiallyDisabled = current.shell.save.disabled
  await vi.waitFor(() => expect(sheet().getRange('B1').getValue()).toBe(5))
  sheet().getRange('B1').activate(); grid.ribbon('goal-seek-open')
  const dialog = document.querySelector<HTMLElement>('[aria-label="单变量求解"]')
  expect(dialog).not.toBeNull()
  dialog!.querySelector<HTMLInputElement>('[aria-label="目标值"]')!.value = '100'
  const byCell = dialog!.querySelector<HTMLInputElement>('[aria-label="可变单元格"]')!
  byCell.value = 'A1'; byCell.dispatchEvent(new Event('input'))
  dialog!.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  await vi.waitFor(() => expect(dialog!.querySelector('[role="status"]')!.textContent).toContain('未找到解'), { timeout: 10000 })
  expect(sheet().getRange('A1').getValue()).toBe(2)
  expect(draft.operations).toEqual([])
  expect(current.shell.statusLabel.textContent).toBe('已保存')
  expect(current.shell.save.disabled).toBe(initiallyDisabled)
  current.view?.dispose()
}, 20000)

it('rejects a sheet switch during the wait for existing draft persistence before data table writes', async () => {
  const source = await applyWorkbookOperations(await fixture(), [{ kind: 'applySheetEdits', plan: { renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'] } }])
  const current = await open(source, new NativeDraft(identity, store()), vi.fn())
  const workbook = grid.api.getActiveWorkbook()
  sheet().getRange('C5').setValue(42)
  sheet().getRange('A1:B3').activate()
  grid.ribbon('data-table-open')
  const dialog = document.querySelector<HTMLElement>('[aria-label="模拟运算表"]')!
  const input = dialog.querySelector<HTMLInputElement>('[aria-label="列输入单元格"]')!
  input.value = 'D1'; input.dispatchEvent(new Event('input'))
  dialog.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(grid.api.syncExecuteCommand('univer.command.undo')).toBe(false)
  expect(sheet().getRange('C5').getValue()).toBe(42)
  workbook.setActiveSheet(workbook.getSheetByName('Other'))
  await vi.waitFor(() => expect(dialog.querySelector('[role="alert"]')!.textContent).toContain('工作表身份已变化'))
  expect(workbook.getSheetByName('Other').getRange('D1').getValue()).toBeNull()
  expect(current.shell.save.disabled).toBe(false)
  current.view?.dispose()
})

it('runs a column data table in manual mode, restores inputs and saves only static results after draft recovery', async () => {
  const source = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 20, formula: '=D1*2' } },
    { sheetName: 'Sheet1', row: 0, column: 3, writeValue: true, cell: { value: 10 } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 3 } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: 5 } },
  ])
  const storage = store(), draft = new NativeDraft(identity, storage)
  const save = vi.fn(async (request: NativeSaveRequest) => {
    const bytes = await applyWorkbookOperations(source, request.operations)
    const model = (await readWorkbook(bytes)).sheets[0]!
    expect(model.cells.D1?.value).toBe(10)
    expect(model.cells.B1?.formula).toBe('=D1*2')
    expect(model.cells.B2?.value).toBe(6)
    expect(model.cells.B3?.value).toBe(10)
    expect(model.cells.B2?.formula).toBeUndefined()
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/table.xlsx' } }, validation: { issues: [] } }
  })
  let current = await open(source, draft, save)
  await vi.waitFor(() => expect(sheet().getRange('B1').getValue()).toBe(20))
  sheet().getRange('A1:B3').activate()
  grid.ribbon('calc-mode:manual')
  grid.ribbon('data-table-open')
  const dialog = document.querySelector<HTMLElement>('[aria-label="模拟运算表"]')
  expect(dialog).not.toBeNull()
  const column = dialog!.querySelector<HTMLInputElement>('[aria-label="列输入单元格"]')!
  column.value = 'D1'; column.dispatchEvent(new Event('input'))
  dialog!.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  current.shell.save.click()
  expect(save).not.toHaveBeenCalled()
  await vi.waitFor(() => expect(dialog!.textContent).toContain('已生成 2 个结果'), { timeout: 10000 })
  expect(sheet().getRange('D1').getValue()).toBe(10)
  expect(sheet().getRange('B2:B3').getValues()).toEqual([[6], [10]])
  history('undo')
  expect(sheet().getRange('B2:B3').getValues()).toEqual([[null], [null]])
  history('redo')
  await vi.waitFor(() => expect(draft.operations).toHaveLength(1))
  expect((draft.operations[0] as any).edits.map((edit: any) => [edit.row, edit.column])).toEqual([[1, 1], [2, 1]])
  current.view?.dispose()
  current = await open(source, new NativeDraft(identity, storage), save)
  expect(sheet().getRange('B2:B3').getValues()).toEqual([[6], [10]])
  current.shell.save.click()
  await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toContain('已保存修订 2'))
  expect(save).toHaveBeenCalledTimes(1)
  current.view?.dispose()
}, 20000)

afterEach(() => {
  grid.failNameImport = false
  grid.realRibbon = false
  for (const instance of grid.instances.splice(0)) instance.dispose()
  document.body.replaceChildren()
})


it('shows formulas per sheet and saves the view, and holds results in manual calculation until Calculate Now', async () => {
  const source = await fixture(), draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/c.xlsx' } }, validation: { issues: [] } }
  })
  const cell = () => sheet().getRange(0, 1)
  await vi.waitFor(() => expect(cell().getValue()).toBe(6))
  grid.ribbon('toggle-show-formulas')
  expect(cell().getDisplayValue()).toBe('=A1*3')
  await vi.waitFor(() => expect(draft.operations).toEqual([{ kind: 'applyPageSetups', setups: [{ sheetName: 'Sheet1', showFormulas: true }] }]))
  grid.ribbon('toggle-show-formulas')
  expect(cell().getDisplayValue()).not.toBe('=A1*3')
  expect(cell().getValue()).toBe(6)
  await vi.waitFor(() => expect(draft.operations).toEqual([]))
  grid.ribbon('calc-mode:manual')
  expect(await grid.api.executeCommand('sheet.command.set-range-values', { range: { startRow: 0, endRow: 0, startColumn: 0, endColumn: 0 }, value: { v: 5 } })).toBe(true)
  await new Promise(resolve => setTimeout(resolve, 300))
  expect(cell().getValue()).toBe(6)
  grid.ribbon('calculate-now')
  await vi.waitFor(() => expect(cell().getValue()).toBe(15))
  grid.ribbon('toggle-show-formulas')
  await vi.waitFor(() => expect(draft.operations.map((op: any) => op.kind)).toEqual(['applyCellEdits', 'applyPageSetups']))
  expect((draft.operations[0] as any).edits.map((edit: any) => [edit.row, edit.column])).toEqual([[0, 0]])
  current.shell.save.click()
  await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const saved = (await readWorkbook(downloaded!)).sheets[0]!
  expect(saved.showFormulas).toBe(true)
  expect(saved.cells.A1?.value).toBe(5)
  expect(saved.cells.B1?.formula).toBe('=A1*3')
  current.view?.dispose()
})


it('calculates source function overrides on initial native load without adding draft edits', async () => {
  const source = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 2 } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: null, formula: '=CELL("filename",A1)' } },
    { sheetName: 'Sheet1', row: 0, column: 2, writeValue: true, cell: { value: null, formula: '=RATE(5,-100,100,10)' } },
    { sheetName: 'Sheet1', row: 0, column: 3, writeValue: true, cell: { value: null, formula: '=MINIFS(A1:A1,A1:A1,99)' } },
    { sheetName: 'Sheet1', row: 0, column: 4, writeValue: true, cell: { value: null, formula: '=MAXIFS(A1:A1,A1:A1,99)' } },
  ])
  const draft = new NativeDraft(identity, store()), save = vi.fn()
  const current = await open(source, draft, save, '报表/运营 %.xlsx')
  try {
    await vi.waitFor(() => {
      expect(sheet().getRange('B1').getValue()).toBe('报表/[运营 %.xlsx]Sheet1')
      expect(sheet().getRange('C1').getValue()).toBeCloseTo(0.9623255039434997, 9)
      expect(sheet().getRange('D1').getValue()).toBe(0)
      expect(sheet().getRange('E1').getValue()).toBe(0)
    }, { timeout: 3000 })
    expect(draft.operations).toEqual([])
    expect(save).not.toHaveBeenCalled()
  } finally { current.view?.dispose() }
})

it('inserts source checkboxes through Ribbon, restores the draft and saves their interactive identity', async () => {
  const source = await fixture(), storage = store(), draft = new NativeDraft(identity, storage)
  let downloaded: Uint8Array | undefined
  const save = vi.fn(async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/checkbox.xlsx' } }, validation: { issues: [] } }
  })
  let current = await open(source, draft, save)
  try {
    sheet().getRange('C3:C4').activate()
    grid.ribbon('insert-checkbox')
    await vi.waitFor(() => expect(draft.operations.some(operation => operation.kind === 'replaceSheetDataValidations')).toBe(true))
    expect(sheet().getDataValidations()[0].rule.type).toBe('checkbox')
    history('undo')
    await vi.waitFor(() => expect(draft.operations).toEqual([]))
    history('redo')
    await vi.waitFor(() => expect(draft.operations.some(operation => operation.kind === 'replaceSheetDataValidations')).toBe(true))
    current.view?.dispose()
    current = await open(source, new NativeDraft(identity, storage), save)
    expect(sheet().getDataValidations()[0].rule.type).toBe('checkbox')
    current.shell.save.click()
    await vi.waitFor(() => expect(downloaded).toBeDefined())
    const saved = await readWorkbook(downloaded!)
    expect(saved.sheets[0]!.dataValidations!.rules[0]!.rule.type).toBe('checkbox')
    expect(saved.sheets[0]!.cells.B1?.formula).toBe('=A1*3')
    expect(save).toHaveBeenCalledTimes(1)
  } finally { current.view?.dispose() }
})

it('keeps repeated criteria formulas correct for imported text columns without creating edits', async () => {
  const source = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: '2026-06' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: '2026-05' } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: '2026-06' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 30 } },
    { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: 20 } },
    { sheetName: 'Sheet1', row: 2, column: 1, writeValue: true, cell: { value: 50 } },
    ...[0, 1, 2].map(row => ({ sheetName: 'Sheet1', row, column: 2, writeValue: true, cell: { value: null, formula: '=SUMIFS(B1:B3,A1:A3,"2026-06")' } })),
  ])
  const draft = new NativeDraft(identity, store()), save = vi.fn()
  const current = await open(source, draft, save)
  try {
    await vi.waitFor(() => expect(sheet().getRange('C1:C3').getValues()).toEqual([[80], [80], [80]]), { timeout: 3000 })
    expect(draft.operations).toEqual([])
    expect(save).not.toHaveBeenCalled()
  } finally { current.view?.dispose() }
})

it('keeps formula bar visibility in the session and preserves native cell draft edits', async () => {
  const source = await fixture(), storage = store(), draft = new NativeDraft(identity, storage)
  let finishSave!: (value: unknown) => void
  const save = vi.fn((_request: NativeSaveRequest) => new Promise(resolve => { finishSave = resolve }))
  let current = await open(source, draft, save)
  try {
    const host = () => document.querySelector<HTMLElement>('.workbook-grid')!
    grid.ribbon('toggle-formula-bar')
    expect(host().classList.contains('workbook-formula-bar-hidden')).toBe(true)
    expect(draft.operations).toEqual([])
    sheet().getRange('A1').setValue(7)
    await vi.waitFor(() => expect(draft.operations).toHaveLength(1))
    expect(draft.operations[0]).toMatchObject({ kind: 'applyCellEdits', edits: [{ row: 0, column: 0, cell: { value: 7 } }] })
    current.view?.dispose(); current = await open(source, new NativeDraft(identity, storage), save)
    expect(host().classList.contains('workbook-formula-bar-hidden')).toBe(false)
    expect(sheet().getRange('A1').getValue()).toBe(7)
    current.shell.save.click()
    await vi.waitFor(() => expect(save).toHaveBeenCalledOnce())
    grid.ribbon('toggle-formula-bar'); expect(host().classList.contains('workbook-formula-bar-hidden')).toBe(false)
    finishSave({ revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/view.xlsx' } }, validation: { issues: [] } })
    await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toContain('已保存修订 2'))
    grid.ribbon('toggle-formula-bar'); expect(host().classList.contains('workbook-formula-bar-hidden')).toBe(true)
    expect(save.mock.calls[0]![0].operations).toHaveLength(1)
  } finally { current.view?.dispose() }
})

it('atomically rejects removal referenced by incomplete source conditional formatting', async () => {
  const base = await applyWorkbookOperations(await fixture(), [{ kind: 'applySheetEdits', plan: {
    renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'],
  } }])
  const packageSource = await createBufferEntrySource(base), path = 'xl/worksheets/sheet2.xml'
  const unknown = '<conditionalFormatting sqref="A1"><cfRule type="future" priority="1"><formula>Sheet1!A1&gt;0</formula><alien/></cfRule></conditionalFormatting>'
  const xml = (await packageSource.readText(path)).replace('</worksheet>', `${unknown}</worksheet>`)
  const source = (await assemblePackage(base, { replaced: new Map([[path, xml]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
  const draft = new NativeDraft(identity, store()), save = vi.fn()
  const current = await open(source, draft, save)
  try {
    const workbook = grid.api.getActiveWorkbook(), before = workbook.getSnapshot()
    expect(await grid.api.executeCommand('sheet.command.remove-sheet', {
      unitId: workbook.getId(), subUnitId: workbook.getSheetByName('Sheet1').getSheetId(),
    })).toBe(false)
    expect(workbook.getSnapshot()).toEqual(before)
    expect(document.querySelector('.workbook-feedback')?.textContent).toContain('条件格式仍引用')
    expect(grid.api.syncExecuteCommand('univer.command.undo')).toBe(false)
    expect(draft.operations).toEqual([])
    expect(current.shell.statusLabel.textContent).toBe('已保存')
    expect(save).not.toHaveBeenCalled()
  } finally { current.view?.dispose() }
})

it.each(['plain', 'rename', 'insert-row'])('allows removal after clearing the current conditional formula reference: %s', async variant => {
  const base = await applyWorkbookOperations(await fixture(), [{ kind: 'applySheetEdits', plan: {
    renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'],
  } }])
  const source = await applyWorkbookOperations(base, [{ kind: 'replaceSheetConditionalFormats', sheetName: 'Other', rules: [{
    ranges: [{ startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 }], stopIfTrue: false,
    rule: { type: 'highlightCell', subType: 'formula', value: 'Sheet1!A1>0', style: { bg: { rgb: '#C6EFCE' } } },
  }] }])
  const draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/removed.xlsx' } }, validation: { issues: [] } }
  })
  try {
    const workbook = grid.api.getActiveWorkbook(), other = workbook.getSheetByName('Other')
    if (variant === 'rename') {
      expect(grid.api.syncExecuteCommand('sheet.command.set-worksheet-name', {
        unitId: workbook.getId(), subUnitId: other.getSheetId(), name: 'Renamed',
      })).toBe(true)
      await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applySheetEdits')).toBe(true))
    }
    if (variant === 'insert-row') {
      expect(grid.api.syncExecuteCommand('sheet.command.insert-row-by-range', {
        unitId: workbook.getId(), subUnitId: other.getSheetId(), range: { startRow: 1, endRow: 1, startColumn: 0, endColumn: 9 }, direction: 0,
      })).toBe(true)
      await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyRowColumnOps')).toBe(true))
    }
    for (const rule of other.getConditionalFormattingRules()) {
      expect(grid.api.syncExecuteCommand('sheet.command.set-conditional-rule', {
        unitId: workbook.getId(), subUnitId: other.getSheetId(), cfId: rule.cfId,
        rule: { ...rule, rule: { ...rule.rule, value: '=TRUE' } },
      })).toBe(true)
    }
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'replaceSheetConditionalFormats')).toBe(true))
    expect(await grid.api.executeCommand('sheet.command.remove-sheet', {
      unitId: workbook.getId(), subUnitId: workbook.getSheetByName('Sheet1').getSheetId(),
    }), document.querySelector('.workbook-feedback')?.textContent ?? '').toBe(true)
    const name = variant === 'rename' ? 'Renamed' : 'Other'
    expect(workbook.getSheets().map((item: any) => item.getSheetName())).toEqual([name])
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applySheetEdits'
      && (op.plan as { removals: string[] }).removals.length)).toBe(true))
    const kinds = draft.operations.map(op => op.kind)
    expect(kinds.indexOf('replaceSheetConditionalFormats')).toBeLessThan(kinds.lastIndexOf('applySheetEdits'))
    expect(draft.operations.find(op => op.kind === 'replaceSheetConditionalFormats')).toMatchObject({ sheetName: name })
    current.shell.save.click()
    await vi.waitFor(() => expect(downloaded).toBeDefined())
    const saved = await readWorkbook(downloaded!)
    expect(saved.sheets.map(item => item.name)).toEqual([name])
    expect(saved.sheets[0]!.conditionalFormatting!.rules[0]!.rule.value).toBe('TRUE')
  } finally { current.view?.dispose() }
})

it('atomically rejects removal referenced by incomplete source data validation', async () => {
  const base = await applyWorkbookOperations(await fixture(), [{ kind: 'applySheetEdits', plan: {
    renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'],
  } }])
  const packageSource = await createBufferEntrySource(base), path = 'xl/worksheets/sheet2.xml'
  const unknown = '<dataValidations count="1"><dataValidation type="list" sqref="B1:B4" future="1"><formula1>Sheet1!$A$1:$A$5</formula1></dataValidation></dataValidations>'
  const xml = (await packageSource.readText(path)).replace('</worksheet>', `${unknown}</worksheet>`)
  const source = (await assemblePackage(base, { replaced: new Map([[path, xml]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
  const draft = new NativeDraft(identity, store()), save = vi.fn()
  const current = await open(source, draft, save)
  try {
    const workbook = grid.api.getActiveWorkbook(), before = workbook.getSnapshot()
    expect(await grid.api.executeCommand('sheet.command.remove-sheet', {
      unitId: workbook.getId(), subUnitId: workbook.getSheetByName('Sheet1').getSheetId(),
    })).toBe(false)
    expect(workbook.getSnapshot()).toEqual(before)
    expect(document.querySelector('.workbook-feedback')?.textContent).toContain('数据验证仍引用')
    expect(grid.api.syncExecuteCommand('univer.command.undo')).toBe(false)
    expect(draft.operations).toEqual([])
    expect(current.shell.statusLabel.textContent).toBe('已保存')
    expect(save).not.toHaveBeenCalled()
  } finally { current.view?.dispose() }
})

it.each(['plain', 'rename', 'insert-row', 'with-cf'])('saves data validation removal before deleting its former source: %s', async variant => {
  const base = await applyWorkbookOperations(await fixture(), [{ kind: 'applySheetEdits', plan: {
    renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'],
  } }])
  let source = await applyWorkbookOperations(base, [{ kind: 'replaceSheetDataValidations', sheetName: 'Other', rules: [{
    ranges: [{ startRow: 0, endRow: 3, startColumn: 1, endColumn: 1 }], rule: { type: 'list', formula1: '=Sheet1!$A$1:$A$5' },
  }] }])
  if (variant === 'with-cf') source = await applyWorkbookOperations(source, [{ kind: 'replaceSheetConditionalFormats', sheetName: 'Other', rules: [{
    ranges: [{ startRow: 0, endRow: 3, startColumn: 1, endColumn: 1 }], stopIfTrue: false,
    rule: { type: 'highlightCell', subType: 'formula', value: 'Sheet1!A1>0', style: { bg: { rgb: '#C6EFCE' } } },
  }] }])
  const draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/dv-removed.xlsx' } }, validation: { issues: [] } }
  })
  try {
    const workbook = grid.api.getActiveWorkbook(), other = workbook.getSheetByName('Other')
    if (variant === 'rename') {
      expect(grid.api.syncExecuteCommand('sheet.command.set-worksheet-name', {
        unitId: workbook.getId(), subUnitId: other.getSheetId(), name: 'Renamed',
      })).toBe(true)
      await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applySheetEdits')).toBe(true))
    }
    if (variant === 'insert-row') {
      expect(grid.api.syncExecuteCommand('sheet.command.insert-row-by-range', {
        unitId: workbook.getId(), subUnitId: other.getSheetId(), range: { startRow: 1, endRow: 1, startColumn: 0, endColumn: 9 }, direction: 0,
      })).toBe(true)
      await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyRowColumnOps')).toBe(true))
    }
    for (const { rule } of other.getDataValidations()) {
      expect(grid.api.syncExecuteCommand('data-validation.mutation.removeRule', {
        unitId: workbook.getId(), subUnitId: other.getSheetId(), ruleId: rule.uid,
      })).toBe(true)
    }
    for (const rule of other.getConditionalFormattingRules()) {
      expect(grid.api.syncExecuteCommand('sheet.command.set-conditional-rule', {
        unitId: workbook.getId(), subUnitId: other.getSheetId(), cfId: rule.cfId,
        rule: { ...rule, rule: { ...rule.rule, value: '=TRUE' } },
      })).toBe(true)
    }
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'replaceSheetDataValidations')).toBe(true))
    expect(await grid.api.executeCommand('sheet.command.remove-sheet', {
      unitId: workbook.getId(), subUnitId: workbook.getSheetByName('Sheet1').getSheetId(),
    }), document.querySelector('.workbook-feedback')?.textContent ?? '').toBe(true)
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applySheetEdits'
      && (op.plan as { removals: string[] }).removals.length)).toBe(true))
    const name = variant === 'rename' ? 'Renamed' : 'Other', kinds = draft.operations.map(op => op.kind)
    expect(kinds.indexOf('replaceSheetDataValidations')).toBeLessThan(kinds.lastIndexOf('applySheetEdits'))
    expect(draft.operations.find(op => op.kind === 'replaceSheetDataValidations')).toMatchObject({ sheetName: name, rules: [] })
    current.shell.save.click()
    await vi.waitFor(() => expect(downloaded).toBeDefined())
    const saved = await readWorkbook(downloaded!)
    expect(saved.sheets.map(item => item.name)).toEqual([name])
    expect(saved.sheets[0]!.dataValidations!.rules).toEqual([])
  } finally { current.view?.dispose() }
})

it.each(['=Sheet1!A1', '=[report-workbook]sheet1!a1'])('atomically rejects removal referenced by live cell formula %s', async formula => {
  const base = await applyWorkbookOperations(await fixture(), [{ kind: 'applySheetEdits', plan: {
    renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'],
  } }])
  const source = await applyCellEdits(base, [{ sheetName: 'Other', row: 0, column: 2, writeValue: true, cell: { value: null, formula } }])
  const draft = new NativeDraft(identity, store()), current = await open(source, draft, vi.fn())
  try {
    const workbook = grid.api.getActiveWorkbook(), before = workbook.getSnapshot()
    expect(await grid.api.executeCommand('sheet.command.remove-sheet', {
      unitId: workbook.getId(), subUnitId: workbook.getSheetByName('Sheet1').getSheetId(),
    })).toBe(false)
    expect(workbook.getSnapshot()).toEqual(before)
    expect(grid.api.syncExecuteCommand('univer.command.undo')).toBe(false)
    expect(draft.operations).toEqual([])
    expect(document.querySelector('.workbook-feedback')?.textContent).toContain('公式仍引用')
  } finally { current.view?.dispose() }
})

it.each(['plain', 'rename', 'insert-row'])('saves cleared cell reference before deleting its former source: %s', async variant => {
  const base = await applyWorkbookOperations(await fixture(), [{ kind: 'applySheetEdits', plan: {
    renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'],
  } }])
  const source = await applyCellEdits(base, [{ sheetName: 'Other', row: 0, column: 2, writeValue: true, cell: { value: null, formula: '=Sheet1!A1' } }])
  const draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/cell-removed.xlsx' } }, validation: { issues: [] } }
  })
  try {
    const workbook = grid.api.getActiveWorkbook(), other = workbook.getSheetByName('Other')
    if (variant === 'rename') {
      expect(grid.api.syncExecuteCommand('sheet.command.set-worksheet-name', {
        unitId: workbook.getId(), subUnitId: other.getSheetId(), name: 'Renamed',
      })).toBe(true)
      await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applySheetEdits')).toBe(true))
    }
    if (variant === 'insert-row') {
      expect(grid.api.syncExecuteCommand('sheet.command.insert-row-by-range', {
        unitId: workbook.getId(), subUnitId: other.getSheetId(), range: { startRow: 0, endRow: 0, startColumn: 0, endColumn: 9 }, direction: 0,
      })).toBe(true)
      await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyRowColumnOps')).toBe(true))
    }
    const address = variant === 'insert-row' ? 'C2' : 'C1'
    other.getRange(address).setValue(42)
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyCellEdits')).toBe(true))
    expect(await grid.api.executeCommand('sheet.command.remove-sheet', {
      unitId: workbook.getId(), subUnitId: workbook.getSheetByName('Sheet1').getSheetId(),
    }), document.querySelector('.workbook-feedback')?.textContent ?? '').toBe(true)
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applySheetEdits'
      && (op.plan as { removals: string[] }).removals.length)).toBe(true))
    const kinds = draft.operations.map(op => op.kind)
    expect(kinds.indexOf('applyCellEdits')).toBeLessThan(kinds.lastIndexOf('applySheetEdits'))
    current.shell.save.click()
    await vi.waitFor(() => expect(downloaded).toBeDefined())
    const saved = await readWorkbook(downloaded!), name = variant === 'rename' ? 'Renamed' : 'Other'
    expect(saved.sheets.map(item => item.name)).toEqual([name])
    expect(saved.sheets[0]!.cells[address]).toMatchObject({ value: 42 })
    expect(saved.sheets[0]!.cells[address]!.formula).toBeUndefined()
  } finally { current.view?.dispose() }
})

it('retains unprojected shared formula dependency after only its anchor is edited', async () => {
  const base = await applyWorkbookOperations(await fixture(), [{ kind: 'applySheetEdits', plan: {
    renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'],
  } }])
  const packageSource = await createBufferEntrySource(base), path = 'xl/worksheets/sheet2.xml'
  const xml = (await packageSource.readText(path)).replace(/<sheetData\b[^>]*(?:\/>|>[\s\S]*?<\/sheetData>)/,
    '<sheetData><row r="1"><c r="C1"><f t="shared" si="0" ref="C1:C2">Sheet1!A1</f><v>2</v></c></row><row r="2"><c r="C2"><f t="shared" si="0"/><v>3</v></c></row></sheetData>')
  const source = (await assemblePackage(base, { replaced: new Map([[path, xml]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
  const draft = new NativeDraft(identity, store()), current = await open(source, draft, vi.fn())
  try {
    const workbook = grid.api.getActiveWorkbook(), other = workbook.getSheetByName('Other')
    other.getRange('C1').setValue(42)
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyCellEdits')).toBe(true))
    const before = workbook.getSnapshot(), operations = structuredClone(draft.operations)
    expect(await grid.api.executeCommand('sheet.command.remove-sheet', {
      unitId: workbook.getId(), subUnitId: workbook.getSheetByName('Sheet1').getSheetId(),
    })).toBe(false)
    expect(workbook.getSnapshot()).toEqual(before)
    expect(draft.operations).toEqual(operations)
    expect(document.querySelector('.workbook-feedback')?.textContent).toContain('未完整投影')
  } finally { current.view?.dispose() }
})

it.each(['global', 'local'])('atomically rejects referenced sheet removal from %s defined names', async scope => {
  const base = await applyWorkbookOperations(await fixture(), [{ kind: 'applySheetEdits', plan: {
    renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'],
  } }])
  const source = await applyWorkbookOperations(base, [{ kind: 'applyDefinedNames', plan: { sets: [{
    name: 'DeleteDependency', refersTo: 'Sheet1!$A$1', ...(scope === 'local' ? { scopeSheetName: 'Other' } : {}),
  }] } }])
  const draft = new NativeDraft(identity, store()), current = await open(source, draft, vi.fn())
  try {
    const workbook = grid.api.getActiveWorkbook(), before = workbook.getSnapshot()
    expect(await grid.api.executeCommand('sheet.command.remove-sheet', {
      unitId: workbook.getId(), subUnitId: workbook.getSheetByName('Sheet1').getSheetId(),
    })).toBe(false)
    expect(workbook.getSnapshot()).toEqual(before)
    expect(grid.api.syncExecuteCommand('univer.command.undo')).toBe(false)
    expect(draft.operations).toEqual([])
    expect(document.querySelector('.workbook-feedback')?.textContent).toContain('定义名称')
  } finally { current.view?.dispose() }
})

it.each(['plain', 'rename', 'local'])('saves changed defined name before deleting its former source: %s', async variant => {
  const base = await applyWorkbookOperations(await fixture(), [{ kind: 'applySheetEdits', plan: {
    renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'],
  } }])
  const source = await applyWorkbookOperations(base, [{ kind: 'applyDefinedNames', plan: { sets: [{
    name: 'DeleteDependency', refersTo: 'Sheet1!$A$1', ...(variant === 'local' ? { scopeSheetName: 'Other' } : {}),
  }] } }])
  const draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/names-removed.xlsx' } }, validation: { issues: [] } }
  })
  try {
    const workbook = grid.api.getActiveWorkbook(), other = workbook.getSheetByName('Other')
    if (variant === 'rename') {
      expect(grid.api.syncExecuteCommand('sheet.command.set-worksheet-name', {
        unitId: workbook.getId(), subUnitId: other.getSheetId(), name: 'Renamed',
      })).toBe(true)
      await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applySheetEdits')).toBe(true))
    }
    const name = variant === 'rename' ? 'Renamed' : 'Other'
    workbook.getDefinedNames().find((item: any) => item.getName() === 'DeleteDependency').setRef(`${name}!$B$1`)
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyDefinedNames')).toBe(true))
    expect(await grid.api.executeCommand('sheet.command.remove-sheet', {
      unitId: workbook.getId(), subUnitId: workbook.getSheetByName('Sheet1').getSheetId(),
    }), document.querySelector('.workbook-feedback')?.textContent ?? '').toBe(true)
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applySheetEdits'
      && (op.plan as { removals: string[] }).removals.length)).toBe(true))
    const kinds = draft.operations.map(op => op.kind)
    expect(kinds.indexOf('applyDefinedNames')).toBeLessThan(kinds.lastIndexOf('applySheetEdits'))
    current.shell.save.click()
    await vi.waitFor(() => expect(downloaded).toBeDefined())
    const saved = await readWorkbook(downloaded!)
    expect(saved.sheets.map(item => item.name)).toEqual([name])
    expect(saved.definedNames).toEqual([{ name: 'DeleteDependency', refersTo: `${name}!$B$1`, ...(variant === 'local' ? { scopeSheetName: name } : {}) }])
  } finally { current.view?.dispose() }
})

it.each(['builtin', 'failed-import'])('protects actual source defined names missing from live projection: %s', async variant => {
  const base = await applyWorkbookOperations(await fixture(), [{ kind: 'applySheetEdits', plan: {
    renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'],
  } }])
  let source: Uint8Array
  if (variant === 'failed-import') {
    source = await applyWorkbookOperations(base, [{ kind: 'applyDefinedNames', plan: { sets: [{ name: 'LostDependency', refersTo: 'Sheet1!$A$1' }] } }])
    grid.failNameImport = true
  } else {
    const packageSource = await createBufferEntrySource(base), path = 'xl/workbook.xml'
    const xml = (await packageSource.readText(path)).replace('</workbook>', '<definedNames><definedName name="_xlnm.Print_Area" localSheetId="1">Sheet1!$A$1</definedName></definedNames></workbook>')
    source = (await assemblePackage(base, { replaced: new Map([[path, xml]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
  }
  const draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/preserved-name.xlsx' } }, validation: { issues: [] } }
  })
  try {
    const workbook = grid.api.getActiveWorkbook(), before = workbook.getSnapshot()
    expect(workbook.getDefinedNames()).toEqual([])
    expect(await grid.api.executeCommand('sheet.command.remove-sheet', {
      unitId: workbook.getId(), subUnitId: workbook.getSheetByName('Sheet1').getSheetId(),
    })).toBe(false)
    expect(workbook.getSnapshot()).toEqual(before)
    expect(draft.operations).toEqual([])
    expect(document.querySelector('.workbook-feedback')?.textContent).toContain('未完整投影')
    if (variant === 'failed-import') {
      workbook.getSheetByName('Other').getRange('B2').setValue(17)
      await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyCellEdits')).toBe(true))
      expect(draft.operations.some(op => op.kind === 'applyDefinedNames')).toBe(false)
      current.shell.save.click()
      await vi.waitFor(() => expect(downloaded).toBeDefined())
      expect((await readWorkbook(downloaded!)).definedNames).toEqual([{ name: 'LostDependency', refersTo: 'Sheet1!$A$1' }])
    }
  } finally { current.view?.dispose() }
})

it('allows deleting a sheet together with only its own local defined name', async () => {
  const base = await applyWorkbookOperations(await fixture(), [{ kind: 'applySheetEdits', plan: {
    renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'],
  } }])
  const source = await applyWorkbookOperations(base, [{ kind: 'applyDefinedNames', plan: { sets: [
    { name: 'OwnDependency', refersTo: 'Sheet1!$A$1', scopeSheetName: 'Sheet1' },
    { name: 'KeepName', refersTo: 'Other!$B$1' },
  ] } }])
  const draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/own-name.xlsx' } }, validation: { issues: [] } }
  })
  try {
    const workbook = grid.api.getActiveWorkbook()
    expect(await grid.api.executeCommand('sheet.command.remove-sheet', {
      unitId: workbook.getId(), subUnitId: workbook.getSheetByName('Sheet1').getSheetId(),
    })).toBe(true)
    await vi.waitFor(() => expect(draft.operations).toEqual([{ kind: 'applySheetEdits', plan: {
      renames: [], additions: [], removals: ['Sheet1'], order: ['Other'],
    } }]))
    current.shell.save.click()
    await vi.waitFor(() => expect(downloaded).toBeDefined())
    expect((await readWorkbook(downloaded!)).definedNames).toEqual([{ name: 'KeepName', refersTo: 'Other!$B$1' }])
  } finally { current.view?.dispose() }
})

it('keeps failed deleted-local name identity separate from a removed same-name global', async () => {
  const base = await applyWorkbookOperations(await fixture(), [{ kind: 'applySheetEdits', plan: {
    renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'],
  } }])
  const source = await applyWorkbookOperations(base, [{ kind: 'applyDefinedNames', plan: { sets: [
    { name: 'LostDependency', refersTo: 'Sheet1!$A$1', scopeSheetName: 'Sheet1' },
    { name: 'LostDependency', refersTo: 'Other!$B$1' },
  ] } }])
  grid.failNameImport = 'local'
  const draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/scoped-names.xlsx' } }, validation: { issues: [] } }
  })
  try {
    const workbook = grid.api.getActiveWorkbook()
    expect(workbook.getDefinedNames()).toHaveLength(1)
    workbook.getDefinedNames()[0].delete()
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyDefinedNames')).toBe(true))
    expect(await grid.api.executeCommand('sheet.command.remove-sheet', {
      unitId: workbook.getId(), subUnitId: workbook.getSheetByName('Sheet1').getSheetId(),
    })).toBe(true)
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applySheetEdits')).toBe(true))
    expect(draft.operations.find(op => op.kind === 'applyDefinedNames')).toMatchObject({ plan: { removes: ['LostDependency'] } })
    current.shell.save.click()
    await vi.waitFor(() => expect(downloaded).toBeDefined())
    expect((await readWorkbook(downloaded!)).definedNames ?? []).toEqual([])
  } finally { current.view?.dispose() }
})

it.each(['Source', 'Other'])('uses actual unprojected chart XML before removing a sheet: %s', async reference => {
  const base = await applyWorkbookOperations(await fixture(), [{ kind: 'applySheetEdits', plan: {
    renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'],
  } }])
  const relation = (kind: string, target: string) => `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/${kind}" Target="${target}"/></Relationships>`
  const chart = `<chartSpace xmlns="http://schemas.openxmlformats.org/drawingml/2006/chart"><chart><f>${reference === 'Source' ? 'Sheet1' : 'Other'}!$A$1:$A$5</f></chart></chartSpace>`
  const added = new Map([
    ['xl/worksheets/_rels/sheet2.xml.rels', relation('drawing', '../drawings/drawing1.xml')],
    ['xl/drawings/drawing1.xml', '<drawing/>'],
    ['xl/drawings/_rels/drawing1.xml.rels', relation('chart', '../charts/chart1.xml')],
    ['xl/charts/chart1.xml', chart],
  ])
  const source = (await assemblePackage(base, { replaced: new Map(), added, addedBinary: new Map(), removedEntries: [], addedEntries: [...added.keys()], touchedEntries: [...added.keys()] })).buffer
  const draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/chart-preserved.xlsx' } }, validation: { issues: [] } }
  })
  try {
    const workbook = grid.api.getActiveWorkbook(), before = workbook.getSnapshot()
    const removed = await grid.api.executeCommand('sheet.command.remove-sheet', {
      unitId: workbook.getId(), subUnitId: workbook.getSheetByName('Sheet1').getSheetId(),
    })
    expect(removed).toBe(reference === 'Other')
    if (reference === 'Source') {
      expect(workbook.getSnapshot()).toEqual(before)
      expect(grid.api.syncExecuteCommand('univer.command.undo')).toBe(false)
      expect(draft.operations).toEqual([])
      expect(document.querySelector('.workbook-feedback')?.textContent).toContain('图表')
    } else {
      await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applySheetEdits')).toBe(true))
      current.shell.save.click()
      await vi.waitFor(() => expect(downloaded).toBeDefined())
      const output = await createBufferEntrySource(downloaded!)
      expect(await output.readText('xl/charts/chart1.xml')).toBe(chart)
      expect((await readWorkbook(downloaded!)).sheets.map(sheet => sheet.name)).toEqual(['Other'])
    }
  } finally { current.view?.dispose() }
})

it('keeps chart references current when a source sheet is renamed before removal', async () => {
  const base = await applyWorkbookOperations(await fixture(), [{ kind: 'applySheetEdits', plan: {
    renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'],
  } }])
  const relation = (kind: string, target: string) => `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/${kind}" Target="${target}"/></Relationships>`
  const path = 'xl/charts/chart1.xml'
  const chart = '<q:chartSpace xmlns:q="http://schemas.openxmlformats.org/drawingml/2006/chart"><q:chart><q:f>Sheet1!$A$1:$A$5</q:f></q:chart></q:chartSpace>'
  const added = new Map([
    ['xl/worksheets/_rels/sheet2.xml.rels', relation('drawing', '../drawings/drawing1.xml')],
    ['xl/drawings/drawing1.xml', '<drawing/>'],
    ['xl/drawings/_rels/drawing1.xml.rels', relation('chart', '../charts/chart1.xml')],
    [path, chart],
  ])
  const source = (await assemblePackage(base, { replaced: new Map(), added, addedBinary: new Map(), removedEntries: [], addedEntries: [...added.keys()], touchedEntries: [...added.keys()] })).buffer
  const draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/renamed-chart.xlsx' } }, validation: { issues: [] } }
  })
  try {
    const workbook = grid.api.getActiveWorkbook(), id = workbook.getSheetByName('Sheet1').getSheetId()
    expect(grid.api.syncExecuteCommand('sheet.command.set-worksheet-name', { unitId: workbook.getId(), subUnitId: id, name: 'Renamed' })).toBe(true)
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applySheetEdits')).toBe(true))
    current.shell.save.click()
    await vi.waitFor(() => expect(downloaded).toBeDefined())
    expect(await (await createBufferEntrySource(downloaded!)).readText(path)).toBe(chart.replace('Sheet1!', 'Renamed!'))
    const snapshot = workbook.getSnapshot(), operations = structuredClone(draft.operations)
    expect(await grid.api.executeCommand('sheet.command.remove-sheet', { unitId: workbook.getId(), subUnitId: id })).toBe(false)
    expect(workbook.getSnapshot()).toEqual(snapshot)
    expect(draft.operations).toEqual(operations)
    expect(document.querySelector('.workbook-feedback')?.textContent).toContain('图表')
  } finally { current.view?.dispose() }
})

it.each([false, true])('deletes owned chart parts and protects a shared surviving chart: shared=%s', async shared => {
  const base = await applyWorkbookOperations(await fixture(), [{ kind: 'applySheetEdits', plan: {
    renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'],
  } }])
  const relation = (kind: string, target: string) => `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/${kind}" Target="${target}"/></Relationships>`
  const chartPath = 'xl/charts/chart1.xml', drawingPath = 'xl/drawings/drawing1.xml'
  const added = new Map([
    ['xl/worksheets/_rels/sheet1.xml.rels', relation('drawing', '../drawings/drawing1.xml')],
    [drawingPath, '<drawing/>'],
    ['xl/drawings/_rels/drawing1.xml.rels', relation('chart', '../charts/chart1.xml')],
    [chartPath, '<chartSpace xmlns="http://schemas.openxmlformats.org/drawingml/2006/chart"><f>Sheet1!$A$1</f></chartSpace>'],
    ...(shared ? [['xl/worksheets/_rels/sheet2.xml.rels', relation('drawing', '../drawings/drawing1.xml')] as [string, string]] : []),
  ])
  const source = (await assemblePackage(base, { replaced: new Map(), added, addedBinary: new Map(), removedEntries: [], addedEntries: [...added.keys()], touchedEntries: [...added.keys()] })).buffer
  const draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/owned-removed.xlsx' } }, validation: { issues: [] } }
  })
  try {
    const workbook = grid.api.getActiveWorkbook(), before = workbook.getSnapshot()
    expect(await grid.api.executeCommand('sheet.command.remove-sheet', { unitId: workbook.getId(), subUnitId: workbook.getSheetByName('Sheet1').getSheetId() })).toBe(!shared)
    if (shared) {
      expect(workbook.getSnapshot()).toEqual(before)
      expect(draft.operations).toEqual([])
      expect(document.querySelector('.workbook-feedback')?.textContent).toContain('图表')
    } else {
      await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applySheetEdits')).toBe(true))
      current.shell.save.click()
      await vi.waitFor(() => expect(downloaded).toBeDefined())
      const output = await createBufferEntrySource(downloaded!), input = await createBufferEntrySource(source)
      expect(await output.has(chartPath)).toBe(false)
      expect(await output.has(drawingPath)).toBe(false)
      expect(await output.has('xl/drawings/_rels/drawing1.xml.rels')).toBe(false)
      for (const part of ['xl/worksheets/sheet2.xml', 'xl/styles.xml']) expect(await output.readText(part)).toBe(await input.readText(part))
      expect((await readWorkbook(downloaded!)).sheets.map(sheet => sheet.name)).toEqual(['Other'])
    }
  } finally { current.view?.dispose() }
})

it('refuses removing a sheet whose table is referenced by a surviving sparse cell formula', async () => {
  const source = await applyWorkbookOperations(await fixture(), [
    { kind: 'applySheetEdits', plan: { renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'] } },
    { kind: 'applyTableAdditions', additions: [{ worksheetSheetName: 'Sheet1', area: { startRow: 0, endRow: 1, startColumn: 0, endColumn: 0 }, name: 'SalesData', columnNames: ['Amount'], style: '', bandedRows: false }] },
  ])
  const draft = new NativeDraft(identity, store()), current = await open(source, draft, vi.fn(async () => { throw new Error('unexpected save') }))
  try {
    const workbook = grid.api.getActiveWorkbook(), other = workbook.getSheetByName('Other')
    other.getRange(999, 15).setValue('=SUM(SalesData[Amount])')
    await vi.waitFor(() => expect(draft.operations.length).toBeGreaterThan(0))
    const before = workbook.getSnapshot(), operations = structuredClone(draft.operations)
    expect(await grid.api.executeCommand('sheet.command.remove-sheet', { unitId: workbook.getId(), subUnitId: workbook.getSheetByName('Sheet1').getSheetId() })).toBe(false)
    expect(workbook.getSnapshot()).toEqual(before)
    expect(draft.operations).toEqual(operations)
    expect(document.querySelector('.workbook-feedback')?.textContent).toContain('SalesData')
  } finally { current.view?.dispose() }
})

it('saves clearing a structured table reference before deleting its owner sheet', async () => {
  const source = await applyWorkbookOperations(await fixture(), [
    { kind: 'applySheetEdits', plan: { renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'] } },
    { kind: 'applyTableAdditions', additions: [{ worksheetSheetName: 'Sheet1', area: { startRow: 0, endRow: 1, startColumn: 0, endColumn: 0 }, name: 'SalesData', columnNames: ['Amount'], style: '', bandedRows: false }] },
    { kind: 'applyCellEdits', edits: [{ sheetName: 'Other', row: 0, column: 0, writeValue: true, cell: { value: null, formula: '=SUM(SalesData[Amount])' } }] },
  ])
  const draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/table-removed.xlsx' } }, validation: { issues: [] } }
  })
  try {
    const workbook = grid.api.getActiveWorkbook()
    workbook.getSheetByName('Other').getRange(0, 0).setValue(1)
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyCellEdits')).toBe(true))
    const tables = structuredClone(workbook.getTableList())
    const removed = await grid.api.executeCommand('sheet.command.remove-sheet', { unitId: workbook.getId(), subUnitId: workbook.getSheetByName('Sheet1').getSheetId() })
    expect(removed, document.querySelector('.workbook-feedback')?.textContent ?? '').toBe(true)
    expect(grid.api.syncExecuteCommand('univer.command.undo')).toBe(true)
    expect(workbook.getTableList()).toEqual(tables)
    expect(grid.api.syncExecuteCommand('univer.command.redo')).toBe(true)
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applySheetEdits')).toBe(true))
    current.shell.save.click()
    await vi.waitFor(() => expect(downloaded).toBeDefined())
    const output = await readWorkbook(downloaded!)
    expect(output.sheets.map(sheet => sheet.name)).toEqual(['Other'])
    expect(output.sheets[0]!.cells.A1!.value).toBe(1)
    expect(await (await createBufferEntrySource(downloaded!)).paths()).not.toContain('xl/tables/table1.xml')
  } finally { current.view?.dispose() }
})

function pivotRemovalFixture(): Uint8Array {
  return new Uint8Array(execFileSync(resolve(process.cwd(), '../../../.venv/bin/python'), ['-c', `
from openpyxl import Workbook
from openpyxl.pivot.table import TableDefinition, Location
from openpyxl.pivot.cache import CacheDefinition, CacheSource, WorksheetSource, CacheField, SharedItems
from io import BytesIO
import sys
book=Workbook();source=book.active;source.title='Source';source.append(['Category','Amount']);source.append(['A',10])
pivot=book.create_sheet('Pivot');book.create_sheet('Unused')
table=TableDefinition(name='Report',cacheId=1,dataCaption='Values',location=Location(ref='A1:B3',firstHeaderRow=1,firstDataRow=1,firstDataCol=1))
table.cache=CacheDefinition(cacheSource=CacheSource(type='worksheet',worksheetSource=WorksheetSource(ref='A1:B2',sheet='Source')),cacheFields=[CacheField(name='Category',sharedItems=SharedItems()),CacheField(name='Amount',sharedItems=SharedItems())])
pivot.add_pivot(table);out=BytesIO();book.save(out);sys.stdout.buffer.write(out.getvalue())
`]))
}

it.each([false, true])('atomically refuses all pivot source row/column commands and raw mutations (renamed=%s)', async renamed => {
  const source = pivotRemovalFixture(), draft = new NativeDraft(identity, store()), save = vi.fn(async () => { throw new Error('unexpected save') })
  const current = await open(source, draft, save)
  try {
    const workbook = grid.api.getActiveWorkbook(), sourceId = workbook.getSheetByName('Source').getSheetId(), name = "财务 O'Brien & 数据"
    if (renamed) {
      expect(grid.api.syncExecuteCommand('sheet.command.set-worksheet-name', { unitId: workbook.getId(), subUnitId: sourceId, name })).toBe(true)
      await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applySheetEdits')).toBe(true))
    }
    const { IUndoRedoService } = await import('@univerjs/core')
    const stack = grid.instances.at(-1).__getInjector().get(IUndoRedoService)
    const before = workbook.getSnapshot(), operations = structuredClone(draft.operations), draftState = [draft.canUndo, draft.canRedo, draft.dirty]
    const topUndo = stack.pitchTopUndoElement(), topRedo = stack.pitchTopRedoElement(), label = current.shell.status.textContent
    for (const id of ['sheet.command.insert-row-by-range', 'sheet.command.remove-row-by-range', 'sheet.command.insert-col-by-range', 'sheet.command.remove-col-by-range',
      'sheet.command.insert-row', 'sheet.command.remove-row', 'sheet.command.insert-col', 'sheet.command.remove-col',
      'sheet.mutation.insert-row', 'sheet.mutation.remove-rows', 'sheet.mutation.insert-col', 'sheet.mutation.remove-col']) {
      expect(grid.api.syncExecuteCommand(id, { unitId: workbook.getId(), subUnitId: sourceId, range: { startRow: 0, endRow: 0, startColumn: 0, endColumn: 0 }, direction: 0 })).toBe(false)
      expect(workbook.getSnapshot()).toEqual(before); expect(draft.operations).toEqual(operations); expect([draft.canUndo, draft.canRedo, draft.dirty]).toEqual(draftState)
      expect(stack.pitchTopUndoElement()).toBe(topUndo); expect(stack.pitchTopRedoElement()).toBe(topRedo)
      expect(current.shell.status.textContent).toBe(label)
      expect(document.querySelector('.workbook-feedback')?.textContent).toContain(`仍有透视表读取工作表 "${renamed ? name : 'Source'}"`)
    }
    expect(save).not.toHaveBeenCalled()
  } finally { current.view?.dispose() }
})

it('keeps rejected native Ribbon row/column facade calls from marking the pivot source dirty or replacing its reason', async () => {
  const source = pivotRemovalFixture(), storage = store(), draft = new NativeDraft(identity, storage), save = vi.fn(async () => { throw new Error('unexpected save') })
  const actual = await vi.importActual<typeof import('./workbook-ribbon')>('./workbook-ribbon')
  const current = await open(source, draft, save)
  try {
    const workbook = grid.api.getActiveWorkbook()
    workbook.setActiveSheet(workbook.getSheetByName('Source')); workbook.getActiveSheet().getRange('A2').activate()
    const { IUndoRedoService } = await import('@univerjs/core'), stack = grid.instances.at(-1).__getInjector().get(IUndoRedoService)
    const before = workbook.getSnapshot(), operations = structuredClone(draft.operations), label = current.shell.statusLabel.textContent
    const undo = stack.pitchTopUndoElement(), redo = stack.pitchTopRedoElement()
    for (const action of ['insert-row-here', 'delete-row-here', 'insert-col-here', 'delete-col-here']) {
      grid.apply.mockImplementationOnce(actual.applyWorkbookRibbonCommand as never)
      grid.ribbon(action)
      expect(workbook.getSnapshot()).toEqual(before)
      expect(draft.operations).toEqual(operations)
      expect(stack.pitchTopUndoElement()).toBe(undo); expect(stack.pitchTopRedoElement()).toBe(redo)
      expect(current.shell.statusLabel.textContent).toBe(label)
      expect(document.querySelector('.workbook-feedback')?.textContent).toBe('仍有透视表读取工作表 "Source" 的来源数据，已拒绝插入/删除行列。')
    }
    expect(save).not.toHaveBeenCalled()
  } finally { current.view?.dispose(); grid.apply.mockReset(); grid.apply.mockReturnValue(false) }
})

it.each([false, true])('allows unrelated sheet row/column changes with pivot source parts retained through undo and draft save (renamed=%s)', async renamed => {
  const source = pivotRemovalFixture(), draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => { downloaded = await applyWorkbookOperations(source, request.operations); return { revision: 2, revisionRegistered: true } })
  try {
    const workbook = grid.api.getActiveWorkbook(), subUnitId = workbook.getSheetByName('Unused').getSheetId()
    if (renamed) {
      expect(grid.api.syncExecuteCommand('sheet.command.set-worksheet-name', { unitId: workbook.getId(), subUnitId: workbook.getSheetByName('Source').getSheetId(), name: "财务 O'Brien & 数据" })).toBe(true)
      await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applySheetEdits')).toBe(true))
    }
    for (const id of ['sheet.command.insert-row-by-range', 'sheet.command.insert-col-by-range']) {
      expect(grid.api.syncExecuteCommand(id, { unitId: workbook.getId(), subUnitId, range: { startRow: 1, endRow: 1, startColumn: 1, endColumn: 1 }, direction: 0 })).toBe(true)
      await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyRowColumnOps')).toBe(true))
      for (const action of ['undo', 'redo']) expect(grid.api.syncExecuteCommand(`univer.command.${action}`), document.querySelector('.workbook-feedback')?.textContent ?? '').toBe(true)
    }
    current.shell.save.click(); await vi.waitFor(() => expect(downloaded).toBeDefined())
    const before = await createBufferEntrySource(source), after = await createBufferEntrySource(downloaded!)
    for (const path of (await before.paths()).filter(path => path.startsWith('xl/pivot') && !(renamed && path.includes('pivotCacheDefinition')))) expect(await after.readText(path)).toBe(await before.readText(path))
    expect(await after.readText('xl/pivotCache/pivotCacheDefinition1.xml')).toContain(renamed ? '财务 O&apos;Brien &amp; 数据' : 'sheet="Source"')
  } finally { current.view?.dispose() }
})

it('atomically refuses a pivot source sheet deletion before mutating the workbook', async () => {
  const source = pivotRemovalFixture(), draft = new NativeDraft(identity, store())
  const save = vi.fn(async () => { throw new Error('unexpected save') }), current = await open(source, draft, save)
  try {
    const workbook = grid.api.getActiveWorkbook(), before = workbook.getSnapshot(), operations = structuredClone(draft.operations)
    expect(await grid.api.executeCommand('sheet.command.remove-sheet', { unitId: workbook.getId(), subUnitId: workbook.getSheetByName('Source').getSheetId() })).toBe(false)
    expect(workbook.getSnapshot()).toEqual(before)
    expect(draft.operations).toEqual(operations)
    expect(document.body.textContent).toContain('仍有透视表')
    expect(save).not.toHaveBeenCalled()
  } finally { current.view?.dispose() }
})

it('saves an unrelated sheet deletion while retaining pivot cache and pivot parts', async () => {
  const source = pivotRemovalFixture(), draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const save = vi.fn(async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { documentId: identity.documentId, revision: 2, revisionRegistered: true }
  }), current = await open(source, draft, save)
  try {
    const workbook = grid.api.getActiveWorkbook()
    expect(await grid.api.executeCommand('sheet.command.remove-sheet', { unitId: workbook.getId(), subUnitId: workbook.getSheetByName('Unused').getSheetId() })).toBe(true)
    history('undo');expect(workbook.getSheets().map((item: any) => item.getSheetName())).toEqual(['Source','Pivot','Unused'])
    history('redo')
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applySheetEdits')).toBe(true))
    current.shell.save.click()
    await vi.waitFor(() => expect(save).toHaveBeenCalledOnce())
    await vi.waitFor(() => expect(downloaded).toBeDefined())
    const before = await createBufferEntrySource(source), after = await createBufferEntrySource(downloaded!)
    for (const path of ['xl/pivotCache/pivotCacheDefinition1.xml','xl/pivotTables/pivotTable1.xml']) expect(await after.readText(path)).toBe(await before.readText(path))
    expect((await readWorkbook(downloaded!)).sheets.map(sheet => sheet.name)).toEqual(['Source','Pivot'])
  } finally { current.view?.dispose() }
})

it.each([false, true])('checks independent source identities for readonly tables before sheet deletion (dependent=%s)', async dependent => {
  let source = await applyWorkbookOperations(await fixture(), [
    { kind: 'applySheetEdits', plan: { renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'] } },
    { kind: 'applyTableAdditions', additions: [{ worksheetSheetName: 'Sheet1', area: { startRow: 0, endRow: 1, startColumn: 0, endColumn: 0 }, name: 'SalesData', columnNames: ['Amount'], style: '', bandedRows: false }] },
  ])
  if (dependent) source = await applyCellEdits(source, [{ sheetName:'Other',row:0,column:0,writeValue:true,cell:{value:null,formula:'=SUM(SalesData[Amount])'} }])
  const original = await createBufferEntrySource(source), path = (await original.paths()).find(path => /^xl\/tables\/.*\.xml$/.test(path))!
  source = (await assemblePackage(source, { replaced:new Map([[path,(await original.readText(path)).replace('tableColumns count="1"','tableColumns count="9"')]]), added:new Map(), addedBinary:new Map(), removedEntries:[], addedEntries:[], touchedEntries:[path] })).buffer
  expect((await readWorkbook(source)).sheets[0]!.tablesReadOnlyReason).toBeTruthy()
  const draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const save = vi.fn(async (request: NativeSaveRequest) => { downloaded=await applyWorkbookOperations(source,request.operations);return {documentId:identity.documentId,revision:2,revisionRegistered:true} })
  const current = await open(source,draft,save)
  try {
    const workbook=grid.api.getActiveWorkbook(), before=workbook.getSnapshot(), operations=structuredClone(draft.operations)
    expect(await grid.api.executeCommand('sheet.command.remove-sheet',{unitId:workbook.getId(),subUnitId:workbook.getSheetByName('Sheet1').getSheetId()})).toBe(!dependent)
    if(dependent){expect(workbook.getSnapshot()).toEqual(before);expect(draft.operations).toEqual(operations);expect(document.body.textContent).toContain('SalesData')}
    else {
      history('undo');expect(workbook.getSheetByName('Sheet1')).toBeTruthy();history('redo')
      await vi.waitFor(()=>expect(draft.operations.some(op=>op.kind==='applySheetEdits')).toBe(true))
      current.shell.save.click();await vi.waitFor(()=>expect(downloaded).toBeDefined())
      expect((await readWorkbook(downloaded!)).sheets.map(sheet=>sheet.name)).toEqual(['Other'])
      expect(await (await createBufferEntrySource(downloaded!)).has(path)).toBe(false)
    }
  } finally {current.view?.dispose()}
})

it('keeps pivot cache source identity current after renaming its worksheet', async () => {
  const source = pivotRemovalFixture(), draft = new NativeDraft(identity, store()), name = "财务 O'Brien & 数据"
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true }
  })
  try {
    const workbook = grid.api.getActiveWorkbook(), id = workbook.getSheetByName('Source').getSheetId()
    expect(grid.api.syncExecuteCommand('sheet.command.set-worksheet-name', { unitId: workbook.getId(), subUnitId: id, name })).toBe(true)
    history('undo'); expect(workbook.getSheetByName('Source')).toBeTruthy(); history('redo')
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applySheetEdits')).toBe(true))
    current.shell.save.click(); await vi.waitFor(() => expect(downloaded).toBeDefined())
    const { pivotCacheReadsFromSheet } = await import('@sheets-web/xlsx-engine/pivot-cache-source')
    const xml = await (await createBufferEntrySource(downloaded!)).readText('xl/pivotCache/pivotCacheDefinition1.xml')
    expect(pivotCacheReadsFromSheet(xml, name)).toBe(true)
    expect(pivotCacheReadsFromSheet(xml, 'Source')).toBe(false)
    const before = workbook.getSnapshot(), operations = structuredClone(draft.operations)
    expect(await grid.api.executeCommand('sheet.command.remove-sheet', { unitId: workbook.getId(), subUnitId: id })).toBe(false)
    expect(workbook.getSnapshot()).toEqual(before); expect(draft.operations).toEqual(operations)
    expect(document.querySelector('.workbook-feedback')?.textContent).toContain('仍有透视表')
  } finally { current.view?.dispose() }
})


it('formal binary refresh mounts before file loading, uses workbook CSRF and downloads only XLSX',async()=>{
  window.history.replaceState({},'','/reports/v1/workbooks/report/1');localStorage.clear()
  document.cookie='report_workbook_csrf=workbook-token';document.cookie='report_editor_csrf=wrong-md'
  document.body.innerHTML='<main id="app"></main>'
  const css=document.createElement('style')
  css.textContent=(await import('./style.css?raw')).default+(await import('./workbook.css?raw')).default+(await import('./office-theme.css?raw')).default+(await import('./binary-refresh.css?raw')).default
  document.head.append(css)
  const source=await fixture(),sha='d'.repeat(64)
  const task={taskId:'recalc-workbook',status:'completed',result:{issueCodes:['code_only']},execution:{status:'completed',runId:'run',issueCodes:[]}}
  const fetcher=vi.fn(async(url:string)=>new Response(JSON.stringify(url.endsWith('/context')?{reportId:'report',revision:1,contextSha256:'e'.repeat(64),sha256:sha,dataRefresh:{available:true}}:url.endsWith('/delivery')?{task,delivery:{xlsx:{downloadUrl:'/actual.xlsx'},word:{downloadUrl:'/wrong.docx'},validation:{ok:false,issues:[{code:'xlsx_validation_failed'}]}}}:task)))
  vi.stubGlobal('fetch',fetcher)
  const shell=createEditorShell(document.querySelector('#app')!,'full','xlsx')
  const current=await createWorkbookEditorView(shell,{file:async()=>{
    expect(document.querySelector('[data-action=binary-refresh]')).not.toBeNull()
    return {bytes:source.slice().buffer as ArrayBuffer,sha256:sha}
  }})
  try{
    const action=document.querySelector<HTMLButtonElement>('[data-action=binary-refresh]')!
    expect(action.disabled).toBe(false);action.click()
    await vi.waitFor(()=>expect(document.querySelector('.binary-refresh-result a')).not.toBeNull())
    const post=fetcher.mock.calls.find(([url])=>String(url).endsWith('/recalculations'))!
    expect(post[0]).toBe('/reports/v1/workbooks/report/1/api/recalculations')
    const call=(fetcher.mock.calls as unknown as [string,RequestInit][]).find(([url])=>url.endsWith('/recalculations'))!
    expect(new Headers(call[1].headers).get('X-CSRF-Token')).toBe('workbook-token')
    expect(JSON.parse(call[1].body as string)).toEqual({requestId:expect.any(String),expectedBinarySha256:sha})
    const links=document.querySelectorAll<HTMLAnchorElement>('.binary-refresh-result a');expect(links).toHaveLength(1);expect(links[0].getAttribute('href')).toBe('/actual.xlsx')
    for(let element:Element|null=links[0];element;element=element.parentElement)expect(getComputedStyle(element).display).not.toBe('none')
    expect(document.body.textContent).toContain('xlsx_validation_failed');expect(document.body.textContent).toContain('code_only')
  }finally{current?.dispose();window.dispatchEvent(new Event('pagehide'));css.remove();window.history.replaceState({},'','/')}
})

it('formal workbook flushes the active input, saves once, keeps unregistered download and never dispatches on the old source',async()=>{
  window.history.replaceState({},'','/reports/v1/workbooks/report/1');localStorage.clear();document.body.innerHTML='<main id="app"></main>'
  const source=await fixture(),sha='d'.repeat(64)
  const fetcher=vi.fn(async()=>new Response(JSON.stringify({reportId:'report',revision:1,contextSha256:'e'.repeat(64),sha256:sha,dataRefresh:{available:true}})))
  vi.stubGlobal('fetch',fetcher)
  const request=vi.fn(async()=>({revision:2,revisionRegistered:false,xlsx:{downloadUrl:'/unregistered.xlsx'},validation:{ok:false,issues:[{message:'未登记'}]}}))
  const shell=createEditorShell(document.querySelector('#app')!,'full','xlsx')
  const current=await createWorkbookEditorView(shell,{file:async()=>({bytes:source.slice().buffer as ArrayBuffer,sha256:sha}),request:request as never})
  try{
    const workbook=grid.api.getActiveWorkbook()
    const end=vi.fn(async()=>{sheet().getRange('A1').setValue(123);return true})
    workbook.isCellEditing=()=>true;workbook.endEditingAsync=end
    // Facade wrappers are fresh objects; keep the active editor wrapper stable.
    const get=vi.spyOn(grid.api,'getActiveWorkbook').mockReturnValue(workbook)
    document.querySelector<HTMLButtonElement>('[data-action=binary-refresh]')!.click()
    await vi.waitFor(()=>expect(request).toHaveBeenCalledOnce())
    expect(end).toHaveBeenCalledOnce();expect(document.querySelector<HTMLAnchorElement>('[data-action=xlsx-download]')!.getAttribute('href')).toBe('/unregistered.xlsx')
    expect(fetcher.mock.calls).toHaveLength(1)
    get.mockRestore()
  }finally{current?.dispose();window.dispatchEvent(new Event('pagehide'));window.history.replaceState({},'','/')}
})


it('formal workbook recovers cached task before failed preview and retains saving after a successful reload',async()=>{
  window.history.replaceState({},'','/reports/v1/workbooks/report/1');localStorage.clear();document.body.innerHTML='<main id="app"></main>'
  const source=await fixture(),sha='d'.repeat(64)
  const task={taskId:'recalc-workbook',status:'completed',result:null,execution:{status:'completed',runId:'run',issueCodes:[]}}
  let available=true,fail=false
  const fetcher=vi.fn(async(url:string)=>new Response(JSON.stringify(url.endsWith('/context')?{reportId:'report',revision:1,contextSha256:'e'.repeat(64),sha256:sha,dataRefresh:{available}}:url.endsWith('/delivery')?{task,delivery:{xlsx:{downloadUrl:'/actual.xlsx'},validation:{ok:false,issues:[{code:'still_failed'}]}}}:task)))
  vi.stubGlobal('fetch',fetcher)
  const open=async()=>{
    const shell=createEditorShell(document.querySelector('#app')!,'full','xlsx')
    const current=await createWorkbookEditorView(shell,{file:async()=>{if(fail)throw Error('workbook bytes missing');return {bytes:source.slice().buffer as ArrayBuffer,sha256:sha}}})
    return {shell,current}
  }
  let current=await open()
  try{
    document.querySelector<HTMLButtonElement>('[data-action=binary-refresh]')!.click()
    await vi.waitFor(()=>expect(document.querySelector('.binary-refresh-result a')).not.toBeNull())
    current.current?.dispose();window.dispatchEvent(new Event('pagehide'));document.body.innerHTML='<main id="app"></main>'
    current=await open()
    await vi.waitFor(()=>expect(document.querySelector('.binary-refresh-result a')).not.toBeNull())
    expect(current.shell.save.disabled).toBe(false)
    current.current?.dispose();window.dispatchEvent(new Event('pagehide'));document.body.innerHTML='<main id="app"></main>'
    available=false;fail=true;current=await open()
    await vi.waitFor(()=>expect(document.querySelector('.binary-refresh-result a')).not.toBeNull())
    expect(document.querySelector('[data-action=binary-refresh]')).toBeNull()
    expect(document.body.textContent).toContain('workbook bytes missing')
  }finally{current.current?.dispose();window.dispatchEvent(new Event('pagehide'));window.history.replaceState({},'','/')}
})
