import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { applyCellEdits, applyDefinedNames, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createWorkbookEditorView } from './workbook-main'
import { createNativeOfficeTransport } from './native-office-view'
import { NativeDraft, type NativeDraftIdentity, type NativeSaveRequest } from './native-draft'
import { validateWorkbookReplacement } from './workbook-find-replace'
import { openFindReplace } from './workbook-vendor/grid/sync'
import { createEditorShell } from './shell'

const grid = vi.hoisted(() => ({ snapshot: undefined as any, listener: (_command: any, _options?: any) => {}, before: (_command: any) => {} }))
vi.mock('@univerjs/core', async importOriginal => ({ ...(await importOriginal<typeof import('@univerjs/core')>()), LocaleType: { ZH_CN: 'zhCN' }, mergeLocales: () => ({}) }))
vi.mock('@univerjs/preset-sheets-core', () => ({ UniverSheetsCorePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-find-replace', () => ({ UniverSheetsFindReplacePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-drawing', () => ({ UniverSheetsDrawingPreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-table', () => ({ UniverSheetsTablePreset: () => ({ plugins: [] }) }))
vi.mock('./workbook-ribbon', () => ({ mountWorkbookRibbon: () => ({ dispose() {} }), applyWorkbookRibbonCommand: () => false }))
vi.mock('./workbook-vendor/grid/decimal-step', () => ({ stepSelectionDecimals() {} }))
vi.mock('./workbook-vendor/grid/sparkline-render', () => ({ setSparklines() {}, setSparklineWorkbookResolver() {} }))
vi.mock('./workbook-vendor/grid/chart-render', () => ({ setCharts() {} }))
vi.mock('./workbook-vendor/grid/create-univer', () => ({ createUniver: () => {
  const worksheet = { getSheetName: () => 'Sheet1' }
  const workbook = { getId: () => 'report-workbook', getSnapshot: () => grid.snapshot,
    getSheets: () => [worksheet], getSheetBySheetId: () => worksheet }
  return { univer: { dispose() {} }, univerAPI: { Event: { BeforeCommandExecute: 'BeforeCommandExecute' },
    addEvent(_event: string, listener: typeof grid.before) { grid.before = listener; return { dispose() {} } },
    getActiveWorkbook: () => grid.snapshot ? workbook : null,
    disposeUnit() {}, createWorkbook(data: unknown) { grid.snapshot = structuredClone(data); return workbook },
    onCommandExecuted(listener: typeof grid.listener) { grid.listener = listener; return { dispose() {} } } } }
} }))

const identity: NativeDraftIdentity = { documentId: 'xlsx-recovery', revision: 1, sourceSha256: 'a'.repeat(64),
  scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } }
const context = { context: { ...identity, format: 'xlsx', sourceFile: { sha256: identity.sourceSha256 } }, editingEnabled: true }
const store = () => {
  const data = new Map<string, string>()
  return { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => { data.set(key, value) }, removeItem: (key: string) => { data.delete(key) } }
}
let source: Uint8Array
beforeEach(async () => {
  grid.snapshot = undefined
  source = await applyCellEdits(await createBlankWorkbook(), [{ sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: '原始值' } }])
})
afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks() })
async function open(draft: NativeDraft, save: (request: NativeSaveRequest) => Promise<unknown>) {
  document.body.innerHTML = '<main id="app"></main>'
  const shell = createEditorShell(document.querySelector('#app')!, 'full', 'xlsx')
  const transport = createNativeOfficeTransport({ api: { save } as never, context: context as never, draft })
  const view = await createWorkbookEditorView(shell, { native: true, draft, request: transport.workbook,
    file: async () => ({ bytes: source.slice().buffer, sha256: identity.sourceSha256 }) } as any)
  return { shell, view }
}
function setGridValue(value: string, commandId = 'sheet.mutation.set-range-values') {
  grid.snapshot.sheets['sheet-0'].cellData[0][0].v = value
  grid.listener({ id: commandId, params: {} })
}

it('persists native XLSX grid edits before save and restores them into the grid after refresh', async () => {
  const storage = store()
  const draft = new NativeDraft(identity, storage)
  const first = await open(draft, async () => { throw Error('未请求保存') })
  setGridValue('刷新前未保存')
  await vi.waitFor(() => expect(draft.operations).toEqual([{ kind: 'applyCellEdits', edits: [expect.objectContaining({ sheetName: 'Sheet1', row: 0, column: 0, cell: { value: '刷新前未保存' } })] }]))
  first.view?.dispose()
  const recovered = new NativeDraft(identity, storage)
  const second = await open(recovered, async () => { throw Error('未请求保存') })
  expect(grid.snapshot.sheets['sheet-0'].cellData[0][0].v).toBe('刷新前未保存')
  expect(second.shell.statusLabel.textContent).toContain('未保存')
  second.view?.dispose()
})

it('retains a failed native XLSX save request across refresh and saves later grid edits without losing recovery', async () => {
  const storage = store()
  let sequence = 0
  const newDraft = () => new NativeDraft(identity, storage, () => `request-${++sequence}`)
  const requests: NativeSaveRequest[] = []
  let downloaded: Uint8Array | undefined
  const save = async (request: NativeSaveRequest) => {
    requests.push(request)
    if (requests.length < 3) throw Error('网络故障')
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/saved.xlsx' } }, validation: { issues: [] } }
  }
  const first = await open(newDraft(), save)
  setGridValue('失败保存的草稿')
  first.shell.save.click()
  await vi.waitFor(() => expect(first.shell.statusLabel.textContent).toContain('保存失败'))
  first.view?.dispose()
  const draft = newDraft()
  const second = await open(draft, save)
  expect(grid.snapshot.sheets['sheet-0'].cellData[0][0].v).toBe('失败保存的草稿')
  second.shell.save.click()
  await vi.waitFor(() => expect(requests).toHaveLength(2))
  expect(requests[1]).toEqual(requests[0])
  await vi.waitFor(() => expect(second.shell.save.disabled).toBe(false))
  setGridValue('刷新后继续编辑')
  second.shell.save.click()
  await vi.waitFor(() => expect(second.shell.statusLabel.textContent).toContain('已保存修订 2'))
  expect(requests[2].requestId).not.toBe(requests[0].requestId)
  expect((await readWorkbook(downloaded!)).sheets[0].cells.A1.value).toBe('刷新后继续编辑')
  expect(draft.closed).toBe(true)
  second.view?.dispose()
})

it('retains the recovery request identity when Univer only recalculates an unchanged formula', async () => {
  source = await applyCellEdits(source, [{ sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: null, formula: '=1+1' } }])
  const storage = store()
  let sequence = 0
  const newDraft = () => new NativeDraft(identity, storage, () => `request-${++sequence}`)
  const requests: NativeSaveRequest[] = []
  const save = async (request: NativeSaveRequest) => { requests.push(request); throw Error('网络故障') }
  const first = await open(newDraft(), save)
  setGridValue('待恢复值')
  first.shell.save.click()
  await vi.waitFor(() => expect(first.shell.statusLabel.textContent).toContain('保存失败'))
  first.view?.dispose()
  const recovered = await open(newDraft(), save)
  grid.snapshot.sheets['sheet-0'].cellData[0][1].v = 2
  grid.listener({ id: 'sheet.mutation.set-range-values', params: {} })
  recovered.shell.save.click()
  await vi.waitFor(() => expect(recovered.shell.statusLabel.textContent).toContain('保存失败'))
  expect(requests[1]).toEqual(requests[0])
  recovered.view?.dispose()
})

