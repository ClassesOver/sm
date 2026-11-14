import type { WorkbookModel, SheetNotesModel } from '@sheets-web/xlsx-engine'
import { NOTE_LIMIT, NOTE_TEXT_LIMIT, noteKey } from '@sheets-web/xlsx-engine'
import { createModal } from './modal'
import type { WorkbookOperation } from './workbook-draft'
import type { UniverWorkbookData } from './workbook-vendor/core/univer-data'

export interface GridNote { id: string; row: number; col: number; note: string; width: number; height: number; show?: boolean }
export interface NoteSheet {
  getSheetId(): string; getSheetName(): string
  getNotes(): GridNote[]
  getSelection(): { getActiveRange(): { getRow(): number; getColumn(): number; getHeight(): number; getWidth(): number } | null } | null
  getRange(row: number, col: number): { getNote(): GridNote | null }
  setActiveSelection(range: ReturnType<NoteSheet['getRange']>): unknown
}
export interface NoteWorkbook {
  getId(): string; getWorkbook(): unknown; getActiveSheet(): NoteSheet | null
  getSheets(): NoteSheet[]; getSheetBySheetId(id: string): NoteSheet | null
}
export function validateNoteCoordinates(row: number, column: number): void {
  if (!Number.isSafeInteger(row) || row < 0 || row > 1048575 || !Number.isSafeInteger(column) || column < 0 || column > 16383) throw new Error('批注目标坐标无效')
}
export function adjacentNote(notes: GridNote[], row: number, column: number, next: boolean): GridNote | undefined {
  const ordered = [...notes].sort((a, b) => a.row - b.row || a.col - b.col)
  return next
    ? ordered.find(note => note.row > row || note.row === row && note.col > column) ?? ordered[0]
    : ordered.reverse().find(note => note.row < row || note.row === row && note.col < column) ?? ordered[0]
}
export function validateNoteCommand(workbook: NoteWorkbook | null, command: { id: string; params?: unknown }): { sheet: NoteSheet; notes: GridNote[] } {
  if (!workbook) throw new Error('工作簿尚未就绪')
  const params = command.params as { unitId?: string; sheetId?: string; subUnitId?: string; row?: number; col?: number; noteId?: string; note?: GridNote; newPosition?: { row: number; col: number } } | undefined
  const mutation = command.id.startsWith('sheet.mutation.')
  if (params?.unitId !== undefined && params.unitId !== workbook.getId() || mutation && params?.unitId !== workbook.getId()) throw new Error('批注工作簿身份不匹配')
  if (params?.sheetId !== undefined && params?.subUnitId !== undefined && params.sheetId !== params.subUnitId) throw new Error('批注目标工作表身份不匹配')
  const id = params?.sheetId ?? params?.subUnitId
  const sheet = id !== undefined ? workbook.getSheetBySheetId(id) : mutation ? null : workbook.getActiveSheet()
  if (!sheet) throw new Error('批注目标工作表不存在')
  const notes = sheet.getNotes()
  if (command.id.endsWith('update-note')) {
    validateNoteCoordinates(params?.row!, params?.col!)
    validateNoteText(params?.note?.note!)
    const sameId = params?.note?.id === undefined ? undefined : notes.find(note => note.id === params.note!.id)
    if (sameId && (sameId.row !== params?.row || sameId.col !== params?.col)) throw new Error('批注目标身份或坐标不匹配')
    const proposed = notes.filter(note => note.row !== params!.row || note.col !== params!.col)
    proposed.push({ ...params!.note!, row: params!.row!, col: params!.col! })
    validateNoteCollection(proposed)
    return { sheet, notes: proposed }
  }
  if (params?.row !== undefined || params?.col !== undefined) validateNoteCoordinates(params.row!, params.col!)
  if (mutation) {
    const target = params?.noteId !== undefined ? notes.find(note => note.id === params.noteId) : notes.find(note => note.row === params?.row && note.col === params?.col)
    if (!target || params?.row !== undefined && (target.row !== params.row || target.col !== params.col)) throw new Error('批注目标身份或坐标不匹配')
    if (command.id.endsWith('update-note-position')) validateNoteCoordinates(params?.newPosition?.row!, params?.newPosition?.col!)
    if (command.id.endsWith('remove-note')) return { sheet, notes: notes.filter(note => note !== target) }
  }
  return { sheet, notes }
}
function validateNoteCollection(notes: GridNote[]): void {
  if (notes.length > NOTE_LIMIT || new Set(notes.map(note => noteKey(note.row, note.col))).size !== notes.length) throw new Error('批注集合超出预算或目标重复')
  let total = 0
  for (const note of notes) {
    validateNoteCoordinates(note.row, note.col)
    validateNoteText(note.note)
    total += note.note.length
  }
  if (total > 1024 * 1024) throw new Error('批注集合超出预算')
}
export interface NoteTarget { workbook: NoteWorkbook; sheetId: string; row: number; column: number; before: string }
export function captureNoteTarget(workbook: NoteWorkbook | null): NoteTarget | undefined {
  const sheet = workbook?.getActiveSheet(), range = sheet?.getSelection()?.getActiveRange()
  if (!workbook || !sheet || !range) return undefined
  if (range.getHeight() !== 1 || range.getWidth() !== 1) throw new Error('批注编辑仅支持单个单元格，请缩小选区')
  validateNoteCoordinates(range.getRow(), range.getColumn())
  return { workbook, sheetId: sheet.getSheetId(), row: range.getRow(), column: range.getColumn(), before: JSON.stringify(sheet.getRange(range.getRow(), range.getColumn()).getNote()) }
}
export function validateNoteTarget(target: NoteTarget, workbook: NoteWorkbook | null, editable: boolean): NoteSheet {
  if (!editable) throw new Error('当前工作簿不可编辑或正在保存')
  if (!workbook || target.workbook.getWorkbook() !== workbook.getWorkbook()) throw new Error('批注原选区已失效')
  validateNoteCoordinates(target.row, target.column)
  const sheet = workbook.getSheetBySheetId(target.sheetId)
  if (!sheet || JSON.stringify(sheet.getRange(target.row, target.column).getNote()) !== target.before) throw new Error('批注已变化，请重新打开后编辑')
  return sheet
}
export function noteSource(model: WorkbookModel | undefined, sheetName: string): SheetNotesModel {
  const source = model?.sheets.find(s => s.name === sheetName)?.notes
  if (!source || source.readOnlyReason || !source.sourceIdentity) throw new Error(source?.readOnlyReason ?? '批注来源尚未完成身份读取，请先保存并重新打开')
  return source
}
export function noteStructureReason(model: WorkbookModel | undefined, workbook: NoteWorkbook | null, command: { id: string; params?: unknown }): string | undefined {
  if (!/^sheet\.(?:command|mutation)\.(?:(?:insert|delete)-range(?:-|$)|move-range$|sort-range$|move-(?:row|rows|col|cols)(?:-|$)|(?:insert|remove)-(?:row|rows|col|cols)(?:-|$)|insert-multi-(?:rows|cols)(?:-|$))/.test(command.id)) return undefined
  // Sorts and row/column insert/remove relocate notes in-grid through the
  // official ref-range followers; the save pairs those moves and keeps authors.
  const params = command.params as { sheetId?: string; subUnitId?: string; from?: { subUnitId?: string }; to?: { subUnitId?: string } } | undefined
  const ids = [params?.sheetId, params?.subUnitId, params?.from?.subUnitId, params?.to?.subUnitId].filter((id): id is string => typeof id === 'string')
  const sheets = ids.length ? [...new Set(ids)].map(id => workbook?.getSheetBySheetId(id)) : [workbook?.getActiveSheet()]
  if (sheets.some(sheet => {
    if (!sheet) return false
    const modelSheet = model?.sheets.find(item => item.name === sheet.getSheetName())
    return !!modelSheet?.notes?.readOnlyReason || !!modelSheet?.threads?.threads.length
  })) return '此批注来源尚不支持当前结构修改；请保留批注原位置并使用受支持的行列插删'
}

