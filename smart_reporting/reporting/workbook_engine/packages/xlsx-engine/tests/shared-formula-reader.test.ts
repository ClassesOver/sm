import { expect, it } from 'vitest'
import JSZip from 'jszip'
import { applyCellEdits, createBlankWorkbook, readWorkbook, type CellEdit } from '../src'

async function workbook(rows: string) {
  const zip = await JSZip.loadAsync(await createBlankWorkbook())
  zip.file('xl/worksheets/sheet1.xml', `<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:F4"/><sheetData>${rows}</sheetData></worksheet>`)
  return zip.generateAsync({ type: 'uint8array' })
}
const row = (n: number, cells: string) => `<row r="${n}">${cells}</row>`
const group = row(1, '<c r="B1"><f t="shared" si="0" ref="B1:B3">A1+$D$1</f><v>12</v></c>') +
  row(2, '<c r="B2" s="0"><f t="shared" si="0"/><v>22</v></c>') +
  row(3, '<c r="B3"><f si="0" t="shared"></f><v>32</v></c>')
const edit = (row: number, value: number): CellEdit => ({ sheetName: 'Sheet1', row, column: 1, writeValue: true, cell: { value } })

it('reads both self-closing and paired-empty shared followers as formulas', async () => {
  const cells = (await readWorkbook(await workbook(group))).sheets[0]!.cells
  expect(cells.B1!.formula).toBe('=A1+$D$1')
  expect(cells.B2).toMatchObject({ value: null, formula: '=A2+$D$1', styleIndex: 0 })
  expect(cells.B3!.formula).toBe('=A3+$D$1')
})

it.each([
  ['D3+$A$1+B$2+$C4', 'E5+$A$1+C$2+$C6'],
  ['SUM(B:B)+SUM($C:$C)+SUM(3:4)+SUM($5:$5)', 'SUM(C:C)+SUM($C:$C)+SUM(5:6)+SUM($5:$5)'],
  ['&quot;say &quot;&quot;B1&quot;&quot;&quot;&amp;LOG10(A1)', '"say ""B1"""&LOG10(B3)'],
  ["'My A1 Sheet'!B2+Sheet2!$A1", "'My A1 Sheet'!C4+Sheet2!$A3"],
  ['SUM(Table1[Q1])+名A1+A1+TaxRate', 'SUM(Table1[Q1])+名A1+B3+TaxRate'],
  ['SUM([@A1])+SUM([A1])+SUM(表一[Q1])+A1', 'SUM([@A1])+SUM([A1])+SUM(表一[Q1])+B3'],
  ["SUM(Table1[Col']A1])+SUM(Table1[Col'[Q1']])+A1", "SUM(Table1[Col']A1])+SUM(Table1[Col'[Q1']])+B3"],
  ['\\A1+XFE1+A1048577+A1_名+A1.名+名A1+A1', '\\A1+XFE1+A1048577+A1_名+A1.名+名A1+B3'],
  ['SUM(A1:XFE1)+SUM(XFE1:A1)+SUM(A1:A1048577)', 'SUM(B3:XFE1)+SUM(XFE1:B3)+SUM(B3:A1048577)'],
  ['SUM(S1:S3!A1)+SUM(A1:B2!C3)', 'SUM(S1:S3!B3)+SUM(A1:B2!D5)'],
  ['SUM(A1:OFFSET(A1,1,0))+SUM(A1:INDEX(A:A,10))+SUM(A1:TaxRate)', 'SUM(B3:OFFSET(B3,1,0))+SUM(B3:INDEX(B:B,10))+SUM(B3:TaxRate)'],
  ['SUM(Sheet1!A1:Sheet1!A2)', 'SUM(Sheet1!B3:Sheet1!B4)'],
  ["SUM('S1':'S3'!A1)+'[Book.xlsx]S1'!A1+[1]S1!A1", "SUM('S1':'S3'!B3)+'[Book.xlsx]S1'!B3+[1]S1!B3"],
  ["SUM('My S1:S3'!A1)+SUM(S1:S3!A:A)+SUM(S1:S3!1:2)", "SUM('My S1:S3'!B3)+SUM(S1:S3!B:B)+SUM(S1:S3!3:4)"],
  ['XFD1+A1048576+$XFD$1048576', '#REF!+#REF!+$XFD$1048576'],
  ['_xlfn.MINIFS(A1:A2,A1:A2,1)', 'MINIFS(B3:B4,B3:B4,1)'],
])('expands shared relative references without rewriting literals/names: %s', async (formula, expected) => {
  const bytes = await workbook(row(1, `<c r="B1"><f t="shared" si="3" ref="B1:C3">${formula}</f></c>`) + row(3, '<c r="C3"><f t="shared" si="3"/></c>'))
  expect((await readWorkbook(bytes)).sheets[0]!.cells.C3!.formula).toBe(`=${expected}`)
  const detached = await applyCellEdits(bytes, [edit(0, 99)])
  expect((await readWorkbook(detached)).sheets[0]!.cells.C3!.formula).toBe(`=${expected}`)
})