it('waits for structural draft capture before saving a later grid edit', async () => {
  const draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: {}, validation: { issues: [] } }
  })
  const cells = grid.snapshot.sheets['sheet-0'].cellData
  cells[1] = cells[0]
  delete cells[0]
  grid.listener({ id: 'sheet.mutation.insert-row', params: { subUnitId: 'sheet-0', range: { startRow: 0, endRow: 0, startColumn: 0, endColumn: 0 } } })
  cells[0] = { 0: { v: '新行' } }
  grid.listener({ id: 'sheet.mutation.set-range-values', params: {} })
  current.shell.save.click()
  expect(current.shell.editor.inert).toBe(true)
  await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const saved = await readWorkbook(downloaded!)
  expect(saved.sheets[0].cells.A1.value).toBe('新行')
  expect(saved.sheets[0].cells.A2.value).toBe('原始值')
  current.view?.dispose()
})

it('preserves defined names and formulas when Univer undoes and redoes a row deletion', async () => {
  source = await applyDefinedNames(await applyCellEdits(source, [
    { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: null, formula: '=A1' } },
  ]), { sets: [{ name: 'Revenue', refersTo: 'Sheet1!$A$1' }] })
  source = await applyWorkbookOperations(source, [{ kind: 'applySheetMerges', sheetName: 'Sheet1', ranges: ['C1:D2'] }])
  const draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: {}, validation: { issues: [] } }
  })
  const initialCells = structuredClone(grid.snapshot.sheets['sheet-0'].cellData)
  const range = { startRow: 0, endRow: 0, startColumn: 0, endColumn: 25 }
  const remove = (trigger: string) => {
    grid.snapshot.sheets['sheet-0'].cellData = { 0: { 1: { f: '=#REF!', v: null } } }
    grid.listener({ id: 'sheet.mutation.remove-rows', params: { subUnitId: 'sheet-0', range, trigger } })
  }
  const restore = () => {
    grid.snapshot.sheets['sheet-0'].cellData = structuredClone(initialCells)
    grid.listener({ id: 'sheet.mutation.insert-row', params: { subUnitId: 'sheet-0', range, trigger: 'univer.command.undo' } })
    grid.listener({ id: 'sheet.mutation.set-range-values', params: { trigger: 'univer.command.undo' } })
  }
  remove('sheet.command.remove-row')
  await vi.waitFor(() => expect(draft.operations[0]).toMatchObject({ kind: 'applyRowColumnOps' }))
  restore()
  await vi.waitFor(() => expect(draft.operations).toEqual([]))
  remove('univer.command.redo')
  await vi.waitFor(() => expect(draft.operations[0]).toMatchObject({ kind: 'applyRowColumnOps', ops: [{ kind: 'remove-rows', index: 0, count: 1 }] }))
  const deleted = await readWorkbook(await applyWorkbookOperations(source, draft.operations))
  expect(deleted.definedNames?.find(name => name.name === 'Revenue')?.refersTo).toBe('Sheet1!#REF!')
  restore()
  current.shell.save.click()
  await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const restored = await readWorkbook(downloaded!)
  expect(restored.sheets[0].cells.A1.value).toBe('原始值')
  expect(restored.sheets[0].cells.B2.formula).toBe('=A1')
  expect(restored.definedNames?.find(name => name.name === 'Revenue')?.refersTo).toBe('Sheet1!$A$1')
  expect(restored.sheets[0].merges).toEqual(['C1:D2'])
  current.view?.dispose()
})

