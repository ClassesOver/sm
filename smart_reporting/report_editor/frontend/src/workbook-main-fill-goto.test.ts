import { afterEach, expect, it, vi } from 'vitest'
import { applyCellEdits, applyDefinedNames, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { planFillSeries, fillSeriesLine } from './workbook-fill-series'
import { resolveGoToRef } from './workbook-goto'
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

const identity: NativeDraftIdentity = { documentId: 'main-fill-goto', revision: 1, sourceSha256: 'b'.repeat(64),
  scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } }
const store = () => { const data = new Map<string, string>(); return { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => { data.set(key, value) }, removeItem: (key: string) => { data.delete(key) } } }
async function fixture() {
  return applyDefinedNames(await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 2 } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 'text' } },
  ]), { sets: [{ name: 'Target', refersTo: 'Sheet1!$C$3:$D$4' }] })
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


it('keeps the fixed-source series planner and Go To resolution', () => {
  expect(fillSeriesLine([1], 4, { direction: 'columns', type: 'linear', dateUnit: 'day', trend: false, step: 2, stop: 5 })).toEqual([1, 3, 5])
  expect(fillSeriesLine([2], 4, { direction: 'columns', type: 'growth', dateUnit: 'day', trend: false, step: 3, stop: null })).toEqual([2, 6, 18, 54])
  expect(fillSeriesLine([45322], 3, { direction: 'columns', type: 'date', dateUnit: 'month', trend: false, step: 1, stop: null })).toEqual([45322, 45351, 45382])
  expect(planFillSeries([['x', 1]], { direction: 'rows', type: 'linear', dateUnit: 'day', trend: false, step: 1, stop: null })).toEqual([])
  expect(resolveGoToRef(' c5 ', [])).toBe('c5')
  expect(resolveGoToRef('target', [{ name: 'Target', ref: '=Sheet1!$C$3' }])).toBe('Sheet1!$C$3')
  for (const bad of ['A0', 'XFE1', 'A1048577', 'hello', 'Sheet1!', '']) expect(resolveGoToRef(bad, []), bad).toBeNull()
})

it('fills a linear series through the dialog and saves it, and Go To selects names read-only', async () => {
  const source = await fixture(), draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/f.xlsx' } }, validation: { issues: [] } }
  })
  sheet().setActiveSelection(sheet().getRange(0, 0, 5, 1))
  grid.ribbon('fill-series-open')
  const dialog = document.querySelector<HTMLElement>('.workbook-ribbon-fill-dialog')!
  expect(dialog.querySelector<HTMLInputElement>('input[name="workbook-fill-direction"][value="columns"]')!.checked).toBe(true)
  expect(dialog.querySelector<HTMLInputElement>('input[name="workbook-fill-type"][value="linear"]')!.checked).toBe(true)
  expect(dialog.querySelector<HTMLFieldSetElement>('[data-fill-group="unit"]')!.disabled).toBe(true)
  const step = dialog.querySelector<HTMLInputElement>('[data-fill-step]')!
  step.value = 'x'; step.dispatchEvent(new Event('input', { bubbles: true }))
  expect(dialog.querySelector<HTMLButtonElement>('.workbook-ribbon-format-apply')!.disabled).toBe(true)
  step.value = '3'; step.dispatchEvent(new Event('input', { bubbles: true }))
  dialog.querySelector<HTMLFormElement>('form')!.requestSubmit()
  expect(sheet().getRange(0, 0, 5, 1).getValues().map((row: unknown[]) => row[0])).toEqual([2, 5, 8, 11, 14])
  current.shell.save.click()
  await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const cells = (await readWorkbook(downloaded!)).sheets[0]!.cells
  expect([1, 2, 3, 4, 5].map(row => cells[`A${row}`]?.value)).toEqual([2, 5, 8, 11, 14])
  // 保存后只读：定位仍可用
  grid.ribbon('goto-open')
  const goto = document.querySelector<HTMLElement>('.workbook-ribbon-goto-dialog')!
  expect([...goto.querySelectorAll('[data-goto-name]')].map(node => node.getAttribute('data-goto-name'))).toEqual(['Target'])
  const input = goto.querySelector<HTMLInputElement>('[data-goto-reference]')!
  input.value = 'nowhere'; goto.querySelector<HTMLFormElement>('form')!.requestSubmit()
  expect(goto.querySelector('[role="alert"]')!.textContent).toContain('无法定位')
  goto.querySelector<HTMLButtonElement>('[data-goto-name="Target"]')!.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }))
  const range = grid.api.getActiveWorkbook().getActiveRange().getRange()
  expect([range.startRow, range.startColumn, range.endRow, range.endColumn]).toEqual([2, 2, 3, 3])
  current.view?.dispose()
})
