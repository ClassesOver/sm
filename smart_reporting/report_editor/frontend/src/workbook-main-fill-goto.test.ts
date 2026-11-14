import { applyPageSetups } from '../../../reporting/workbook_engine/packages/xlsx-engine/src/page-setup'
import { afterEach, expect, it, vi } from 'vitest'
import { IUndoRedoService } from '@univerjs/core'
import { assemblePackage } from '@sheets-web/xlsx-engine'
import { applyCellEdits, applyDefinedNames, applyTableAdditions, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { planFillSeries, fillSeriesLine } from './workbook-fill-series'
import { resolveGoToRef } from './workbook-goto'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createWorkbookEditorView } from './workbook-main'
import { createNativeOfficeTransport } from './native-office-view'
import { NativeDraft, type NativeDraftIdentity, type NativeSaveRequest } from './native-draft'
import { createEditorShell } from './shell'
import { readBackSnapshot } from './workbook-vendor/grid/sync'
import { planWorkbookTextToColumns } from './workbook-text-to-columns'
import * as validationAdapter from './workbook-data-validation'
import { planWorkbookDedupe } from './workbook-dedupe'
import { workbookTableConfig } from './workbook-tables'
import * as gotoReveal from './workbook-goto-reveal'
import { createPivotPlan } from './workbook-pivot'
import { protectSheet } from '../../../reporting/workbook_engine/packages/xlsx-engine/src/protection'

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
vi.mock('./workbook-vendor/grid/paste-special',async original=>{const actual=await original<typeof import('./workbook-vendor/grid/paste-special')>();return {...actual,readPasteSpecialSource:async()=>({kind:'text' as const,rows:[['7']]})}})
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
  const { UniverSheetsConditionalFormattingPlugin } = await import('@univerjs/sheets-conditional-formatting')
  const { UniverSheetsNotePlugin } = await import('@univerjs/sheets-note')
  const { UniverSheetsSortPlugin } = await import('@univerjs/sheets-sort')
  const { UniverFormulaEnginePlugin } = await import('@univerjs/engine-formula')
  const { UniverSheetsFormulaPlugin } = await import('@univerjs/sheets-formula')
  const { UniverSheetsDataValidationPlugin } = await import('@univerjs/sheets-data-validation')
  const { UniverSheetsTablePlugin } = await import('@univerjs/sheets-table')
  await import('@univerjs/sheets/facade')
  await import('@univerjs/sheets-filter/facade')
  await import('@univerjs/sheets-conditional-formatting/facade')
  await import('@univerjs/sheets-note/facade')
  await import('@univerjs/sheets-data-validation/facade')
  await import('@univerjs/sheets-table/facade')
  return { createUniver: () => {
    const univer = new Univer({ locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: mergeLocales(CoreZhCN, NoteZhCN) } })
    grid.instances.push(univer)
    univer.registerPlugin(UniverSheetsPlugin)
    univer.registerPlugin(UniverSheetsFilterPlugin)
    univer.registerPlugin(UniverSheetsConditionalFormattingPlugin)
    univer.registerPlugin(UniverSheetsNotePlugin)
    univer.registerPlugin(UniverSheetsSortPlugin)
    univer.registerPlugin(UniverFormulaEnginePlugin)
    univer.registerPlugin(UniverSheetsFormulaPlugin)
    univer.registerPlugin(UniverSheetsDataValidationPlugin)
    univer.registerPlugin(UniverSheetsTablePlugin, workbookTableConfig)
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
async function open(source: Uint8Array, draft: NativeDraft, save: (request: NativeSaveRequest) => Promise<unknown>, editingEnabled = true) {
  document.body.innerHTML = '<main id="app"></main>'
  const shell = createEditorShell(document.querySelector('#app')!, 'full', 'xlsx')
  const context = { context: { ...identity, format: 'xlsx', sourceFile: { sha256: identity.sourceSha256 } }, editingEnabled }
  const transport = createNativeOfficeTransport({ api: { save } as never, context: context as never, draft })
  const view = await createWorkbookEditorView(shell, { native: true, draft, request: transport.workbook,
    file: async () => ({ bytes: source.slice().buffer as ArrayBuffer, sha256: identity.sourceSha256 }) })
  return { shell, view }
}
const sheet = () => grid.api.getActiveWorkbook().getActiveSheet()
it('rejects stale header/footer targets and protected or read-only editing without creating a draft', async () => {
  const source = await fixture(), draft = new NativeDraft(identity, store()), current = await open(source, draft, async () => ({}))
  try {
    grid.ribbon('header-footer-open')
    const actual = grid.api.getActiveWorkbook.bind(grid.api), book = actual()
    grid.api.getActiveWorkbook = () => new Proxy(book, { get: (target, key) => key === 'getWorkbook' ? () => ({}) : Reflect.get(target, key, target) })
    document.querySelector<HTMLTextAreaElement>('[data-header-footer-field=header-left]')!.value = 'stale'
    document.querySelector('.workbook-header-footer-dialog form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    expect(document.querySelector('.workbook-header-footer-dialog [role=alert]')!.textContent).toMatch(/变化/)
    expect(draft.operations).toEqual([])
    grid.api.getActiveWorkbook = actual
  } finally { current.view?.dispose() }
  for (const protectedSheet of [false, true]) {
    const protectedSource = protectedSheet ? await protectSheet(source, 'Sheet1', true) : source
    const empty = new NativeDraft(identity, store()), opened = await open(protectedSource, empty, async () => ({}), protectedSheet)
    try {
      if (!protectedSheet) opened.shell.editor.inert = true
      grid.ribbon('header-footer-open')
      expect(document.querySelector<HTMLElement>('.workbook-header-footer-overlay')!.hidden).toBe(true)
      grid.ribbon('refresh-all')
      await vi.waitFor(() => expect(empty.operations).toEqual([]))
      expect(sheet().getRange('A1').getValue()).toBe(2)
    } finally { opened.view?.dispose() }
  }
})
it('refreshes visible pivot output from manual draft with native undo, redo and save', async () => {
  const rows = [['区域', '收入'], ['东', 10], ['东', 20], ['西', 30]]
  const base = await applyCellEdits(await createBlankWorkbook(), rows.flatMap((row, r) => row.map((value, c) => ({ sheetName: 'Sheet1', row: r, column: c, writeValue: true, cell: { value } }))))
  const source = await applyWorkbookOperations(base, (await createPivotPlan(base, { name: '分析', sourceSheetName: 'Sheet1', sourceRange: 'A1:B4', targetSheetName: 'Sheet1', targetCell: 'E1', rowFields: ['区域'], columnFields: [], values: [{ field: '收入', agg: 'sum' }] })).operations)
  const draft = new NativeDraft(identity, store()); let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/refresh.xlsx' } }, validation: { issues: [] } }
  })
  try {
    sheet().getRange('B2').setValue(90); sheet().getRange('K1').setValue('manual note')
    grid.ribbon('refresh-all')
    await vi.waitFor(() => expect(sheet().getRange('F4').getValue()).toBe(140))
    expect(sheet().getRange('K1').getValue()).toBe('manual note')
    grid.ribbon('undo')
    await vi.waitFor(() => expect(sheet().getRange('F4').getValue()).toBe(60))
    expect(sheet().getRange('B2').getValue()).toBe(90)
    grid.ribbon('redo')
    await vi.waitFor(() => expect(sheet().getRange('F4').getValue()).toBe(140))
    current.shell.save.click()
    await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toContain('已保存修订 2'))
    expect((await readWorkbook(downloaded!)).sheets[0]?.cells.F4?.value).toBe(140)
  } finally { current.view?.dispose() }
})
it('edits header/footer through main, restores the draft and preserves manual cells', async () => {
  const source = await applyPageSetups(await fixture(), [{ sheetName: 'Sheet1', header: { left: 'Old', center: '&P' }, footer: { right: '&N' } }])
  const storage = store(), draft = new NativeDraft(identity, storage)
  let downloaded: Uint8Array | undefined
  const save = async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/header.xlsx' } }, validation: { issues: [] } }
  }
  const current = await open(source, draft, save)
  try {
    sheet().getRange('A1').setValue('manual draft')
    grid.ribbon('header-footer-open')
    const input = document.querySelector<HTMLTextAreaElement>('[data-header-footer-field="header-left"]')
    expect(input).not.toBeNull(); expect(input!.value).toBe('Old')
    input!.value = 'New && literal'
    document.querySelector<HTMLFormElement>('.workbook-header-footer-dialog form')!.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }))
    await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyPageSetups')).toBe(true))
    const page = draft.operations.find(op => op.kind === 'applyPageSetups') as any
    expect(page.setups).toEqual([{ sheetName: 'Sheet1', header: { left: 'New && literal', center: '&P', right: '' } }])
  } finally { current.view?.dispose() }
  const restored = await open(source, new NativeDraft(identity, storage), save)
  try {
    grid.ribbon('header-footer-open')
    expect(document.querySelector<HTMLTextAreaElement>('[data-header-footer-field="header-left"]')!.value).toBe('New && literal')
    document.querySelector<HTMLButtonElement>('[data-header-footer-cancel]')!.click()
    restored.shell.save.click()
    await vi.waitFor(() => expect(restored.shell.statusLabel.textContent).toContain('已保存修订 2'))
    const model = await readWorkbook(downloaded!)
    expect(model.sheets[0]?.cells.A1?.value).toBe('manual draft')
    expect(model.sheets[0]?.headerFooter).toMatchObject({ oddHeader: '&LNew && literal&C&P', oddFooter: '&R&N' })
  } finally { restored.view?.dispose() }
})
it('opens real source queries through main and navigates without changing manual draft or history', async () => {
  const source = await fixture(), ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
  const parts = new Map([['xl/connections.xml', `<connections xmlns="${ns}"><connection id="1" name="Imported"><textPr sourceFile="C:/private/data.csv"/></connection></connections>`], ['xl/worksheets/_rels/sheet1.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="q" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/queryTable" Target="../queryTables/queryTable1.xml"/></Relationships>'], ['xl/queryTables/queryTable1.xml', `<queryTable xmlns="${ns}" name="Target" connectionId="1"/>`]])
  const bytes = (await assemblePackage(source, { replaced: parts, added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [] })).buffer
  const storage = store(), draft = new NativeDraft(identity, storage), save = vi.fn()
  const current = await open(bytes, draft, save)
  try {
    sheet().getRange('A1').setValue('manual query draft')
    const before = grid.api.getActiveWorkbook().save()
    grid.ribbon('queries-open')
    await vi.waitFor(() => expect(document.querySelectorAll('[data-query-entry]')).toHaveLength(1))
    expect(document.querySelector('.workbook-queries-dialog')?.textContent).toContain('data.csv')
    document.querySelector<HTMLButtonElement>('[data-query-entry="0"]')!.click()
    await vi.waitFor(() => expect(grid.api.getActiveWorkbook().getActiveRange().getA1Notation()).toBe('C3:D4'))
    expect(grid.api.getActiveWorkbook().save().sheets).toEqual(before.sheets)
    expect(sheet().getRange('A1').getValue()).toBe('manual query draft'); expect(save).not.toHaveBeenCalled()
    await grid.api.undo(); expect(sheet().getRange('A1').getValue()).toBe(2)
  } finally { current.view?.dispose() }
})
it('imports CSV through the main command and preserves manual draft through undo, restore and native save', async () => {
  const source = await fixture(), storage = store(), draft = new NativeDraft(identity, storage)
  let downloaded: Uint8Array | undefined
  const save = async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/csv.xlsx' } }, validation: { issues: [] } }
  }
  const current = await open(source, draft, save)
  try {
    sheet().getRange('A1').setValue('manual draft')
    sheet().getRange('C5').setFontWeight('bold')
    sheet().getRange('C5').activate()
    grid.ribbon('import-csv')
    const input = document.querySelector<HTMLInputElement>('input[type=file]')
    expect(input).not.toBeNull()
    Object.defineProperty(input!, 'files', { value: [{ size: 40, arrayBuffer: async () => new TextEncoder().encode('名称,金额,公式\n中文,12.5,=1+1').buffer }] })
    input!.dispatchEvent(new Event('change'))
    await vi.waitFor(() => expect(sheet().getRange('C5:E6').getValues()).toEqual([['名称','金额','公式'],['中文',12.5,'=1+1']]))
    expect(sheet().getRange('E6').getFormula()).toBe('')
    expect(sheet().getRange('C5').getCellStyleData()?.bl).toBe(1)
    await grid.api.undo(); expect(sheet().getRange('C5').getValue()).toBeNull(); expect(sheet().getRange('A1').getValue()).toBe('manual draft')
    await grid.api.redo()
    await vi.waitFor(() => expect(draft.operations.length, current.shell.editor.querySelector('.workbook-feedback')?.textContent ?? '').toBeGreaterThan(0))
  } finally { current.view?.dispose() }
  const restored = await open(source, new NativeDraft(identity, storage), save)
  try {
    expect(sheet().getRange('E6').getValue()).toBe('=1+1')
    restored.shell.save.click()
    await vi.waitFor(() => expect(restored.shell.statusLabel.textContent).toContain('已保存修订 2'))
    const model = await readWorkbook(downloaded!)
    expect(model.sheets[0]?.cells.A1?.value).toBe('manual draft')
    expect(model.sheets[0]?.cells.D6?.value).toBe(12.5)
    expect(model.sheets[0]?.cells.E6?.value).toBe('=1+1')
    expect(model.sheets[0]?.cells.E6?.formula).toBeUndefined()
  } finally { restored.view?.dispose() }
})

