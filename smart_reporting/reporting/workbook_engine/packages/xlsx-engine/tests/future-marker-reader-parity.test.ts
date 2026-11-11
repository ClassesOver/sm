import { expect, it } from 'vitest'
import JSZip from 'jszip'
import { createBlankWorkbook, applyCellEdits, readWorkbook } from '../src'

it.each(['MINIFS', 'MAXIFS'])('normalizes its own saved %s storage call on real ZIP read', async name => {
  const formula = `=${name}(A1:A2,A1:A2,">0")`
  const bytes = await applyCellEdits(await createBlankWorkbook(), [{ sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: null, formula } }])
  const zip = await JSZip.loadAsync(bytes), xml = await zip.file('xl/worksheets/sheet1.xml')!.async('string')
  expect(xml).toContain(`_xlfn.${name}(`)
  const actual = (await readWorkbook(bytes)).sheets[0]!.cells.B1!.formula
  expect(actual).toBe(formula)
  const saved = await applyCellEdits(bytes, [{ sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: null, formula: actual! } }])
  expect((await readWorkbook(saved)).sheets[0]!.cells.B1!.formula).toBe(formula)
  const stored = await (await JSZip.loadAsync(saved)).file('xl/worksheets/sheet1.xml')!.async('string')
  expect(stored).toContain(`_xlfn.${name}(`); expect(stored).not.toContain('_xlfn._xlfn.')
})

it.each([
  ['_XlFn.MINIFS \t(A1:A2,A1:A2,1)', '=MINIFS \t(A1:A2,A1:A2,1)'],
  ['_xlfn._xlws.FILTER(A1:A2,A1:A2&gt;0)', '=FILTER(A1:A2,A1:A2>0)'],
  ['_xlws.FILTER(A1:A2,A1:A2&gt;0)', '=FILTER(A1:A2,A1:A2>0)'],
  ['IF(TRUE,&quot;_xlfn.MINIFS(&quot;,_xlfn.MINIFS(A1:A2,A1:A2,&quot;&gt;0&quot;))', '=IF(TRUE,"_xlfn.MINIFS(",MINIFS(A1:A2,A1:A2,">0"))'],
  ['IF(TRUE,&quot;escaped &quot;&quot;_xlfn.MAXIFS(&quot;&quot;&quot;,_xlfn.MAXIFS(A1:A2,A1:A2,&quot;&gt;0&quot;))', '=IF(TRUE,"escaped ""_xlfn.MAXIFS(""",MAXIFS(A1:A2,A1:A2,">0"))'],
  ["'Data_xlfn.MINIFS'!A1+_xlfn.MINIFS(A1:A2,A1:A2,1)", "='Data_xlfn.MINIFS'!A1+MINIFS(A1:A2,A1:A2,1)"],
  ['Budget_xlfn.Total(A1)+_xlfn.MINIFS(A1:A2,A1:A2,1)', '=Budget_xlfn.Total(A1)+MINIFS(A1:A2,A1:A2,1)'],
  ["SUM(Table1[Col']_xlfn.MINIFS(A1)])+_xlfn.MAXIFS(A1:A2,A1:A2,1)", "=SUM(Table1[Col']_xlfn.MINIFS(A1)])+MAXIFS(A1:A2,A1:A2,1)"],
  ["SUM(Table1[Col'[part']_xlws.FILTER(A1)])", "=SUM(Table1[Col'[part']_xlws.FILTER(A1)])"],
  ['SUM(Table1[_xlfn.MINIFS(A1)])', '=SUM(Table1[_xlfn.MINIFS(A1)])'],
  ['&quot;_xlfn.MINIFS(A1)&quot;', '="_xlfn.MINIFS(A1)"'],
  ["'Data _xlfn.MINIFS(A1)'!A1", "='Data _xlfn.MINIFS(A1)'!A1"],
  ['Budget_xlfn.Total(A1)', '=Budget_xlfn.Total(A1)'],
  ['SUM(Table1[_xlfn.MINIFS])+_xlfn.MAXIFS(A1:A2,A1:A2,1)', '=SUM(Table1[_xlfn.MINIFS])+MAXIFS(A1:A2,A1:A2,1)'],
])('strips only storage function tokens from real ZIP: %s', async (stored, expected) => {
  const zip = await JSZip.loadAsync(await createBlankWorkbook())
  zip.file('xl/worksheets/sheet1.xml', `<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="B1"><f>${stored}</f></c></row></sheetData></worksheet>`)
  const bytes = await zip.generateAsync({ type: 'uint8array' })
  expect((await readWorkbook(bytes)).sheets[0]!.cells.B1!.formula).toBe(expected)
})