it('retains manual deletion and insertion as distinct structural operations', async () => {
  source = await applyDefinedNames(source, { sets: [{ name: 'Revenue', refersTo: 'Sheet1!$A$1' }] })
  const draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: {}, validation: { issues: [] } }
  })
  const range = { startRow: 0, endRow: 0, startColumn: 0, endColumn: 25 }
  grid.snapshot.sheets['sheet-0'].cellData = {}
  grid.listener({ id: 'sheet.mutation.remove-rows', params: { subUnitId: 'sheet-0', range, trigger: 'sheet.command.remove-row' } })
  grid.listener({ id: 'sheet.mutation.insert-row', params: { subUnitId: 'sheet-0', range, trigger: 'sheet.command.insert-row' } })
  grid.snapshot.sheets['sheet-0'].cellData = { 0: { 0: { v: null } } }
  setGridValue('重填值')
  current.shell.save.click()
  await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const restored = await readWorkbook(downloaded!)
  expect(restored.sheets[0].cells.A1.value).toBe('重填值')
  expect(restored.definedNames?.find(name => name.name === 'Revenue')?.refersTo).toBe('Sheet1!#REF!')
  current.view?.dispose()
})

it('preserves unsupported XLSX recovery operations and refuses to replace them with an empty grid', async () => {
  const draft = new NativeDraft(identity, store())
  const operations = [{ kind: 'futureOperation', value: '保留' }]
  draft.setOperations(operations)
  await expect(open(draft, async () => { throw Error('不应保存') })).rejects.toThrow('workbook_operation_invalid')
  expect(draft.operations).toEqual(operations)
})