it('disposes a pending CSV read before it can mutate the closed editor', async () => {
  const current = await open(await fixture(), new NativeDraft(identity, store()), async () => ({}))
  let finish!: (value: ArrayBuffer) => void
  try {
    sheet().getRange('C5').activate(); grid.ribbon('import-csv')
    const input = document.querySelector<HTMLInputElement>('input[type=file]')
    expect(input).not.toBeNull()
    Object.defineProperty(input!, 'files', { value: [{ size: 3, arrayBuffer: () => new Promise<ArrayBuffer>(resolve => { finish = resolve }) }] })
    input!.dispatchEvent(new Event('change'))
    current.view?.dispose()
    expect(input!.isConnected).toBe(false)
    finish(new TextEncoder().encode('x,y').buffer as ArrayBuffer)
    await Promise.resolve(); await Promise.resolve()
  } finally { current.view?.dispose() }
})
it('rejects header rename before changing cells when a protected sheet consumes the column', async () => {
  let source = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Name' } },
  ])
  source = await applyTableAdditions(source, [{ worksheetSheetName: 'Sheet1', name: 'Staff',
    area: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 }, columnNames: ['Name'], bandedRows: true }])
  source = await applyWorkbookOperations(source, [
    { kind: 'applySheetEdits', plan: { renames: [], additions: [{ name: 'Locked' }], removals: [], order: ['Sheet1', 'Locked'] } },
    { kind: 'applyCellEdits', edits: [{ sheetName: 'Locked', row: 0, column: 0, writeValue: true, cell: { value: null, formula: 'SUM(Staff[Name])' } }] },
    { kind: 'protectSheet', sheetName: 'Locked', protect: true },
  ])
  const current = await open(source, new NativeDraft(identity, store()), async () => ({}))
  sheet().getRange(0, 0).setValue('Employee')
  expect(sheet().getRange(0, 0).getValue()).toBe('Name')
  expect(grid.api.getActiveWorkbook().getTableList()[0].columns[0].displayName).toBe('Name')
  expect(current.shell.editor.querySelector('.workbook-feedback')?.textContent).toContain('受保护')
  current.view?.dispose()
})
it.each([['', 'Column1'], ['Qty', 'Qty'], ['  Employee  ', 'Employee']])('normalizes table header %j with matching cell and metadata', async (input, expected) => {
  let source = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Name' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 'Qty' } },
  ])
  source = await applyTableAdditions(source, [{ worksheetSheetName: 'Sheet1', name: 'Staff',
    area: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 1 }, columnNames: ['Name', 'Qty'], bandedRows: true }])
  const current = await open(source, new NativeDraft(identity, store()), async () => ({}))
  sheet().getRange(0, 0).setValue(input)
  expect(sheet().getRange(0, 0).getValue()).toBe(expected)
  const names = () => grid.api.getActiveWorkbook().getTableList()[0].columns.map((column: any) => column.displayName)
  expect(names()).toEqual([expected, input === 'Qty' ? 'Qty2' : 'Qty'])
  expect(sheet().getRange(0, 1).getValue()).toBe(input === 'Qty' ? 'Qty2' : 'Qty')
  await grid.api.undo()
  expect(names()).toEqual(['Name', 'Qty'])
  expect(sheet().getRange(0, 1).getValue()).toBe('Qty')
  await grid.api.redo()
  expect(names()).toEqual([expected, input === 'Qty' ? 'Qty2' : 'Qty'])
  current.view?.dispose()
})
it('keeps table column names in sync with edited headers through undo, draft restore and save', async () => {
  let source = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Name' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 'Qty' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'Ada' } },
  ])
  source = await applyTableAdditions(source, [{ worksheetSheetName: 'Sheet1', name: 'Staff',
    area: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 1 }, columnNames: ['Name', 'Qty'], bandedRows: true }])
  const storage = store(), draft = new NativeDraft(identity, storage)
  source = await applyWorkbookOperations(source, [{ kind: 'replaceSheetDataValidations', sheetName: 'Sheet1', rules: [
    { ranges: [{ startRow: 0, endRow: 2, startColumn: 3, endColumn: 3 }], rule: { type: 'list', formula1: '=Staff[Name]' } },
  ] }, { kind: 'applyDefinedNames', plan: { sets: [{ name: 'Employees', refersTo: 'Staff[[Name]]' }] } },
  { kind: 'applyCellEdits', edits: [{ sheetName: 'Sheet1', row: 4, column: 0, writeValue: true, cell: { value: null, formula: 'SUM(Staff[Name])' } }] }])
  let downloaded: Uint8Array | undefined
  const save = async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/f.xlsx' } }, validation: { issues: [] } }
  }
  const current = await open(source, draft, save)
  sheet().getRange(0, 0).clearContent()
  expect(sheet().getRange(0, 0).getValue()).toBe('Column1')
  expect(grid.api.getActiveWorkbook().getTableList()[0].columns[0].displayName).toBe('Column1')
  await grid.api.undo()
  expect(sheet().getRange(0, 0).getValue()).toBe('Name')
  sheet().getRange(4, 0).setFormula('=SUM(Staff[Name])+1')
  sheet().getRange(0, 0, 5, 2).setValues([[{ v: 'Employee' }, { v: 'Qty' }], [{ v: 'Ada' }, null], [null, null], [null, null], [{ f: '=SUM(Staff[Name])+2' }, null]])
  await grid.api.undo()
  expect(sheet().getRange(4, 0).getFormula()).toBe('=SUM(Staff[Name])+1')
  await grid.api.undo()
  sheet().getRange(0, 0).setValue('Employee')
  expect(grid.api.getActiveWorkbook().getTableList()[0].columns[0].displayName).toBe('Employee')
  const { ISuperTableService } = await import('@univerjs/engine-formula')
  const registered = () => grid.instances.at(-1).__getInjector().get(ISuperTableService).getTable(grid.api.getActiveWorkbook().getId(), 'Staff')
  expect(registered().titleMap.get('Employee')).toBe(0)
  expect(registered().titleMap.has('Name')).toBe(false)
  expect(sheet().getDataValidations()[0].rule.formula1).toBe('=Staff[Employee]')
  expect(grid.api.getActiveWorkbook().getDefinedNames()[0].getFormulaOrRefString()).toBe('Staff[[Employee]]')
  expect(sheet().getRange(4, 0).getFormula()).toBe('=SUM(Staff[Employee])')
  await grid.api.undo()
  expect(grid.api.getActiveWorkbook().getTableList()[0].columns[0].displayName).toBe('Name')
  expect(registered().titleMap.get('Name')).toBe(0)
  expect(sheet().getDataValidations()[0].rule.formula1).toBe('=Staff[Name]')
  await grid.api.redo()
  expect(grid.api.getActiveWorkbook().getTableList()[0].columns[0].displayName).toBe('Employee')
  await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyTableEdits')).toBe(true))
  current.view?.dispose()
  const restored = await open(source, new NativeDraft(identity, storage), save)
  expect(grid.api.getActiveWorkbook().getTableList()[0].columns[0].displayName).toBe('Employee')
  restored.shell.save.click()
  await vi.waitFor(() => expect(restored.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const model = await readWorkbook(downloaded!)
  expect(model.sheets[0]?.tables?.[0]?.columns.map(column => column.name)).toEqual(['Employee', 'Qty'])
  expect(model.sheets[0]?.cells.A1?.value).toBe('Employee')
  expect(model.sheets[0]?.dataValidations?.rules[0]?.rule.formula1).toBe('=Staff[Employee]')
  expect(model.definedNames?.find(name => name.name === 'Employees')?.refersTo).toBe('Staff[[Employee]]')
  expect(model.sheets[0]?.cells.A5?.formula).toBe('=SUM(Staff[Employee])')
  restored.view?.dispose()
})
it.each([[0, 0, ['Ada', 'Grace', 'Total']], [1, 1, ['Grace']], [1, 0, ['Grace', 'Total']]])('excludes exactly the declared header and totals rows (%i/%i)', async (header, totals, expected) => {
  let source = await applyCellEdits(await createBlankWorkbook(), ['Ada', 'Grace', 'Total'].map((value, row) =>
    ({ sheetName: 'Sheet1', row, column: 0, writeValue: true, cell: { value } })))
  source = await applyTableAdditions(source, [{ worksheetSheetName: 'Sheet1', name: 'Staff',
    area: { startRow: 0, startColumn: 0, endRow: 2, endColumn: 1 }, columnNames: ['Name', 'Qty'], bandedRows: true }])
  const { assemblePackage, createBufferEntrySource } = await import('../../../reporting/workbook_engine/packages/xlsx-engine/src/zip')
  const path = 'xl/tables/table1.xml', zip = await createBufferEntrySource(source)
  const xml = (await zip.readText(path)).replace('totalsRowShown="0"', `headerRowCount="${header}" totalsRowCount="${totals}" totalsRowShown="${totals}"`)
  source = (await assemblePackage(source, { replaced: new Map([[path, xml]]), added: new Map(), addedBinary: new Map(),
    removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
  source = await applyWorkbookOperations(source, [{ kind: 'replaceSheetDataValidations', sheetName: 'Sheet1', rules: [
    { ranges: [{ startRow: 0, endRow: 2, startColumn: 2, endColumn: 2 }], rule: { type: 'list', formula1: '=staff[[NAME]]' } },
  ] }])
  const draft = new NativeDraft(identity, store())
  const current = await open(source, draft, async () => ({}))
  const { DataValidatorRegistryService } = await import('@univerjs/data-validation')
  const validator = grid.instances.at(-1).__getInjector().get(DataValidatorRegistryService).getValidatorItem('list')
  await vi.waitFor(() => expect(validator.getList(sheet().getDataValidations()[0].rule, grid.api.getActiveWorkbook().getId(), sheet().getSheetId())).toEqual(expected))
  sheet().insertColumns(1, 1)
  expect(grid.api.getActiveWorkbook().getTableList()[0].columns.map((item: any) => item.displayName)).toEqual(['Name', 'Column1', 'Qty'])
  if (header) expect(sheet().getRange(0, 1).getValue()).toBe('Column1')
  await grid.api.undo(); await grid.api.redo()
  expect(grid.api.getActiveWorkbook().getTableList()[0].columns.map((item: any) => item.displayName)).toEqual(['Name', 'Column1', 'Qty'])
  await grid.api.undo()
  const before = structuredClone(grid.api.getActiveWorkbook().getSnapshot()), tables = structuredClone(grid.api.getActiveWorkbook().getTableList())
  const undo = grid.instances.at(-1).__getInjector().get(IUndoRedoService)
  const historyBefore = undo.pitchTopUndoElement()
  const indices = header ? (totals ? [0, 1, 2] : [0]) : [0]
  for (const startRow of indices) {
    const endRow = header ? startRow : 2
    expect(await grid.api.executeCommand('sheet.command.remove-row', { unitId: grid.api.getActiveWorkbook().getId(), subUnitId: sheet().getSheetId(),
      range: { startRow, endRow, startColumn: 0, endColumn: 9 } })).toBe(false)
    expect(structuredClone(grid.api.getActiveWorkbook().getSnapshot())).toEqual(before)
    expect(grid.api.getActiveWorkbook().getTableList()).toEqual(tables)
    expect(undo.pitchTopUndoElement()).toEqual(historyBefore)
    expect(draft.operations).toEqual([])
  }
  expect(await grid.api.executeCommand('sheet.command.remove-col', { unitId: grid.api.getActiveWorkbook().getId(), subUnitId: sheet().getSheetId(),
    range: { startRow: 0, endRow: 9, startColumn: 1, endColumn: 1 } })).toBe(true)
  await grid.api.undo()
  expect(grid.api.getActiveWorkbook().getTableList()[0].meta?.nativeTotalsRowCount).toBe(totals)
  await vi.waitFor(() => expect(validator.getList(sheet().getDataValidations()[0].rule, grid.api.getActiveWorkbook().getId(), sheet().getSheetId())).toEqual(expected))
  if (header && !totals) {
    expect(await grid.api.executeCommand('sheet.command.remove-row', { unitId: grid.api.getActiveWorkbook().getId(), subUnitId: sheet().getSheetId(),
      range: { startRow: 2, endRow: 4, startColumn: 0, endColumn: 9 } })).toBe(true)
    expect(grid.api.getActiveWorkbook().getTableList()[0].range.endRow).toBe(1)
    await vi.waitFor(() => expect(validator.getList(sheet().getDataValidations()[0].rule, grid.api.getActiveWorkbook().getId(), sheet().getSheetId())).toEqual(['Grace']))
    await grid.api.undo(); await grid.api.redo()
    expect(grid.api.getActiveWorkbook().getTableList()[0].range.endRow).toBe(1)
  }
  current.view?.dispose()
})

it('loads actual table list sources without replacing structured source identities', async () => {
  let source = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Name' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'Ada' } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: 'Grace' } },
  ])
  source = await applyTableAdditions(source, [{ worksheetSheetName: 'Sheet1', name: 'Staff',
    area: { startRow: 0, startColumn: 0, endRow: 2, endColumn: 0 }, columnNames: ['Name'], bandedRows: true }])
  source = await applyDefinedNames(source, { sets: [{ name: 'Choices', refersTo: 'staff[[NAME]]' }] })
  source = await applyWorkbookOperations(source, [{ kind: 'replaceSheetDataValidations', sheetName: 'Sheet1', rules: [
    { ranges: [{ startRow: 0, endRow: 2, startColumn: 2, endColumn: 2 }], rule: { type: 'list', formula1: '=Staff[Name]' } },
    { ranges: [{ startRow: 0, endRow: 2, startColumn: 3, endColumn: 3 }], rule: { type: 'list', formula1: '=Choices' } },
  ] }])
  const storage = store(), draft = new NativeDraft(identity, storage)
  let downloaded: Uint8Array | undefined
  const save = async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/f.xlsx' } }, validation: { issues: [] } }
  }
  const current = await open(source, draft, save)
  expect(grid.api.getActiveWorkbook().getTableList()).toMatchObject([{ name: 'Staff', range: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 } }])
  const { DataValidatorRegistryService } = await import('@univerjs/data-validation')
  const validator = grid.instances.at(-1).__getInjector().get(DataValidatorRegistryService).getValidatorItem('list')
  for (const { rule } of sheet().getDataValidations()) {
    expect(validator.validatorFormula(rule, grid.api.getActiveWorkbook().getId(), sheet().getSheetId()).success).toBe(true)
    await vi.waitFor(() => expect(validator.getList(rule, grid.api.getActiveWorkbook().getId(), sheet().getSheetId())).toEqual(['Ada', 'Grace']))
  }
  expect(sheet().getDataValidations().map((item: any) => item.rule.formula1)).toEqual(['=Staff[Name]', '=Choices'])
  const { SheetRangeThemeModel } = await import('@univerjs/sheets')
  const themes = grid.instances.at(-1).__getInjector().get(SheetRangeThemeModel)
  expect(themes.getCellStyle(grid.api.getActiveWorkbook().getId(), sheet().getSheetId(), 0, 0)).toMatchObject({ bg: { rgb: '#4472C4' }, cl: { rgb: '#FFFFFF' } })
  expect(themes.getCellStyle(grid.api.getActiveWorkbook().getId(), sheet().getSheetId(), 1, 0)).toMatchObject({ bg: { rgb: '#DAE3F3' } })
  expect(draft.operations).toEqual([])
  const tableId = grid.api.getActiveWorkbook().getTableList()[0].id
  expect(grid.api.syncExecuteCommand('sheet.command.set-table-config', { unitId: grid.api.getActiveWorkbook().getId(), tableId, config: { name: 'Unsaved' } })).toBe(false)
  expect(grid.api.getActiveWorkbook().getTableList()[0].name).toBe('Staff')
  expect(grid.api.syncExecuteCommand('sheet.mutation.set-sheet-table', { unitId: grid.api.getActiveWorkbook().getId(), tableId, config: { name: 'Unsaved' } })).toBe(false)
  expect(grid.api.getActiveWorkbook().getTableList()[0].name).toBe('Staff')
  const rule = sheet().getDataValidations()[0].rule
  expect(grid.api.syncExecuteCommand('sheets.command.update-data-validation-options', { unitId: grid.api.getActiveWorkbook().getId(), subUnitId: sheet().getSheetId(), ruleId: rule.uid, options: { prompt: '选择姓名' } })).toBe(true)
  sheet().insertRows(0, 1)
  await vi.waitFor(() => expect(validator.getList(sheet().getDataValidations()[0].rule, grid.api.getActiveWorkbook().getId(), sheet().getSheetId())).toEqual(['Ada', 'Grace']))
  expect(sheet().getDataValidations()[0].rule.formula1).toBe('=Staff[Name]')
  history('undo'); history('redo')
  sheet().insertRows(3, 1)
  sheet().getRange(3, 0).setValue('Hopper')
  await vi.waitFor(() => expect(validator.getList(sheet().getDataValidations()[0].rule, grid.api.getActiveWorkbook().getId(), sheet().getSheetId())).toEqual(['Ada', 'Hopper', 'Grace']))
  history('undo'); history('undo')
  await vi.waitFor(() => expect(validator.getList(sheet().getDataValidations()[0].rule, grid.api.getActiveWorkbook().getId(), sheet().getSheetId())).toEqual(['Ada', 'Grace']))
  sheet().setName('Renamed')
  await vi.waitFor(() => expect(validator.getList(sheet().getDataValidations()[0].rule, grid.api.getActiveWorkbook().getId(), sheet().getSheetId())).toEqual(['Ada', 'Grace']))
  await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applySheetEdits')).toBe(true))
  current.view?.dispose()
  const restored = await open(source, new NativeDraft(identity, storage), save)
  expect(sheet().getDataValidations()[0].rule.formula1).toBe('=Staff[Name]')
  restored.shell.save.click()
  await vi.waitFor(() => expect(restored.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const model = await readWorkbook(downloaded!)
  expect(model.sheets[0]?.tables?.[0]?.range).toEqual({ startRow: 1, endRow: 3, startColumn: 0, endColumn: 0 })
  expect(model.sheets[0]?.dataValidations?.rules[0]?.rule.formula1).toBe('=Staff[Name]')
  expect(model.definedNames).toContainEqual({ name: 'Choices', refersTo: 'staff[[NAME]]' })
  restored.view?.dispose()
})
it('loads validation rules and persists official edits through undo, draft restore and save', async () => {
  const ranges = [{ startRow: 1, endRow: 4, startColumn: 1, endColumn: 1 }]
  const source = await applyWorkbookOperations(await createBlankWorkbook(), [{ kind: 'replaceSheetDataValidations', sheetName: 'Sheet1', rules: [{ ranges, rule: { type: 'whole', operator: 'greaterThan', formula1: '0' } }] }])
  const storage = store(), draft = new NativeDraft(identity, storage)
  let downloaded: Uint8Array | undefined
  const save = async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/f.xlsx' } }, validation: { issues: [] } }
  }
  const current = await open(source, draft, save)
  expect(sheet().getDataValidations()).toHaveLength(1)
  const uid = sheet().getDataValidations()[0].rule.uid
  expect(grid.api.syncExecuteCommand('sheets.command.update-data-validation-options', { unitId: grid.api.getActiveWorkbook().getId(), subUnitId: sheet().getSheetId(), ruleId: uid, options: { showErrorMessage: true, errorTitle: '数量', error: '填写正整数' } })).toBe(true)
  await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'replaceSheetDataValidations')).toBe(true))
  await grid.api.undo()
  await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'replaceSheetDataValidations')).toBe(false))
  await grid.api.redo()
  await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'replaceSheetDataValidations')).toBe(true))
  current.view?.dispose()
  const restored = await open(source, new NativeDraft(identity, storage), save)
  expect(sheet().getDataValidations()[0].rule.error).toBe('填写正整数')
  restored.shell.save.click()
  await vi.waitFor(() => expect(restored.shell.statusLabel.textContent).toContain('已保存修订 2'))
  expect((await readWorkbook(downloaded!)).sheets[0]?.dataValidations?.rules[0]?.rule.error).toBe('填写正整数')
  restored.view?.dispose()
})
it('retains editable validation rules after deleting a complete rule and restoring the combined draft', async () => {
  const rules = [0, 1].map(row => ({ ranges: [{ startRow: row, endRow: row, startColumn: 0, endColumn: 0 }], rule: { type: 'whole', operator: 'greaterThan', formula1: '0' } }))
  const source = await applyWorkbookOperations(await createBlankWorkbook(), [{ kind: 'replaceSheetDataValidations', sheetName: 'Sheet1', rules }])
  const storage = store(), draft = new NativeDraft(identity, storage)
  let downloaded: Uint8Array | undefined
  const save = async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/f.xlsx' } }, validation: { issues: [] } }
  }
  const current = await open(source, draft, save)
  sheet().deleteRows(0, 1)
  await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyRowColumnOps')).toBe(true))
  expect(sheet().getDataValidations()).toHaveLength(1)
  const uid = sheet().getDataValidations()[0].rule.uid
  expect(grid.api.syncExecuteCommand('sheets.command.update-data-validation-options', { unitId: grid.api.getActiveWorkbook().getId(), subUnitId: sheet().getSheetId(), ruleId: uid, options: { showErrorMessage: true, error: '剩余规则' } })).toBe(true)
  await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'replaceSheetDataValidations')).toBe(true))
  await grid.api.undo()
  await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'replaceSheetDataValidations')).toBe(false))
  await grid.api.redo()
  await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'replaceSheetDataValidations')).toBe(true))
  current.view?.dispose()
  const restored = await open(source, new NativeDraft(identity, storage), save)
  expect(sheet().getDataValidations()[0].rule.error).toBe('剩余规则')
  restored.shell.save.click()
  await vi.waitFor(() => expect(restored.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const result = (await readWorkbook(downloaded!)).sheets[0]!.dataValidations!
  expect(result.readOnlyReason).toBeUndefined()
  expect(result.rules).toHaveLength(1)
  expect(result.rules[0]?.rule.error).toBe('剩余规则')
  restored.view?.dispose()
})
it('migrates cross-sheet validation formulas with structure and rename through undo and draft restore', async () => {
  let source = await applyWorkbookOperations(await createBlankWorkbook(), [{ kind: 'applySheetEdits', plan: { renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'] } }])
  source = await applyWorkbookOperations(source, [{ kind: 'replaceSheetDataValidations', sheetName: 'Sheet1', rules: [{ ranges: [{ startRow: 1, endRow: 3, startColumn: 1, endColumn: 1 }], rule: { type: 'list', formula1: '=Other!$A$1:$A$3' } }] }])
  const storage = store(), draft = new NativeDraft(identity, storage)
  let downloaded: Uint8Array | undefined
  const save = async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/f.xlsx' } }, validation: { issues: [] } }
  }
  const current = await open(source, draft, save)
  const workbook = grid.api.getActiveWorkbook()
  const rule = () => workbook.getSheetByName('Sheet1').getDataValidations()[0].rule
  workbook.setActiveSheet(workbook.getSheetByName('Other'))
  sheet().insertRowsBefore(0, 1)
  expect(rule().formula1).toBe('=Other!$A$2:$A$4')
  await grid.api.undo()
  expect(rule().formula1).toBe('=Other!$A$1:$A$3')
  await grid.api.redo()
  expect(rule().formula1).toBe('=Other!$A$2:$A$4')
  sheet().setName('Renamed')
  expect(rule().formula1).toBe('=Renamed!$A$2:$A$4')
  await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applySheetEdits')).toBe(true))
  current.view?.dispose()
  const restored = await open(source, new NativeDraft(identity, storage), save)
  expect(grid.api.getActiveWorkbook().getSheetByName('Sheet1').getDataValidations()[0].rule.formula1).toBe('=Renamed!$A$2:$A$4')
  restored.shell.save.click()
  await vi.waitFor(() => expect(restored.shell.statusLabel.textContent).toContain('已保存修订 2'))
  expect((await readWorkbook(downloaded!)).sheets[0]?.dataValidations?.rules[0]?.rule.formula1).toBe('=Renamed!$A$2:$A$4')
  restored.view?.dispose()
})
it('migrates validation references on protected sheets atomically and keeps direct edits blocked', async () => {
  let source = await applyWorkbookOperations(await createBlankWorkbook(), [{ kind: 'applySheetEdits', plan: { renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'] } }])
  source = await applyWorkbookOperations(source, [
    { kind: 'replaceSheetDataValidations', sheetName: 'Sheet1', rules: [{ ranges: [{ startRow: 1, endRow: 3, startColumn: 1, endColumn: 1 }], rule: { type: 'list', formula1: '=Other!$A$1:$A$3' } }] },
    { kind: 'protectSheet', sheetName: 'Sheet1', protect: true },
  ])
  const storage = store(), draft = new NativeDraft(identity, storage)
  let downloaded: Uint8Array | undefined
  const save = async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/f.xlsx' } }, validation: { issues: [] } }
  }
  const current = await open(source, draft, save)
  const workbook = grid.api.getActiveWorkbook(), protectedSheet = workbook.getSheetByName('Sheet1')
  const rule = () => protectedSheet.getDataValidations()[0].rule
  expect(grid.api.syncExecuteCommand('sheets.command.update-data-validation-options', { unitId: workbook.getId(), subUnitId: protectedSheet.getSheetId(), ruleId: rule().uid, options: { error: 'forbidden' } })).toBe(false)
  workbook.setActiveSheet(workbook.getSheetByName('Other'))
  const rows = sheet().getMaxRows()
  sheet().insertRowsBefore(0, 1)
  expect(sheet().getMaxRows()).toBe(rows + 1)
  expect(rule().formula1).toBe('=Other!$A$2:$A$4')
  await grid.api.undo()
  expect(sheet().getMaxRows()).toBe(rows)
  expect(rule().formula1).toBe('=Other!$A$1:$A$3')
  await grid.api.redo()
  expect(rule().formula1).toBe('=Other!$A$2:$A$4')
  await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyRowColumnOps')).toBe(true))
  expect(draft.operations.some(op => op.kind === 'replaceSheetDataValidations')).toBe(false)
  current.view?.dispose()
  const restored = await open(source, new NativeDraft(identity, storage), save)
  expect(grid.api.getActiveWorkbook().getSheetByName('Sheet1').getDataValidations()[0].rule.formula1).toBe('=Other!$A$2:$A$4')
  restored.shell.save.click()
  await vi.waitFor(() => expect(restored.shell.statusLabel.textContent).toContain('已保存修订 2'))
  expect((await readWorkbook(downloaded!)).sheets[0]?.dataValidations?.rules[0]?.rule.formula1).toBe('=Other!$A$2:$A$4')
  restored.view?.dispose()
})
it('rejects a validation follower budget failure before changing rows or undo history', async () => {
  const source = await applyWorkbookOperations(await createBlankWorkbook(), [{ kind: 'replaceSheetDataValidations', sheetName: 'Sheet1', rules: [{ ranges: [{ startRow: 1, endRow: 3, startColumn: 1, endColumn: 1 }], rule: { type: 'whole', operator: 'greaterThan', formula1: '=A2' } }] }])
  const draft = new NativeDraft(identity, store())
  const current = await open(source, draft, async () => ({}))
  const rows = sheet().getMaxRows(), formula = sheet().getDataValidations()[0].rule.formula1
  const validate = vi.spyOn(validationAdapter, 'validateDataValidationEdit').mockImplementation(() => { throw new Error('数据验证超出本地草稿预算，请先保存当前修改') })
  try {
    expect(grid.api.syncExecuteCommand('sheet.command.insert-row-by-range', { unitId: grid.api.getActiveWorkbook().getId(), subUnitId: sheet().getSheetId(), range: { startRow: 0, endRow: 0, startColumn: 0, endColumn: 9 }, direction: 0 })).toBe(false)
    expect(validate).toHaveBeenCalled()
    expect(sheet().getMaxRows()).toBe(rows)
    expect(sheet().getDataValidations()[0].rule.formula1).toBe(formula)
    expect(grid.instances.at(-1).__getInjector().get(IUndoRedoService).pitchTopUndoElement()).toBeNull()
    expect(draft.operations).toEqual([])
  } finally { validate.mockRestore(); current.view?.dispose() }
})
it('accepts a defined-name validation list without replacing its source identity', async () => {
  let source = await applyDefinedNames(await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Ada' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'Grace' } },
  ]), { sets: [{ name: 'Choices', refersTo: 'Alias' }, { name: 'Alias', refersTo: 'Sheet1!$A$1:$A$2' }] })
  source = await applyWorkbookOperations(source, [{ kind: 'replaceSheetDataValidations', sheetName: 'Sheet1', rules: [{ ranges: [{ startRow: 0, endRow: 2, startColumn: 2, endColumn: 2 }], rule: { type: 'list', formula1: '=Choices' } }] }])
  source = await applyWorkbookOperations(source, [{ kind: 'replaceSheetDataValidations', sheetName: 'Sheet1', rules: [{ ranges: [{ startRow: 0, endRow: 2, startColumn: 2, endColumn: 2 }], rule: { type: 'list', formula1: '=Choices' } }, { ranges: [{ startRow: 0, endRow: 0, startColumn: 3, endColumn: 3 }], rule: { type: 'list', formula1: '=A1' } }] }])
  let downloaded: Uint8Array | undefined
  const storage = store(), draft = new NativeDraft(identity, storage)
  const save = async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/f.xlsx' } }, validation: { issues: [] } }
  }
  const current = await open(source, draft, save)
  const { DataValidatorRegistryService } = await import('@univerjs/data-validation')
  const validator = grid.instances.at(-1).__getInjector().get(DataValidatorRegistryService).getValidatorItem('list')
  const cellRule = sheet().getDataValidations()[1].rule
  expect(validator.validatorFormula(cellRule, grid.api.getActiveWorkbook().getId(), sheet().getSheetId()).success).toBe(true)
  await vi.waitFor(() => expect(validator.getList(cellRule, grid.api.getActiveWorkbook().getId(), sheet().getSheetId())).toEqual(['Ada']))
  const rule = sheet().getDataValidations()[0].rule
  expect(validator.validatorFormula(rule, grid.api.getActiveWorkbook().getId(), sheet().getSheetId()).success).toBe(true)
  expect(rule.formula1).toBe('=Choices')
  await vi.waitFor(() => expect(validator.getList(rule, grid.api.getActiveWorkbook().getId(), sheet().getSheetId())).toEqual(['Ada', 'Grace']))
  grid.api.getActiveWorkbook().getDefinedNames().find((item: any) => item.getName() === 'Alias').setRef('Sheet1!$A$2:$A$2')
  await vi.waitFor(() => expect(validator.getList(rule, grid.api.getActiveWorkbook().getId(), sheet().getSheetId())).toEqual(['Grace']))
  history('undo')
  await vi.waitFor(() => expect(validator.getList(rule, grid.api.getActiveWorkbook().getId(), sheet().getSheetId())).toEqual(['Ada', 'Grace']))
  history('redo')
  await vi.waitFor(() => expect(validator.getList(rule, grid.api.getActiveWorkbook().getId(), sheet().getSheetId())).toEqual(['Grace']))
  sheet().getRange(1, 0).setValue('Hopper')
  await vi.waitFor(() => expect(validator.getList(rule, grid.api.getActiveWorkbook().getId(), sheet().getSheetId())).toEqual(['Hopper']))
  expect(validator.validatorFormula({ ...rule, formula1: '=MissingName' }, grid.api.getActiveWorkbook().getId(), sheet().getSheetId()).success).toBe(false)
  expect(validator.validatorFormula({ ...rule, ranges: [{ startRow: 1, endRow: 1, startColumn: 0, endColumn: 0 }] }, grid.api.getActiveWorkbook().getId(), sheet().getSheetId()).success).toBe(false)
  expect(grid.api.syncExecuteCommand('sheets.command.update-data-validation-options', { unitId: grid.api.getActiveWorkbook().getId(), subUnitId: sheet().getSheetId(), ruleId: rule.uid, options: { prompt: '选择姓名' } })).toBe(true)
  expect(grid.api.syncExecuteCommand('sheet.command.insert-row-by-range', { unitId: grid.api.getActiveWorkbook().getId(), subUnitId: sheet().getSheetId(), range: { startRow: 0, endRow: 0, startColumn: 0, endColumn: 9 }, direction: 0 })).toBe(true)
  expect(sheet().getDataValidations()[0].rule.formula1).toBe('=Choices')
  await vi.waitFor(() => expect(validator.getList(sheet().getDataValidations()[0].rule, grid.api.getActiveWorkbook().getId(), sheet().getSheetId())).toEqual(['Hopper']))
  history('undo')
  expect(sheet().getDataValidations()[0].rule.formula1).toBe('=Choices')
  history('redo')
  expect(sheet().getDataValidations()[0].rule.formula1).toBe('=Choices')
  await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'replaceSheetDataValidations')).toBe(true))
  sheet().setName('Renamed')
  expect(sheet().getDataValidations()[0].rule.formula1).toBe('=Choices')
  history('undo')
  expect(sheet().getDataValidations()[0].rule.formula1).toBe('=Choices')
  history('redo')
  expect(sheet().getDataValidations()[0].rule.formula1).toBe('=Choices')
  await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applySheetEdits')).toBe(true))
  current.view?.dispose()
  const restored = await open(source, new NativeDraft(identity, storage), save)
  expect(sheet().getDataValidations()[0].rule.formula1).toBe('=Choices')
  restored.shell.save.click()
  await vi.waitFor(() => expect(restored.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const model = await readWorkbook(downloaded!)
  expect(model.sheets[0]?.dataValidations?.rules[0]?.rule.formula1).toBe('=Choices')
  expect(model.definedNames).toContainEqual({ name: 'Choices', refersTo: 'Alias' })
  expect(model.definedNames).toContainEqual({ name: 'Alias', refersTo: 'Renamed!$A$3' })
  restored.view?.dispose()
})
it('deduplicates captured rows with header, typed values, undo and saved output', async () => {
  const rows = [['Name', 'Flag'], ['Ada', true], ['ADA', true], ['Grace', false], ['Grace', false]]
  const source = await applyCellEdits(await createBlankWorkbook(), rows.flatMap((row, r) => row.map((value, c) => ({ sheetName: 'Sheet1', row: r, column: c, writeValue: true, cell: { value } }))))
  let downloaded: Uint8Array | undefined
  const storage = store(), draft = new NativeDraft(identity, storage)
  const save = async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/f.xlsx' } }, validation: { issues: [] } }
  }
  const current = await open(source, draft, save)
  sheet().setActiveSelection(sheet().getRange(0, 0, 5, 2))
  grid.ribbon('remove-duplicates-open')
  const dialog = document.querySelector<HTMLElement>('[role="dialog"][aria-label="删除重复值"]')!
  expect(dialog).not.toBeNull()
  expect(dialog.hidden).toBe(false)
  sheet().setActiveSelection(sheet().getRange(8, 8))
  dialog.querySelector<HTMLButtonElement>('[type="submit"]')!.click()
  expect(dialog.querySelector('[role="alert"]')!.textContent).toBe('')
  expect(sheet().getRange(2, 0).getValue()).toBe('Grace')
  expect(sheet().getRange(3, 0).getValue()).toBeNull()
  history('undo')
  expect(sheet().getRange(2, 0).getValue()).toBe('ADA')
  history('redo')
  await vi.waitFor(() => expect(draft.dirty).toBe(true))
  current.view?.dispose()
  const restored = await open(source, new NativeDraft(identity, storage), save)
  expect(sheet().getRange(2, 0).getValue()).toBe('Grace')
  restored.shell.save.click()
  await vi.waitFor(() => expect(restored.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const model = (await readWorkbook(downloaded!)).sheets[0]!
  expect([model.cells.A1?.value, model.cells.A2?.value, model.cells.A3?.value, model.cells.B3?.value]).toEqual(['Name', 'Ada', 'Grace', false])
  expect(model.cells.A4?.value ?? null).toBeNull()
  expect(model.cells.B5?.value ?? null).toBeNull()
  restored.view?.dispose()
})
const history = (direction: 'undo' | 'redo') => expect(grid.api.syncExecuteCommand(`univer.command.${direction}`)).toBe(true)
it('does not confuse uncalculated formulas with blanks or leave tail formulas behind', () => {
  const range = { startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 }
  expect(() => planWorkbookDedupe({ getRange: () => range, getCellDatas: () => [[{ f: '=1' }], [{ f: '=2' }], [{ f: '=3' }]], getValues: () => [[null], [null], [null]] }, false)).toThrow('计算')
  const plan = planWorkbookDedupe({ getRange: () => range, getCellDatas: () => [[{ v: 'x' }], [{ v: 'X' }], [{ v: '', f: '=IF(1=1,"","x")' }]], getValues: () => [['x'], ['X'], ['']] }, false)
  expect(plan.value[1]?.[0]?.v).toBe('')
  expect(plan.value[2]?.[0]).toMatchObject({ v: null, f: null })
})
it('keeps type-distinct rows, removes headerless duplicates and rejects oversized reads before materialization', async () => {
  const source = await applyCellEdits(await createBlankWorkbook(), [true, 1, '1', true].map((value, row) => ({ sheetName: 'Sheet1', row, column: 0, writeValue: true, cell: { value } })))
  const current = await open(source, new NativeDraft(identity, store()), async () => ({}))
  sheet().setActiveSelection(sheet().getRange(0, 0, 4, 1))
  grid.ribbon('remove-duplicates-open')
  const dialog = document.querySelector<HTMLElement>('[role="dialog"][aria-label="删除重复值"]')!
  dialog.querySelector<HTMLInputElement>('input')!.checked = false
  dialog.querySelector<HTMLButtonElement>('[type="submit"]')!.click()
  expect(dialog.querySelector('[role="alert"]')!.textContent).toBe('')
  expect(sheet().getRange(0, 0, 4, 1).getValues().flat()).toEqual([true, 1, '1', null])
  expect(() => planWorkbookDedupe({ getRange: () => ({ startRow: 0, endRow: 2000, startColumn: 0, endColumn: 0 }), getCellDatas: () => { throw new Error('materialized') }, getValues: () => [] }, false)).toThrow('2000')
  current.view?.dispose()
})

it('refuses protected and merged dedupe selections and leaves no-op selections clean', async () => {
  const source = await applyCellEdits(await createBlankWorkbook(), ['a', 'b'].map((value, row) => ({ sheetName: 'Sheet1', row, column: 0, writeValue: true, cell: { value } })))
  const draft = new NativeDraft(identity, store())
  const current = await open(source, draft, async () => ({}))
  const submit = () => document.querySelector<HTMLButtonElement>('[aria-label="删除重复值"] [type="submit"]')!.click()
  sheet().setActiveSelection(sheet().getRange(0, 0, 2, 1)); grid.ribbon('remove-duplicates-open'); submit()
  expect(draft.dirty).toBe(false)
  grid.ribbon('sheet-protect'); grid.ribbon('remove-duplicates-open'); submit()
  expect(document.querySelector('[aria-label="删除重复值"] [role="alert"]')!.textContent).toContain('保护')
  expect(sheet().getRange(1, 0).getValue()).toBe('b')
  grid.ribbon('sheet-protect')
  sheet().getRange(0, 0, 1, 2).merge()
  sheet().setActiveSelection(sheet().getRange(0, 0, 2, 2)); grid.ribbon('remove-duplicates-open'); submit()
  expect(document.querySelector('[aria-label="删除重复值"] [role="alert"]')!.textContent).toContain('合并')
  current.view?.dispose()
})
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

it('flash-fills only empty cells from adjacent columns and saves with undo/redo', async () => {
  const source = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Ada' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 'Lovelace' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'Grace' } },
    { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: 'Hopper' } },
    { sheetName: 'Sheet1', row: 0, column: 2, writeValue: true, cell: { value: 'Ada Lovelace' } },
  ])
  const storage = store(), draft = new NativeDraft(identity, storage)
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/f.xlsx' } }, validation: { issues: [] } }
  })
  sheet().setActiveSelection(sheet().getRange(0, 2, 2, 1))
  grid.ribbon('flash-fill')
  expect(sheet().getRange(0, 2, 2, 1).getValues().map((row: unknown[]) => row[0])).toEqual(['Ada Lovelace', 'Grace Hopper'])
  history('undo')
  expect(sheet().getRange(0, 2, 2, 1).getValues().map((row: unknown[]) => row[0])).toEqual(['Ada Lovelace', null])
  history('redo')
  await vi.waitFor(() => expect(draft.dirty).toBe(true))
  current.view?.dispose()
  const restored = await open(source, new NativeDraft(identity, storage), async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/f.xlsx' } }, validation: { issues: [] } }
  })
  expect(sheet().getRange(0, 2, 2, 1).getValues().map((row: unknown[]) => row[0])).toEqual(['Ada Lovelace', 'Grace Hopper'])
  restored.shell.save.click()
  await vi.waitFor(() => expect(restored.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const cells = (await readWorkbook(downloaded!)).sheets[0]!.cells
  expect([cells.C1?.value, cells.C2?.value]).toEqual(['Ada Lovelace', 'Grace Hopper'])
  restored.view?.dispose()
})

