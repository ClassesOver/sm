import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { applyCellEdits, applyDefinedNames, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createWorkbookEditorView } from './workbook-main'
import { createNativeOfficeTransport } from './native-office-view'
import { NativeDraft, type NativeDraftIdentity, type NativeSaveRequest } from './native-draft'
import { createEditorShell } from './shell'

const grid = vi.hoisted(() => ({ snapshot: undefined as any, listener: (_command: any) => {} }))
vi.mock('@univerjs/core', () => ({ LocaleType: { ZH_CN: 'zhCN' }, mergeLocales: () => ({}) }))
vi.mock('@univerjs/preset-sheets-core', () => ({ UniverSheetsCorePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-find-replace', () => ({ UniverSheetsFindReplacePreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-drawing', () => ({ UniverSheetsDrawingPreset: () => ({}) }))
vi.mock('@univerjs/preset-sheets-table', () => ({ UniverSheetsTablePreset: () => ({}) }))
vi.mock('./workbook-ribbon', () => ({ mountWorkbookRibbon: () => ({ dispose() {} }), applyWorkbookRibbonCommand: () => false }))
vi.mock('./workbook-vendor/grid/decimal-step', () => ({ stepSelectionDecimals() {} }))
vi.mock('./workbook-vendor/grid/sparkline-render', () => ({ setSparklines() {} }))
vi.mock('./workbook-vendor/grid/chart-render', () => ({ setCharts() {} }))
vi.mock('./workbook-vendor/grid/create-univer', () => ({ createUniver: () => {
  const worksheet = { getSheetName: () => 'Sheet1' }
  const workbook = { getId: () => 'report-workbook', getSnapshot: () => grid.snapshot,
    getSheets: () => [worksheet], getSheetBySheetId: () => worksheet }
  return { univer: { dispose() {} }, univerAPI: { getActiveWorkbook: () => grid.snapshot ? workbook : null,
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

it('rejects an XLSX draft bound to a different source before applying its operations', async () => {
  const draft = new NativeDraft({ ...identity, sourceSha256: 'b'.repeat(64) }, store())
  draft.setOperations([{ kind: 'applyCellEdits', edits: [{ sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: '外来来源' } }] }])
  await expect(open(draft, async () => { throw Error('不应保存') })).rejects.toThrow('工作簿来源已变化')
  expect(grid.snapshot).toBeUndefined()
  expect(draft.operations[0]).toMatchObject({ edits: [{ cell: { value: '外来来源' } }] })
})
