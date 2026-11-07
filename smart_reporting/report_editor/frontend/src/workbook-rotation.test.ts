import { expect, it, vi } from 'vitest'
import { applyCellEdits, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { buildWorkbookData } from './workbook-vendor/core/univer-data'
import { logicalStyleOf, toUniverStyle, fromUniverStyle, styleDelta } from './workbook-vendor/core/style-map'
import { diffToEdits } from './workbook-vendor/core/session-core'
import { ooxmlRotationToUniver, univerRotationToOoxml, ROTATION_VALUES } from './workbook-rotation'
import { applyWorkbookRibbonCommand, mountWorkbookRibbon, selectedWorkbookRotation, type RibbonWorkbook } from './workbook-ribbon'

it.each([[0, 0], [45, 45], [90, 90], [135, -45], [180, -90], [37, 37], [127, -37], [255, 'v']])('maps OOXML %s to Univer %s and preserves source unit semantics', (ooxml, angle) => {
  const tr = ooxmlRotationToUniver(Number(ooxml))!
  expect(tr).toEqual(angle === 'v' ? { a: 0, v: 1 } : { a: angle })
  expect(univerRotationToOoxml(tr)).toBe(ooxml)
  expect(fromUniverStyle(toUniverStyle({ textRotation: Number(ooxml) }))).toEqual({ textRotation: ooxml })
})
it('does not fabricate invalid angles or mistake unset/explicit normal rotation for an edit', () => {
  for (const value of [-1, 181, 254, 256, NaN, Infinity, 1.5]) expect(ooxmlRotationToUniver(value)).toBeUndefined()
  expect(univerRotationToOoxml({ a: -91 })).toBeUndefined()
  expect(univerRotationToOoxml(undefined)).toBeUndefined()
  expect(styleDelta(undefined, { textRotation: 0 })).toBeUndefined()
  expect(styleDelta({ textRotation: 135 }, {})).toBeUndefined()
  expect(styleDelta({ textRotation: 135 }, { textRotation: 0 })).toEqual({ textRotation: 0 })
})
it('routes exactly the six fixed-source rotation values through the registered Univer command callback', () => {
  const range = {}, workbook = { getActiveSheet: () => ({ getSelection: () => ({ getActiveRange: () => range }) }) } as RibbonWorkbook
  const rotate = vi.fn()
  for (const id of Object.keys(ROTATION_VALUES)) applyWorkbookRibbonCommand(id as never, workbook, undefined, rotate)
  expect(rotate.mock.calls).toEqual([[45], [-45], ['v'], [90], [-90], [0]])
  expect(() => applyWorkbookRibbonCommand('rotate:31' as never, workbook, undefined, rotate)).toThrow(/Unsupported/)
  expect(rotate).toHaveBeenCalledTimes(6)
})
it('refreshes active, mixed, no-selection and saving states without replacing the clicked control', () => {
  const host = document.createElement('div'), callback = vi.fn()
  let rotation: number | 'mixed' | undefined = 135, editable = true
  const ribbon = mountWorkbookRibbon(host, callback, { rotation: () => rotation, editable: () => editable })
  const button = host.querySelector<HTMLButtonElement>('[data-ribbon-command="rotate:-45"]')!
  expect(button.getAttribute('aria-pressed')).toBe('true')
  button.click(); expect(callback).toHaveBeenCalledWith('rotate:-45')
  rotation = 'mixed'; ribbon.refreshState()
  expect(button.getAttribute('aria-pressed')).toBe('false'); expect(button.disabled).toBe(false)
  editable = false; ribbon.refreshState(); expect(button.disabled).toBe(true)
  editable = true; rotation = undefined; ribbon.refreshState(); expect(button.disabled).toBe(true)
  rotation = 255; ribbon.refreshState()
  expect(host.querySelector('[data-ribbon-command="rotate:vertical"]')!.getAttribute('aria-pressed')).toBe('true')
  expect(host.querySelector('[data-ribbon-command="rotate:-45"]')).toBe(button)
  ribbon.dispose()
})
it('reads composed per-cell styles so mixed ranges never borrow the first cell active state', () => {
  let angles = [45, 45]
  const workbook = { getActiveSheet: () => ({ getSelection: () => ({ getActiveRange: () => ({ getHeight: () => 2, getWidth: () => 1, getRow: () => 0, getColumn: () => 0 }) }), getRange: (row: number) => ({ getCellStyleData: () => ({ tr: { a: angles[row] } }) }) }) } as unknown as RibbonWorkbook
  expect(selectedWorkbookRotation(workbook)).toBe(45)
  angles = [45, -45]; expect(selectedWorkbookRotation(workbook)).toBe('mixed')
  expect(selectedWorkbookRotation(null)).toBeUndefined()
})
it('roundtrips source/default/stacked rotation through import, readback, existing edit schema and actual XLSX bytes', async () => {
  const source = await applyCellEdits(await createBlankWorkbook(), [135, 255, 37].map((textRotation, column) => ({ sheetName: 'Sheet1', row: 0, column, writeValue: true, cell: { value: column === 2 ? 42 : `source-${column}` }, style: { textRotation, bold: true, numberFormat: '0.00' } })))
  const model = await readWorkbook(source), data = buildWorkbookData(model, 'rotation', 'rotation')
  const sheet = data.sheets[data.sheetOrder[0]]!
  expect(fromUniverStyle(data.styles![String(sheet.cellData[0][0].s)])).toMatchObject({ textRotation: 135, bold: true })
  const readback = { sheets: [{ name: 'Sheet1', cells: Object.fromEntries(Object.entries(model.sheets[0].cells).map(([address, cell]) => [address, { value: cell.value, style: fromUniverStyle(toUniverStyle(logicalStyleOf(model.styles, model.styles.cellXfs[cell.styleIndex ?? 0], model.themePalette)!)) }])) }] }
  expect(diffToEdits(model, readback)).toEqual([])
  readback.sheets[0].cells.A1.style.textRotation = 0
  readback.sheets[0].cells.B1.style.textRotation = 45
  const edits = diffToEdits(model, readback)
  expect(edits.map(edit => edit.style)).toEqual([{ textRotation: 0 }, { textRotation: 45 }])
  const result = await readWorkbook(await applyWorkbookOperations(source, [{ kind: 'applyCellEdits', edits }]))
  expect([result.sheets[0].cells.A1, result.sheets[0].cells.B1, result.sheets[0].cells.C1].map(cell => result.styles.cellXfs[cell.styleIndex!].alignment?.textRotation ?? 0)).toEqual([0, 45, 37])
  expect(result.sheets[0].cells.C1.value).toBe(42)
})

it('refuses rotation affordances for unmodeled inherited source styles even with a selected cell', () => {
  const host = document.createElement('div'), callback = vi.fn()
  const ribbon = mountWorkbookRibbon(host, callback, { rotation: () => 0, editable: () => true, unavailableReason: () => 'inherited source style' })
  const button = host.querySelector<HTMLButtonElement>('[data-ribbon-command="rotate:0"]')!
  expect(button.disabled).toBe(true); expect(button.title).toContain('inherited source style')
  button.click(); expect(callback).not.toHaveBeenCalled()
  ribbon.dispose()
})