export function withWorkbookNotes(data: UniverWorkbookData, model: WorkbookModel): UniverWorkbookData {
  const resource: Record<string, Record<number, Record<number, GridNote>>> = {}
  for (const sheet of Object.values(data.sheets)) {
    const source = model.sheets.find(s => s.name === sheet.name)?.notes
    if (!source || source.readOnlyReason && !(source as any).pictureProjection) continue
    for (const note of source.notes) {
      const row = ((resource[sheet.id] ??= {})[note.row] ??= {})
      row[note.column] = { id: `legacy-${note.row}-${note.column}`, row: note.row, col: note.column, note: note.text, width: 240, height: 140, show: false }
      sheet.rowCount = Math.max(sheet.rowCount, note.row + 1)
      sheet.columnCount = Math.max(sheet.columnCount, note.column + 1)
    }
  }
  const existing = (data as UniverWorkbookData & { resources?: { name: string; data: string }[] }).resources ?? []
  return Object.assign(data, { resources: [...existing.filter(item => item.name !== 'SHEET_NOTE_PLUGIN'), { name: 'SHEET_NOTE_PLUGIN', data: JSON.stringify(resource) }] })
}
export function workbookNoteOperations(model: WorkbookModel, workbook: NoteWorkbook | null): WorkbookOperation[] {
  const operations: WorkbookOperation[] = []
  for (const sheet of workbook?.getSheets() ?? []) {
    if (typeof sheet.getNotes !== 'function') continue
    const current = sheet.getNotes(), source = model.sheets.find(s => s.name === sheet.getSheetName())?.notes
    if (!source) { if (current.length) throw new Error('新增工作表请先保存后再编辑批注'); continue }
    if (source.readOnlyReason) {
      const projected = (source as any).pictureProjection && current.length === source.notes.length && current.every(note => source.notes.some(before => before.row === note.row && before.column === note.col && before.text === note.note))
      if (current.length && !projected) throw new Error(source.readOnlyReason)
      continue
    }
    const original = new Map(source.notes.map(n => [noteKey(n.row, n.column), n]))
    const latest = new Map(current.map(n => [noteKey(n.row, n.col), n]))
    validateNoteCollection(current)
    // Sorts and row/column followers relocate notes in-grid; a cyclic
    // permutation leaves every key occupied, so moves are paired by TEXT
    // across the unconsumed pools (the engine keeps the moved author). Keys
    // present on both sides with different text become in-place text edits.
    const unchangedSource = new Set<string>()
    for (const note of current) if (original.get(noteKey(note.row, note.col))?.text === note.note) unchangedSource.add(noteKey(note.row, note.col))
    const sourcePool = source.notes.filter(n => !unchangedSource.has(noteKey(n.row, n.column))).sort((a, b) => a.row - b.row || a.column - b.column)
    const livePool = current.filter(n => !unchangedSource.has(noteKey(n.row, n.col))).sort((a, b) => a.row - b.row || a.col - b.col)
    const moveOfLive = new Map<number, number>()
    const takenSource = new Set<number>()
    for (const [liveIndex, note] of livePool.entries()) {
      const match = sourcePool.findIndex((candidate, index) => !takenSource.has(index) && candidate.text === note.note)
      if (match >= 0) { moveOfLive.set(liveIndex, match); takenSource.add(match) }
    }
    for (const note of current) validateNoteText(note.note)
    // Text pairing only proposes moves; the patch must reproduce the WHOLE
    // final note collection. Simulate the engine's order-independent apply
    // (frees, then move targets) and diff that against the live grid: every
    // remaining mismatch becomes a plain edit/add/delete. The engine forbids
    // a plain change on any move endpoint, so a move whose endpoint still
    // needs a plain change (e.g. sort-swap A1/A2 then edit A1) is demoted to
    // in-place edits and the diff recomputed — losing at most the moved
    // author, never the visible text.
    let moves = [...moveOfLive].map(([liveIndex, sourceIndex]) => ({ from: sourcePool[sourceIndex]!, to: livePool[liveIndex]! }))
    let changes: ({ row: number; column: number; text: string | null } | { fromRow: number; fromColumn: number; toRow: number; toColumn: number })[]
    for (;;) {
      const state = new Map(source.notes.map(n => [noteKey(n.row, n.column), { row: n.row, column: n.column, text: n.text }]))
      for (const { from } of moves) state.delete(noteKey(from.row, from.column))
      for (const { from, to } of moves) state.set(noteKey(to.row, to.col), { row: to.row, column: to.col, text: from.text })
      const plain: { row: number; column: number; text: string | null }[] = []
      for (const note of current) if (state.get(noteKey(note.row, note.col))?.text !== note.note) plain.push({ row: note.row, column: note.col, text: note.note })
      for (const [key, note] of state) if (!latest.has(key)) plain.push({ row: note.row, column: note.column, text: null })
      const plainKeys = new Set(plain.map(change => noteKey(change.row, change.column)))
      const kept = moves.filter(({ from, to }) => !plainKeys.has(noteKey(from.row, from.column)) && !plainKeys.has(noteKey(to.row, to.col)))
      if (kept.length === moves.length) {
        changes = [...moves.map(({ from, to }) => ({ fromRow: from.row, fromColumn: from.column, toRow: to.row, toColumn: to.col })), ...plain]
        break
      }
      moves = kept
    }
    if (changes.length) operations.push({ kind: 'patchSheetNotes', sheetName: sheet.getSheetName(), sourceIdentity: source.sourceIdentity, changes })
  }
  return operations
}
export function validateNoteText(text: string): string {
  if (typeof text !== 'string' || text.length > NOTE_TEXT_LIMIT || /[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(text)) throw new Error('批注最多 32767 字符，且不能含无效控制字符')
  return text
}
export function validateNoteBudget(operations: WorkbookOperation[], staged: WorkbookOperation[], structuralCount: number): void {
  const all = [...staged, ...operations]
  if (all.length + structuralCount > 450 || new TextEncoder().encode(JSON.stringify(all)).length > 8 * 1024 * 1024) throw new Error('批注超出本地草稿预算，请先保存当前修改')
}
export function createNoteDialog(root: HTMLElement, apply: (target: NoteTarget, text: string) => void) {
  let target: NoteTarget | undefined
  let writable = true
  const modal = createModal({ root, label: '单元格批注', overlayClass: 'workbook-ribbon-note-overlay', cardClass: 'workbook-ribbon-note-dialog', closeLabel: '关闭批注', content: `
    <h2>单元格批注</h2><form class="workbook-ribbon-note-form workbook-ribbon-format-form">
      <p class="workbook-ribbon-note-author"></p>
      <label>批注内容<textarea maxlength="32767" rows="8" aria-describedby="workbook-ribbon-note-error"></textarea></label>
      <p id="workbook-ribbon-note-error" role="alert"></p>
      <div class="workbook-ribbon-note-actions"><button type="button">取消</button><button type="submit">应用</button></div>
    </form>` })
  const input = modal.card.querySelector('textarea')!, error = modal.card.querySelector<HTMLElement>('[role="alert"]')!
  modal.card.querySelector('form button[type="button"]')!.addEventListener('click', modal.close)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    try { if (!writable) throw new Error('当前批注仅供阅读'); if (!target) throw new Error('请先选择单元格'); apply(target, validateNoteText(input.value)); modal.close() }
    catch (cause) { error.textContent = (cause as Error).message; input.setAttribute('aria-invalid', 'true') }
  })
  return { open(captured: NoteTarget, source: SheetNotesModel, editable = true) {
    writable = editable
    input.readOnly = !editable
    modal.card.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled = !editable
    target = captured
    const current = captured.workbook.getSheetBySheetId(captured.sheetId)?.getRange(captured.row, captured.column).getNote()
    input.value = current?.note ?? ''; error.textContent = ''; input.removeAttribute('aria-invalid')
    modal.card.querySelector<HTMLElement>('.workbook-ribbon-note-author')!.textContent = `作者：${source.notes.find(n => n.row === captured.row && n.column === captured.column)?.author ?? '用户'}`
    modal.open(input)
  }, dispose: modal.remove }
}
