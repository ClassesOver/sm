import { afterEach, expect, it, vi } from 'vitest'
import { insertNowCellEdit, installInsertNowShortcuts } from './workbook-insert-now'

afterEach(() => document.body.replaceChildren())

it('builds static date/time edits for the active cell with the workbook date epoch', () => {
  const sheetName = 'Data'
  const date = new Date(2026, 10, 13, 9, 7, 5)
  const date1900 = insertNowCellEdit(sheetName, 4, 2, 'date', date, false)
  const date1904 = insertNowCellEdit(sheetName, 4, 2, 'date', date, true)
  const time = insertNowCellEdit(sheetName, 4, 2, 'time', date, false)
  expect(date1900).toEqual({ kind: 'applyCellEdits', edits: [{ sheetName, row: 4, column: 2, writeValue: true,
    cell: { value: (Date.UTC(2026, 10, 13, 9, 7, 5) - Date.UTC(1899, 11, 30)) / 86400000 | 0 },
    style: { numberFormat: 'yyyy/m/d' } }] })
  expect(date1904.edits[0]!.cell.value).toBe((date1900.edits[0]!.cell.value as number) - 1462)
  expect(time.edits[0]!.cell.value).toBeCloseTo((9 * 3600 + 7 * 60 + 5) / 86400)
  expect(time.edits[0]!.style).toEqual({ numberFormat: 'h:mm' })
})

it('dispatches source Ctrl/Cmd+semicolon date and shifted time only from an editable sheet target', () => {
  document.body.innerHTML = '<main><div id="workbook-grid"><canvas tabindex="0"></canvas></div><input><div contenteditable="true"></div></main>'
  const host = document.querySelector('main')!, grid = host.querySelector('#workbook-grid canvas')!
  let editable = true, editing = false
  const dispatch = vi.fn()
  const handle = installInsertNowShortcuts(host, () => editable, () => editing, dispatch)
  const press = (target: Element, init: KeyboardEventInit = {}) => {
    const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, code: 'Semicolon', ctrlKey: true, ...init })
    target.dispatchEvent(event)
    return event
  }
  expect(press(grid).defaultPrevented).toBe(true)
  expect(press(grid, { metaKey: true, ctrlKey: false, shiftKey: true }).defaultPrevented).toBe(true)
  expect(dispatch.mock.calls).toEqual([['date'], ['time']])
  for (const [target, init] of [
    [grid, { shiftKey: true, altKey: true }], [host.querySelector('input')!, {}],
    [host.querySelector('[contenteditable]')!, {}], [grid, { isComposing: true }],
    [grid, { keyCode: 229 }], [grid, { ctrlKey: false, metaKey: false }],
  ] as [Element, KeyboardEventInit][]) expect(press(target, init).defaultPrevented).toBe(false)
  editable = false; expect(press(grid).defaultPrevented).toBe(false)
  editable = true; editing = true; expect(press(grid).defaultPrevented).toBe(false)
  editing = false
  const dialog = document.createElement('div'); dialog.setAttribute('role', 'dialog'); host.append(dialog)
  expect(press(grid).defaultPrevented).toBe(false)
  expect(dispatch).toHaveBeenCalledTimes(2)
  handle.dispose(); dialog.remove()
  expect(press(grid).defaultPrevented).toBe(false)
})
