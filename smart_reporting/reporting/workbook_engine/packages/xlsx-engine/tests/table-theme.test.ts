import { describe, expect, it } from 'vitest'

import { applyCellEdits, createBlankWorkbook, applyThemeState, type TableAddition } from '../src'
import { applySheetEdits } from '../src/sheet-ops'
import { applyTableAdditions } from '../src/table-add'
import { assemblePackage, createBufferEntrySource, inventoryXlsx } from '../src/zip'

async function partOf(bytes: Uint8Array, path: string): Promise<string> {
  const source = await createBufferEntrySource(bytes)
  return source.readText(path)
}

async function hasPart(bytes: Uint8Array, path: string): Promise<boolean> {
  const source = await createBufferEntrySource(bytes)
  return source.has(path)
}

async function buildWorkbook(): Promise<Uint8Array> {
  return applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Name' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 'Qty' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'a' } },
    { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: 1 } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: 'b' } },
    { sheetName: 'Sheet1', row: 2, column: 1, writeValue: true, cell: { value: 2 } },
  ])
}

async function workbookWithMergedCells(): Promise<Uint8Array> {
  const bytes = await buildWorkbook()
  const worksheetPath = 'xl/worksheets/sheet1.xml'
  const worksheet = await partOf(bytes, worksheetPath)
  const mergedWorksheet = worksheet.replace(
    '</worksheet>',
    '<mergeCells count="1"><mergeCell ref="A1:B2"/></mergeCells></worksheet>',
  )
  return (
    await assemblePackage(bytes, {
      replaced: new Map([[worksheetPath, mergedWorksheet]]),
      added: new Map(),
      addedBinary: new Map(),
      removedEntries: [],
      addedEntries: [],
      touchedEntries: [worksheetPath],
    })
  ).buffer
}

async function buildTwoSheetWorkbook(): Promise<Uint8Array> {
  const blank = await createBlankWorkbook()
  const withSecond = await applySheetEdits(blank, {
    renames: [],
    additions: [{ name: 'Data' }],
    removals: [],
    order: ['Sheet1', 'Data'],
  })
  return applyCellEdits(withSecond, [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Name' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'a' } },
    { sheetName: 'Data', row: 0, column: 0, writeValue: true, cell: { value: 'Name' } },
    { sheetName: 'Data', row: 1, column: 0, writeValue: true, cell: { value: 'b' } },
  ])
}

async function mutatePart(
  bytes: Uint8Array,
  path: string,
  transform: (content: string) => string,
  addedBinary = new Map<string, Uint8Array>(),
): Promise<Uint8Array> {
  const content = await partOf(bytes, path)
  return (
    await assemblePackage(bytes, {
      replaced: new Map([[path, transform(content)]]),
      added: new Map(),
      addedBinary,
      removedEntries: [],
      addedEntries: [...addedBinary.keys()],
      touchedEntries: [path, ...addedBinary.keys()],
    })
  ).buffer
}

function tableAddition(): TableAddition {
  return {
    worksheetSheetName: 'Sheet1',
    area: { startRow: 0, startColumn: 0, endRow: 2, endColumn: 1 },
    name: 'Stock',
    columnNames: ['Name', 'Qty'],
    bandedRows: true,
  }
}

const THEME_XML =
  '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
  '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Office">' +
  '<a:themeElements>' +
  '<a:clrScheme name="Office">' +
  '<a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>' +
  '<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>' +
  '<a:dk2><a:srgbClr val="44546A"/></a:dk2>' +
  '<a:lt2><a:srgbClr val="E7E6E6"/></a:lt2>' +
  '<a:accent1><a:srgbClr val="4472C4"/></a:accent1>' +
  '<a:accent2><a:srgbClr val="ED7D31"/></a:accent2>' +
  '<a:accent3><a:srgbClr val="A5A5A5"/></a:accent3>' +
  '<a:accent4><a:srgbClr val="FFC000"/></a:accent4>' +
  '<a:accent5><a:srgbClr val="5B9BD5"/></a:accent5>' +
  '<a:accent6><a:srgbClr val="70AD47"/></a:accent6>' +
  '<a:hlink><a:srgbClr val="0563C1"/></a:hlink>' +
  '<a:folHlink><a:srgbClr val="954F72"/></a:folHlink>' +
  '</a:clrScheme>' +
  '<a:fontScheme name="Office">' +
  '<a:majorFont><a:latin typeface="Calibri Light"/></a:majorFont>' +
  '<a:minorFont><a:latin typeface="Calibri"/></a:minorFont>' +
  '</a:fontScheme>' +
  '</a:themeElements>' +
  '</a:theme>'

