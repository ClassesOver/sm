import { expect, it } from 'vitest'
import { applyCellEdits, applyPageSetupState, applyPageSetups, createBlankWorkbook, readWorkbook } from '../src'

it('roundtrips the default, enabled and restored RTL sheet view through actual ZIP', async () => {
  const source = await createBlankWorkbook()
  expect((await readWorkbook(source)).sheets[0]).toHaveProperty('rightToLeft', false)
  const rtl = await applyPageSetups(source, [{ sheetName: 'Sheet1', rightToLeft: true }])
  expect((await readWorkbook(rtl)).sheets[0]).toHaveProperty('rightToLeft', true)
  const ltr = await applyPageSetups(rtl, [{ sheetName: 'Sheet1', rightToLeft: false }])
  expect((await readWorkbook(ltr)).sheets[0]).toHaveProperty('rightToLeft', false)
})

it('keeps RTL on unrelated cell edits and preserves every other sheet-view and protection byte', async () => {
  const xml = '<worksheet><sheetViews><sheetView showGridLines="0" showRowColHeaders="0" zoomScale="125" workbookViewId="0"><selection activeCell="C4" sqref="C4"/></sheetView></sheetViews><sheetData/><sheetProtection sheet="1" password="AA12"/><extLst><ext uri="foreign"/></extLst></worksheet>'
  const enabled = applyPageSetupState(xml, { sheetName: 'Sheet1', rightToLeft: true } as never)
  expect(enabled).toBe(xml.replace('<sheetView ', '<sheetView rightToLeft="1" '))
  expect(applyPageSetupState(enabled, { sheetName: 'Sheet1', rightToLeft: false } as never)).toBe(xml)
  const rtl = await applyPageSetups(await createBlankWorkbook(), [{ sheetName: 'Sheet1', rightToLeft: true }])
  const changed = await applyCellEdits(rtl, [{ sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'unrelated' } }])
  const model = await readWorkbook(changed)
  expect(model.sheets[0]).toHaveProperty('rightToLeft', true)
  expect(model.sheets[0]!.cells.A1?.value).toBe('unrelated')
})