it('flash-fill keeps target formulas, formatting and notes and writes formula-like results as text', async () => {
  const source = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'alpha' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'beta' } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: 'gamma' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: '=alpha' } },
    { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: null }, style: { bold: true } },
    { sheetName: 'Sheet1', row: 2, column: 1, writeValue: true, cell: { value: null, formula: '=IF(1=1,"","x")' } },
  ])
  let downloaded: Uint8Array | undefined
  const current = await open(source, new NativeDraft(identity, store()), async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/f.xlsx' } }, validation: { issues: [] } }
  })
  expect(grid.api.syncExecuteCommand('sheet.command.update-note', { unitId: grid.api.getActiveWorkbook().getId(), subUnitId: sheet().getSheetId(), row: 1, col: 1, note: { note: '目标批注', width: 240, height: 140 } })).toBe(true)
  sheet().setActiveSelection(sheet().getRange(0, 1)) // 单格向下探测左列
  grid.ribbon('flash-fill')
  expect(sheet().getRange(1, 1).getValue()).toBe('=beta')
  expect(sheet().getRange(1, 1).getFormula()).toBe('')
  expect(sheet().getRange(2, 1).getFormula()).toBe('=IF(1=1,"","x")')
  current.shell.save.click()
  await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const book = await readWorkbook(downloaded!), model = book.sheets[0]!
  expect(model.cells.B2?.value).toBe('=beta')
  expect(model.cells.B2?.formula).toBeUndefined()
  const xf = book.styles.cellXfs[model.cells.B2!.styleIndex ?? 0]!
  expect(book.styles.fonts[xf.fontId]?.bold).toBe(true)
  expect(model.cells.B3?.formula).toBe('=IF(1=1,"","x")')
  expect(model.notes?.notes.some(note => note.text === '目标批注')).toBe(true)
  current.view?.dispose()
})

