import { afterEach, expect, it, vi } from 'vitest'
import { applyCellEdits, applySheetEdits, createBlankWorkbook, protectSheet, readWorkbook } from '@sheets-web/xlsx-engine'
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

const identity: NativeDraftIdentity = { documentId: 'main-protection', revision: 1, sourceSha256: 'b'.repeat(64),
  scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } }
const store = () => { const data = new Map<string, string>(); return { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => { data.set(key, value) }, removeItem: (key: string) => { data.delete(key) } } }
async function fixture() {
  const two = await applySheetEdits(await createBlankWorkbook(), { renames: [], additions: [{ name: 'Open' }], removals: [], order: ['Sheet1', 'Open'] })
  return protectSheet(await applyCellEdits(two, [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'a1' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 'b1' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'a2' } },
    { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: 'b2' } },
    { sheetName: 'Sheet1', row: 4, column: 0, writeValue: true, cell: { value: null, formula: '=B2' } },
  ]), 'Sheet1', true)
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
const kinds = (draft: NativeDraft) => draft.operations.map((op: any) => op.kind)
const write = (row: number, column: number, value: string) => grid.api.executeCommand('sheet.command.set-range-values', { range: { startRow: row, endRow: row, startColumn: column, endColumn: column }, value: { v: value } })
afterEach(() => {
  for (const instance of grid.instances.splice(0)) instance.dispose()
  document.body.replaceChildren()
})


it('keeps a protected sheet read-only until unprotected, then saves unprotect before edits', async () => {
  const source = await fixture(), draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/p.xlsx' } }, validation: { issues: [] } }
  })
  await write(0, 0, 'blocked').catch(() => false)
  expect(sheet().getRange(0, 0).getValue()).toBe('a1')
  expect(current.shell.editor.textContent).toContain('工作表受保护')
  grid.ribbon('sheet-protect')
  expect(await write(0, 0, 'edited')).toBe(true)
  await vi.waitFor(() => expect(kinds(draft)).toEqual(['protectSheet', 'applyCellEdits']))
  expect(draft.operations[0]).toEqual({ kind: 'protectSheet', sheetName: 'Sheet1', protect: false })
  current.shell.save.click()
  await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const saved = await readWorkbook(downloaded!)
  expect(saved.sheets[0]!.protection).toBeUndefined()
  expect(saved.sheets[0]!.cells.A1?.value).toBe('edited')
  current.view?.dispose()
})

it('protects after edits, blocks later edits, and locks the workbook structure', async () => {
  const source = await fixture(), draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/p.xlsx' } }, validation: { issues: [] } }
  })
  const workbook = grid.api.getActiveWorkbook()
  workbook.setActiveSheet(workbook.getSheetByName('Open'))
  expect(await write(0, 0, 'before')).toBe(true)
  grid.ribbon('sheet-protect')
  await write(1, 0, 'after').catch(() => false)
  expect(sheet().getRange(1, 0).getValue()).not.toBe('after')
  grid.ribbon('workbook-protect')
  await grid.api.executeCommand('sheet.command.set-worksheet-name', { subUnitId: sheet().getSheetId(), name: 'Renamed' }).catch(() => false)
  expect(sheet().getSheetName()).toBe('Open')
  expect(current.shell.editor.textContent).toContain('工作簿结构受保护')
  await vi.waitFor(() => expect(kinds(draft)).toEqual(['applyCellEdits', 'protectSheet', 'protectWorkbookStructure']))
  current.shell.save.click()
  await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const saved = await readWorkbook(downloaded!)
  expect(saved.sheets[1]!.protection).toEqual({ protected: true, hasPassword: false })
  expect(saved.sheets[1]!.cells.A1?.value).toBe('before')
  expect(saved.sheets[0]!.protection).toEqual({ protected: true, hasPassword: false })
  expect(saved.workbookProtection).toEqual({ lockStructure: true, hasPassword: false })
  current.view?.dispose()
})
