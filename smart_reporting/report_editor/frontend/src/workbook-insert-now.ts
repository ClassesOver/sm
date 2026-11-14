import { hasWorkbookModal, isWorkbookGridKeyTarget } from './workbook-shortcut-target'

export type InsertNowKind = 'date' | 'time'
const DAY_MS = 86_400_000
const EPOCH_1900_MS = Date.UTC(1899, 11, 30)
const DATE_1904_OFFSET = 1462

export function insertNowCellEdit(sheetName: string, row: number, column: number, kind: InsertNowKind,
  now = new Date(), date1904 = false): { kind: 'applyCellEdits'; edits: { sheetName: string; row: number; column: number;
    writeValue: true; cell: { value: number }; style: { numberFormat: string } }[] } {
  if (!sheetName || !Number.isSafeInteger(row) || row < 0 || !Number.isSafeInteger(column) || column < 0) throw new Error('活动单元格身份无效')
  const localAsUtc = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate(), now.getHours(), now.getMinutes(), now.getSeconds())
  const serial = (localAsUtc - EPOCH_1900_MS) / DAY_MS
  const time = kind === 'time'
  return { kind: 'applyCellEdits', edits: [{ sheetName, row, column, writeValue: true,
    cell: { value: time ? serial - Math.floor(serial) : Math.floor(serial) - (date1904 ? DATE_1904_OFFSET : 0) },
    style: { numberFormat: time ? 'h:mm' : 'yyyy/m/d' } }] }
}

export function installInsertNowShortcuts(host: HTMLElement, editable: () => boolean, cellEditing: () => boolean,
  command: (kind: InsertNowKind) => void): { dispose(): void } {
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.defaultPrevented || event.isComposing || event.keyCode === 229 || event.code !== 'Semicolon' || event.altKey ||
      !(event.ctrlKey || event.metaKey) || event.ctrlKey && event.metaKey || !editable() || cellEditing() ||
      !isWorkbookGridKeyTarget(event.target) || hasWorkbookModal(host.ownerDocument)) return
    event.preventDefault()
    command(event.shiftKey ? 'time' : 'date')
  }
  window.addEventListener('keydown', onKeyDown)
  return { dispose() { window.removeEventListener('keydown', onKeyDown) } }
}
