import { afterEach, expect, it } from 'vitest'
import { Univer, UniverInstanceType, ICommandService, IUniverInstanceService, LocaleType } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { UniverSheetsNotePlugin } from '@univerjs/sheets-note'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-note/facade'
import { applySheetNotes, createBlankWorkbook, readWorkbook, sha256Hex, type WorkbookModel } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { NativeDraft, type NativeDraftIdentity, type NativeOperation } from './native-draft'
import { buildWorkbookData } from './workbook-vendor/core/univer-data'
import { adjacentNote, captureNoteTarget, createNoteDialog, noteSource, validateNoteBudget, validateNoteCommand, validateNoteTarget, validateNoteText, withWorkbookNotes, workbookNoteOperations, type GridNote, type NoteWorkbook } from './workbook-notes'

const storage = () => { const data = new Map<string, string>(); return { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => { data.set(key, value) }, removeItem: (key: string) => { data.delete(key) } } }
async function fixture() {
  const bytes = await applySheetNotes(await createBlankWorkbook(), 'Sheet1', [
    { row: 0, column: 0, author: 'Alice', text: '<script>source</script>\n第二行' },
    { row: 2, column: 1, author: 'Bob', text: 'untouched' },
  ])
  const model = await readWorkbook(bytes)
  return { bytes, model }
}
/** Mimics the documented public facade only. It does not claim to emulate Univer command history. */
function facade(model: WorkbookModel) {
  let notes: GridNote[] = model.sheets[0]!.notes!.notes.map(n => ({ id: `legacy-${n.row}-${n.column}`, row: n.row, col: n.column, note: n.text, width: 240, height: 140, show: false }))
  let selection = { row: 0, column: 0, height: 1, width: 1 }
  const identity = {}
  const sheet = { getSheetId: () => 'sheet-0', getSheetName: () => 'Sheet1', getNotes: () => structuredClone(notes),
    getSelection: () => ({ getActiveRange: () => ({ getRow: () => selection.row, getColumn: () => selection.column, getHeight: () => selection.height, getWidth: () => selection.width }) }),
    getRange: (row: number, col: number) => ({ getNote: () => notes.find(n => n.row === row && n.col === col) ?? null }), setActiveSelection() {} }
  const workbook: NoteWorkbook = { getId: () => 'book', getWorkbook: () => identity, getActiveSheet: () => sheet, getSheets: () => [sheet], getSheetBySheetId: id => id === 'sheet-0' ? sheet : null }
  return { workbook, setNotes: (next: GridNote[]) => { notes = structuredClone(next) }, select: (next: typeof selection) => { selection = next } }
}
afterEach(() => document.body.replaceChildren())

it('projects real source notes to the official SHEET_NOTE_PLUGIN sheet/row/column resource without interpreting HTML', async () => {
  const { model } = await fixture()
  const projected = withWorkbookNotes(buildWorkbookData(model, 'book', 'book'), model) as any
  const resource = projected.resources.find((r: any) => r.name === 'SHEET_NOTE_PLUGIN')
  const value = JSON.parse(resource.data)
  expect(value['sheet-0'][0][0]).toMatchObject({ row: 0, col: 0, note: '<script>source</script>\n第二行', show: false })
  expect(value['sheet-0'][2][1].note).toBe('untouched')
  expect(Object.keys(value['sheet-0'])).toEqual(['0', '2'])
})

it('preserves unrelated preset resources and replaces a stale note resource only once', async () => {
  const { model } = await fixture()
  const data = Object.assign(buildWorkbookData(model, 'book', 'book'), { resources: [
    { name: 'DRAWING_PLUGIN', data: '{"keep":true}' }, { name: 'SHEET_NOTE_PLUGIN', data: '{}' },
  ] })
  const projected = withWorkbookNotes(data, model) as any
  expect(projected.resources.filter((r: any) => r.name === 'SHEET_NOTE_PLUGIN')).toHaveLength(1)
  expect(projected.resources.find((r: any) => r.name === 'DRAWING_PLUGIN')).toEqual({ name: 'DRAWING_PLUGIN', data: '{"keep":true}' })
})

