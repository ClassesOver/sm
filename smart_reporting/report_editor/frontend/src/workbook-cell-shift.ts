/**
 * Insert Cells / Delete Cells (fixed source GenOffice f8c17004
 * `apps/sheets/src/renderer/insert-delete-cells.ts` + `InsertDeleteCellsDialog.tsx`):
 * a whole-row or whole-column selection inserts/removes those lines at once;
 * any other selection asks how to shift the neighbours. The grid runs the same
 * official Univer commands; the save journals each shift as the engine's
 * `applyCellShift` (Univer has no dedicated mutation for it, so the command and
 * its undo element are tracked instead).
 */
import { formatAddress } from '@sheets-web/xlsx-engine'
import { createModal } from './modal'

export type CellsMode = 'insert' | 'delete'
export type CellsChoice = 'shift-horizontal' | 'shift-vertical' | 'entire-row' | 'entire-column'
export type CellShiftDirection = 'right' | 'down' | 'left' | 'up'
export const CELLS_CHOICES: readonly CellsChoice[] = ['shift-horizontal', 'shift-vertical', 'entire-row', 'entire-column']
export const DEFAULT_CELLS_CHOICE: CellsChoice = 'shift-vertical'

export const INSERT_ROWS_COMMAND = 'sheet.command.insert-row-before'
export const INSERT_COLS_COMMAND = 'sheet.command.insert-col-before'
export const REMOVE_ROWS_COMMAND = 'sheet.command.remove-row'
export const REMOVE_COLS_COMMAND = 'sheet.command.remove-col'
/** Univer range-shift commands → engine shift direction. */
export const CELL_SHIFT_COMMANDS: Readonly<Record<string, CellShiftDirection>> = {
  'sheet.command.insert-range-move-right': 'right',
  'sheet.command.insert-range-move-down': 'down',
  'sheet.command.delete-range-move-left': 'left',
  'sheet.command.delete-range-move-up': 'up',
}

export function cellsCommandId(mode: CellsMode, choice: CellsChoice): string {
  switch (choice) {
    case 'entire-row': return mode === 'insert' ? INSERT_ROWS_COMMAND : REMOVE_ROWS_COMMAND
    case 'entire-column': return mode === 'insert' ? INSERT_COLS_COMMAND : REMOVE_COLS_COMMAND
    case 'shift-horizontal': return mode === 'insert' ? 'sheet.command.insert-range-move-right' : 'sheet.command.delete-range-move-left'
    case 'shift-vertical': return mode === 'insert' ? 'sheet.command.insert-range-move-down' : 'sheet.command.delete-range-move-up'
  }
}

export interface CellRange { startRow: number; endRow: number; startColumn: number; endColumn: number; rangeType?: number }
export interface SelectionShape { readonly range: CellRange; readonly rowCount: number; readonly columnCount: number }
// Univer RANGE_TYPE: NORMAL 0, ROW 1, COLUMN 2, ALL 3.
export const isWholeRowSelection = ({ range, columnCount }: SelectionShape) =>
  range.rangeType === 1 || range.rangeType === 3 || (range.startColumn <= 0 && range.endColumn >= columnCount - 1)
export const isWholeColumnSelection = ({ range, rowCount }: SelectionShape) =>
  range.rangeType === 2 || range.rangeType === 3 || (range.startRow <= 0 && range.endRow >= rowCount - 1)

export type CellsDecision = { kind: 'direct'; choice: CellsChoice } | { kind: 'dialog' }
/** Whole rows/columns act at once like Excel; anything else needs the dialog. */
export function decideCellsAction(shape: SelectionShape): CellsDecision {
  if (isWholeRowSelection(shape)) return { kind: 'direct', choice: 'entire-row' }
  if (isWholeColumnSelection(shape)) return { kind: 'direct', choice: 'entire-column' }
  return { kind: 'dialog' }
}

/** Univer's insert-before commands count from `value`; range shifts take the captured range. */
export function cellsCommandParams(mode: CellsMode, choice: CellsChoice, range: CellRange): Record<string, unknown> | undefined {
  const plain = { startRow: range.startRow, endRow: range.endRow, startColumn: range.startColumn, endColumn: range.endColumn }
  if (choice === 'shift-horizontal' || choice === 'shift-vertical') return { range: plain }
  if (mode !== 'insert') return undefined
  return { value: choice === 'entire-row' ? range.endRow - range.startRow + 1 : range.endColumn - range.startColumn + 1 }
}

export const cellShiftRange = (range: CellRange) => {
  const first = formatAddress(range.startRow, range.startColumn), last = formatAddress(range.endRow, range.endColumn)
  return first === last ? first : `${first}:${last}`
}

/** One journaled shift; `element` is its Univer undo element, so a real Undo/Redo drops/restores it. */
export interface CellShiftEntry { readonly sheetId: string; readonly cellShift: { range: string; shift: CellShiftDirection }; readonly element: unknown }

const LABELS: Record<CellsMode, Record<CellsChoice, string>> = {
  insert: { 'shift-horizontal': '活动单元格右移', 'shift-vertical': '活动单元格下移', 'entire-row': '整行', 'entire-column': '整列' },
  delete: { 'shift-horizontal': '右侧单元格左移', 'shift-vertical': '下方单元格上移', 'entire-row': '整行', 'entire-column': '整列' },
}

export function createCellsDialog(root: HTMLElement, apply: (mode: CellsMode, choice: CellsChoice) => void) {
  let mode: CellsMode = 'insert'
  const modal = createModal({ root, label: '插入或删除单元格', overlayClass: 'workbook-ribbon-format-overlay', cardClass: 'workbook-ribbon-format-dialog workbook-ribbon-cells-dialog', closeLabel: '关闭', content: `
    <h2 class="workbook-ribbon-cells-title"></h2><form class="workbook-ribbon-format-form">
      <fieldset class="workbook-ribbon-cells-choices" role="radiogroup">${CELLS_CHOICES.map(choice =>
        `<label><input type="radio" name="workbook-cells-choice" value="${choice}"><span data-choice-label="${choice}"></span></label>`).join('')}</fieldset>
      <p class="workbook-ribbon-format-error" role="alert"></p>
      <div class="workbook-ribbon-format-actions"><button type="button" class="workbook-ribbon-format-cancel">取消</button><button type="submit" class="workbook-ribbon-format-apply">确定</button></div>
    </form>` })
  const error = modal.card.querySelector<HTMLElement>('[role="alert"]')!
  const radios = [...modal.card.querySelectorAll<HTMLInputElement>('input[type="radio"]')]
  modal.card.querySelector('.workbook-ribbon-format-cancel')!.addEventListener('click', modal.close)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    const choice = radios.find(radio => radio.checked)?.value as CellsChoice | undefined
    try { apply(mode, choice ?? DEFAULT_CELLS_CHOICE); modal.close() } catch (cause) { error.textContent = (cause as Error).message }
  })
  return {
    open(next: CellsMode) {
      mode = next
      const title = next === 'insert' ? '插入' : '删除'
      modal.card.querySelector('.workbook-ribbon-cells-title')!.textContent = title
      modal.card.querySelector('fieldset')!.setAttribute('aria-label', title)
      for (const choice of CELLS_CHOICES) modal.card.querySelector(`[data-choice-label="${choice}"]`)!.textContent = LABELS[next][choice]
      const initial = radios.find(radio => radio.value === DEFAULT_CELLS_CHOICE)!
      radios.forEach(radio => { radio.checked = radio === initial })
      error.textContent = ''
      modal.open(initial)
    },
    dispose: modal.remove,
  }
}
