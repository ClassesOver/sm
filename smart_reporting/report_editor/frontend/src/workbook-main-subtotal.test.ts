import { afterEach, expect, it, vi } from 'vitest'
import { applyCellEdits, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createWorkbookEditorView } from './workbook-main'
import { createNativeOfficeTransport } from './native-office-view'
import { NativeDraft, type NativeDraftIdentity, type NativeSaveRequest } from './native-draft'
import { createEditorShell } from './shell'
import { readWorkbookOutline } from './workbook-outline'
import { ICommandService, IUndoRedoService } from '@univerjs/core'

const grid = vi.hoisted(() => ({ api: undefined as any, ribbon: undefined as any, apply: vi.fn(() => false), instances: [] as any[] }))
vi.mock('@univerjs/preset-sheets-core', () => ({ UniverSheetsCorePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-note', () => ({ UniverSheetsNotePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-find-replace', () => ({ UniverSheetsFindReplacePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-drawing', () => ({ UniverSheetsDrawingPreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-table', () => ({ UniverSheetsTablePreset: () => ({ plugins: [] }) }))
vi.mock('@univerjs/preset-sheets-conditional-formatting', () => ({ UniverSheetsConditionalFormattingPreset: () => ({ plugins: [] }) }))
vi.mock('./workbook-ribbon', () => ({
  mountWorkbookRibbon: (_host: unknown, callback: unknown) => { grid.ribbon = callback; return { dispose() {}, refreshState() {} } },
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
  await import('@univerjs/sheets-formula/facade')
  await import('@univerjs/sheets-table/facade')
  await import('@univerjs/sheets-conditional-formatting/facade')
  await import('@univerjs/sheets/facade')
  await import('@univerjs/sheets-note/facade')
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

const identity: NativeDraftIdentity = { documentId: 'main-subtotal', revision: 1, sourceSha256: 'b'.repeat(64), scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } }
const store = () => { const data = new Map<string, string>(); return { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => { data.set(key, value) }, removeItem: (key: string) => { data.delete(key) } } }
const rows = [['Group', 'Value'], ['A', 10], ['A', 20], ['B', 30], ['B', 40], ['Tail', 99]]
async function fixture(extra: Record<string, any>[] = []) {
  return applyWorkbookOperations(await createBlankWorkbook('Data'), [
    { kind: 'applySheetEdits', plan: { renames: [], additions: [{ name: 'Dependent' }], removals: [], order: ['Data', 'Dependent'] } },
    { kind: 'applyCellEdits', edits: [...rows.flatMap((row, r) => row.map((value, c) => ({ sheetName: 'Data', row: r + 4, column: c + 2, writeValue: true, cell: { value } }))),
      { sheetName: 'Dependent', row: 0, column: 0, writeValue: true, cell: { value: null, formula: '=Data!$D$8' } },
    ] },
    { kind: 'applyDefinedNames', plan: { sets: [{ name: 'Body', refersTo: "'Data'!$C$6:$D$9" }] } },
    ...extra,
  ])
}
async function open(source: Uint8Array, draft: NativeDraft, save: (request: NativeSaveRequest) => Promise<unknown> = async () => { throw Error('没有请求保存') }) {
  document.body.innerHTML = '<main id="app"></main>'
  const shell = createEditorShell(document.querySelector('#app')!, 'full', 'xlsx')
  const context = { context: { ...identity, format: 'xlsx', sourceFile: { sha256: identity.sourceSha256 } }, editingEnabled: true }
  const transport = createNativeOfficeTransport({ api: { save } as never, context: context as never, draft })
  const view = await createWorkbookEditorView(shell, { native: true, draft, request: transport.workbook, file: async () => ({ bytes: source.slice().buffer as ArrayBuffer, sha256: identity.sourceSha256 }) })
  return { shell, view }
}
const sheet = () => grid.api.getActiveWorkbook().getActiveSheet()
function dialog(agg = 'sum') {
  sheet().getRange('C5:D9').activate()
  grid.ribbon('subtotal-open')
  const card = document.querySelector<HTMLElement>('[role="dialog"][aria-label="分类汇总"]') ?? [...document.querySelectorAll<HTMLElement>('[role="dialog"]')].find(node => node.textContent?.includes('分类汇总'))!
  expect(card).toBeDefined()
  card.querySelector<HTMLSelectElement>('[aria-label="汇总方式"]')!.value = agg
  return card
}
async function submit(agg = 'sum') {
  const card = dialog(agg)
  card.querySelector<HTMLFormElement>('form')!.requestSubmit()
  await vi.waitFor(() => expect(sheet().getRange('C12').getValue()).toBe('Grand Total'))
}
afterEach(() => {
  vi.restoreAllMocks()
  for (const instance of grid.instances.splice(0)) instance.dispose()
  document.body.replaceChildren()
})
it('opens via the ribbon and cancels without touching cells, draft or undo history', async () => {
  const source = await fixture(), draft = new NativeDraft(identity, store()), current = await open(source, draft)
  const before = structuredClone(grid.api.getActiveWorkbook().getSnapshot())
  const history = grid.instances.at(-1).__getInjector().get(IUndoRedoService), undo = history.pitchTopUndoElement()
  dialog().querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click()
  await Promise.resolve()
  expect(grid.api.getActiveWorkbook().getSnapshot()).toEqual(before)
  expect(draft.operations).toEqual([])
  expect(history.pitchTopUndoElement()).toBe(undo)
  current.view?.dispose()
})
it.each(['sum', 'count', 'average'] as const)('executes %s from the main dialog, undoes and redoes once, restores the draft and saves one set of inserts', async agg => {
  const source = await fixture(), storage = store(), draft = new NativeDraft(identity, storage)
  const first = await open(source, draft)
  await submit(agg)
  const expected = { sum: 100, count: 4, average: 25 }[agg]!
  await vi.waitFor(() => expect(sheet().getRange('D12').getValue()).toBe(expected))
  await vi.waitFor(() => expect(draft.operations.filter(op => op.kind === 'applyRowColumnOps')).toHaveLength(3))
  await grid.api.undo()
  expect(sheet().getRange('C5:D10').getValues()).toEqual(rows)
  expect(readWorkbookOutline(sheet()).rows.size).toBe(0)
  await vi.waitFor(() => expect(draft.operations).toEqual([]))
  await grid.api.redo()
  await vi.waitFor(() => expect(sheet().getRange('D12').getValue()).toBe(expected))
  await vi.waitFor(() => expect(draft.operations.filter(op => op.kind === 'applyRowColumnOps')).toHaveLength(3))
  const beforeRefresh = draft.operations
  first.view?.dispose()
  const restored = new NativeDraft(identity, storage)
  let downloaded: Uint8Array | undefined, request: NativeSaveRequest | undefined
  const second = await open(source, restored, async payload => {
    request = payload
    downloaded = await applyWorkbookOperations(source, payload.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/subtotal.xlsx' } }, validation: { issues: [] } }
  })
  expect(sheet().getRange('C13:D13').getValues()).toEqual([['Tail', 99]])
  expect(restored.operations).toEqual(beforeRefresh)
  second.shell.save.click()
  await vi.waitFor(() => expect(second.shell.statusLabel.textContent).toContain('已保存修订 2'))
  expect(request!.operations.filter(op => op.kind === 'applyRowColumnOps')).toHaveLength(3)
  const saved = await readWorkbook(downloaded!)
  expect(saved.sheets[0]!.cells.C13.value).toBe('Tail')
  expect(saved.sheets[0]!.cells.D12.formula).toBe(`=SUBTOTAL(${agg === 'sum' ? 9 : agg === 'count' ? 3 : 1},$D$6:$D$11)`)
  expect(saved.sheets[0]!.outlineSummaryBelow).toBe(true)
  expect(saved.sheets[1]!.cells.A1.formula).toBe('=Data!$D$9')
  expect(saved.definedNames).toContainEqual({ name: 'Body', refersTo: "'Data'!$C$6:$D$10" })
  second.view?.dispose()
})
it('rolls back a late rejected command without leaving main draft or history entries', async () => {
  const source = await fixture(), draft = new NativeDraft(identity, store()), current = await open(source, draft)
  const native = grid.instances.at(-1), commands = native.__getInjector().get(ICommandService), history = native.__getInjector().get(IUndoRedoService)
  const undo = history.pitchTopUndoElement(), redo = history.pitchTopRedoElement(), run = commands.syncExecuteCommand.bind(commands)
  let inserts = 0
  const spy = vi.spyOn(commands, 'syncExecuteCommand').mockImplementation(((id: string, params: any, options: any) => {
    if (id === 'sheet.command.insert-row-by-range' && ++inserts === 2) return false
    return run(id, params, options)
  }) as typeof commands.syncExecuteCommand)
  const card = dialog()
  card.querySelector<HTMLFormElement>('form')!.requestSubmit()
  await vi.waitFor(() => expect(card.querySelector('[role="alert"]')!.textContent).not.toBe(''))
  spy.mockRestore()
  expect(sheet().getRange('C5:D10').getValues()).toEqual(rows)
  expect(readWorkbookOutline(sheet()).rows.size).toBe(0)
  await vi.waitFor(() => expect(draft.operations).toEqual([]))
  expect(history.pitchTopUndoElement()).toBe(undo)
  expect(history.pitchTopRedoElement()).toBe(redo)
  current.view?.dispose()
})
it('refuses a protected source before the first native insert', async () => {
  const source = await fixture([{ kind: 'protectSheet', sheetName: 'Data', protect: true }]), draft = new NativeDraft(identity, store()), current = await open(source, draft)
  const commands = grid.instances.at(-1).__getInjector().get(ICommandService)
  const execute = vi.spyOn(commands, 'syncExecuteCommand')
  sheet().getRange('C5:D9').activate()
  grid.ribbon('subtotal-open')
  await vi.waitFor(() => expect(current.shell.editor.querySelector('.workbook-feedback')!.textContent).toMatch(/保护/))
  expect(execute.mock.calls.some(([id]) => id === 'sheet.command.insert-row-by-range')).toBe(false)
  expect(draft.operations).toEqual([])
  expect(sheet().getRange('C5:D10').getValues()).toEqual(rows)
  current.view?.dispose()
})
it.each(['sparkline', 'pivot'])('refuses an existing %s dependency before any native insert', async dependency => {
  const extra = dependency === 'sparkline'
    ? { kind: 'appendSheetSparklines', sheetName: 'Data', groups: [{ type: 'line', cells: [{ cell: 'G6', sourceRef: 'Data!$C$6:$D$6' }] }] }
    : { kind: 'addPivot', addition: { worksheetSheetName: 'Dependent', sourceSheetName: 'Data', sourceArea: { startRow: 4, startColumn: 2, endRow: 8, endColumn: 3 }, location: { startRow: 5, startColumn: 0, endRow: 8, endColumn: 1 }, name: 'ByGroup', fieldNames: ['Group', 'Value'], rowFieldIndices: [0], rowLevelItems: [['A', 'B']], rowLines: [{ t: 'data', members: [0] }, { t: 'data', members: [1] }], values: [{ fieldIndex: 1, agg: 'sum' }] } }
  const source = await fixture([extra]), draft = new NativeDraft(identity, store()), current = await open(source, draft)
  const commands = grid.instances.at(-1).__getInjector().get(ICommandService), execute = vi.spyOn(commands, 'syncExecuteCommand')
  const card = dialog()
  card.querySelector<HTMLFormElement>('form')!.requestSubmit()
  await vi.waitFor(() => expect(card.querySelector('[role="alert"]')!.textContent).toMatch(dependency === 'sparkline' ? /迷你图/ : /透视表/))
  expect(execute.mock.calls.some(([id]) => id === 'sheet.command.insert-row-by-range')).toBe(false)
  expect(draft.operations).toEqual([])
  expect(sheet().getRange('C5:D10').getValues()).toEqual(rows)
  current.view?.dispose()
})
it('refuses the combined staged-operation budget before any native insert', async () => {
  const source = await fixture(), draft = new NativeDraft(identity, store())
  const existing = Array.from({ length: 496 }, () => ({ kind: 'applySheetOutline', sheetName: 'Data', summaryBelow: true }))
  draft.setOperations(existing)
  const current = await open(source, draft), commands = grid.instances.at(-1).__getInjector().get(ICommandService)
  const execute = vi.spyOn(commands, 'syncExecuteCommand'), card = dialog()
  card.querySelector<HTMLFormElement>('form')!.requestSubmit()
  await vi.waitFor(() => expect(card.querySelector('[role="alert"]')!.textContent).toMatch(/操作|预算|500|超限/))
  expect(execute.mock.calls.some(([id]) => id === 'sheet.command.insert-row-by-range')).toBe(false)
  expect(draft.operations).toEqual(existing)
  expect(sheet().getRange('C5:D10').getValues()).toEqual(rows)
  current.view?.dispose()
}, 20000)
