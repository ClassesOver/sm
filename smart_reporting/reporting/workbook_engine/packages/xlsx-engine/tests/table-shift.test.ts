import { describe, expect, it } from 'vitest'

import { applyCellEdits, createBlankWorkbook, readWorkbook } from '../src'
import { applyRowColumnOps } from '../src/sheet-ops'
import { createBufferEntrySource } from '../src/zip'
import { assemblePackage } from '../src/zip'

async function partOf(bytes: Uint8Array, path: string): Promise<string> {
  const source = await createBufferEntrySource(bytes)
  return source.readText(path)
}

/// Builds a workbook whose Sheet1 carries a real Excel table "Sales" over
/// A1:C3 (header row + 2 data rows), wired through rels and content types.
async function buildTableWorkbook(): Promise<Uint8Array> {
  const blank = await createBlankWorkbook()
  const seeded = await applyCellEdits(blank, [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Item' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 'Qty' } },
    { sheetName: 'Sheet1', row: 0, column: 2, writeValue: true, cell: { value: 'Price' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'A' } },
    { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: 1 } },
    { sheetName: 'Sheet1', row: 1, column: 2, writeValue: true, cell: { value: 10 } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: 'B' } },
    { sheetName: 'Sheet1', row: 2, column: 1, writeValue: true, cell: { value: 2 } },
    { sheetName: 'Sheet1', row: 2, column: 2, writeValue: true, cell: { value: 20 } },
  ])
  const worksheetXml = await partOf(seeded, 'xl/worksheets/sheet1.xml')
  const withTableElement = worksheetXml.replace(
    /<\/sheetData>/,
    '</sheetData><tableParts count="1"><tablePart r:id="rIdTable1"/></tableParts>',
  )
  const relsXml =
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
    '<Relationship Id="rIdTable1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/table" Target="../tables/table1.xml"/>' +
    '</Relationships>'
  const tableXml =
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
    '<table xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" id="1" name="Sales" displayName="Sales" ref="A1:C3" headerRowCount="1">' +
    '<autoFilter ref="A1:C3"/>' +
    '<tableColumns count="3">' +
    '<tableColumn id="1" name="Item"/><tableColumn id="2" name="Qty"/><tableColumn id="3" name="Price"/>' +
    '</tableColumns>' +
    '<tableStyleInfo name="TableStyleMedium2" showRowStripes="1"/>' +
    '</table>'
  const contentTypes = (await partOf(seeded, '[Content_Types].xml')).replace(
    '</Types>',
    '<Override PartName="/xl/tables/table1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/></Types>',
  )
  const mutation = await assemblePackage(seeded, {
    replaced: new Map<string, string>([
      ['xl/worksheets/sheet1.xml', withTableElement],
      ['xl/worksheets/_rels/sheet1.xml.rels', relsXml],
      ['[Content_Types].xml', contentTypes],
    ]),
    added: new Map([['xl/tables/table1.xml', tableXml]]),
    addedBinary: new Map(),
    removedEntries: [],
    addedEntries: ['xl/tables/table1.xml'],
    touchedEntries: [
      'xl/worksheets/sheet1.xml',
      'xl/worksheets/_rels/sheet1.xml.rels',
      '[Content_Types].xml',
      'xl/tables/table1.xml',
    ],
  })
  return mutation.buffer
}

describe('table part shifting', () => {
  it('inserting a column inside the table widens it and writes the header cell', async () => {
    const bytes = await buildTableWorkbook()
    const edited = await applyRowColumnOps(bytes, 'Sheet1', [
      { kind: 'insert-cols', index: 1, count: 1 },
    ])
    const table = await partOf(edited, 'xl/tables/table1.xml')
    expect(table).toContain('ref="A1:D3"')
    expect(table).toContain('count="4"')
    expect(table).toContain('<tableColumn id="4" name="Column1"/>')
    const worksheet = await partOf(edited, 'xl/worksheets/sheet1.xml')
    expect(worksheet).toContain('<c r="B1" t="inlineStr"><is><t xml:space="preserve">Column1</t></is></c>')
    // the cells moved right around the new column
    const model = await readWorkbook(edited)
    expect(model.sheets[0]?.cells.B1?.value).toBe('Column1')
    expect(model.sheets[0]?.cells.C1?.value).toBe('Qty')
    expect(model.sheets[0]?.cells.D2?.value).toBe(10)
  })

  it('deleting a column inside the table shrinks it and drops the entry', async () => {
    const bytes = await buildTableWorkbook()
    const edited = await applyRowColumnOps(bytes, 'Sheet1', [
      { kind: 'remove-cols', index: 1, count: 1 },
    ])
    const table = await partOf(edited, 'xl/tables/table1.xml')
    expect(table).toContain('ref="A1:B3"')
    expect(table).toContain('count="2"')
    expect(table).not.toContain('name="Qty"')
    const model = await readWorkbook(edited)
    expect(model.sheets[0]?.cells.B1?.value).toBe('Price')
  })

  it('inserting a row above the table moves its ref down', async () => {
    const bytes = await buildTableWorkbook()
    const edited = await applyRowColumnOps(bytes, 'Sheet1', [
      { kind: 'insert-rows', index: 0, count: 1 },
    ])
    const table = await partOf(edited, 'xl/tables/table1.xml')
    expect(table).toContain('ref="A2:C4"')
    expect(table).toContain('<autoFilter ref="A2:C4"/>')
  })

  it('deleting the header row is refused', async () => {
    const bytes = await buildTableWorkbook()
    await expect(
      applyRowColumnOps(bytes, 'Sheet1', [{ kind: 'remove-rows', index: 0, count: 1 }]),
    ).rejects.toThrow(/header row/)
  })

  it('deleting all data rows is refused', async () => {
    const bytes = await buildTableWorkbook()
    await expect(
      applyRowColumnOps(bytes, 'Sheet1', [{ kind: 'remove-rows', index: 1, count: 2 }]),
    ).rejects.toThrow(/without data rows/)
  })

  it('deleting every table column is refused', async () => {
    const bytes = await buildTableWorkbook()
    await expect(
      applyRowColumnOps(bytes, 'Sheet1', [{ kind: 'remove-cols', index: 0, count: 3 }]),
    ).rejects.toThrow(/Deleting all columns/)
  })

  it('columns outside the table span leave it untouched', async () => {
    const bytes = await buildTableWorkbook()
    const edited = await applyRowColumnOps(bytes, 'Sheet1', [
      { kind: 'insert-cols', index: 3, count: 1 }, // at the right edge boundary (3 > endColumn 2? boundary 3 = just past the table)
    ])
    const table = await partOf(edited, 'xl/tables/table1.xml')
    expect(table).toContain('ref="A1:C3"') // unchanged: boundary is outside (strictly-inside rule)
    expect(table).toContain('count="3"')
  })
})