it('splits a column into typed values, keeps styles and notes, restores drafts and saves with undo/redo', async () => {
  const source = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Ada,001,TRUE,=A9' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'Grace,42,FALSE,' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: null }, style: { bold: true } },
    { sheetName: 'Sheet1', row: 8, column: 4, writeValue: true, cell: { value: null, formula: '=SUM(1,2)' } },
  ])
  const storage = store()
  let downloaded: Uint8Array | undefined
  const save = async (request: NativeSaveRequest) => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/f.xlsx' } }, validation: { issues: [] } }
  }
  const draft = new NativeDraft(identity, storage)
  const current = await open(source, draft, save)
  expect(grid.api.syncExecuteCommand('sheet.command.update-note', { unitId: grid.api.getActiveWorkbook().getId(), subUnitId: sheet().getSheetId(), row: 0, col: 1, note: { note: '保留分列批注', width: 240, height: 140 } })).toBe(true)
  sheet().setActiveSelection(sheet().getRange(0, 0, 2, 1))
  grid.ribbon('text-to-columns:2')
  expect(sheet().getRange(0, 0, 2, 4).getValues()).toEqual([['Ada', '001', 1, '=A9'], ['Grace', 42, 0, null]])
  expect(sheet().getRange(0, 3).getFormula()).toBe('')
  const readback = readBackSnapshot(grid.api.getActiveWorkbook().save()).sheets[0]!.cells
  expect([readback.C1?.value, readback.C2?.value]).toEqual([true, false])
  history('undo')
  expect(sheet().getRange(0, 0).getValue()).toBe('Ada,001,TRUE,=A9')
  expect(sheet().getRange(0, 1).getValue()).toBeNull()
  history('redo')
  await vi.waitFor(() => expect(draft.operations.some(op => op.kind === 'applyCellEdits' && JSON.stringify(op).includes('Grace'))).toBe(true))
  current.view?.dispose()
  const restored = await open(source, new NativeDraft(identity, storage), save)
  expect(sheet().getRange(0, 0, 2, 4).getValues()).toEqual([['Ada', '001', true, '=A9'], ['Grace', 42, false, null]])
  restored.shell.save.click()
  await vi.waitFor(() => expect(restored.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const book = await readWorkbook(downloaded!), model = book.sheets[0]!
  expect([model.cells.A1?.value, model.cells.B1?.value, model.cells.C1?.value, model.cells.D1?.value]).toEqual(['Ada', '001', true, '=A9'])
  expect([model.cells.A2?.value, model.cells.B2?.value, model.cells.C2?.value]).toEqual(['Grace', 42, false])
  expect(model.cells.D1?.formula).toBeUndefined()
  expect(model.cells.E9?.formula).toBe('=SUM(1,2)')
  const xf = book.styles.cellXfs[model.cells.B1!.styleIndex ?? 0]!
  expect(book.styles.fonts[xf.fontId]?.bold).toBe(true)
  expect(model.notes?.notes.some(note => note.text === '保留分列批注')).toBe(true)
  restored.view?.dispose()
})