it('diffs one cell rather than replacing the collection, preserving author identity and untouched notes on actual engine replay', async () => {
  const { bytes, model } = await fixture(), grid = facade(model)
  const next = grid.workbook.getActiveSheet()!.getNotes()
  next[0]!.note = 'edited $& <xml>'
  grid.setNotes(next)
  const operations = workbookNoteOperations(model, grid.workbook)
  expect(operations).toEqual([{ kind: 'patchSheetNotes', sheetName: 'Sheet1', sourceIdentity: model.sheets[0]!.notes!.sourceIdentity, changes: [{ row: 0, column: 0, text: 'edited $& <xml>' }] }])
  const reopened = await readWorkbook(await applyWorkbookOperations(bytes, operations))
  expect(reopened.sheets[0]!.notes!.notes).toEqual([{ row: 0, column: 0, author: 'Alice', text: 'edited $& <xml>' }, { row: 2, column: 1, author: 'Bob', text: 'untouched' }])
})

it('freezes the original cell through selection changes and rejects changed note, workbook identity and edit lock', async () => {
  const { model } = await fixture(), grid = facade(model), captured = captureNoteTarget(grid.workbook)!
  grid.select({ row: 2, column: 1, height: 1, width: 1 })
  expect(validateNoteTarget(captured, grid.workbook, true)).toBe(grid.workbook.getActiveSheet())
  expect(captured.row).toBe(0)
  expect(() => validateNoteTarget(captured, grid.workbook, false)).toThrow('不可编辑')
  expect(() => validateNoteTarget(captured, facade(model).workbook, true)).toThrow('失效')
  const notes = grid.workbook.getActiveSheet()!.getNotes(); notes[0]!.note = 'changed elsewhere'; grid.setNotes(notes)
  expect(() => validateNoteTarget(captured, grid.workbook, true)).toThrow('已变化')
  grid.select({ row: 0, column: 0, height: 2, width: 1 })
  expect(() => captureNoteTarget(grid.workbook)).toThrow('单个单元格')
})

it('renders source author/text literally in the reusable modal and applies the captured target', async () => {
  const { model } = await fixture(), grid = facade(model), captured = captureNoteTarget(grid.workbook)!
  const received: unknown[] = []
  const dialog = createNoteDialog(document.body, (target, text) => received.push({ target, text }))
  dialog.open(captured, model.sheets[0]!.notes!)
  expect(document.body.querySelector('script')).toBeNull()
  expect(document.body.querySelector('textarea')!.value).toBe('<script>source</script>\n第二行')
  expect(document.body.querySelector('.workbook-ribbon-note-author')!.textContent).toBe('作者：Alice')
  grid.select({ row: 2, column: 1, height: 1, width: 1 })
  document.body.querySelector('textarea')!.value = 'modal edit'
  document.body.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
  expect(received).toEqual([{ target: captured, text: 'modal edit' }])
  dialog.dispose()
})

it('keeps note navigation ordered when selection is not itself a note and validates mutation identity and coordinates', async () => {
  const { model } = await fixture(), grid = facade(model)
  grid.select({ row: 20, column: 20, height: 1, width: 1 })
  expect(adjacentNote(grid.workbook.getActiveSheet()!.getNotes(), 20, 20, false)).toMatchObject({ row: 2, col: 1 })
  expect(adjacentNote(grid.workbook.getActiveSheet()!.getNotes(), 20, 20, true)).toMatchObject({ row: 0, col: 0 })
  const valid = { id: 'legacy-0-0', row: 0, col: 0, note: 'new text', width: 240, height: 140 }
  expect(() => validateNoteCommand(grid.workbook, { id: 'sheet.mutation.update-note', params: { unitId: 'foreign', sheetId: 'sheet-0', row: 0, col: 0, note: valid } })).toThrow('身份')
  expect(() => validateNoteCommand(grid.workbook, { id: 'sheet.mutation.update-note', params: { unitId: 'book', sheetId: 'sheet-0', row: 0, col: 1, note: valid } })).toThrow('身份')
  expect(() => validateNoteCommand(grid.workbook, { id: 'sheet.mutation.update-note', params: { unitId: 'book', sheetId: 'sheet-0', row: -1, col: 0, note: valid } })).toThrow('坐标')
})

