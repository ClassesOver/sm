import { expect, it, vi } from 'vitest'
import JSZip from 'jszip'
import { Univer, LocaleType, IUniverInstanceService } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-formula/facade'
import { applyCellEdits, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { buildWorkbookData } from './workbook-vendor/core/univer-data'
import { loadWorkbookData, readBack } from './workbook-vendor/grid/sync'
import { diffToEdits } from './workbook-vendor/core/session-core'

it('does not save recalculation as an edit, including when only formula formatting changed', async () => {
  const { applyCellEdits } = await import('@sheets-web/xlsx-engine')
  const baseline = await readWorkbook(await applyCellEdits(await createBlankWorkbook(), [{ sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: null, formula: '=1+2' } }]))
  expect(diffToEdits(baseline, { sheets: [{ name: 'Sheet1', cells: { B1: { formula: '=1+2', value: 3 } } }] })).toEqual([])
  expect(diffToEdits(baseline, { sheets: [{ name: 'Sheet1', cells: { B1: { formula: '=1+2', value: 3, style: { bold: true } } } }] })[0]).toMatchObject({ writeValue: false, style: { bold: true } })
  expect(diffToEdits(baseline, { sheets: [{ name: 'Sheet1', cells: { B1: { formula: '=1+3', value: 4 } } }] })[0]).toMatchObject({ writeValue: true, cell: { formula: '=1+3' } })
  expect(diffToEdits(baseline, { sheets: [{ name: 'Sheet1', cells: { B1: { value: 3 } } }] })[0]).toMatchObject({ writeValue: true, cell: { value: 3 } })
})

it('calculates imported shared followers, edits with undo/redo, and saves only the changed cell', async () => {
  const zip = await JSZip.loadAsync(await createBlankWorkbook())
  zip.file('xl/worksheets/sheet1.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:B3"/><sheetData>' +
    '<row r="1"><c r="A1"><v>2</v></c><c r="B1"><f t="shared" si="0" ref="B1:B3">A1*2</f><v>999</v></c></row>' +
    '<row r="2"><c r="A2"><v>3</v></c><c r="B2"><f t="shared" si="0"/><v>999</v></c></row>' +
    '<row r="3"><c r="A3"><v>4</v></c><c r="B3"><f t="shared" si="0"/><v>999</v></c></row>' +
    '</sheetData></worksheet>')
  const source = await zip.generateAsync({ type: 'uint8array' }), baseline = await readWorkbook(source)
  const univer = new Univer({ locale: LocaleType.EN_US, locales: { [LocaleType.EN_US]: {} } })
  univer.registerPlugin(UniverSheetsPlugin)
  univer.registerPlugin(UniverFormulaEnginePlugin)
  univer.registerPlugin(UniverSheetsFormulaPlugin)
  const api = FUniver.newAPI(univer), runtime = { univer, univerAPI: api }
  try {
    loadWorkbookData(runtime, buildWorkbookData(baseline, 'shared-import', 'Shared'))
    univer.__getInjector().get(IUniverInstanceService).focusUnit('shared-import')
    const sheet = api.getActiveWorkbook()!.getActiveSheet()!
    expect(sheet.getRange('B2').getFormula()).toBe('=A2*2')
    await vi.waitFor(() => expect(sheet.getRange('B1:B3').getValues()).toEqual([[4], [6], [8]]))
    expect(diffToEdits(baseline, readBack(runtime))).toEqual([])
    sheet.getRange('B1').setValue(42)
    await api.undo()
    expect(sheet.getRange('B1').getFormula()).toBe('=A1*2')
    await api.redo()
    const edits = diffToEdits(baseline, readBack(runtime))
    expect(edits).toHaveLength(1)
    expect(edits[0]).toMatchObject({ row: 0, column: 1, writeValue: true, cell: { value: 42 } })
    const reopened = await readWorkbook(await applyCellEdits(source, edits))
    expect(reopened.sheets[0]!.cells.B1!.value).toBe(42)
    expect(reopened.sheets[0]!.cells.B2!.formula).toBe('=A2*2')
    expect(reopened.sheets[0]!.cells.B3!.formula).toBe('=A3*2')
    loadWorkbookData(runtime, buildWorkbookData(reopened, 'shared-import', 'Shared'))
    univer.__getInjector().get(IUniverInstanceService).focusUnit('shared-import')
    await vi.waitFor(() => expect(api.getActiveWorkbook()!.getActiveSheet()!.getRange('B1:B3').getValues()).toEqual([[42], [6], [8]]))
  } finally { univer.dispose() }
}, 15000)
