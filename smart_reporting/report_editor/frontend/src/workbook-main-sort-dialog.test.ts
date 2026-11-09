import { afterEach, expect, it, vi } from 'vitest'
import { applyCellEdits, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { sortOrderRules, sortColumnOptions } from './workbook-sort-dialog'
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
vi.mock('@univerjs/preset-sheets-table', () => ({ UniverSheetsTablePreset: () => ({}) }))
vi.mock('./workbook-ribbon', () => ({
  mountWorkbookRibbon: (_host: unknown, callback: unknown) => { grid.ribbon = callback; return { dispose() {}, refreshState() {} } },
  applyWorkbookRibbonCommand: grid.apply,
}))
vi.mock('./workbook-vendor/grid/decimal-step', () => ({ stepSelectionDecimals() {} }))
vi.mock('./workbook-vendor/grid/sparkline-render', () => ({ setSparklines() {} }))
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

const identity: NativeDraftIdentity = { documentId: 'main-sort', revision: 1, sourceSha256: 'b'.repeat(64),
  scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } }
const store = () => { const data = new Map<string, string>(); return { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => { data.set(key, value) }, removeItem: (key: string) => { data.delete(key) } } }
const rows: [string, number][] = [['东', 3], ['西', 1], ['东', 1], ['西', 2]]
async function fixture() {
  return applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: '地区' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: '金额' } },
    ...rows.flatMap(([region, amount], index) => [
      { sheetName: 'Sheet1', row: index + 1, column: 0, writeValue: true, cell: { value: region } },
      { sheetName: 'Sheet1', row: index + 1, column: 1, writeValue: true, cell: { value: amount } },
    ]),
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
afterEach(() => {
  for (const instance of grid.instances.splice(0)) instance.dispose()
  document.body.replaceChildren()
})


it('builds rules from levels like the fixed source', () => {
  const range = { startRow: 0, endRow: 4, startColumn: 1, endColumn: 2 }
  expect(sortColumnOptions(range)).toEqual([{ label: '列 B', colIndex: 1 }, { label: '列 C', colIndex: 2 }])
  expect(sortOrderRules(range, [{ colIndex: 2, order: 'desc' }, { colIndex: -1, order: 'asc' }, { colIndex: 2, order: 'asc' }])).toEqual([{ colIndex: 2, type: 'desc' }])
  expect(() => sortOrderRules(range, [{ colIndex: -1, order: 'asc' }])).toThrow(/至少/)
  expect(() => sortOrderRules(range, [{ colIndex: 0, order: 'asc' }])).toThrow(/不在所选区域/)
  expect(sortColumnOptions({ startRow: 0, endRow: 1, startColumn: 0, endColumn: 40 })).toHaveLength(26)
})

it('sorts by two levels below a header through the dialog and saves the result', async () => {
  const source = await fixture(), draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/s.xlsx' } }, validation: { issues: [] } }
  })
  sheet().setActiveSelection(sheet().getRange(0, 0, 5, 2))
  grid.ribbon('sort-custom-open')
  const dialog = document.querySelector<HTMLElement>('.workbook-ribbon-sort-dialog')!
  expect(dialog.querySelector<HTMLInputElement>('[data-sort-header]')!.checked).toBe(true)
  const level = (index: number) => dialog.querySelector<HTMLElement>(`[data-sort-level="${index}"]`)!
  expect([...level(1).querySelectorAll('[data-sort-column] option')].map(option => option.textContent)).toEqual(['（无）', '列 A', '列 B'])
  level(0).querySelector<HTMLSelectElement>('[data-sort-column]')!.value = '0'
  level(1).querySelector<HTMLSelectElement>('[data-sort-column]')!.value = '1'
  level(1).querySelector<HTMLSelectElement>('[data-sort-order]')!.value = 'desc'
  dialog.querySelector<HTMLFormElement>('form')!.requestSubmit()
  expect(sheet().getRange(0, 0, 5, 2).getValues()).toEqual([['地区', '金额'], ['东', 3], ['东', 1], ['西', 2], ['西', 1]])
  current.shell.save.click()
  await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const cells = (await readWorkbook(downloaded!)).sheets[0]!.cells
  expect([1, 2, 3, 4, 5].map(row => [cells[`A${row}`]?.value, cells[`B${row}`]?.value])).toEqual([['地区', '金额'], ['东', 3], ['东', 1], ['西', 2], ['西', 1]])
  current.view?.dispose()
})
