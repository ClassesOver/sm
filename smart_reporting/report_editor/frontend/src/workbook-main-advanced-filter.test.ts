import { afterEach, expect, it, vi } from 'vitest'
import { createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createWorkbookEditorView } from './workbook-main'
import { createNativeOfficeTransport } from './native-office-view'
import { NativeDraft, type NativeDraftIdentity, type NativeSaveRequest } from './native-draft'
import { createEditorShell } from './shell'
import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'
import { independentPython } from './test-independent-python'
import { ICommandService, IUndoRedoService } from '@univerjs/core'

const grid = vi.hoisted(() => ({ api: undefined as any, ribbon: undefined as any, apply: vi.fn(() => false), instances: [] as any[] }))
vi.mock('@univerjs/preset-sheets-filter', () => ({ UniverSheetsFilterPreset: () => ({}) }))
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
  const { UniverSheetsFilterPlugin } = await import('@univerjs/sheets-filter')
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
  await import('@univerjs/sheets-filter/facade')
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

const identity: NativeDraftIdentity = { documentId: 'advanced-filter', revision: 1, sourceSha256: 'c'.repeat(64), scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } }
const store = () => { const data = new Map<string, string>(); return { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => { data.set(key, value) }, removeItem: (key: string) => { data.delete(key) } } }
const rows = [['Group', 'Value', 'Other'], ['A', 5, 'keep'], ['A', 10, 'keep'], ['B', 20, 'drop'], ['A', 40, 'keep'], ['Tail', 99, 'outside']]
const range = { startRow: 4, endRow: 8, startColumn: 2, endColumn: 4 }
async function fixture(filter = true, extra: Record<string, any>[] = []) {
  return applyWorkbookOperations(await createBlankWorkbook('Data'), [
    { kind: 'applyCellEdits', edits: rows.flatMap((row, r) => row.map((value, c) => ({ sheetName: 'Data', row: r + 4, column: c + 2, writeValue: true, cell: { value } }))) },
    ...(filter ? [{ kind: 'applySheetFilter', sheetName: 'Data', filter: { range, columns: [{ colId: 2, values: ['keep'] }] }, hiddenRows: [7] }] : []), ...extra,
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
const currentFeedback = () => document.querySelector('.workbook-feedback')?.textContent
const sheet = () => grid.api.getActiveWorkbook().getActiveSheet()
function dialog() {
  sheet().getRange('C5:E9').activate(); grid.ribbon('filter-advanced')
  const card = document.querySelector<HTMLElement>('[role="dialog"][aria-label="高级筛选"]')!
  expect(card).not.toBeNull(); return card
}
function select(card: HTMLElement, label: string, value: string) {
  const field = card.querySelector<HTMLInputElement | HTMLSelectElement>(`[aria-label="${label}"]`)!
  expect(field, label).not.toBeNull(); field.value = value
  field.dispatchEvent(new Event('change', { bubbles: true })); field.dispatchEvent(new Event('input', { bubbles: true }))
}
function apply(card: HTMLElement, column: number, first: readonly string[], second?: readonly string[], and = true) {
  select(card, '高级筛选字段', String(column)); select(card, '第一条件运算符', first[0]!); select(card, '第一条件值', first[1]!)
  if (second) { select(card, '第二条件运算符', second[0]!); select(card, '第二条件值', second[1]!); select(card, '条件连接', and ? 'and' : 'or') }
  card.querySelector<HTMLFormElement>('form')!.requestSubmit()
}
afterEach(() => { vi.restoreAllMocks(); for (const instance of grid.instances.splice(0)) instance.dispose(); document.body.replaceChildren() })
it.each([true, false])('cancels real main advanced filter with existing=%s without cells, draft or history changes', async existing => {
  const draft = new NativeDraft(identity, store()), current = await open(await fixture(existing), draft)
  const before = structuredClone(grid.api.getActiveWorkbook().getSnapshot()), history = grid.instances.at(-1).__getInjector().get(IUndoRedoService), undo = history.pitchTopUndoElement()
  dialog().querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click()
  expect(grid.api.getActiveWorkbook().getSnapshot()).toEqual(before); expect(draft.operations).toEqual([]); expect(history.pitchTopUndoElement()).toBe(undo)
  current.view?.dispose()
})
it('does not save filter-cache visibility as a false outline hidden change on a no-edit save', async () => {
  const draft = new NativeDraft(identity, store())
  let request: NativeSaveRequest | undefined
  const current = await open(await fixture(), draft, async payload => {
    request = payload
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/unchanged.xlsx' } }, validation: { issues: [] } }
  })
  current.shell.save.click()
  await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toContain('已保存修订 2'))
  expect(request!.operations.filter(operation => operation.kind === 'applySheetOutline')).toEqual([])
  current.view?.dispose()
})
it('does not retain a false outline visibility draft after changing and undoing a real filter', async () => {
  const draft = new NativeDraft(identity, store()), current = await open(await fixture(), draft)
  apply(dialog(), 1, ['lessThan', '10'])
  await vi.waitFor(() => expect(sheet().getFilter().getFilteredOutRows().sort((a: number, b: number) => a - b)).toEqual([6, 7, 8]))
  await grid.api.undo()
  expect(sheet().getFilter().getFilteredOutRows()).toContain(7)
  expect(sheet().getSheet().getRowRawVisible(7)).toBe(true)
  await vi.waitFor(() => expect(draft.operations).toEqual([]))
  await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toBe('已保存'))
  const cleanLeave = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(cleanLeave)
  expect(cleanLeave.defaultPrevented).toBe(false)
  await grid.api.redo()
  await vi.waitFor(() => expect(draft.operations).not.toEqual([]))
  expect(current.shell.statusLabel.textContent).toBe('有未保存修改')
  const dirtyLeave = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(dirtyLeave)
  expect(dirtyLeave.defaultPrevented).toBe(true)
  current.view?.dispose()
})
it('omits raw visibility from an outline-level edit on a source-filter-hidden row', async () => {
  const source = await fixture(), draft = new NativeDraft(identity, store()), current = await open(source, draft)
  sheet().hideRows(5)
  sheet().getRange('A8').activate()
  grid.ribbon('outline-group:rows')
  await vi.waitFor(() => expect(draft.operations.find(operation => operation.kind === 'applySheetOutline')).toBeDefined())
  const outline = draft.operations.find(operation => operation.kind === 'applySheetOutline') as any
  expect(outline.rows).toContainEqual({ index: 7, level: 1, collapsed: false })
  const saved = await readWorkbook(await applyWorkbookOperations(source, draft.operations as any))
  expect(saved.sheets[0]!.rows.find(row => row.row === 8)).toMatchObject({ outlineLevel: 1, hidden: true })
  expect(saved.sheets[0]!.rows.find(row => row.row === 6)).toMatchObject({ hidden: true })
  current.view?.dispose()
})
it('keeps outline hidden writeback when a filter is newly created without a source filter', async () => {
  const source = await fixture(false), draft = new NativeDraft(identity, store()), current = await open(source, draft)
  apply(dialog(), 1, ['lessThan', '10'])
  await vi.waitFor(() => expect(sheet().getFilter()).not.toBeNull())
  sheet().getRange('A6:A7').activate()
  grid.ribbon('outline-group:rows'); grid.ribbon('outline-hide-detail')
  await vi.waitFor(() => expect(draft.operations.find(operation => operation.kind === 'applySheetOutline')).toBeDefined())
  const outline = draft.operations.find(operation => operation.kind === 'applySheetOutline') as any
  expect(outline.rows).toContainEqual({ index: 5, level: 1, collapsed: false, hidden: true })
  const saved = await readWorkbook(await applyWorkbookOperations(source, draft.operations as any))
  expect(saved.sheets[0]!.rows.find(row => row.row === 6)).toMatchObject({ outlineLevel: 1, hidden: true })
  current.view?.dispose()
})
it('leaves source-filter visibility to the filter operation after clearing criteria', async () => {
  const source = await fixture(), draft = new NativeDraft(identity, store()), current = await open(source, draft)
  const workbook = grid.api.getActiveWorkbook(), commands = grid.instances.at(-1).__getInjector().get(ICommandService)
  expect(commands.syncExecuteCommand('sheet.command.clear-filter-criteria', { unitId: workbook.getId(), subUnitId: sheet().getSheetId() })).toBe(true)
  await vi.waitFor(() => expect(draft.operations.find(operation => operation.kind === 'applySheetFilter')).toBeDefined())
  expect(draft.operations.filter(operation => operation.kind === 'applySheetOutline')).toEqual([])
  current.view?.dispose()
})
function nativePatch(source: Uint8Array, operations: unknown[], expected: { hidden: readonly number[]; column: number; and?: boolean; filters: { val: string; operator?: string }[] }) {
  const repo = resolve(__dirname, '../../../..')
  const result = spawnSync(independentPython(), ['-c', `
import base64,json,sys
from io import BytesIO
from zipfile import ZipFile
from lxml import etree
from openpyxl import load_workbook
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin);original=base64.b64decode(p['source']);data=patch_office('xlsx',original,p['operations']);e=p['expected']
with ZipFile(BytesIO(data)) as z:
 assert z.testzip() is None
 for n in z.namelist():
  if n.endswith(('.xml','.rels')):etree.fromstring(z.read(n))
 root=etree.fromstring(z.read('xl/worksheets/sheet1.xml'));ns={'m':root.nsmap[None]};af=root.find('m:autoFilter',ns);assert af.get('ref')=='C5:E9'
 cf=af.find('m:filterColumn[@colId="'+str(e['column'])+'"]/m:customFilters',ns)
 assert (cf.get('and')=='1')==e.get('and',False)
 assert [dict(x.attrib) for x in cf]==e['filters']
 assert af.find('m:filterColumn[@colId="2"]/m:filters/m:filter',ns).get('val')=='keep'
a=load_workbook(BytesIO(original));s=load_workbook(BytesIO(data))['Data']
assert [[c.value for c in row] for row in a['Data']]==[[c.value for c in row] for row in s]
assert sorted(r for r,d in s.row_dimensions.items() if d.hidden)==e['hidden']
assert not s.row_dimensions[5].hidden and s['C10'].value=='Tail' and s['D10'].value==99
print(base64.b64encode(data).decode())
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify({ source: Buffer.from(source).toString('base64'), operations, expected }), encoding: 'utf8', maxBuffer: 30 * 1024 * 1024 })
  expect(result.status, result.stderr).toBe(0); return new Uint8Array(Buffer.from(result.stdout.trim(), 'base64'))
}
it.each([
  { name: 'AND', column: 1, first: ['greaterThanOrEqual', '10'], second: ['lessThan', '30'], and: true, filtered: [5, 7, 8], hidden: [6, 8, 9] },
  { name: 'OR', column: 1, first: ['lessThan', '10'], second: ['greaterThan', '30'], and: false, filtered: [6, 7], hidden: [7, 8] },
  { name: 'text equal', column: 0, first: ['equal', 'A'], filtered: [7], hidden: [8] },
] as const)('runs $name using the real filter plugin at C5 and saves restored main drafts through Python native_office', async item => {
  const source = await fixture(), storage = store(), draft = new NativeDraft(identity, storage), first = await open(source, draft)
  const old = sheet().getFilter().getColumnFilterCriteria(4)
  apply(dialog(), item.column, item.first, 'second' in item ? item.second : undefined, 'and' in item ? item.and : true)
  await vi.waitFor(() => expect(sheet().getFilter().getFilteredOutRows().sort((a: number, b: number) => a - b)).toEqual(item.filtered))
  expect(sheet().getFilter().getColumnFilterCriteria(4)).toEqual(old)
  await vi.waitFor(() => expect(draft.operations.filter(op => op.kind === 'applySheetFilter'), currentFeedback()).toHaveLength(1))
  const conditions: (readonly string[])[] = [item.first]
  if ('second' in item && item.second) conditions.push(item.second)
  const filters = conditions.map(([operator, val]) => ({ val: val!, ...(operator === 'equal' ? {} : { operator: operator! }) }))
  const filterOp = draft.operations.find(op => op.kind === 'applySheetFilter') as any
  expect(filterOp.filter.range).toEqual(range)
  expect(filterOp.filter.columns).toContainEqual({ colId: item.column, customs: { ...('and' in item && item.and ? { and: true } : {}), filters } })
  await grid.api.undo()
  expect(sheet().getFilter().getColumnFilterCriteria(2 + item.column) == null).toBe(true)
  await vi.waitFor(() => expect(draft.operations).toEqual([]))
  await grid.api.redo()
  await vi.waitFor(() => expect(draft.operations.filter(op => op.kind === 'applySheetFilter'), currentFeedback()).toHaveLength(1))
  const beforeRefresh = draft.operations; first.view?.dispose()
  const restored = new NativeDraft(identity, storage)
  let downloaded: Uint8Array | undefined, request: NativeSaveRequest | undefined
  const second = await open(source, restored, async payload => {
    request = payload; downloaded = nativePatch(source, payload.operations, { hidden: item.hidden, column: item.column, and: 'and' in item ? item.and : false, filters })
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/advanced-filter.xlsx' } }, validation: { issues: [] } }
  })
  expect(restored.operations).toEqual(beforeRefresh)
  expect(sheet().getFilter().getFilteredOutRows().sort((a: number, b: number) => a - b)).toEqual(item.filtered)
  second.shell.save.click()
  await vi.waitFor(() => expect(second.shell.statusLabel.textContent).toContain('已保存修订 2'), { timeout: 30000 })
  expect(request!.operations.filter(op => op.kind === 'applySheetFilter')).toHaveLength(1)
  expect((await readWorkbook(downloaded!)).sheets[0]!.cells.C10.value).toBe('Tail')
  second.view?.dispose()
}, 45000)
it('creates a missing filter at confirmation and undoes creation and criteria in one step', async () => {
  const draft = new NativeDraft(identity, store()), current = await open(await fixture(false), draft)
  apply(dialog(), 1, ['greaterThanOrEqual', '10'], ['lessThan', '30'])
  await vi.waitFor(() => expect(sheet().getFilter()?.getFilteredOutRows().sort((a: number, b: number) => a - b)).toEqual([5, 8]))
  await grid.api.undo(); expect(sheet().getFilter()).toBeNull()
  await vi.waitFor(() => expect(draft.operations).toEqual([]))
  await grid.api.redo()
  await vi.waitFor(() => expect(sheet().getFilter()?.getFilteredOutRows().sort((a: number, b: number) => a - b)).toEqual([5, 8]))
  current.view?.dispose()
})
it('keeps a rejected native command out of the main draft and undo/redo history', async () => {
  const draft = new NativeDraft(identity, store()), current = await open(await fixture(), draft)
  const commands = grid.instances.at(-1).__getInjector().get(ICommandService), history = grid.instances.at(-1).__getInjector().get(IUndoRedoService)
  const undo = history.pitchTopUndoElement(), redo = history.pitchTopRedoElement(), run = commands.syncExecuteCommand.bind(commands), card = dialog()
  const before = structuredClone(grid.api.getActiveWorkbook().getSnapshot())
  vi.spyOn(commands, 'syncExecuteCommand').mockImplementation(((id: string, params: any, options: any) => id === 'sheet.command.set-filter-criteria' ? false : run(id, params, options)) as typeof commands.syncExecuteCommand)
  apply(card, 1, ['greaterThan', '10'])
  await vi.waitFor(() => expect(card.querySelector('[role="alert"]')?.textContent).toMatch(/未|失败|拒绝/))
  expect(grid.api.getActiveWorkbook().getSnapshot()).toEqual(before); expect(draft.operations).toEqual([])
  expect(history.pitchTopUndoElement()).toBe(undo); expect(history.pitchTopRedoElement()).toBe(redo); current.view?.dispose()
})
it('refuses a protected source before any criteria mutation', async () => {
  const draft = new NativeDraft(identity, store()), current = await open(await fixture(true, [{ kind: 'protectSheet', sheetName: 'Data', protect: true }]), draft)
  const execute = vi.spyOn(grid.instances.at(-1).__getInjector().get(ICommandService), 'syncExecuteCommand')
  sheet().getRange('C5:E9').activate(); grid.ribbon('filter-advanced')
  await vi.waitFor(() => expect(current.shell.editor.querySelector('.workbook-feedback')!.textContent).toMatch(/保护/))
  expect(execute.mock.calls.some(([id]) => id === 'sheet.command.set-filter-criteria')).toBe(false)
  expect(draft.operations).toEqual([]); current.view?.dispose()
})
it('refuses dateGroups before opening a mutating UI and keeps unrelated operations empty', async () => {
  const source = await fixture(false, [{ kind: 'applySheetFilter', sheetName: 'Data', filter: { range, columns: [{ colId: 0, dateGroups: [{ year: 2024, month: 1, dateTimeGrouping: 'month' }] }] } }]), draft = new NativeDraft(identity, store()), current = await open(source, draft)
  const execute = vi.spyOn(grid.instances.at(-1).__getInjector().get(ICommandService), 'syncExecuteCommand')
  sheet().getRange('C5:E9').activate(); grid.ribbon('filter-advanced')
  await vi.waitFor(() => expect(currentFeedback()).toMatch(/日期分组/))
  expect(document.querySelector('[role="dialog"][aria-label="高级筛选"]')?.closest<HTMLElement>('[hidden]')).not.toBeNull()
  expect(execute.mock.calls.some(([id]) => id === 'sheet.command.set-filter-criteria')).toBe(false)
  expect(draft.operations).toEqual([]); current.view?.dispose()
})
it('rejects a stale selection in main without applying criteria', async () => {
  const draft = new NativeDraft(identity, store()), current = await open(await fixture(), draft), card = dialog()
  sheet().getRange('C12').activate(); apply(card, 1, ['greaterThan', '10'])
  await vi.waitFor(() => expect(card.querySelector('[role="alert"]')?.textContent).toMatch(/变化|重新/))
  expect(sheet().getFilter().getColumnFilterCriteria(3) == null).toBe(true)
  expect(draft.operations).toEqual([]); current.view?.dispose()
})
it('rejects a complete staged-operation budget before the first criteria command', async () => {
  const draft = new NativeDraft(identity, store()), existing = Array.from({ length: 500 }, () => ({ kind: 'applySheetOutline', sheetName: 'Data', summaryBelow: true }))
  draft.setOperations(existing)
  const current = await open(await fixture(), draft), execute = vi.spyOn(grid.instances.at(-1).__getInjector().get(ICommandService), 'syncExecuteCommand'), card = dialog()
  apply(card, 1, ['greaterThan', '10'])
  await vi.waitFor(() => expect(card.querySelector('[role="alert"]')?.textContent).toMatch(/操作|预算|500|超限/), { timeout: 10000 })
  expect(execute.mock.calls.some(([id]) => id === 'sheet.command.set-filter-criteria')).toBe(false)
  expect(draft.operations).toEqual(existing); current.view?.dispose()
}, 20000)
it('retains a manually hidden row when the real main filter changes', async () => {
  const draft = new NativeDraft(identity, store()), current = await open(await fixture(), draft)
  sheet().hideRows(5)
  apply(dialog(), 1, ['lessThan', '10'], ['greaterThan', '30'], false)
  await vi.waitFor(() => expect((draft.operations.find(op => op.kind === 'applySheetFilter') as any)?.hiddenRows, currentFeedback()).toEqual([5, 6, 7]))
  expect(sheet().getSheet().getRowManager().getRowData()[5].hd).toBe(1)
  current.view?.dispose()
})
it('refuses a Table overlap during real file preflight before creating a filter', async () => {
  const source = await fixture(false, [{ kind: 'applyTableAdditions', additions: [{ worksheetSheetName: 'Data', area: range, name: 'TableData', columnNames: ['Group', 'Value', 'Other'], bandedRows: true }] }])
  const draft = new NativeDraft(identity, store()), current = await open(source, draft), card = dialog()
  const execute = vi.spyOn(grid.instances.at(-1).__getInjector().get(ICommandService), 'syncExecuteCommand')
  apply(card, 1, ['greaterThan', '10'])
  await vi.waitFor(() => expect(card.querySelector('[role="alert"]')?.textContent).toMatch(/Table|表格/), { timeout: 10000 })
  expect(execute.mock.calls.some(([id]) => id === 'sheet.command.set-filter-criteria' || id === 'sheet.command.set-filter-range')).toBe(false)
  expect(sheet().getFilter()).toBeNull(); expect(draft.operations).toEqual([]); current.view?.dispose()
})
it('shows a previously cached filter-hidden row when changed criteria match it', async () => {
  const source = await fixture(false, [{ kind: 'applySheetFilter', sheetName: 'Data', filter: { range, columns: [{ colId: 1, customs: { filters: [{ operator: 'greaterThanOrEqual', val: '10' }] } }] }, hiddenRows: [5] }])
  const draft = new NativeDraft(identity, store()), current = await open(source, draft)
  expect(sheet().getSheet().getRowVisible(5)).toBe(false)
  apply(dialog(), 1, ['lessThan', '10'])
  await vi.waitFor(() => expect(sheet().getFilter().getFilteredOutRows().sort((a: number, b: number) => a - b)).toEqual([6, 7, 8]))
  expect(sheet().getSheet().getRowVisible(5)).toBe(true)
  await vi.waitFor(() => expect((draft.operations.find(op => op.kind === 'applySheetFilter') as any)?.hiddenRows).toEqual([6, 7, 8]))
  expect(draft.operations.filter(operation => operation.kind === 'applySheetOutline')).toEqual([])
  current.view?.dispose()
})