describe('table creation', () => {
  it('creates the table part and wires rels + content type + tableParts', async () => {
    const bytes = await buildWorkbook()
    const edited = await applyTableAdditions(bytes, [tableAddition()])
    expect(await hasPart(edited, 'xl/tables/table1.xml')).toBe(true)

    const table = await partOf(edited, 'xl/tables/table1.xml')
    expect(table).toContain('id="1" name="Stock" displayName="Stock" ref="A1:B3" totalsRowShown="0"')
    expect(table).toContain('<autoFilter ref="A1:B3"/>')
    expect(table).toContain('<tableColumn id="1" name="Name"/><tableColumn id="2" name="Qty"/>')
    expect(table).toContain(
      '<tableStyleInfo name="TableStyleMedium2" showFirstColumn="0" showLastColumn="0" showRowStripes="1" showColumnStripes="0"/>',
    )

    const contentTypes = await partOf(edited, '[Content_Types].xml')
    expect(contentTypes).toContain(
      '<Override PartName="/xl/tables/table1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/>',
    )
    const rels = await partOf(edited, 'xl/worksheets/_rels/sheet1.xml.rels')
    expect(rels).toContain('Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/table"')
    expect(rels).toContain('Target="../tables/table1.xml"')
    const worksheet = await partOf(edited, 'xl/worksheets/sheet1.xml')
    expect(worksheet).toContain('<tableParts count="1"><tablePart r:id="rId1"/></tableParts>')
    // schema order: tableParts after sheetData, before extLst
    expect(worksheet.indexOf('</sheetData>')).toBeLessThan(worksheet.indexOf('<tableParts'))

    // two additions in one call must allocate two distinct parts and detect overlap
    const batch = await applyTableAdditions(bytes, [
      { ...tableAddition(), name: 'One', area: { startRow: 4, startColumn: 0, endRow: 6, endColumn: 1 } },
      { ...tableAddition(), name: 'Two', area: { startRow: 8, startColumn: 0, endRow: 10, endColumn: 1 } },
    ])
    expect(await hasPart(batch, 'xl/tables/table1.xml')).toBe(true)
    expect(await hasPart(batch, 'xl/tables/table2.xml')).toBe(true)
    await expect(
      applyTableAdditions(bytes, [
        { ...tableAddition(), name: 'OverlapOne', area: { startRow: 4, startColumn: 0, endRow: 6, endColumn: 1 } },
        { ...tableAddition(), name: 'OverlapTwo', area: { startRow: 5, startColumn: 1, endRow: 7, endColumn: 2 } },
      ]),
    ).rejects.toThrow(/same operation/)

    // A separate second call also allocates id=2 and tableParts count=2.
    const twice = await applyTableAdditions(edited, [
      { ...tableAddition(), name: 'Other', area: { startRow: 5, startColumn: 0, endRow: 7, endColumn: 1 } },
    ])
    expect(await hasPart(twice, 'xl/tables/table2.xml')).toBe(true)
    const worksheet2 = await partOf(twice, 'xl/worksheets/sheet1.xml')
    expect(worksheet2).toContain('<tableParts count="2">')
  })

  it('allocates unique ids and paths after the existing highest tableN path', async () => {
    const bytes = await buildWorkbook()
    const seeded = await assemblePackage(bytes, {
      replaced: new Map(),
      added: new Map([
        ['xl/tables/table9.xml', '<table xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" id="9" name="Old" displayName="Old" ref="D1:E2"/>'],
      ]),
      addedBinary: new Map(),
      removedEntries: [],
      addedEntries: ['xl/tables/table9.xml'],
      touchedEntries: ['xl/tables/table9.xml'],
    })
    const edited = await applyTableAdditions(seeded.buffer, [
      { ...tableAddition(), name: 'One', area: { startRow: 4, startColumn: 0, endRow: 5, endColumn: 1 } },
      { ...tableAddition(), name: 'Two', area: { startRow: 7, startColumn: 0, endRow: 8, endColumn: 1 } },
    ])
    expect(await hasPart(edited, 'xl/tables/table10.xml')).toBe(true)
    expect(await hasPart(edited, 'xl/tables/table11.xml')).toBe(true)
    expect(await partOf(edited, 'xl/tables/table10.xml')).toContain('id="10"')
    expect(await partOf(edited, 'xl/tables/table11.xml')).toContain('id="11"')
  })

  it('allows identical ranges on different sheets but rejects overlaps on one sheet', async () => {
    const bytes = await buildTwoSheetWorkbook()
    const oneColumn = { ...tableAddition(), columnNames: ['Name'] }
    const sameRange = await applyTableAdditions(bytes, [
      { ...oneColumn, name: 'SheetOne', area: { startRow: 0, startColumn: 0, endRow: 1, endColumn: 0 } },
      { ...oneColumn, name: 'SheetTwo', worksheetSheetName: 'Data', area: { startRow: 0, startColumn: 0, endRow: 1, endColumn: 0 } },
    ])
    expect(await hasPart(sameRange, 'xl/tables/table1.xml')).toBe(true)
    expect(await hasPart(sameRange, 'xl/tables/table2.xml')).toBe(true)
    await expect(
      applyTableAdditions(bytes, [
        { ...oneColumn, name: 'First', area: { startRow: 0, startColumn: 0, endRow: 1, endColumn: 0 } },
        { ...oneColumn, name: 'Second', area: { startRow: 1, startColumn: 0, endRow: 2, endColumn: 0 } },
      ]),
    ).rejects.toThrow(/same operation/)
  })

  it('rejects true sheet autoFilter and defined-name collisions', async () => {
    const bytes = await buildWorkbook()
    const withFilter = await mutatePart(bytes, 'xl/worksheets/sheet1.xml', (xml) =>
      xml.replace('</sheetData>', '</sheetData><autoFilter ref="A1:B3"/>'),
    )
    await expect(applyTableAdditions(withFilter, [tableAddition()])).rejects.toThrow(/sheet auto-filter/)

    const withDefinedName = await mutatePart(bytes, 'xl/workbook.xml', (xml) =>
      xml.replace('</sheets>', '</sheets><definedNames><definedName name="Stock">Sheet1!$A$1</definedName></definedNames>'),
    )
    await expect(applyTableAdditions(withDefinedName, [tableAddition()])).rejects.toThrow(/defined name/)
  })

  it('expands a self-closing tableParts element', async () => {
    const selfClosing = await mutatePart(await buildWorkbook(), 'xl/worksheets/sheet1.xml', (xml) =>
      xml.replace('</worksheet>', '<tableParts count="0"/></worksheet>'),
    )
    const edited = await applyTableAdditions(selfClosing, [tableAddition()])
    const worksheet = await partOf(edited, 'xl/worksheets/sheet1.xml')
    expect(worksheet).toContain('<tableParts count="1"><tablePart r:id="rId1"/></tableParts>')
    expect(worksheet.match(/<tableParts\b/g)).toHaveLength(1)
  })

  it('rejects DOCTYPE and ENTITY declarations without changing the source buffer', async () => {
    const bytes = await buildWorkbook()
    const withDoctype = await mutatePart(bytes, 'xl/worksheets/sheet1.xml', (xml) =>
      '<!DOCTYPE worksheet [<!ENTITY x "blocked">]>' + xml,
    )
    const doctypeSnapshot = withDoctype.slice()
    await expect(applyTableAdditions(withDoctype, [tableAddition()])).rejects.toThrow(/DOCTYPE 或 ENTITY/)
    expect(withDoctype).toEqual(doctypeSnapshot)
    const before = bytes.slice()
    await expect(applyTableAdditions(bytes, [tableAddition(), { ...tableAddition(), name: 'Overlap', area: { startRow: 1, startColumn: 1, endRow: 2, endColumn: 2 } }])).rejects.toThrow(/same operation/)
    expect(bytes).toEqual(before)
  })

  it('preserves unrelated opaque binary, extLst, and rels entries', async () => {
    const bytes = await buildWorkbook()
    const opaque = new Uint8Array([0, 1, 2, 255, 8, 13])
    const seeded = await mutatePart(
      bytes,
      'xl/worksheets/sheet1.xml',
      (xml) => xml.replace('</worksheet>', '<extLst><x:opaque xmlns:x="urn:test"/></extLst></worksheet>'),
      new Map([
        ['xl/media/opaque.bin', opaque],
        ['xl/custom/opaque.rels', new Uint8Array([7, 6, 5, 4])],
      ]),
    )
    const beforeEntries = await inventoryXlsx(seeded)
    const sourceSnapshot = seeded.slice()
    const edited = await applyTableAdditions(seeded, [{ ...tableAddition(), name: 'Added', area: { startRow: 5, startColumn: 0, endRow: 6, endColumn: 1 } }])
    expect(seeded).toEqual(sourceSnapshot)
    const afterEntries = await inventoryXlsx(edited)
    const afterByPath = new Map(afterEntries.map((entry) => [entry.path, entry.sha256]))
    for (const path of ['xl/media/opaque.bin', 'xl/custom/opaque.rels']) {
      expect(afterByPath.get(path)).toBe(beforeEntries.find((entry) => entry.path === path)?.sha256)
    }
    expect(await partOf(edited, 'xl/worksheets/sheet1.xml')).toContain('<extLst><x:opaque xmlns:x="urn:test"/></extLst>')
  })

  it('fails closed on collisions, overlaps, and bad column names', async () => {
    const bytes = await buildWorkbook()
    const withTable = await applyTableAdditions(bytes, [tableAddition()])
    // duplicate name (both name= and displayName= namespaces)
    await expect(applyTableAdditions(withTable, [tableAddition()])).rejects.toThrow(/already taken/)
    // overlapping area with the existing table
    await expect(
      applyTableAdditions(withTable, [{ ...tableAddition(), name: 'Other', area: { startRow: 2, startColumn: 1, endRow: 4, endColumn: 2 } }]),
    ).rejects.toThrow(/overlaps an existing table/)
    // merged cells inside the area
    const merged = await workbookWithMergedCells()
    await expect(applyTableAdditions(merged, [tableAddition()])).rejects.toThrow(/overlaps merged cells/)
    // width mismatch and duplicate/blank column names
    await expect(
      applyTableAdditions(bytes, [{ ...tableAddition(), columnNames: ['Only'] }]),
    ).rejects.toThrow(/spans 2 columns/)
    await expect(
      applyTableAdditions(bytes, [{ ...tableAddition(), columnNames: ['X', 'x'] }]),
    ).rejects.toThrow(/duplicate column name/)
    await expect(
      applyTableAdditions(bytes, [{ ...tableAddition(), columnNames: ['X', ' '] }]),
    ).rejects.toThrow(/blank column name/)
    // header-only area
    await expect(
      applyTableAdditions(bytes, [
        { ...tableAddition(), area: { startRow: 0, startColumn: 0, endRow: 0, endColumn: 1 } },
      ]),
    ).rejects.toThrow(/header row plus at least one data row/)
    // unknown sheet
    await expect(
      applyTableAdditions(bytes, [{ ...tableAddition(), worksheetSheetName: 'Nope' }]),
    ).rejects.toThrow(/not found/)
  })
})

