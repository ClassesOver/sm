import { afterEach, expect, it, vi } from 'vitest'
import { applyCellEdits, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { assemblePackage, createBufferEntrySource } from '../../../reporting/workbook_engine/packages/xlsx-engine/src/zip'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createWorkbookEditorView } from './workbook-main'
import { createNativeOfficeTransport } from './native-office-view'
import { NativeDraft, type NativeDraftIdentity, type NativeSaveRequest } from './native-draft'
import { createEditorShell } from './shell'

const grid = vi.hoisted(() => ({ api: undefined as any, ribbon: undefined as any, apply: vi.fn(() => false), instances: [] as any[] }))
vi.mock('@univerjs/preset-sheets-core', () => ({ UniverSheetsCorePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-note', () => ({ UniverSheetsNotePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-find-replace', () => ({ UniverSheetsFindReplacePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-drawing', () => ({ UniverSheetsDrawingPreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-table', () => ({ UniverSheetsTablePreset: () => ({ plugins: [] }) }))
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
  await import('@univerjs/sheets/facade')
  await import('@univerjs/sheets-note/facade')
  await import('@univerjs/sheets-formula/facade')
  await import('@univerjs/sheets-data-validation/facade')
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

const identity: NativeDraftIdentity = { documentId: 'main-cell-shift', revision: 1, sourceSha256: 'b'.repeat(64),
  scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } }
const store = () => { const data = new Map<string, string>(); return { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => { data.set(key, value) }, removeItem: (key: string) => { data.delete(key) } } }
async function fixture() {
  return applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'a1' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 'b1' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'a2' } },
    { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: 'b2' } },
    { sheetName: 'Sheet1', row: 4, column: 0, writeValue: true, cell: { value: null, formula: '=B2' } },
  ])
}
async function open(source: Uint8Array, draft: NativeDraft, save: (request: NativeSaveRequest) => Promise<unknown>) {
  document.body.innerHTML = '<main id="app"></main>'
  const shell = createEditorShell(document.querySelector('#app')!, 'full', 'xlsx')
  const context = { context: { ...identity, format: 'xlsx', sourceFile: { sha256: identity.sourceSha256 } }, editingEnabled: true }
  const transport = createNativeOfficeTransport({ api: { save } as never, context: context as never, draft })
  const view = await createWorkbookEditorView(shell, { native: true, draft, request: transport.workbook,
    file: async () => ({ bytes: source.slice().buffer as ArrayBuffer, sha256: identity.sourceSha256 }) })
  return { shell, view }
}
const sheet = () => grid.api.getActiveWorkbook().getActiveSheet()
const history = (direction: 'undo' | 'redo') => expect(grid.api.syncExecuteCommand(`univer.command.${direction}`)).toBe(true)
const shifts = (draft: NativeDraft) => draft.operations.filter((op: any) => op.kind === 'applyCellShift')
afterEach(() => {
  for (const instance of grid.instances.splice(0)) instance.dispose()
  document.body.replaceChildren()
})

it('journals Insert Cells shift right with Undo/Redo and saves it through the engine', async () => {
  const source = await fixture(), draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/shift.xlsx' } }, validation: { issues: [] } }
  })
  expect(await grid.api.executeCommand('sheet.command.insert-range-move-right', { range: { startRow: 1, endRow: 1, startColumn: 0, endColumn: 0 } })).toBe(true)
  expect(sheet().getRange(1, 0, 1, 3).getValues()[0]).toEqual([null, 'a2', 'b2'])
  await vi.waitFor(() => expect(shifts(draft)).toEqual([{ kind: 'applyCellShift', sheetName: 'Sheet1', range: 'A2', shift: 'right' }]))
  expect(draft.operations.some((op: any) => op.kind === 'applyRowColumnOps')).toBe(false)
  history('undo')
  await vi.waitFor(() => expect(shifts(draft)).toEqual([]))
  history('redo')
  await vi.waitFor(() => expect(shifts(draft)).toHaveLength(1))
  current.shell.save.click()
  await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const saved = (await readWorkbook(downloaded!)).sheets[0]!.cells
  expect([saved.A2?.value, saved.B2?.value, saved.C2?.value]).toEqual([undefined, 'a2', 'b2'])
  expect([saved.A1?.value, saved.B1?.value]).toEqual(['a1', 'b1'])
  expect(saved.A5?.formula).toBe('=C2')
  current.view?.dispose()
})

it('opens the Insert dialog for a cell selection and shifts down by default', async () => {
  const source = await fixture(), draft = new NativeDraft(identity, store())
  const current = await open(source, draft, async () => { throw Error('unused') })
  sheet().setActiveSelection(sheet().getRange(0, 1))
  grid.ribbon('insert-cells')
  const dialog = document.querySelector<HTMLElement>('.workbook-ribbon-cells-dialog')!
  expect(dialog.querySelector<HTMLInputElement>('input[value="shift-vertical"]')!.checked).toBe(true)
  expect([...dialog.querySelectorAll('[data-choice-label]')].map(node => node.textContent)).toEqual(['活动单元格右移', '活动单元格下移', '整行', '整列'])
  dialog.querySelector<HTMLFormElement>('form')!.requestSubmit()
  await vi.waitFor(() => expect(shifts(draft)).toEqual([{ kind: 'applyCellShift', sheetName: 'Sheet1', range: 'B1', shift: 'down' }]))
  expect(sheet().getRange(0, 1, 3, 1).getValues().map((row: unknown[]) => row[0])).toEqual([null, 'b1', 'b2'])
  current.view?.dispose()
})

it('undoes a shift the engine refuses and states the reason', async () => {
  const base = await fixture()
  const source = await (async () => {
    const path = 'xl/worksheets/sheet1.xml'
    const xml = (await (await createBufferEntrySource(base)).readText(path)).replace('</sheetData>',
      '</sheetData><dataValidations count="1"><dataValidation type="whole" sqref="B2"><formula1>1</formula1></dataValidation></dataValidations>')
    return (await assemblePackage(base, { replaced: new Map([[path, xml]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
  })()
  const draft = new NativeDraft(identity, store())
  const current = await open(source, draft, async () => { throw Error('unused') })
  expect(await grid.api.executeCommand('sheet.command.insert-range-move-right', { range: { startRow: 1, endRow: 1, startColumn: 0, endColumn: 0 } })).toBe(true)
  await vi.waitFor(() => expect(current.shell.editor.textContent).toContain('数据验证位于移位区域'))
  await vi.waitFor(() => expect(sheet().getRange(1, 0, 1, 2).getValues()[0]).toEqual(['a2', 'b2']))
  await vi.waitFor(() => expect(shifts(draft)).toEqual([]))
  current.view?.dispose()
})