it('persists the grid mutations emitted by Univer undo and redo into the same native draft', async () => {
  const draft = new NativeDraft(identity, store())
  const view = await open(draft, async () => { throw Error('不应保存') })
  setGridValue('修改值')
  await vi.waitFor(() => expect(draft.operations).not.toEqual([]))
  setGridValue('原始值')
  await vi.waitFor(() => expect(draft.operations).toEqual([]))
  setGridValue('修改值')
  await vi.waitFor(() => expect(draft.operations[0]).toMatchObject({ edits: [{ cell: { value: '修改值' } }] }))
  view.view?.dispose()
})

it('persists number-format mutations through Undo Redo refresh and format-only save', async () => {
  source = await applyCellEdits(source, [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 1234.567 } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: null, formula: '=A1*2' } },
  ])
  const storage = store(), draft = new NativeDraft(identity, storage)
  const first = await open(draft, async () => { throw Error('不应保存') })
  const before = structuredClone(grid.snapshot), id = grid.snapshot.sheetOrder[0]
  grid.snapshot.styles.customNumber = { ...(grid.snapshot.styles[grid.snapshot.sheets[id].cellData[0][0].s] ?? {}), n: { pattern: '#,##0.000' } }
  grid.snapshot.sheets[id].cellData[0][0].s = 'customNumber'
  const after = structuredClone(grid.snapshot)
  grid.listener({ id: 'sheet.mutation.set.numfmt', params: {} })
  await vi.waitFor(() => expect(draft.operations[0]).toMatchObject({ kind: 'applyCellEdits', edits: [{ row: 0, column: 0, writeValue: false, style: { numberFormat: '#,##0.000' } }] }))
  grid.snapshot = before
  grid.listener({ id: 'sheet.mutation.remove.numfmt', params: { trigger: 'univer.command.undo' } })
  await vi.waitFor(() => expect(draft.operations).toEqual([]))
  grid.snapshot = after
  grid.listener({ id: 'sheet.mutation.set.numfmt', params: { trigger: 'univer.command.redo' } })
  await vi.waitFor(() => expect(draft.operations).not.toEqual([]))
  first.view?.dispose()
  let downloaded: Uint8Array | undefined
  const restored = await open(new NativeDraft(identity, storage), async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: {}, validation: { issues: [] } }
  })
  const cell = grid.snapshot.sheets[id].cellData[0][0]
  expect(grid.snapshot.styles[cell.s].n.pattern).toBe('#,##0.000')
  expect(cell.v).toBe(1234.567)
  expect(grid.snapshot.sheets[id].cellData[0][1].f).toBe('=A1*2')
  restored.shell.save.click()
  await vi.waitFor(() => expect(restored.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const saved = await readWorkbook(downloaded!)
  expect(saved.sheets[0].cells.A1.value).toBe(1234.567)
  expect(saved.sheets[0].cells.B1.formula).toBe('=A1*2')
  restored.view?.dispose()
})

