import { describe, expect, it } from 'vitest'
import { applyTableAdditions, createBlankWorkbook, readWorkbook } from '../src'
import { applyRowColumnOps } from '../src/sheet-ops'
import { assemblePackage, createBufferEntrySource } from '../src/zip'

async function fixture() {
  return applyTableAdditions(await createBlankWorkbook(), [{
    worksheetSheetName: 'Sheet1', name: 'Staff',
    area: { startRow: 0, startColumn: 0, endRow: 3, endColumn: 1 },
    columnNames: ['Name & role', 'Qty'], bandedRows: true,
  }])
}
async function change(bytes: Uint8Array, path: string, transform: (xml: string) => string) {
  const source = await createBufferEntrySource(bytes)
  return (await assemblePackage(bytes, {
    replaced: new Map([[path, transform(await source.readText(path))]]),
    added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path],
  })).buffer
}

describe('workbook table context', () => {
  it('uses the mandatory displayName when optional name is absent and accepts explicit Internal relationships', async () => {
    let bytes = await change(await fixture(), 'xl/tables/table1.xml', xml => xml.replace(' name="Staff"', ''))
    bytes = await change(bytes, 'xl/worksheets/_rels/sheet1.xml.rels', xml => xml.replace('Target="', 'TargetMode="Internal" Target="'))
    const sheet = (await readWorkbook(bytes)).sheets[0]!
    expect(sheet.tables?.[0]?.name).toBe('Staff')
    expect(sheet.tablesReadOnlyReason).toBeUndefined()
  })

  it('decodes escaped column characters and preserves escaped literal escape prefixes', async () => {
    const bytes = await change(await fixture(), 'xl/tables/table1.xml', xml => xml
      .replace('Name &amp; role', 'Name_x000A_Role').replace('name="Qty"', 'name="_x005F_x000A_"'))
    expect((await readWorkbook(bytes)).sheets[0]!.tables?.[0]?.columns.map(column => column.name)).toEqual(['Name\nRole', '_x000A_'])
  })

  it.each([
    ['xl/worksheets/sheet1.xml', (xml: string) => xml.replace('<tableParts count="1">', '<tableParts count="0"/><tableParts count="1">')],
    ['xl/tables/table1.xml', (xml: string) => xml.replace('</table>', '')],
    ['xl/tables/table1.xml', (xml: string) => xml.replace('<tableColumns count=', '<tableColumns xmlns="urn:foreign" count=')],
    ['xl/tables/table1.xml', (xml: string) => xml.replace('<tableColumn id=', '<tableColumn xmlns="urn:foreign" id=')],
    ['xl/tables/table1.xml', (xml: string) => xml.replace('<tableStyleInfo name=', '<tableStyleInfo xmlns="urn:foreign" name=')],
    ['xl/worksheets/sheet1.xml', (xml: string) => xml.replace(/<tableParts[^>]*>[\s\S]*?<\/tableParts>/, '<tableParts count="1"/>')],
    ['xl/worksheets/sheet1.xml', (xml: string) => xml.replace('<tablePart r:id="rId1"/>', '<tablePart r:id="rId1">')],
    ['xl/tables/table1.xml', (xml: string) => xml.replace('<tableColumns count="2"', '<tableColumns count="9"')],
    ['xl/tables/table1.xml', (xml: string) => xml.replace('id="1"', 'id="broken"')],
    ['xl/worksheets/sheet1.xml', (xml: string) => xml.replace('xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"', 'xmlns:r="urn:unrelated"')],
    ['xl/tables/table1.xml', (xml: string) => xml.replace('xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"', 'xmlns="urn:unrelated"')],
  ])('withholds incomplete or foreign table context (%s)', async (path, transform) => {
    const bytes = await change(await fixture(), path as string, transform as (xml: string) => string)
    const sheet = (await readWorkbook(bytes)).sheets[0]!
    expect(sheet.tables).toEqual([])
    expect(sheet.tablesReadOnlyReason).toBeTruthy()
  })

  it('does not discover orphan table parts by scanning the ZIP', async () => {
    let bytes = await change(await fixture(), 'xl/worksheets/sheet1.xml', xml => xml.replace(/<tableParts[^>]*>[\s\S]*?<\/tableParts>/, ''))
    // 真正孤儿没有任何incoming表关系；保留关系但缺tablePart应被完整性守卫拒绝。
    bytes = await change(bytes, 'xl/worksheets/_rels/sheet1.xml.rels', xml => xml.replace(/<Relationship\b[^>]*\/table"[^>]*\/>/, ''))
    const sheet = (await readWorkbook(bytes)).sheets[0]!
    expect(sheet.tables).toEqual([])
    expect(sheet.tableSources).toEqual([])
    expect(sheet.tablesReadOnlyReason).toBeUndefined()
  })

  it('reads headerless tables with absolute package targets and alternate relationship prefixes', async () => {
    let bytes = await change(await fixture(), 'xl/tables/table1.xml', xml => xml.replace('totalsRowShown="0"', 'headerRowCount="0" totalsRowShown="0"'))
    bytes = await change(bytes, 'xl/worksheets/_rels/sheet1.xml.rels', xml => xml.replace('../tables/table1.xml', '/xl/tables/table1.xml'))
    bytes = await change(bytes, 'xl/worksheets/sheet1.xml', xml => xml.replaceAll('xmlns:r=', 'xmlns:rel=').replaceAll('r:id=', 'rel:id='))
    const table = (await readWorkbook(bytes)).sheets[0]!.tables?.[0]
    expect(table?.headerRowCount).toBe(0)
    expect(table?.totalsRowCount).toBe(0)
    expect(table?.columns[0]?.name).toBe('Name & role')
  })

  it('reads prefixed SpreadsheetML table parts through the existing package normalizer', async () => {
    const bytes = await change(await fixture(), 'xl/tables/table1.xml', xml => xml
      .replace('xmlns=', 'xmlns:x=')
      .replace(/<(\/?)(table(?:Columns|Column|StyleInfo)?|autoFilter)(?=[\s/>])/g, '<$1x:$2'))
    expect((await readWorkbook(bytes)).sheets[0]!.tables?.[0]?.name).toBe('Staff')
  })

  it('reads table identity, decoded columns and options through the owning worksheet relationship', async () => {
    const bytes = await change(await fixture(), 'xl/tables/table1.xml', xml =>
      xml.replace('totalsRowShown="0"', 'totalsRowShown="1" totalsRowCount="1"'))
    const sheet = (await readWorkbook(bytes)).sheets[0]!
    expect(sheet.tables).toEqual([{
      id: '1', name: 'Staff', displayName: 'Staff', path: 'xl/tables/table1.xml',
      range: { startRow: 0, startColumn: 0, endRow: 3, endColumn: 1 },
      headerRowCount: 1, totalsRowCount: 1, filterButton: true,
      columns: [{ id: '1', name: 'Name & role' }, { id: '2', name: 'Qty' }],
      style: { name: 'TableStyleMedium2', showFirstColumn: false, showLastColumn: false, showRowStripes: true, showColumnStripes: false },
    }])
    expect(sheet.tablesReadOnlyReason).toBeUndefined()
  })

  it('reads shifted table ranges and generated columns after actual structural edits', async () => {
    const bytes = await applyRowColumnOps(await fixture(), 'Sheet1', [
      { kind: 'insert-rows', index: 2, count: 1 },
      { kind: 'insert-cols', index: 1, count: 1 },
    ])
    const table = (await readWorkbook(bytes)).sheets[0]!.tables?.[0]
    expect(table?.range).toEqual({ startRow: 0, startColumn: 0, endRow: 4, endColumn: 2 })
    expect(table?.columns.map(column => column.name)).toEqual(['Name & role', 'Column1', 'Qty'])
  })

  it.each([
    (xml: string) => xml.replace('Target="../tables/table1.xml"', 'Target="https://example.com/table.xml" TargetMode="External"'),
    (xml: string) => xml.replace('Target="../tables/table1.xml"', 'Target="../../../table.xml"'),
    (xml: string) => xml.replace('/relationships/table"', '/relationships/image"'),
  ])('keeps the workbook readable but exposes no table context for invalid ownership', async transform => {
    const bytes = await change(await fixture(), 'xl/worksheets/_rels/sheet1.xml.rels', transform)
    const sheet = (await readWorkbook(bytes)).sheets[0]!
    expect(sheet.tables).toEqual([])
    expect(sheet.tablesReadOnlyReason).toBeTruthy()
  })

  it('rejects inconsistent column counts without making the workbook unreadable', async () => {
    const bytes = await change(await fixture(), 'xl/tables/table1.xml', xml => xml.replace('ref="A1:B4"', 'ref="A1:C4"'))
    const sheet = (await readWorkbook(bytes)).sheets[0]!
    expect(sheet.tables).toEqual([])
    expect(sheet.tablesReadOnlyReason).toBeTruthy()
  })
})
