import { afterEach, expect, it, vi } from 'vitest'
import { applyCellEdits, applySheetNotes, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
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
  await import('@univerjs/sheets/facade')
  await import('@univerjs/sheets-note/facade')
  return { createUniver: () => {
    const univer = new Univer({ locale: LocaleType.ZH_CN, locales: { [LocaleType.ZH_CN]: mergeLocales(CoreZhCN, NoteZhCN) } })
    grid.instances.push(univer)
    univer.registerPlugin(UniverSheetsPlugin)
    univer.registerPlugin(UniverSheetsNotePlugin)
    univer.registerPlugin(UniverSheetsSortPlugin)
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

const identity: NativeDraftIdentity = { documentId: 'main-notes', revision: 1, sourceSha256: 'a'.repeat(64),
  scope: { database: 'fixture', companyId: 'company', userId: 'user', threadId: 'thread' } }
const store = () => { const data = new Map<string, string>(); return { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => { data.set(key, value) }, removeItem: (key: string) => { data.delete(key) } } }
async function fixture() {
  return applySheetNotes(await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'keep value' } },
  ]), 'Sheet1', [
    { row: 0, column: 0, author: 'Alice', text: 'edit me' },
    { row: 2, column: 2, author: 'Bob', text: 'delete with row' },
    { row: 4, column: 4, author: 'Carol', text: 'delete with col' },
    { row: 6, column: 6, author: 'Dan', text: 'untouched' },
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
const params = () => ({ unitId: grid.api.getActiveWorkbook().getId(), subUnitId: sheet().getSheetId() })
const update = (text: string) => grid.api.syncExecuteCommand('sheet.command.update-note', { ...params(), row: 0, col: 0, note: { note: text, width: 240, height: 140 } })
const history = (direction: 'undo' | 'redo') => expect(grid.api.syncExecuteCommand(`univer.command.${direction}`)).toBe(true)
afterEach(() => {
  for (const instance of grid.instances.splice(0)) instance.dispose()
  grid.apply.mockClear()
  document.body.replaceChildren()
})

it('main captures real note patches and row/column insert/delete Undo Redo, refresh, failed-save retry and engine readback', async () => {
  const source = await fixture(), storage = store()
  let sequence = 0
  const newDraft = () => new NativeDraft(identity, storage, () => `note-request-${++sequence}`)
  const requests: NativeSaveRequest[] = []
  let downloaded: Uint8Array | undefined
  const save = async (request: NativeSaveRequest) => {
    requests.push(request)
    if (requests.length === 1) throw Error('network failed')
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/notes.xlsx' } }, validation: { issues: [] } }
  }
  const draft = newDraft(), first = await open(source, draft, save)
  const positionEvents: { params: any; options: any }[] = []
  grid.api.addEvent(grid.api.Event.BeforeCommandExecute, (event: any) => {
    if (event.id === 'sheet.mutation.update-note-position') positionEvents.push({ params: structuredClone(event.params), options: structuredClone(event.options ?? {}) })
  })
  expect(update('edited <literal>')).toBe(true)
  await vi.waitFor(() => expect(draft.operations).toMatchObject([{ kind: 'patchSheetNotes', changes: [{ row: 0, column: 0, text: 'edited <literal>' }] }]))
  history('undo')
  await vi.waitFor(() => expect(draft.operations).toEqual([]))
  history('redo')
  await vi.waitFor(() => expect(draft.operations).toHaveLength(1))
  sheet().insertRowsBefore(1, 1)
  expect(positionEvents.length).toBeGreaterThan(0)
  expect(positionEvents.every(event => event.params?.silent === true && event.options?.onlyLocal === true)).toBe(true)
  sheet().insertColumnsBefore(1, 1)
  sheet().deleteRows(3, 1)
  sheet().deleteColumns(5, 1)
  const finalNotes = () => sheet().getNotes().map((n: any) => ({ row: n.row, column: n.col, text: n.note })).sort((a: any, b: any) => a.row - b.row)
  const expected = [{ row: 0, column: 0, text: 'edited <literal>' }, { row: 6, column: 6, text: 'untouched' }]
  expect(finalNotes()).toEqual(expected)
  await vi.waitFor(() => expect(draft.operations.filter((op: any) => op.kind === 'applyRowColumnOps')).toHaveLength(4))
  for (let i = 0; i < 4; i++) history('undo')
  expect(sheet().getNotes()).toHaveLength(4)
  await vi.waitFor(() => expect(draft.operations).toMatchObject([{ kind: 'patchSheetNotes', changes: [{ row: 0, column: 0, text: 'edited <literal>' }] }]))
  expect(draft.operations).toHaveLength(1)
  for (let i = 0; i < 4; i++) history('redo')
  expect(finalNotes()).toEqual(expected)
  await vi.waitFor(() => expect(draft.operations.filter((op: any) => op.kind === 'applyRowColumnOps')).toHaveLength(4))
  const operations = structuredClone(draft.operations)
  expect(operations.at(-1)).toMatchObject({ kind: 'patchSheetNotes', changes: [{ row: 0, column: 0, text: 'edited <literal>' }] })
  first.view?.dispose()
  const recovered = newDraft(), second = await open(source, recovered, save)
  expect(finalNotes()).toEqual(expected)
  expect(recovered.operations).toEqual(operations)
  second.shell.save.click()
  await vi.waitFor(() => expect(second.shell.statusLabel.textContent).toContain('保存失败'))
  second.view?.dispose()
  const retried = newDraft(), third = await open(source, retried, save)
  expect(finalNotes()).toEqual(expected)
  third.shell.save.click()
  await vi.waitFor(() => expect(third.shell.statusLabel.textContent).toContain('已保存修订 2'))
  expect(requests[1]).toEqual(requests[0])
  const actual = await readWorkbook(downloaded!)
  expect(actual.sheets[0].cells.A1.value).toBe('keep value')
  expect(actual.sheets[0].notes!.notes).toEqual([
    { ...expected[0], author: 'Alice' }, { ...expected[1], author: 'Dan' },
  ])
  expect(retried.closed).toBe(true)
})

it('main does not dirty or replace failed retry identity for popup view mutations and permits read-only navigation without writes', async () => {
  const source = await fixture(), draft = new NativeDraft(identity, store())
  const requests: NativeSaveRequest[] = []
  const current = await open(source, draft, async request => { requests.push(request); throw Error('network failed') })
  const target = sheet().getRange(0, 0).getNote()
  const view = { unitId: params().unitId, sheetId: params().subUnitId, noteId: target.id }
  expect(grid.api.syncExecuteCommand('sheet.mutation.toggle-note-popup', view)).toBe(true)
  await Promise.resolve()
  expect(draft.operations).toEqual([])
  expect(current.shell.statusLabel.textContent).toBe('已保存')
  expect(update('retry me')).toBe(true)
  current.shell.save.click()
  await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toContain('保存失败'))
  expect(grid.api.syncExecuteCommand('sheet.mutation.toggle-note-popup', view)).toBe(true)
  current.shell.save.click()
  await vi.waitFor(() => expect(requests).toHaveLength(2))
  expect(requests[1]).toEqual(requests[0])
  await vi.waitFor(() => expect(current.shell.save.disabled).toBe(false))
  current.shell.editor.inert = true
  sheet().setActiveSelection(sheet().getRange('A1'))
  grid.ribbon('note-prev')
  expect(sheet().getSelection().getActiveRange().getRow()).toBe(6)
  const input = document.querySelector<HTMLTextAreaElement>('.workbook-ribbon-note-dialog textarea')!
  expect(input.readOnly).toBe(true)
  expect(document.querySelector<HTMLButtonElement>('.workbook-ribbon-note-dialog button[type="submit"]')!.disabled).toBe(true)
  input.value = 'must not write'
  input.closest('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(sheet().getRange(6, 6).getNote().note).toBe('untouched')
  sheet().setActiveSelection(sheet().getRange('B2'))
  grid.ribbon('note-prev')
  expect(sheet().getSelection().getActiveRange().getRow()).toBe(0)
  sheet().setActiveSelection(sheet().getRange('B2'))
  grid.ribbon('note-next')
  expect(sheet().getSelection().getActiveRange().getRow()).toBe(2)
})

it('main rejects invalid note target/budgets and accepts genuine note Undo/Redo; sort with notes is allowed and moves keep authors', async () => {
  const source = await fixture(), draft = new NativeDraft(identity, store())
  const current = await open(source, draft, async () => { throw Error('not saving') })
  const before = structuredClone(sheet().getNotes())
  const valid = { ...params(), row: 0, col: 0, note: { note: 'valid', width: 240, height: 140 } }
  for (const invalid of [
    { ...valid, unitId: 'foreign' }, { ...valid, subUnitId: 'missing' },
    { ...valid, sheetId: 'different' }, { ...valid, row: -1 }, { ...valid, col: 16384 },
    { ...valid, row: 0.5 }, { ...valid, note: { ...valid.note, note: 'x'.repeat(32768) } },
    { ...valid, note: { ...valid.note, id: before[1].id } },
    { ...valid, note: { ...valid.note, note: '\u0000' } },
  ]) expect(grid.api.syncExecuteCommand('sheet.command.update-note', invalid)).toBe(false)
  expect(sheet().getNotes()).toEqual(before)
  expect(draft.operations).toEqual([])
  expect(update('works')).toBe(true)
  history('undo'); history('redo')
  await vi.waitFor(() => expect(draft.operations).toMatchObject([{ kind: 'patchSheetNotes', changes: [{ text: 'works' }] }]))
  current.view?.dispose()
})

it('official sort with notes moves them in the payload and the engine keeps original authors', async () => {
  const source = await applySheetNotes(await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'c-alpha' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'a-beta' } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: 'b-gamma' } },
  ]), 'Sheet1', [
    { row: 0, column: 0, author: 'Alice', text: 'note-on-c-alpha' },
    { row: 2, column: 0, author: 'Bob', text: 'note-on-b-gamma' },
  ])
  const draft = new NativeDraft(identity, store())
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/sorted.xlsx' } }, validation: { issues: [] } }
  })
  const executed = grid.api.syncExecuteCommand('sheet.command.sort-range', {
    range: { startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 },
    orderRules: [{ colIndex: 0, type: 'asc' }],
    ...params(), hasTitle: false,
  })
  expect(executed).toBe(true)
  expect(sheet().getRange(0, 0, 3, 1).getValues().map((row: unknown[]) => row[0])).toEqual(['a-beta', 'b-gamma', 'c-alpha'])
  await vi.waitFor(() => {
    const patch = draft.operations.find((operation: any) => operation.kind === 'patchSheetNotes')
    if (!patch) return false
    expect(patch.sheetName).toBe('Sheet1')
    expect(Array.from(patch.changes as unknown[]).sort((a, b) => (a as any).fromRow - (b as any).fromRow)).toEqual([
      { fromRow: 0, fromColumn: 0, toRow: 2, toColumn: 0 },
      { fromRow: 2, fromColumn: 0, toRow: 1, toColumn: 0 },
    ])
    return true
  })
  current.shell.save.click()
  await vi.waitFor(() => expect(['已保存修订 2', '保存失败，草稿已保留'].some(label => current.shell.statusLabel.textContent.includes(label))).toBe(true))
  const actual = await readWorkbook(downloaded!)
  expect(actual.sheets[0].cells.A1.value).toBe('a-beta')
  expect(actual.sheets[0].notes!.notes).toEqual([
    { row: 1, column: 0, author: 'Bob', text: 'note-on-b-gamma' },
    { row: 2, column: 0, author: 'Alice', text: 'note-on-c-alpha' },
  ])
  current.view?.dispose()
})