it.each([['4', 'a;;3', ['a', null, 3]], ['8', 'a  3', ['a', null, 3]], ['1', 'a\t\t3', ['a', null, 3]]])('splits using delimiter %s and retains empty fields', async (id, input, expected) => {
  const source = await applyCellEdits(await createBlankWorkbook(), [{ sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: input as string } }])
  const current = await open(source, new NativeDraft(identity, store()), async () => ({}))
  sheet().setActiveSelection(sheet().getRange(0, 0))
  grid.ribbon(`text-to-columns:${id}`)
  expect(sheet().getRange(0, 0, 1, 3).getValues()[0]).toEqual(expected)
  current.view?.dispose()
})

it('rejects text-to-columns on occupied output, formulas, merged ranges and protection atomically', async () => {
  const source = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'a,b' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'c,d' } },
    { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: null, formula: '=IF(1=1,"","x")' } },
  ])
  const current = await open(source, new NativeDraft(identity, store()), async () => ({}))
  const before = sheet().getRange(0, 0, 2, 3).getCellDatas()
  sheet().setActiveSelection(sheet().getRange(0, 0, 2, 1)); grid.ribbon('text-to-columns:2')
  expect(current.shell.editor.querySelector('.workbook-feedback')!.textContent).toContain('已有')
  expect(sheet().getRange(0, 0, 2, 3).getCellDatas()).toEqual(before)
  sheet().setActiveSelection(sheet().getRange(0, 0, 2, 2)); grid.ribbon('text-to-columns:2')
  expect(current.shell.editor.querySelector('.workbook-feedback')!.textContent).toContain('单列')
  sheet().setActiveSelection(sheet().getRange(1, 1)); grid.ribbon('text-to-columns:2')
  expect(current.shell.editor.querySelector('.workbook-feedback')!.textContent).toContain('公式')
  sheet().getRange(0, 1, 1, 2).merge()
  sheet().setActiveSelection(sheet().getRange(0, 0)); grid.ribbon('text-to-columns:2')
  expect(current.shell.editor.querySelector('.workbook-feedback')!.textContent).toContain('合并')
  expect(sheet().getRange(0, 0).getValue()).toBe('a,b')
  history('undo')
  grid.ribbon('sheet-protect'); grid.ribbon('text-to-columns:2')
  expect(current.shell.editor.querySelector('.workbook-feedback')!.textContent).toContain('保护')
  expect(sheet().getRange(0, 0).getValue()).toBe('a,b')
  current.view?.dispose()
})