it('rejects an XLSX draft bound to a different source before applying its operations', async () => {
  const draft = new NativeDraft({ ...identity, sourceSha256: 'b'.repeat(64) }, store())
  draft.setOperations([{ kind: 'applyCellEdits', edits: [{ sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: '外来来源' } }] }])
  await expect(open(draft, async () => { throw Error('不应保存') })).rejects.toThrow('工作簿来源已变化')
  expect(grid.snapshot).toBeUndefined()
  expect(draft.operations[0]).toMatchObject({ edits: [{ cell: { value: '外来来源' } }] })
})

it('uses the public facade for Find/Replace and propagates dialog failures', async () => {
  const executeCommand = vi.fn(async () => true)
  const runtime = { univerAPI: { executeCommand } } as any
  await openFindReplace(runtime, false)
  await openFindReplace(runtime, true)
  expect(executeCommand.mock.calls).toEqual([['ui.operation.open-find-dialog'], ['ui.operation.open-replace-dialog']])
  executeCommand.mockResolvedValueOnce(false)
  await expect(openFindReplace(runtime, false)).rejects.toThrow('面板未能打开')
})

it('preflights the official multi-sheet payload, captures mutations, and restores replacements after refresh', async () => {
  source = await applyWorkbookOperations(source, [{ kind: 'applySheetEdits', plan: { renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'] } }])
  source = await applyCellEdits(source, [
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 42 } },
    { sheetName: 'Sheet1', row: 0, column: 2, writeValue: true, cell: { value: true } },
    { sheetName: 'Other', row: 0, column: 0, writeValue: true, cell: { value: null, formula: '=1+1' } },
  ])
  const storage = store(), draft = new NativeDraft(identity, storage)
  const first = await open(draft, async () => { throw Error('不应保存') })
  const ids = grid.snapshot.sheetOrder
  const payload = { unitId: grid.snapshot.id, replacements: [
    { subUnitId: ids[0], count: 1, value: { 0: { 0: { v: '替换后' } } } },
    { subUnitId: ids[1], count: 1, value: { 0: { 0: { f: '=2+2', v: null } } } },
  ] }
  const event = { id: 'sheet.command.replace', params: payload, cancel: false }
  grid.before(event)
  expect(event.cancel).toBe(false)
  const before = structuredClone(grid.snapshot)
  for (const replacement of payload.replacements) {
    const cells = grid.snapshot.sheets[replacement.subUnitId].cellData
    cells[0][0] = { ...cells[0][0], ...replacement.value[0][0] }
    grid.listener({ id: 'sheet.mutation.set-range-values', params: { subUnitId: replacement.subUnitId } })
  }
  await vi.waitFor(() => expect((draft.operations[0] as any).edits).toHaveLength(2))
  const after = structuredClone(grid.snapshot)
  grid.snapshot = before
  grid.listener({ id: 'sheet.mutation.set-range-values', params: { trigger: 'univer.command.undo' } })
  await vi.waitFor(() => expect(draft.operations).toEqual([]))
  grid.snapshot = after
  grid.listener({ id: 'sheet.mutation.set-range-values', params: { trigger: 'univer.command.redo' } })
  await vi.waitFor(() => expect(draft.operations).not.toEqual([]))
  first.view?.dispose()
  const restored = await open(new NativeDraft(identity, storage), async () => { throw Error('不应保存') })
  const model = await readWorkbook(await applyWorkbookOperations(source, draft.operations))
  expect(model.sheets[0].cells.A1.value).toBe('替换后')
  expect(model.sheets[0].cells.B1.value).toBe(42)
  expect(model.sheets[0].cells.C1.value).toBe(true)
  expect(model.sheets[1].cells.A1.formula).toBe('=2+2')
  expect(grid.snapshot.sheets[ids[0]].cellData[0][0].v).toBe('替换后')
  restored.view?.dispose()
})

it('rejects foreign, rich-text and over-budget official payloads without changing grid or draft', async () => {
  const draft = new NativeDraft(identity, store())
  const view = await open(draft, async () => { throw Error('不应保存') })
  const before = structuredClone(grid.snapshot), id = grid.snapshot.sheetOrder[0]
  const payload = (cell: unknown) => ({ unitId: grid.snapshot.id, replacements: [{ subUnitId: id, count: 1, value: { 0: { 0: cell } } }] })
  for (const params of [
    { ...payload({ v: 'foreign' }), unitId: 'foreign' },
    payload({ p: { body: { dataStream: 'rich\r\n' } } }),
    payload({ v: 'x'.repeat(10 * 1024 * 1024) }),
  ]) {
    const event = { id: 'sheet.command.replace', params, cancel: false }
    grid.before(event)
    expect(event.cancel).toBe(true)
    expect(grid.snapshot).toEqual(before)
    expect(draft.operations).toEqual([])
  }
  const model = await readWorkbook(source)
  expect(() => validateWorkbookReplacement({ id: 'sheet.command.replace', params: payload({ v: 'valid' }) }, before, model, [], 500)).toThrow('预算')
  // A cancelled/no-match single replacement must not poison later ordinary edits.
  grid.before({ id: 'ui.command.replace-current-match' })
  await Promise.resolve()
  const edit = { id: 'sheet.command.set-range-values', params: {}, cancel: false }
  grid.before(edit)
  expect(edit.cancel).toBe(false)
  view.view?.dispose()
})

it('blocks Replace through the official dialog while locked but leaves Find usable', async () => {
  const draft = new NativeDraft(identity, store())
  const view = await open(draft, async () => { throw Error('不应保存') })
  view.shell.editor.inert = true
  for (const id of ['ui.operation.open-replace-dialog', 'ui.command.replace-current-match', 'ui.command.replace-all-matches', 'sheet.command.replace']) {
    const event = { id, cancel: false }
    grid.before(event)
    expect(event.cancel).toBe(true)
  }
  const find = { id: 'ui.operation.open-find-dialog', cancel: false }
  grid.before(find)
  expect(find.cancel).toBe(false)
  view.view?.dispose()
})


it('excludes formula inferred formats from cross-sheet drafts while keeping explicit formats Undo Redo and refresh', async () => {
  source = await applyWorkbookOperations(await createBlankWorkbook(), [
    { kind: 'applySheetEdits', plan: { renames: [{ sheetName: 'Sheet1', newName: 'Summary' }], additions: [{ name: 'Details' }], removals: [], order: ['Summary', 'Details'] } },
    { kind: 'applyCellEdits', edits: [
      { sheetName: 'Summary', row: 0, column: 0, writeValue: true, cell: { value: 1234.567 }, style: { numberFormat: '#,##0.00' } },
      { sheetName: 'Details', row: 0, column: 0, writeValue: true, cell: { value: null, formula: '=Summary!A1' }, style: { bold: true, fontFamily: 'Arial', fontSize: 16, fontColor: '#AA2200', fillColor: '#EEEECC' } },
    ] },
  ])
  const storage = store(), draft = new NativeDraft(identity, storage)
  const first = await open(draft, async () => { throw Error('not saving yet') })
  const [summary, details] = grid.snapshot.sheetOrder
  const styleOf = (sheet: string) => { const cell = grid.snapshot.sheets[sheet].cellData[0][0]; return grid.snapshot.styles[cell.s] ?? {} }
  const calculate = () => {
    const options = { onlyLocal: true, fromFormula: true, applyFormulaCalculationResult: true }
    const incoming = { v: 1234.567, t: 2, s: { n: { pattern: '#,##0.00' } } }
    const event: any = { id: 'sheet.mutation.set-range-values', options, params: { unitId: grid.snapshot.id, subUnitId: details, trigger: 'formula-result', cellValue: { 0: { 0: incoming } } } }
    grid.before(event)
    expect(event.cancel).not.toBe(true)
    expect(event.params.trigger).toBe('formula-result')
    expect(incoming.s.n.pattern).toBe('#,##0.00')
    const result = event.params.cellValue[0][0]
    const cell = grid.snapshot.sheets[details].cellData[0][0]
    const style = { ...styleOf(details), ...result.s }
    const id = `calculated-${Object.keys(grid.snapshot.styles).length}`
    grid.snapshot.styles[id] = style
    Object.assign(cell, result, { s: id })
    grid.listener(event, options)
  }
  calculate()
  await Promise.resolve(); await Promise.resolve()
  expect(draft.operations).toEqual([])
  expect(first.shell.statusLabel.textContent).toBe('已保存')
  expect(styleOf(details)).toEqual({ bl: 1, ff: 'Arial', fs: 16, cl: { rgb: '#AA2200' }, bg: { rgb: '#EEEECC' } })
  const before = structuredClone(grid.snapshot)
  const setFormat = (sheet: string, pattern: string) => {
    const id = `user-format-${Object.keys(grid.snapshot.styles).length}`
    grid.snapshot.styles[id] = { ...styleOf(sheet), n: { pattern } }
    grid.snapshot.sheets[sheet].cellData[0][0].s = id
    grid.listener({ id: 'sheet.mutation.set.numfmt', params: { subUnitId: sheet, trigger: 'sheet.command.numfmt.set.numfmt' } })
  }
  setFormat(summary, '#,##0.0000')
  calculate()
  await vi.waitFor(() => expect(draft.operations).toMatchObject([{ kind: 'applyCellEdits', edits: [{ sheetName: 'Summary', writeValue: false, style: { numberFormat: '#,##0.0000' } }] }]))
  expect((draft.operations[0] as any).edits).toHaveLength(1)
  const after = structuredClone(grid.snapshot)
  grid.snapshot = before
  grid.listener({ id: 'sheet.mutation.set.numfmt', params: { trigger: 'univer.command.undo' } })
  await vi.waitFor(() => expect(draft.operations).toEqual([]))
  grid.snapshot = after
  grid.listener({ id: 'sheet.mutation.set.numfmt', params: { trigger: 'univer.command.redo' } })
  await vi.waitFor(() => expect(draft.operations).toHaveLength(1))
  setFormat(details, 'General')
  calculate()
  await vi.waitFor(() => expect((draft.operations[0] as any).edits).toHaveLength(2))
  expect((draft.operations[0] as any).edits.find((edit: any) => edit.sheetName === 'Details')).toMatchObject({ writeValue: false, style: { numberFormat: 'General' } })
  expect(styleOf(details)).toMatchObject({ bl: 1, n: { pattern: 'General' } })
  first.shell.editor.inert = true
  calculate()
  expect(styleOf(details).n.pattern).toBe('General')
  first.view?.dispose()
  const recovered = new NativeDraft(identity, storage)
  let payload: NativeSaveRequest | undefined
  const restored = await open(recovered, async request => { payload = request; throw Error('inspect payload') })
  calculate()
  await Promise.resolve(); await Promise.resolve()
  expect(recovered.operations).toEqual(draft.operations)
  restored.shell.save.click()
  await vi.waitFor(() => expect(payload).toBeDefined())
  const edits = (payload!.operations[0] as any).edits
  expect(edits).toHaveLength(2)
  expect(edits.find((edit: any) => edit.sheetName === 'Summary').style).toEqual({ numberFormat: '#,##0.0000' })
  expect(edits.find((edit: any) => edit.sheetName === 'Details').style).toEqual({ numberFormat: 'General' })
  const saved = await readWorkbook(await applyWorkbookOperations(source, payload!.operations))
  expect(saved.sheets[1].cells.A1.formula).toBe('=Summary!A1')
  expect(saved.sheets[0].cells.A1.value).toBe(1234.567)
  restored.view?.dispose()
})