it('enforces source refusal and notes text/collection/draft budgets before generating payloads', async () => {
  const { model } = await fixture(), grid = facade(model)
  expect(validateNoteText('')).toBe('')
  expect(() => validateNoteText('x'.repeat(32768))).toThrow('32767')
  expect(() => validateNoteText('x\u0000')).toThrow('控制字符')
  expect(() => validateNoteBudget(Array.from({ length: 451 }, () => ({ kind: 'patchSheetNotes' })), [], 0)).toThrow('预算')
  expect(() => validateNoteBudget([{ kind: 'patchSheetNotes', changes: [{ text: 'x'.repeat(8 * 1024 * 1024) }] }], [], 0)).toThrow('预算')
  const budgetNote = (row: number): GridNote => ({ id: `budget-${row}`, row, col: 0, note: 'x'.repeat(32767), width: 240, height: 140 })
  const original = grid.workbook.getActiveSheet()!.getNotes()
  grid.setNotes(Array.from({ length: 33 }, (_, row) => budgetNote(row)))
  expect(() => workbookNoteOperations(model, grid.workbook)).toThrow('预算')
  grid.setNotes(Array.from({ length: 1001 }, (_, row) => ({ ...budgetNote(row), note: 'x' })))
  expect(() => workbookNoteOperations(model, grid.workbook)).toThrow('预算')
  grid.setNotes(original)
  const notes = grid.workbook.getActiveSheet()!.getNotes(); grid.setNotes([...notes, notes[0]!])
  expect(() => workbookNoteOperations(model, grid.workbook)).toThrow('重复')
  model.sheets[0]!.notes!.readOnlyReason = '线程批注不支持'
  expect(() => noteSource(model, 'Sheet1')).toThrow('线程批注')
  expect(() => workbookNoteOperations(model, grid.workbook)).toThrow('线程批注')
})

it('NativeDraft undo/redo and refresh retain actual notes operations, source hash and failed-save retry identity', async () => {
  const { bytes, model } = await fixture(), grid = facade(model), store = storage()
  const identity: NativeDraftIdentity = { documentId: 'notes', revision: 1, sourceSha256: sha256Hex(bytes), scope: { database: 'test', companyId: 'c', userId: 'u', threadId: 't' } }
  const draft = new NativeDraft(identity, store, () => 'notes-request')
  const notes = grid.workbook.getActiveSheet()!.getNotes(); notes[0]!.note = 'restore me'; notes.splice(1, 1); grid.setNotes(notes)
  const operations = workbookNoteOperations(model, grid.workbook) as NativeOperation[]
  draft.setOperations(operations)
  draft.undo(); expect(draft.operations).toEqual([])
  draft.redo(); expect(draft.operations).toEqual(operations)
  const request = draft.beginSave(); draft.saveFailed()
  const recovered = new NativeDraft(identity, store, () => 'different-request')
  expect(recovered.operations).toEqual(operations)
  expect(recovered.beginSave()).toEqual(request)
  const replayed = await applyWorkbookOperations(bytes, request.operations)
  const readback = await readWorkbook(replayed)
  expect(readback.sheets[0]!.notes!.notes).toEqual([{ row: 0, column: 0, author: 'Alice', text: 'restore me' }])
  const resource = withWorkbookNotes(buildWorkbookData(readback, 'book', 'book'), readback) as any
  expect(JSON.parse(resource.resources.find((r: any) => r.name === 'SHEET_NOTE_PLUGIN').data)['sheet-0'][0][0].note).toBe('restore me')
  expect(request.expectedSha256).toBe(sha256Hex(bytes))
  expect(new NativeDraft({ ...identity, sourceSha256: 'f'.repeat(64) }, store).operations).toEqual([])
  expect(sha256Hex(bytes)).toBe(identity.sourceSha256)
})