it('keeps native boolean source rows when splitting a mixed selection again', async () => {
  const current = await open(await createBlankWorkbook(), new NativeDraft(identity, store()), async () => ({}))
  sheet().getRange(0, 0).setValue('TRUE,x')
  sheet().setActiveSelection(sheet().getRange(0, 0)); grid.ribbon('text-to-columns:2')
  sheet().getRange(1, 0).setValue('a,b')
  sheet().getRange(0, 1).clear()
  sheet().setActiveSelection(sheet().getRange(0, 0, 2, 1)); grid.ribbon('text-to-columns:2')
  const readback = readBackSnapshot(grid.api.getActiveWorkbook().save()).sheets[0]!.cells
  expect([readback.A1?.value, readback.A2?.value, readback.B2?.value]).toEqual([true, 'a', 'b'])
  current.view?.dispose()
})

it('preflights split output budgets, sheet edges and rich text before changing the grid', async () => {
  const current = await open(await createBlankWorkbook(), new NativeDraft(identity, store()), async () => ({}))
  sheet().getRange(0, 0, 6, 1).setValues(Array.from({ length: 6 }, () => [','.repeat(32766)]))
  expect(() => planWorkbookTextToColumns(sheet(), sheet().getRange(0, 0, 6, 1), ',')).toThrow('2000')
  expect(() => planWorkbookTextToColumns(sheet(), sheet().getRange(0, 0, 2001, 1), ',')).toThrow('2000')
  sheet().getRange(0, 0).setValue('no delimiter')
  expect(() => planWorkbookTextToColumns(sheet(), sheet().getRange(0, 0), ',')).toThrow('分隔符')
  const edge = sheet().getMaxColumns() - 1
  sheet().getRange(0, edge).setValue('a,b')
  expect(() => planWorkbookTextToColumns(sheet(), sheet().getRange(0, edge), ',')).toThrow('边界')
  // 导入的富文本直接存在底层模型；原生分列不能静默展平它。
  sheet().getSheet().getCellMatrix().setValue(0, 0, { p: { body: { dataStream: 'a,b\r\n' } } })
  expect(() => planWorkbookTextToColumns(sheet(), sheet().getRange(0, 0), ',')).toThrow('富文本')
  current.view?.dispose()
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

it('refuses flash-fill without a usable pattern and on merged or protected targets without changing cells', async () => {
  const source = await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'alpha' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'beta' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 'a' } },
  ])
  const current = await open(source, new NativeDraft(identity, store()), async () => { throw new Error('must not save') })
  const before = sheet().getRange(0, 0, 2, 3).getCellDatas()
  for (const [row, column, rows, columns, reason] of [
    [0, 0, 2, 1, '左侧'], [0, 1, 2, 2, '单列'], [0, 2, 2, 1, '示例'], [0, 1, 2, 1, '无法'],
  ] as const) {
    sheet().setActiveSelection(sheet().getRange(row, column, rows, columns))
    grid.ribbon('flash-fill')
    expect(current.shell.editor.querySelector('.workbook-feedback')!.textContent).toContain(reason)
    expect(sheet().getRange(0, 0, 2, 3).getCellDatas()).toEqual(before)
  }
  sheet().getRange(0, 1).setValues([['alpha!']])
  sheet().getRange(1, 1, 1, 2).merge()
  const merged = sheet().getRange(0, 0, 2, 3).getCellDatas()
  sheet().setActiveSelection(sheet().getRange(0, 1, 2, 1)); grid.ribbon('flash-fill')
  expect(current.shell.editor.querySelector('.workbook-feedback')!.textContent).toContain('合并')
  expect(sheet().getRange(0, 0, 2, 3).getCellDatas()).toEqual(merged)
  history('undo')
  grid.ribbon('sheet-protect'); grid.ribbon('flash-fill')
  expect(sheet().getRange(1, 1).getValue()).toBeNull()
  expect(current.shell.editor.querySelector('.workbook-feedback')!.textContent).toContain('保护')
  current.view?.dispose()
})