it('resolves a follower preceding its master and keeps groups separate', async () => {
  const bytes = await workbook(row(1, '<c r="B1"><f t="shared" si="1"/></c><c r="C1"><f t="shared" si="2">A1*2</f></c>') + row(2, '<c r="B2"><f t="shared" si="1">A2+1</f></c><c r="C2"><f t="shared" si="2"/></c>'))
  const cells = (await readWorkbook(bytes)).sheets[0]!.cells
  expect(cells.B1!.formula).toBe('=A1+1')
  expect(cells.C2!.formula).toBe('=A2*2')
})

it.each([0, 1, 2])('editing group member row %s preserves all other formulas', async target => {
  const bytes = await applyCellEdits(await workbook(group), [edit(target, 99)])
  const cells = (await readWorkbook(bytes)).sheets[0]!.cells
  for (let index = 0; index < 3; index++) {
    if (index === target) expect(cells[`B${index + 1}`]).toMatchObject({ value: 99 })
    else expect(cells[`B${index + 1}`]!.formula).toBe(`=A${index + 1}+$D$1`)
  }
  const xml = await (await JSZip.loadAsync(bytes)).file('xl/worksheets/sheet1.xml')!.async('string')
  expect(xml).not.toContain('t="shared"')
  expect(xml).toContain(target === 1 ? '<v>32</v>' : '<v>22</v>')
})

it('replacing a master formula leaves followers with the original formula', async () => {
  const bytes = await applyCellEdits(await workbook(group), [{ ...edit(0, 0), cell: { value: null, formula: '=100' } }])
  const cells = (await readWorkbook(bytes)).sheets[0]!.cells
  expect(cells.B1!.formula).toBe('=100')
  expect(cells.B2!.formula).toBe('=A2+$D$1')
})

it.each([false, true])('unrelated or style-only edits retain shared formula XML: styleOnly=%s', async styleOnly => {
  const bytes = await applyCellEdits(await workbook(group), [{ ...edit(0, 99), column: styleOnly ? 1 : 4, writeValue: !styleOnly, style: { bold: true } }])
  const xml = await (await JSZip.loadAsync(bytes)).file('xl/worksheets/sheet1.xml')!.async('string')
  expect(xml).toContain('<f t="shared" si="0" ref="B1:B3">A1+$D$1</f>')
  expect(xml).toContain('<f t="shared" si="0"/>')
})

it.each([
  '<c r="B1"><f t="shared" si="9"/><v>42</v></c>',
  '<c r="B1"><f t="shared">A1</f></c>',
  '<c r="B1"><f t="shared" si="0">A1</f></c><c r="C1"><f t="shared" si="0">A2</f></c>',
])('rejects malformed shared groups instead of silently loading constants: %s', async cells => {
  const bytes = await workbook(row(1, cells))
  await expect(readWorkbook(bytes)).rejects.toThrow(/共享公式/)
  await expect(applyCellEdits(bytes, [edit(0, 99)])).rejects.toThrow(/共享公式/)
})

it('does not invent followers from the declared rectangular range', async () => {
  const cells = (await readWorkbook(await workbook(group))).sheets[0]!.cells
  expect(cells.C2).toBeUndefined()
  expect(Object.keys(cells)).toHaveLength(3)
})
