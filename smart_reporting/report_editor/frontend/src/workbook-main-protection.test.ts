import { afterEach, expect, it, vi } from 'vitest'
import { applyCellEdits, applyTableAdditions, createBufferEntrySource, assemblePackage, applySheetEdits, createBlankWorkbook, protectSheet, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createWorkbookEditorView } from './workbook-main'
import { createNativeOfficeTransport } from './native-office-view'
import { NativeDraft, type NativeDraftIdentity, type NativeSaveRequest } from './native-draft'
import { createEditorShell } from './shell'

const grid = vi.hoisted(() => ({ api: undefined as any, ribbon: undefined as any, view: undefined as any, apply: vi.fn(() => false), instances: [] as any[] }))
vi.mock('@univerjs/preset-sheets-core', () => ({ UniverSheetsCorePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-note', () => ({ UniverSheetsNotePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-find-replace', () => ({ UniverSheetsFindReplacePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-drawing', () => ({ UniverSheetsDrawingPreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-table', () => ({ UniverSheetsTablePreset: () => ({ plugins: [] }) }))
vi.mock('./workbook-ribbon', () => ({
  mountWorkbookRibbon: (_host: unknown, callback: unknown, view: unknown) => { grid.ribbon = callback; grid.view = view; return { dispose() {}, refreshState() {} } },
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
  const { UniverSheetsDataValidationPlugin } = await import('@univerjs/sheets-data-validation')
  const { UniverSheetsConditionalFormattingPlugin } = await import('@univerjs/sheets-conditional-formatting')
  const { UniverSheetsTablePlugin } = await import('@univerjs/sheets-table')
  const { UniverSheetsFilterPlugin } = await import('@univerjs/sheets-filter')
  const { UniverSheetsSortPlugin } = await import('@univerjs/sheets-sort')
  const { UniverFormulaEnginePlugin } = await import('@univerjs/engine-formula')
  const { UniverSheetsFormulaPlugin } = await import('@univerjs/sheets-formula')
  await import('@univerjs/sheets/facade')
  await import('@univerjs/sheets-note/facade')
  await import('@univerjs/sheets-table/facade')
  return { createUniver: () => {
    const univer = new Univer({ locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: mergeLocales(CoreZhCN, NoteZhCN) } })
    grid.instances.push(univer)
    univer.registerPlugin(UniverSheetsPlugin)
    univer.registerPlugin(UniverSheetsNotePlugin)
    univer.registerPlugin(UniverSheetsDataValidationPlugin)
    univer.registerPlugin(UniverSheetsConditionalFormattingPlugin)
    univer.registerPlugin(UniverSheetsTablePlugin)
    univer.registerPlugin(UniverSheetsFilterPlugin)
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

it('edits values only inside allowed ranges while retaining sheet protection on save and reopen', async () => {
  const source = await applyWorkbookOperations(await fixture(), [
    { kind: 'protectSheet', sheetName: 'Sheet1', protect: false },
    { kind: 'setSheetEditableRanges', sheetName: 'Sheet1', ranges: [{ name: '录入', sqref: 'B2:B3' }] },
    { kind: 'protectSheet', sheetName: 'Sheet1', protect: true },
  ])
  const draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/ranges.xlsx' } }, validation: { issues: [] } }
  })
  // 官方键盘提交携带完整原生清理标记，不能只用简化API载荷覆盖权限入口。
  expect(await grid.api.executeCommand('sheet.command.set-range-values', {
    range: { startRow: 1, endRow: 1, startColumn: 1, endColumn: 1 },
    value: { v: '允许', f: null, t: undefined, p: null, si: null, s: {} },
  })).toBe(true)
  await write(0, 0, '越界').catch(() => false)
  expect(sheet().getRange(0, 0).getValue()).toBe('a1')
  expect(sheet().getRange(1, 1).getValue()).toBe('允许')
  await vi.waitFor(() => expect(kinds(draft), current.shell.editor.querySelector('.workbook-feedback')?.textContent ?? '').toContain('applyCellEdits'))
  expect(kinds(draft)).not.toContain('protectSheet')
  current.shell.save.click()
  await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const saved = await readWorkbook(downloaded!)
  expect(saved.sheets[0]!.protection?.protected).toBe(true)
  expect(saved.sheets[0]!.cells.B2?.value).toBe('允许')
  current.view?.dispose()
  const reopened = await open(downloaded!, new NativeDraft(identity, store()), vi.fn())
  expect(await grid.api.executeCommand('sheet.command.set-range-values', {
    range: { startRow: 2, endRow: 2, startColumn: 1, endColumn: 1 },
    value: { v: null, f: '=1+1', t: undefined, p: null, si: null },
  })).toBe(true)
  expect(sheet().getRange(2, 1).getFormula()).toBe('=1+1')
  await write(1, 0, '仍越界').catch(() => false)
  expect(sheet().getRange(1, 0).getValue()).toBe('a2')
  reopened.view?.dispose()
})

it('rejects table header metadata changes even when its cells are in allowed edit ranges', async () => {
  let source = await applyWorkbookOperations(await fixture(), [{ kind: 'protectSheet', sheetName: 'Sheet1', protect: false }])
  source = await applyTableAdditions(source, [{ worksheetSheetName: 'Sheet1', name: 'Staff', area: { startRow: 0, endRow: 1, startColumn: 0, endColumn: 1 }, columnNames: ['a1', 'b1'], bandedRows: true }])
  source = await applyWorkbookOperations(source, [
    { kind: 'setSheetEditableRanges', sheetName: 'Sheet1', ranges: [{ name: 'Input', sqref: 'A1:B2' }] },
    { kind: 'protectSheet', sheetName: 'Sheet1', protect: true },
  ])
  const draft = new NativeDraft(identity, store()), current = await open(source, draft, vi.fn())
  await write(0, 0, 'Renamed').catch(() => false)
  expect(sheet().getRange(0, 0).getValue()).toBe('a1')
  expect(grid.api.getActiveWorkbook().getTableList()[0].columns[0].displayName).toBe('a1')
  expect(draft.operations).toEqual([])
  expect(current.shell.editor.querySelector('.workbook-feedback')?.textContent).toContain('表头')
  current.view?.dispose()
})

it('accepts copied native styles on allowed value edits without changing workbook formatting', async () => {
  const source = await applyWorkbookOperations(await fixture(), [
    { kind: 'protectSheet', sheetName: 'Sheet1', protect: false },
    { kind: 'applyCellEdits', edits: [{ sheetName: 'Sheet1', row: 1, column: 1, writeValue: false, cell: { value: null }, style: { fontFamily: 'Calibri', fontSize: 11, fontColor: '#000000', fillColor: '#FFFF00' } }] },
    { kind: 'setSheetEditableRanges', sheetName: 'Sheet1', ranges: [{ name: 'Styled', sqref: 'B2' }] },
    { kind: 'protectSheet', sheetName: 'Sheet1', protect: true },
  ])
  const draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/styled.xlsx' } }, validation: { issues: [] } }
  })
  const style = structuredClone(sheet().getSheet().getComposedCellStyle(1, 1))
  // 实际built浏览器载荷只含字体patch，不含原格填色；保护入口必须保留原始样式。
  const params = { range: { startRow: 1, endRow: 1, startColumn: 1, endColumn: 1 }, value: { v: 'styled input', f: null, si: null, p: null, s: { ff: 'Calibri', fs: 11, cl: { rgb: '#000000' } } } }
  expect(await grid.api.executeCommand('sheet.command.set-range-values', params)).toBe(true)
  await vi.waitFor(() => expect(kinds(draft)).toContain('applyCellEdits'))
  for (const edit of draft.operations.flatMap((op: any) => op.edits ?? [])) { expect(edit.style).toBeUndefined();expect(edit.styleReset).not.toBe(true) }
  expect(await grid.api.executeCommand('sheet.command.set-range-values', { ...params, value: { ...params.value, s: { bl: 1 } } })).toBe(true)
  await grid.api.executeCommand('sheet.command.set-range-values', { ...params, value: { s: { bl: 1 } } }).catch(() => false)
  expect(sheet().getSheet().getComposedCellStyle(1, 1)).toEqual(style)
  current.shell.save.click()
  await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toContain('已保存修订 2'))
  expect((await readWorkbook(downloaded!)).sheets[0]!.cells.B2!.value).toBe('styled input')
  expect(await (await createBufferEntrySource(downloaded!)).readText('xl/styles.xml')).toBe(await (await createBufferEntrySource(source)).readText('xl/styles.xml'))
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

it('keeps unsupported source tables read-only after renaming their worksheet before creating a table', async () => {
  const bytes = await applyTableAdditions(await createBlankWorkbook(), [{ worksheetSheetName: 'Sheet1', name: 'Staff',
    area: { startRow: 0, endRow: 1, startColumn: 0, endColumn: 0 }, columnNames: ['Name'], bandedRows: true }])
  const zip = await createBufferEntrySource(bytes)
  const path = (await zip.paths()).find(path => /^xl\/tables\/table.*\.xml$/.test(path))!
  const xml = (await zip.readText(path)).replace('totalsRowShown="0"', 'totalsRowShown="0" totalsRowCount="2"')
  const source = (await assemblePackage(bytes, { replaced: new Map([[path, xml]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
  const model = await readWorkbook(source)
  expect(model.sheets[0]!.tablesReadOnlyReason).toBeTruthy()
  const draft = new NativeDraft(identity, store()), current = await open(source, draft, vi.fn())
  expect(grid.api.syncExecuteCommand('sheet.command.set-worksheet-name', { unitId: grid.api.getActiveWorkbook().getId(), subUnitId: sheet().getSheetId(), name: 'Renamed' })).toBe(true)
  expect(sheet().getSheetName()).toBe('Renamed')
  sheet().setActiveSelection(sheet().getRange(0, 3, 2, 1))
  grid.ribbon('format-as-table')
  expect(document.querySelector<HTMLElement>('[role="dialog"][aria-label="创建表格"]')!.hidden).toBe(true)
  expect(document.body.textContent).toContain(model.sheets[0]!.tablesReadOnlyReason!)
  current.view?.dispose()
})

it('saves full moved formatting when creating a table without headers through the editor', async () => {
  const source = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'occupied' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 123 }, style: { fontFamily: 'Calibri', fontSize: 11 } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: 456 }, style: { bold: true, fillColor: '#FF0000', numberFormat: '0.000' } },
  ])
  const draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/p.xlsx' } }, validation: { issues: [] } }
  })
  sheet().setActiveSelection(sheet().getRange(1, 0, 2, 1))
  grid.ribbon('format-as-table')
  const dialog = document.querySelector<HTMLElement>('[role="dialog"][aria-label="创建表格"]')!
  expect(dialog.hidden).toBe(false)
  dialog.querySelector<HTMLInputElement>('[aria-label="表包含标题"]')!.checked = false
  dialog.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  expect(dialog.querySelector('[role="alert"]')!.textContent).toBe('')
  expect(dialog.hidden).toBe(true)
  await vi.waitFor(() => expect(kinds(draft)).toContain('applyTableAdditions'))
  current.shell.save.click()
  await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const saved = await readWorkbook(downloaded!)
  const { importedStyleOf } = await import('./workbook-vendor/core/session-core')
  expect(saved.sheets[0]!.cells.A3?.value).toBe(123)
  expect(importedStyleOf(saved, 'Sheet1', 'A3')).toMatchObject({ fontFamily: 'Calibri', fontSize: 11 })
  expect(importedStyleOf(saved, 'Sheet1', 'A3')?.bold).not.toBe(true)
  expect(importedStyleOf(saved, 'Sheet1', 'A3')?.fillColor).toBeUndefined()
  expect(importedStyleOf(saved, 'Sheet1', 'A3')?.numberFormat ?? 'General').toBe('General')
  expect(importedStyleOf(saved, 'Sheet1', 'A4')).toMatchObject({ bold: true, fillColor: '#FF0000', numberFormat: '0.000' })
  expect(saved.sheets[0]!.tables).toHaveLength(1)
  current.view?.dispose()
})

it('saves a header row toggle through the editor and restores the original table on undo', async () => {
  const source = await applyTableAdditions(await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Name' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'Ada' } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: 'Grace' } },
  ]), [{ worksheetSheetName: 'Sheet1', name: 'Staff', area: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 }, columnNames: ['Name'], bandedRows: true }])
  const draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/p.xlsx' } }, validation: { issues: [] } }
  })
  sheet().setActiveSelection(sheet().getRange(1, 0))
  const id = grid.view.table().id
  grid.view.setTableHeaderRow(id, false)
  await vi.waitFor(() => expect(grid.view.table().header).toBe(false))
  expect(sheet().getRange(0, 0).getValue()).toBeNull()
  await vi.waitFor(() => expect(draft.operations).toContainEqual({ kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Sheet1', tableName: 'Staff', area: { startRow: 1, endRow: 2, startColumn: 0, endColumn: 0 }, headerRow: false }] }))
  history('undo')
  expect(sheet().getRange(0, 0).getValue()).toBe('Name')
  await vi.waitFor(() => expect(draft.operations).toEqual([]))
  history('redo')
  current.shell.save.click()
  await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const saved = await readWorkbook(downloaded!)
  expect(saved.sheets[0]!.tables![0]).toMatchObject({ headerRowCount: 0, range: { startRow: 1, endRow: 2, startColumn: 0, endColumn: 0 }, columns: [{ name: 'Name' }] })
  expect(saved.sheets[0]!.cells.A1?.value ?? null).toBeNull()
  expect(saved.sheets[0]!.cells.A2?.value).toBe('Ada')
  expect(saved.sheets[0]!.cells.A3?.value).toBe('Grace')
  current.view?.dispose()
})


it('saves table filter buttons through main, undo and recovered drafts without editing cells', async () => {
  const source = await applyTableAdditions(await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Name' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'Ada' } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: 'Grace' } },
  ]), [{ worksheetSheetName: 'Sheet1', name: 'Staff', area: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 }, columnNames: ['Name'], bandedRows: true }])
  const storage = store(), draft = new NativeDraft(identity, storage)
  let downloaded: Uint8Array | undefined
  const save = async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/p.xlsx' } }, validation: { issues: [] } }
  }
  const current = await open(source, draft, save)
  sheet().setActiveSelection(sheet().getRange(1, 0))
  expect(grid.view.table().filterButton).toBe(true)
  const id = grid.view.table().id
  grid.view.setTableFilterButton(id, false)
  expect(grid.view.table().filterButton).toBe(false)
  const expected = [{ kind: 'applyTableEdits', edits: [{ worksheetSheetName: 'Sheet1', tableName: 'Staff', filterButton: false }] }]
  await vi.waitFor(() => expect(draft.operations).toEqual(expected))
  history('undo')
  await vi.waitFor(() => expect(draft.operations).toEqual([]))
  expect(grid.view.table().filterButton).toBe(true)
  history('redo')
  await vi.waitFor(() => expect(draft.operations).toEqual(expected))
  current.view?.dispose()
  const reopened = await open(source, new NativeDraft(identity, storage), save)
  sheet().setActiveSelection(sheet().getRange(1, 0))
  expect(grid.view.table().filterButton).toBe(false)
  reopened.shell.save.click()
  await vi.waitFor(() => expect(reopened.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const saved = await readWorkbook(downloaded!)
  expect(saved.sheets[0]!.tables![0]).toMatchObject({ filterButton: false, headerRowCount: 1, range: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 } })
  expect(saved.sheets[0]!.cells).toEqual((await readWorkbook(source)).sheets[0]!.cells)
  reopened.view?.dispose()
})