describe('theme state', () => {
  it('rewrites the color scheme slots in renderer index order', () => {
    // values[0] is lt1, values[1] is dk1 (swapped pairs), accents follow
    const values = [
      '#FFFFFF', '#000000', '#EEEEEE', '#333333',
      '#111111', '#222222', '#333344', '#444455',
      '#555566', '#666677', '#0563C1', '#954F72',
    ]
    const xml = applyThemeState(THEME_XML, { colors: { name: 'Custom', values } })
    // lt1 slot takes values[0]; sysClr is replaced by srgbClr
    expect(xml).toContain('<a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>')
    expect(xml).toContain('<a:dk1><a:srgbClr val="000000"/></a:dk1>')
    expect(xml).toContain('<a:accent1><a:srgbClr val="111111"/></a:accent1>')
    expect(xml).toContain('<a:accent6><a:srgbClr val="666677"/></a:accent6>')
    expect(xml).toContain('<a:clrScheme name="Custom">')
    // untouched slots structure elsewhere stays (fontScheme untouched here)
    expect(xml).toContain('<a:latin typeface="Calibri Light"/>')
  })

  it('rewrites major/minor fonts and the scheme name', () => {
    const xml = applyThemeState(THEME_XML, {
      fonts: { name: 'Corp', major: 'Georgia', minor: 'Verdana' },
    })
    expect(xml).toContain('<a:latin typeface="Georgia"/>')
    expect(xml).toContain('<a:latin typeface="Verdana"/>')
    expect(xml).toContain('<a:fontScheme name="Corp">')
    expect(xml).toContain('<a:srgbClr val="4472C4"/>') // colors untouched
  })

  it('fails closed on bad palettes', () => {
    expect(() =>
      applyThemeState(THEME_XML, { colors: { name: 'X', values: ['#000000'] } }),
    ).toThrow(/needs 12 colors/)
    const withBad = Array.from({ length: 12 }, () => '#00FF00')
    withBad[4] = 'nope'
    expect(() => applyThemeState(THEME_XML, { colors: { name: 'X', values: withBad } })).toThrow(
      /not a valid #RRGGBB/,
    )
    const noFonts = THEME_XML.replace(/<a:fontScheme[\s\S]*?<\/a:fontScheme>/, '')
    expect(() =>
      applyThemeState(noFonts, { fonts: { name: 'X', major: 'A', minor: 'B' } }),
    ).toThrow(/no font scheme/)
  })
})