it('official Univer 0.25.1 resource loading and note commands perform actual Undo/Redo and preserve engine save payload', async () => {
  const { bytes, model } = await fixture()
  const univer = new Univer({ locale: LocaleType.ZH_CN })
  try {
    univer.registerPlugin(UniverSheetsPlugin)
    univer.registerPlugin(UniverSheetsNotePlugin)
    univer.createUnit(UniverInstanceType.UNIVER_SHEET, withWorkbookNotes(buildWorkbookData(model, 'notes-book', 'Notes'), model))
    const api = FUniver.newAPI(univer)
    const workbook = api.getActiveWorkbook()!
    const sheet = workbook.getActiveSheet()!
    const commands = univer.__getInjector().get(ICommandService)
    // A real browser focuses the canvas; headless command history needs the same unit focus.
    univer.__getInjector().get(IUniverInstanceService).focusUnit(workbook.getId())
    expect(sheet.getNotes()).toHaveLength(2)
    expect(sheet.getRange(0, 0).getNote()?.note).toBe('<script>source</script>\n第二行')
    expect(commands.syncExecuteCommand('sheet.command.update-note', { unitId: workbook.getId(), subUnitId: sheet.getSheetId(), row: 0, col: 0, note: { note: 'official edited', width: 240, height: 140 } })).toBe(true)
    expect(sheet.getRange(0, 0).getNote()?.note).toBe('official edited')
    expect(commands.syncExecuteCommand('univer.command.undo')).toBe(true)
    expect(sheet.getRange(0, 0).getNote()?.note).toBe('<script>source</script>\n第二行')
    expect(workbookNoteOperations(model, workbook as unknown as NoteWorkbook)).toEqual([])
    expect(commands.syncExecuteCommand('univer.command.redo')).toBe(true)
    const operations = workbookNoteOperations(model, workbook as unknown as NoteWorkbook)
    expect(operations).toMatchObject([{ kind: 'patchSheetNotes', changes: [{ row: 0, column: 0, text: 'official edited' }] }])
    const actual = await readWorkbook(await applyWorkbookOperations(bytes, operations))
    expect(actual.sheets[0]!.notes!.notes[0]).toEqual({ row: 0, column: 0, author: 'Alice', text: 'official edited' })
    expect(actual.sheets[0]!.notes!.notes[1]!.author).toBe('Bob')
  } finally { univer.dispose() }
})

it('sort-swapped notes followed by an edit on a move endpoint replay to exactly the visible notes', async () => {
  // Codex 场景：A1=x、A2=y 排序互换后再把 A1 改为 z。旧差分只发出 A1→A2 移动，
  // 丢掉 z 编辑；保存成功但回放结果与网格不一致。
  const bytes = await applySheetNotes(await createBlankWorkbook(), 'Sheet1', [
    { row: 0, column: 0, author: 'Alice', text: 'x' },
    { row: 1, column: 0, author: 'Bob', text: 'y' },
    { row: 4, column: 2, author: 'Carol', text: 'p' },
    { row: 5, column: 2, author: 'Dan', text: 'q' },
  ])
  const model = await readWorkbook(bytes), grid = facade(model)
  const note = (row: number, col: number, text: string): GridNote => ({ id: `n-${row}-${col}`, row, col, note: text, width: 240, height: 140, show: false })
  // 第二对 C5/C6 只互换不编辑：仍按移动保存，作者随批注迁移。
  grid.setNotes([note(0, 0, 'z'), note(1, 0, 'x'), note(4, 2, 'q'), note(5, 2, 'p')])
  const operations = workbookNoteOperations(model, grid.workbook)
  const reopened = await readWorkbook(await applyWorkbookOperations(bytes, operations))
  expect(reopened.sheets[0]!.notes!.notes.map(({ row, column, text }) => ({ row, column, text }))).toEqual([
    { row: 0, column: 0, text: 'z' }, { row: 1, column: 0, text: 'x' }, { row: 4, column: 2, text: 'q' }, { row: 5, column: 2, text: 'p' },
  ])
  expect(reopened.sheets[0]!.notes!.notes.filter(n => n.column === 2).map(n => n.author)).toEqual(['Dan', 'Carol'])
  // 纯互换（无编辑）依旧只产生移动，不退化为文本改写。
  grid.setNotes([note(0, 0, 'y'), note(1, 0, 'x'), note(4, 2, 'p'), note(5, 2, 'q')])
  const [swap] = workbookNoteOperations(model, grid.workbook) as [{ changes: object[] }]
  expect(swap.changes).toHaveLength(2)
  expect(swap.changes).toEqual(expect.arrayContaining([{ fromRow: 0, fromColumn: 0, toRow: 1, toColumn: 0 }, { fromRow: 1, fromColumn: 0, toRow: 0, toColumn: 0 }]))
  expect(swap.changes.every(change => 'fromRow' in change)).toBe(true)
})
