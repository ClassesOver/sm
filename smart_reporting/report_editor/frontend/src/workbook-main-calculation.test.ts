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

const grid = vi.hoisted(() => ({ api: undefined as any, ribbon: undefined as any, apply: vi.fn(() => false), instances: [] as any[], failNameImport: false as boolean | 'local' }))
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