it('main captures a standalone note cell migration as a move and the save keeps the original author', async () => {
  const source = await fixture(), draft = new NativeDraft(identity, store())
  const requests: NativeSaveRequest[] = []
  let downloaded: Uint8Array | undefined
  const current = await open(source, draft, async request => {
    requests.push(request)
    downloaded = await applyWorkbookOperations(source, request.operations)
    return { revision: 2, revisionRegistered: true, artifacts: { xlsx: { downloadUrl: '/notes.xlsx' } }, validation: { issues: [] } }
  })
  const note = sheet().getRange(0, 0).getNote()!
  expect(grid.api.syncExecuteCommand('sheet.mutation.update-note-position', {
    unitId: params().unitId, sheetId: params().subUnitId, noteId: note.id, newPosition: { row: 1, col: 1 },
  })).toBe(true)
  expect(sheet().getRange(0, 0).getNote()).toBeFalsy()
  expect(sheet().getRange(1, 1).getNote()?.note).toBe('edit me')
  await vi.waitFor(() => expect(draft.operations).toEqual([
    { kind: 'patchSheetNotes', sheetName: 'Sheet1', sourceIdentity: expect.any(String), changes: [
      { fromRow: 0, fromColumn: 0, toRow: 1, toColumn: 1 },
    ] },
  ]))
  sheet().getRange(2, 0).setValue('迁移后的其他单元格编辑')
  await vi.waitFor(() => expect(draft.operations).toEqual(expect.arrayContaining([
    { kind: 'applyCellEdits', edits: [{ sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: '迁移后的其他单元格编辑' } }] },
    { kind: 'patchSheetNotes', sheetName: 'Sheet1', sourceIdentity: expect.any(String), changes: [
      { fromRow: 0, fromColumn: 0, toRow: 1, toColumn: 1 },
    ] },
  ])))
  current.shell.save.click()
  await vi.waitFor(() => expect(current.shell.statusLabel.textContent).toContain('已保存修订 2'))
  const actual = await readWorkbook(downloaded!)
  expect(actual.sheets[0].cells.A3.value).toBe('迁移后的其他单元格编辑')
  expect(actual.sheets[0].notes!.notes.find(item => item.row === 1 && item.column === 1)).toEqual({ row: 1, column: 1, author: 'Alice', text: 'edit me' })
  expect(actual.sheets[0].notes!.notes.find(item => item.row === 0 && item.column === 0)).toBeUndefined()
  expect(actual.sheets[0].notes!.notes).toHaveLength(4)
})