it('reveals the readonly cross-sheet Go To target without snapshot, draft, history or save changes', async () => {
  const source = await applyWorkbookOperations(await fixture(), [{ kind: 'applySheetEdits', plan: {
    renames: [], additions: [{ name: 'Far' }], removals: [], order: ['Sheet1', 'Far'],
  } }])
  const reveal = vi.fn(async (_sheet: any, _row: number, _column: number, _current?: () => boolean) => true), cancel = vi.fn(), dispose = vi.fn()
  const factory = vi.spyOn(gotoReveal, 'createWorkbookReveal').mockReturnValue({ reveal, cancel, dispose })
  const storage = store(), draft = new NativeDraft(identity, storage), save = vi.fn(async () => ({}))
  const current = await open(source, draft, save, false)
  try {
    const book = grid.api.getActiveWorkbook(), snapshot = book.getSnapshot(), label = current.shell.statusLabel.textContent
    const history = grid.instances.at(-1).__getInjector().get(IUndoRedoService)
    const undo = history.pitchTopUndoElement(), redo = history.pitchTopRedoElement()
    grid.ribbon('goto-open')
    const dialog = document.querySelector<HTMLElement>('.workbook-ribbon-goto-dialog')!
    dialog.querySelector<HTMLInputElement>('[data-goto-reference]')!.value = 'Far!D80'
    dialog.querySelector<HTMLFormElement>('form')!.requestSubmit()
    await vi.waitFor(() => expect(reveal).toHaveBeenCalledOnce())
    expect(reveal.mock.calls[0]![0].getSheetName()).toBe('Far')
    expect(reveal.mock.calls[0]!.slice(1, 3)).toEqual([79, 3])
    expect(book.getActiveSheet().getSheetName()).toBe('Far')
    expect(book.getActiveRange().getA1Notation()).toContain('D80')
    await vi.waitFor(() => expect(current.shell.editor.querySelector('.workbook-feedback')?.textContent).toContain('目标已显示'))
    expect(book.getSnapshot()).toEqual(snapshot)
    expect(draft.operations).toEqual([]); expect(save).not.toHaveBeenCalled()
    expect(current.shell.statusLabel.textContent).toBe(label)
    expect(history.pitchTopUndoElement()).toBe(undo); expect(history.pitchTopRedoElement()).toBe(redo)
  } finally { current.view?.dispose(); factory.mockRestore() }
  expect(dispose).toHaveBeenCalled()
})

