import { describe, expect, it } from 'vitest'
import * as engine from '../src'
import { assemblePackage, createBufferEntrySource } from '../src/zip'

async function fixture() {
  return engine.applyTableAdditions(await engine.createBlankWorkbook(), [{
    worksheetSheetName: 'Sheet1', name: 'Staff',
    area: { startRow: 0, startColumn: 0, endRow: 3, endColumn: 1 },
    columnNames: ['Name', 'Qty'], bandedRows: true,
  }])
}

async function change(bytes: Uint8Array, path: string, transform: (xml: string) => string) {
  const source = await createBufferEntrySource(bytes)
  return (await assemblePackage(bytes, {
    replaced: new Map([[path, transform(await source.readText(path))]]),
    added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path],
  })).buffer
}

// Removing metadata preservation or worksheet ownership validation must fail these tests.
describe('existing table file edits', () => {
  it.each([true, false])('rejects a table part shared by another worksheet (remove=%s)', async remove => {
    let bytes = await engine.applySheetEdits(await fixture(), { renames: [], additions: [{ name: 'Other' }], removals: [], order: ['Sheet1', 'Other'] })
    const source = await createBufferEntrySource(bytes)
    const worksheet = await source.readText('xl/worksheets/sheet1.xml')
    const rels = await source.readText('xl/worksheets/_rels/sheet1.xml.rels')
    bytes = (await assemblePackage(bytes, { replaced: new Map([['xl/worksheets/sheet2.xml', worksheet]]),
      added: new Map([['xl/worksheets/_rels/sheet2.xml.rels', rels]]), addedBinary: new Map(),
      removedEntries: [], addedEntries: ['xl/worksheets/_rels/sheet2.xml.rels'], touchedEntries: ['xl/worksheets/sheet2.xml'] })).buffer
    await expect(engine.applyTableEdits(bytes, [{ worksheetSheetName: 'Sheet1', tableName: 'Staff',
      ...(remove ? { remove: true as const } : { columnNames: ['Employee', 'Qty'] }) }])).rejects.toThrow()
  })

  it('requires column names when resizing across worksheet columns', async () => {
    await expect(engine.applyTableEdits(await fixture(), [{ worksheetSheetName: 'Sheet1', tableName: 'Staff',
      area: { startRow: 0, startColumn: 1, endRow: 3, endColumn: 2 } }])).rejects.toThrow()
  })

  it('rejects out-of-bounds areas even when column counts still match', async () => {
    await expect(engine.applyTableEdits(await fixture(), [{ worksheetSheetName: 'Sheet1', tableName: 'Staff',
      area: { startRow: 0, startColumn: 16383, endRow: 3, endColumn: 16384 }, columnNames: ['Left', 'Right'] }])).rejects.toThrow()
  })

  it('preserves namespace declarations on the column container', async () => {
    const bytes = await change(await fixture(), 'xl/tables/table1.xml', xml => xml
      .replace('<tableColumns count=', '<tableColumns xmlns:keep="urn:test" count=')
      .replace('<tableColumn id="2" name="Qty"/>', '<tableColumn id="2" name="Qty"><extLst><ext uri="urn:test"><keep:custom>keep</keep:custom></ext></extLst></tableColumn>'))
    const updated = await engine.applyTableEdits(bytes, [{ worksheetSheetName: 'Sheet1', tableName: 'Staff', columnNames: ['Employee', 'Qty'] }])
    const xml = await (await createBufferEntrySource(updated)).readText('xl/tables/table1.xml')
    expect(xml).toContain('<tableColumns xmlns:keep="urn:test" count="2">')
    expect(xml).toContain('<keep:custom>keep</keep:custom>')
  })

  it('inserts missing style info at table level after columns with nested extensions', async () => {
    const bytes = await change(await fixture(), 'xl/tables/table1.xml', xml => xml
      .replace(/<tableStyleInfo\b[^>]*\/>/, '')
      .replace('<tableColumn id="2" name="Qty"/>', '<tableColumn id="2" name="Qty"><extLst><ext uri="column-extension"/></extLst></tableColumn>'))
    const updated = await engine.applyTableEdits(bytes, [{ worksheetSheetName: 'Sheet1', tableName: 'Staff', style: 'TableStyleDark3' }])
    const result = await createBufferEntrySource(updated)
    const xml = await result.readText('xl/tables/table1.xml')
    expect(xml).toContain('</tableColumns><tableStyleInfo')
    expect(xml).toContain('name="Qty"><extLst><ext uri="column-extension"/></extLst></tableColumn>')
  })

  it('rejects an unregistered table relationship without changing the source package', async () => {
    const bytes = await change(await fixture(), 'xl/worksheets/_rels/sheet1.xml.rels', xml =>
      xml.replace('<Relationship Id=', '<Relationship Id="orphan" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/table" Target="../tables/table1.xml"/><Relationship Id='))
    const snapshot = bytes.slice()
    await expect(engine.applyTableEdits(bytes, [{ worksheetSheetName: 'Sheet1', tableName: 'Staff', remove: true }])).rejects.toThrow('所属关系未完整登记')
    expect(bytes).toEqual(snapshot)
  })

  it('preserves replacement tokens in unrelated table attributes during a column edit', async () => {
    const bytes = await change(await fixture(), 'xl/tables/table1.xml', xml => xml.replace('id="1"', () => 'comment="$&amp; $`" id="1"'))
    const updated = await engine.applyTableEdits(bytes, [{ worksheetSheetName: 'Sheet1', tableName: 'Staff', columnNames: ['Employee', 'Qty'] }])
    const source = await createBufferEntrySource(updated)
    expect(await source.readText('xl/tables/table1.xml')).toContain('comment="$&amp; $`"')
    expect((await engine.readWorkbook(updated)).sheets[0]!.tablesReadOnlyReason).toBeUndefined()
  })

  it('writes literal replacement tokens in column names', async () => {
    const updated = await (engine as any).applyTableEdits(await fixture(), [{
      worksheetSheetName: 'Sheet1', tableName: 'Staff', columnNames: ['$& $`', 'Qty'],
    }])
    expect((await engine.readWorkbook(updated)).sheets[0]!.tables![0]!.columns[0]!.name).toBe('$& $`')
  })

  it('converts tables using an alternate relationship prefix without leaving a dangling tablePart', async () => {
    const bytes = await change(await fixture(), 'xl/worksheets/sheet1.xml', xml =>
      xml.replaceAll('xmlns:r=', 'xmlns:rel=').replaceAll('r:id=', 'rel:id='))
    const updated = await (engine as any).applyTableEdits(bytes, [{
      worksheetSheetName: 'Sheet1', tableName: 'Staff', remove: true,
    }])
    const sheet = (await engine.readWorkbook(updated)).sheets[0]!
    expect(sheet.tables).toEqual([])
    expect(sheet.tablesReadOnlyReason).toBeUndefined()
  })

  it.each([
    { startRow: 0, endRow: 3, startColumn: 0, endColumn: 16384 },
    { startRow: 4, endRow: 3, startColumn: 0, endColumn: 1 },
  ])('rejects invalid geometry without returning a damaged workbook', async area => {
    await expect((engine as any).applyTableEdits(await fixture(), [{
      worksheetSheetName: 'Sheet1', tableName: 'Staff', area,
    }])).rejects.toThrow()
  })

  it('renames and restyles an existing table while preserving its identity', async () => {
    const apply = (engine as any).applyTableEdits
    expect(typeof apply).toBe('function')
    const updated = await apply(await fixture(), [{ worksheetSheetName: 'Sheet1', tableName: 'Staff',
      name: 'Employees', style: 'TableStyleDark3', bandedRows: false, firstColumn: true }])
    const table = (await engine.readWorkbook(updated)).sheets[0]!.tables![0]!
    expect(table.name).toBe('Employees')
    expect(table.id).toBe('1')
    expect(table.style).toEqual({ name: 'TableStyleDark3', showFirstColumn: true, showLastColumn: false, showRowStripes: false, showColumnStripes: false })
  })

  it('keeps column identities with their worksheet positions on a left-edge resize', async () => {
    const apply = (engine as any).applyTableEdits
    expect(typeof apply).toBe('function')
    const updated = await apply(await fixture(), [{ worksheetSheetName: 'Sheet1', tableName: 'Staff',
      area: { startRow: 0, startColumn: 1, endRow: 5, endColumn: 2 }, columnNames: ['Qty', 'New'] }])
    const table = (await engine.readWorkbook(updated)).sheets[0]!.tables![0]!
    expect(table.range).toEqual({ startRow: 0, startColumn: 1, endRow: 5, endColumn: 2 })
    expect(table.columns).toEqual([{ id: '2', name: 'Qty' }, { id: '3', name: 'New' }])
  })

  it('converts to a range by unregistering only the table parts and keeping cell data', async () => {
    const bytes = await fixture()
    const apply = (engine as any).applyTableEdits
    expect(typeof apply).toBe('function')
    const updated = await apply(bytes, [{ worksheetSheetName: 'Sheet1', tableName: 'Staff', remove: true }])
    expect((await engine.readWorkbook(updated)).sheets[0]!.tables).toEqual([])
    const result = await createBufferEntrySource(updated)
    expect(await result.has('xl/tables/table1.xml')).toBe(false)
    expect(await result.readText('[Content_Types].xml')).not.toContain('/xl/tables/table1.xml')
    expect(await result.readText('xl/worksheets/_rels/sheet1.xml.rels')).not.toContain('/relationships/table')
  })

  it('renames columns without losing column ids, formulas, totals or unrelated parts', async () => {
    const bytes = await change(await fixture(), 'xl/tables/table1.xml', xml => xml.replace(
      '<tableColumn id="2" name="Qty"/>',
      '<tableColumn id="2" name="Qty" totalsRowFunction="sum"><calculatedColumnFormula>1+1</calculatedColumnFormula></tableColumn>',
    ))
    const apply = (engine as any).applyTableEdits
    expect(typeof apply).toBe('function')
    const updated = await apply(bytes, [{
      worksheetSheetName: 'Sheet1', tableName: 'Staff',
      columnNames: ['Employee\n_x000A_', 'Total & cost'],
    }])
    const table = (await engine.readWorkbook(updated)).sheets[0]!.tables![0]!
    expect(table.columns).toEqual([
      { id: '1', name: 'Employee\n_x000A_' }, { id: '2', name: 'Total & cost' },
    ])
    const result = await createBufferEntrySource(updated)
    expect(await result.readText('xl/tables/table1.xml')).toContain('totalsRowFunction="sum"><calculatedColumnFormula>1+1</calculatedColumnFormula>')
    const original = await createBufferEntrySource(bytes)
    for (const path of await original.paths()) {
      if (path !== 'xl/tables/table1.xml') expect(await result.readText(path)).toBe(await original.readText(path))
    }
  })

  it('rejects an orphan table part even when its name matches', async () => {
    const bytes = await change(await fixture(), 'xl/worksheets/sheet1.xml', xml =>
      xml.replace(/<tableParts\b[^>]*>[\s\S]*?<\/tableParts>/, ''))
    const apply = (engine as any).applyTableEdits
    expect(typeof apply).toBe('function')
    await expect(apply(bytes, [{
      worksheetSheetName: 'Sheet1', tableName: 'Staff', columnNames: ['Employee', 'Qty'],
    }])).rejects.toThrow()
  })

  it.each([['Name', 'name'], ['', 'Qty'], ['Only one']])('rejects invalid column names %j', async (...columnNames) => {
    const apply = (engine as any).applyTableEdits
    expect(typeof apply).toBe('function')
    await expect(apply(await fixture(), [{
      worksheetSheetName: 'Sheet1', tableName: 'Staff', columnNames,
    }])).rejects.toThrow()
  })
})