it.each(['unrevealed', 'exception'])('keeps the selected target but reports Go To reveal %s truthfully', async failure => {
  let finish!: (value: boolean) => void, fail!: (error: Error) => void
  const result = new Promise<boolean>((resolve, reject) => { finish = resolve; fail = reject })
  const factory = vi.spyOn(gotoReveal, 'createWorkbookReveal').mockReturnValue({ reveal: vi.fn(() => result), cancel: vi.fn(), dispose: vi.fn() })
  const draft = new NativeDraft(identity, store()), current = await open(await fixture(), draft, async () => ({}))
  try {
    const before = grid.api.getActiveWorkbook().getSnapshot(), label = current.shell.statusLabel.textContent
    grid.ribbon('goto-open')
    const dialog = document.querySelector<HTMLElement>('.workbook-ribbon-goto-dialog')!
    dialog.querySelector<HTMLInputElement>('[data-goto-reference]')!.value = 'D80'
    dialog.querySelector<HTMLFormElement>('form')!.requestSubmit()
    expect(current.shell.editor.querySelector('.workbook-feedback')?.textContent).toContain('正在显示目标')
    if (failure === 'exception') fail(new Error('render unavailable')); else finish(false)
    await vi.waitFor(() => expect(current.shell.editor.querySelector('.workbook-feedback')?.textContent).toContain(failure === 'exception' ? '无法显示目标：render unavailable' : '未能将目标显示到可见区域'))
    expect(current.shell.editor.querySelector('.workbook-feedback')?.textContent).not.toContain('目标已显示')
    expect(grid.api.getActiveWorkbook().getActiveRange().getA1Notation()).toContain('D80')
    expect(grid.api.getActiveWorkbook().getSnapshot()).toEqual(before)
    expect(draft.operations).toEqual([]); expect(current.shell.statusLabel.textContent).toBe(label)
  } finally { current.view?.dispose(); factory.mockRestore() }
})

it('ignores stale Go To reveal failures after a newer navigation', async () => {
  let rejectOld!: (reason: Error) => void
  const old = new Promise<boolean>((_resolve, reject) => { rejectOld = reject })
  const reveal = vi.fn().mockReturnValueOnce(old).mockResolvedValueOnce(true)
  const factory = vi.spyOn(gotoReveal, 'createWorkbookReveal').mockReturnValue({ reveal, cancel: vi.fn(), dispose: vi.fn() })
  const current = await open(await fixture(), new NativeDraft(identity, store()), async () => ({}))
  try {
    const navigate = (reference: string) => {
      grid.ribbon('goto-open')
      const dialog = document.querySelector<HTMLElement>('.workbook-ribbon-goto-dialog')!
      dialog.querySelector<HTMLInputElement>('[data-goto-reference]')!.value = reference
      dialog.querySelector<HTMLFormElement>('form')!.requestSubmit()
    }
    navigate('D80'); navigate('C10')
    await vi.waitFor(() => expect(current.shell.editor.querySelector('.workbook-feedback')?.textContent).toBe('已定位到 C10，目标已显示。'))
    rejectOld(new Error('stale failure')); await Promise.resolve(); await Promise.resolve()
    expect(current.shell.editor.querySelector('.workbook-feedback')?.textContent).toBe('已定位到 C10，目标已显示。')
    expect(grid.api.getActiveWorkbook().getActiveRange().getA1Notation()).toContain('C10')
  } finally { current.view?.dispose(); factory.mockRestore() }
})

it('full Paste Special writes through the existing draft and save chain, with cancel and readonly protection',async()=>{
 const originalClipboard=Object.getOwnPropertyDescriptor(navigator,'clipboard')
 const source=await fixture(),draft=new NativeDraft(identity,store());let downloaded:Uint8Array|undefined
 Object.defineProperty(navigator,'clipboard',{configurable:true,value:{read:async()=>[{types:['text/plain'],getType:async()=>({text:async()=> '7'})}]}})
 const current=await open(source,draft,async request=>{downloaded=await applyWorkbookOperations(source,request.operations);return {revision:2,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/p.xlsx'}},validation:{issues:[]}}})
 try{
  sheet().getRange('D4').activate();grid.ribbon('paste-special-open');await vi.waitFor(()=>expect(document.querySelector<HTMLElement>('.workbook-paste-special-overlay')!.hidden).toBe(false))
  const dialog=document.querySelector<HTMLElement>('.workbook-paste-special-overlay')!;[...dialog.querySelectorAll<HTMLInputElement>('.workbook-paste-special-flags input')][1]!.click();dialog.querySelector<HTMLButtonElement>('[data-paste-special-apply]')!.click()
  await vi.waitFor(()=>expect(sheet().getRange('D4').getValue()).toBe(7));await vi.waitFor(()=>expect(draft.operations.some(op=>op.kind==='applyCellEdits')).toBe(true))
  grid.ribbon('undo');await vi.waitFor(()=>expect(sheet().getRange('D4').getValue()).toBeNull());grid.ribbon('redo');await vi.waitFor(()=>expect(sheet().getRange('D4').getValue()).toBe(7))
  const previous=JSON.stringify(draft.operations);grid.ribbon('paste-special-open');await vi.waitFor(()=>expect(dialog.hidden).toBe(false));dialog.querySelector<HTMLButtonElement>('.modal-close')!.click();expect(JSON.stringify(draft.operations)).toBe(previous)
  current.shell.save.click();await vi.waitFor(()=>expect(current.shell.statusLabel.textContent).toContain('已保存修订 2'));expect((await readWorkbook(downloaded!)).sheets[0]!.cells.D4!.value).toBe(7)
  grid.ribbon('paste-special-open');expect(dialog.hidden).toBe(true)
 }finally{current.view?.dispose();if(originalClipboard)Object.defineProperty(navigator,'clipboard',originalClipboard);else Reflect.deleteProperty(navigator,'clipboard')}
})

it('full Paste Special never writes through readonly or protected target guards',async()=>{
 const source=await fixture()
 for(const protectedSheet of [false,true]){
  const draft=new NativeDraft(identity,store()),current=await open(protectedSheet?await protectSheet(source,'Sheet1',true):source,draft,async()=>({}),protectedSheet)
  try{
   const before=grid.api.getActiveWorkbook().getSnapshot();sheet().getRange('D4').activate();grid.ribbon('paste-special-open')
   const dialog=document.querySelector<HTMLElement>('.workbook-paste-special-overlay')!
   if(!protectedSheet){expect(dialog.hidden).toBe(true)}else{
    await vi.waitFor(()=>expect(dialog.hidden).toBe(false));[...dialog.querySelectorAll<HTMLInputElement>('.workbook-paste-special-flags input')][1]!.click();dialog.querySelector<HTMLButtonElement>('[data-paste-special-apply]')!.click()
    await vi.waitFor(()=>expect(dialog.querySelector('[role=alert]')!.textContent).not.toBe(''));expect(dialog.hidden).toBe(false)
   }
   expect(sheet().getRange('D4').getValue()).toBeNull();expect(draft.operations).toEqual([]);expect(grid.api.getActiveWorkbook().getSnapshot().sheets).toEqual(before.sheets)
  }finally{current.view?.dispose()}
 }
})
