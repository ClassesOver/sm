import { describe, expect, it } from 'vitest'

import { createBlankWorkbook, applyCellEdits, readWorkbook, type PivotAddition } from '../src'
import { addPivotTable } from '../src/pivot-add'
import { createBufferEntrySource } from '../src/zip'

async function buildSourceWorkbook(): Promise<Uint8Array> {
  const blank = await createBlankWorkbook()
  return applyCellEdits(blank, [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Region' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 'Product' } },
    { sheetName: 'Sheet1', row: 0, column: 2, writeValue: true, cell: { value: 'Amount' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'East' } },
    { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: 'A' } },
    { sheetName: 'Sheet1', row: 1, column: 2, writeValue: true, cell: { value: 10 } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: 'West' } },
    { sheetName: 'Sheet1', row: 2, column: 1, writeValue: true, cell: { value: 'A' } },
    { sheetName: 'Sheet1', row: 2, column: 2, writeValue: true, cell: { value: 20 } },
    { sheetName: 'Sheet1', row: 3, column: 0, writeValue: true, cell: { value: 'East' } },
    { sheetName: 'Sheet1', row: 3, column: 1, writeValue: true, cell: { value: 'B' } },
    { sheetName: 'Sheet1', row: 3, column: 2, writeValue: true, cell: { value: 15 } },
  ])
}

async function partOf(bytes: Uint8Array, path: string): Promise<string> {
  const source = await createBufferEntrySource(bytes)
  return source.readText(path)
}

async function hasPart(bytes: Uint8Array, path: string): Promise<boolean> {
  const source = await createBufferEntrySource(bytes)
  return source.has(path)
}

function singleLevelPivot(): PivotAddition {
  return {
    worksheetSheetName: 'Sheet1',
    sourceSheetName: 'Sheet1',
    sourceArea: { startRow: 0, startColumn: 0, endRow: 3, endColumn: 2 },
    location: { startRow: 5, startColumn: 0, endRow: 8, endColumn: 2 },
    name: 'ByRegion',
    fieldNames: ['Region', 'Product', 'Amount'],
    rowFieldIndices: [0],
    rowLevelItems: [['East', 'West']],
    rowLines: [
      { t: 'data', members: [0] },
      { t: 'data', members: [1] },
    ],
    values: [{ fieldIndex: 2, agg: 'sum' }],
  }
}

function twoLevelPivot(): PivotAddition {
  return {
    worksheetSheetName: 'Sheet1',
    sourceSheetName: 'Sheet1',
    sourceArea: { startRow: 0, startColumn: 0, endRow: 3, endColumn: 2 },
    location: { startRow: 5, startColumn: 0, endRow: 10, endColumn: 3 },
    name: 'ByRegionProduct',
    fieldNames: ['Region', 'Product', 'Amount'],
    rowFieldIndices: [0, 1],
    rowLevelItems: [
      ['East', 'West'],
      ['A', 'B'],
    ],
    rowLines: [
      { t: 'data', members: [0, 0] },
      { t: 'data', members: [0, 1] },
      { t: 'data', members: [1, 0] },
    ],
    values: [{ fieldIndex: 2, agg: 'sum' }],
  }
}

describe('pivot table creation', () => {
  it('creates the full part family and wires worksheet + workbook', async () => {
    const bytes = await buildSourceWorkbook()
    const edited = await addPivotTable(bytes, singleLevelPivot())
    expect(await hasPart(edited, 'xl/pivotTables/pivotTable1.xml')).toBe(true)
    expect(await hasPart(edited, 'xl/pivotCache/pivotCacheDefinition1.xml')).toBe(true)
    expect(await hasPart(edited, 'xl/pivotCache/pivotCacheRecords1.xml')).toBe(true)
    expect(await hasPart(edited, 'xl/pivotTables/_rels/pivotTable1.xml.rels')).toBe(true)
    expect(await hasPart(edited, 'xl/pivotCache/_rels/pivotCacheDefinition1.xml.rels')).toBe(true)

    const table = await partOf(edited, 'xl/pivotTables/pivotTable1.xml')
    expect(table).toContain('name="ByRegion"')
    expect(table).toContain('<field x="0"/>') // row field
    expect(table).not.toContain('subtotal=') // sum is implicit
    expect(table).toContain('Sum of Amount')

    // cache pre-populated with the three source rows
    const records = await partOf(edited, 'xl/pivotCache/pivotCacheRecords1.xml')
    expect(records).toContain('count="3"')
    expect(records).toContain('<x v="0"/>')
    expect(records).toContain('<n v="15"/>')

    const workbook = await partOf(edited, 'xl/workbook.xml')
    expect(workbook).toContain('<pivotCache cacheId="1"')
    expect((await readWorkbook(edited)).sheets[0]?.name).toBe('Sheet1')
  })

  it('multi-level rows switch to tabular layout with r-repeat axis items', async () => {
    const bytes = await buildSourceWorkbook()
    const edited = await addPivotTable(bytes, twoLevelPivot())
    const table = await partOf(edited, 'xl/pivotTables/pivotTable1.xml')
    expect(table).toContain('compact="0" compactData="0" outline="0" outlineData="0"')
    expect(table).toContain('<rowFields count="2"><field x="0"/><field x="1"/></rowFields>')
    // carry rules: line 1 emits both levels (member 0 encodes bare <x/>);
    // line 2 shares level-0 → r="1"; line 3 breaks level-0 → full re-emit
    expect(table).toContain('<i><x/><x/></i>')
    expect(table).toContain('<i r="1"><x v="1"/></i>')
    expect(table).toContain('<i><x v="1"/><x/></i>')
    // the location is normalized to the computed tabular matrix (3 label/value
    // columns × header + 5 lines + grand total), not the requested rectangle
    expect(table).toContain('<location ref="A6:C12" firstHeaderRow="1" firstDataRow="1" firstDataCol="2"/>')
  })

  it('bakes the computed matrix into worksheet cells', async () => {
    const bytes = await buildSourceWorkbook()
    const edited = await addPivotTable(bytes, twoLevelPivot())
    const sheet = await partOf(edited, 'xl/worksheets/sheet1.xml')
    const cell = (ref: string): string =>
      sheet.match(new RegExp(`<c r="${ref}"[^>]*(?:/>|>([\\s\\S]*?)</c>)`))?.[1]
        ?.replace(/<[^>]+>/g, '')
        .trim() ?? ''
    expect(cell('A6')).toBe('Region')
    expect(cell('B6')).toBe('Product')
    expect(cell('C6')).toBe('Sum of Amount')
    expect(cell('A7')).toBe('East')
    expect(cell('B7')).toBe('A')
    expect(cell('C7')).toBe('10')
    expect(cell('A8')).toBe('') // tabular carry: repeated level-0 stays blank
    expect(cell('B8')).toBe('B')
    expect(cell('C8')).toBe('15')
    expect(cell('A9')).toBe('East')
    expect(cell('B9')).toBe('Subtotal')
    expect(cell('C9')).toBe('25')
    expect(cell('C10')).toBe('20')
    expect(cell('C11')).toBe('20')
    expect(cell('A12')).toBe('Grand Total')
    expect(cell('C12')).toBe('45')
  })

  it('supports a column level and grand-total column items', async () => {
    const bytes = await buildSourceWorkbook()
    const edited = await addPivotTable(bytes, {
      ...twoLevelPivot(),
      name: 'Matrix',
      rowFieldIndices: [0],
      rowLevelItems: [['East', 'West']],
      rowLines: [
        { t: 'data', members: [0] },
        { t: 'data', members: [1] },
      ],
      columnFieldIndices: [1],
      colLevelItems: [['A', 'B']],
      colLines: [
        { t: 'data', members: [0] },
        { t: 'data', members: [1] },
      ],
    })
    const table = await partOf(edited, 'xl/pivotTables/pivotTable1.xml')
    expect(table).toContain('<colFields count="1"><field x="1"/></colFields>')
    expect(table).toContain('firstDataRow="1" firstDataCol="1"')
  })

  it('rejects duplicate names, inconsistent lines, and mismatched widths', async () => {
    const bytes = await buildSourceWorkbook()
    const once = await addPivotTable(bytes, singleLevelPivot())
    await expect(addPivotTable(once, singleLevelPivot())).rejects.toThrow(/already taken/)
    await expect(
      addPivotTable(bytes, {
        ...twoLevelPivot(),
        rowLines: [{ t: 'data', members: [0, 5] }],
      }),
    ).rejects.toThrow(/inconsistent row line/)
    await expect(
      addPivotTable(bytes, { ...singleLevelPivot(), fieldNames: ['Only'] }),
    ).rejects.toThrow(/outside its source|field names/)
    await expect(
      addPivotTable(bytes, { ...singleLevelPivot(), rowLines: [] }),
    ).rejects.toThrow(/no row layout lines/)
  })
})

describe('pivot calculated fields', () => {
  it('appends a databaseField="0" cacheField and points the dataField at it', async () => {
    const bytes = await buildSourceWorkbook()
    const edited = await addPivotTable(bytes, {
      ...singleLevelPivot(),
      name: 'WithCalc',
      values: [
        { fieldIndex: 2, agg: 'sum' },
        { fieldIndex: -1, agg: 'sum', formula: 'Amount*2', calcName: 'Double' },
      ],
    })
    const definition = await partOf(edited, 'xl/pivotCache/pivotCacheDefinition1.xml')
    expect(definition).toContain('cacheFields count="4"')
    expect(definition).toContain('name="Double" formula="(&apos;Amount&apos;*2)" databaseField="0"')
    const table = await partOf(edited, 'xl/pivotTables/pivotTable1.xml')
    expect(table).toContain('pivotFields count="4"')
    // calc dataField fld points at the appended cacheField (index 3)
    expect(table).toContain('<dataField name="Sum of Double" fld="3" baseField="0" baseItem="0"/>')
    // records keep one cell per database field only
    const records = await partOf(edited, 'xl/pivotCache/pivotCacheRecords1.xml')
    expect(records).toContain('<r><x v="0"/><s v="A"/><n v="10"/></r>')
  })

  it('rejects bad calculated fields (missing name, unknown reference, non-sum agg)', async () => {
    const bytes = await buildSourceWorkbook()
    await expect(
      addPivotTable(bytes, {
        ...singleLevelPivot(),
        values: [{ fieldIndex: -1, agg: 'sum', formula: 'Amount*2' }],
      }),
    ).rejects.toThrow(/invalid calculated field/)
    await expect(
      addPivotTable(bytes, {
        ...singleLevelPivot(),
        values: [{ fieldIndex: -1, agg: 'sum', formula: 'Profit', calcName: 'P' }],
      }),
    ).rejects.toThrow(/bad calculated-field formula/)
    await expect(
      addPivotTable(bytes, {
        ...singleLevelPivot(),
        values: [{ fieldIndex: -1, agg: 'count', formula: 'Amount', calcName: 'C' }],
      }),
    ).rejects.toThrow(/invalid calculated field/)
  })
})

describe('pivot filters', () => {
  it('marks filtered-out members h="1" and writes the <filters> block', async () => {
    const bytes = await buildSourceWorkbook()
    const edited = await addPivotTable(bytes, {
      ...singleLevelPivot(),
      name: 'EastOnly',
      filters: [{ kind: 'label', field: 0, op: 'equal', value: 'East' }],
      rowHiddenItems: [[1]], // West
    })
    const table = await partOf(edited, 'xl/pivotTables/pivotTable1.xml')
    // two members; the second (West) is hidden
    expect(table).toContain('<item x="0"/><item x="1" h="1"/><item t="default"/>')
    expect(table).toContain(
      '<filters count="1"><filter fld="0" type="captionEqual" evalOrder="-1" id="1" ' +
        'stringValue1="East"><autoFilter ref="A1"><filterColumn colId="0"><customFilters>' +
        '<customFilter val="East"/></customFilters></filterColumn></autoFilter></filter></filters>',
    )
    // layout lines unchanged by the writer; filtering is the caller's bake
    expect(table).toContain('<i><x/></i>')
  })

  it('keeps sum subtotal implicit and defaults percent modes to 0.00%', async () => {
    const bytes = await buildSourceWorkbook()
    const edited = await addPivotTable(bytes, {
      ...singleLevelPivot(),
      name: 'TopPercent',
      values: [{ fieldIndex: 2, agg: 'sum', showDataAs: 'percentOfTotal' }],
    })
    const table = await partOf(edited, 'xl/pivotTables/pivotTable1.xml')
    // sum stays implicit (no subtotal attr); percent modes default to 0.00% (id 10)
    expect(table).toContain(
      '<dataField name="Sum of Amount" fld="2" showDataAs="percentOfTotal" baseField="0" baseItem="0" numFmtId="10"/>',
    )
    expect(table).not.toContain('subtotal="sum"')
  })

  it('rejects out-of-range hidden items and writes column fields with multiple values', async () => {
    const bytes = await buildSourceWorkbook()
    await expect(
      addPivotTable(bytes, {
        ...singleLevelPivot(),
        rowHiddenItems: [[5]],
      }),
    ).rejects.toThrow(/out-of-range hidden item/)
    const matrix=await addPivotTable(bytes, {
        ...singleLevelPivot(),
        name: 'Matrix',
        columnFieldIndices: [1],
        colLevelItems: [['A', 'B']],
        colLines: [
          { t: 'data', members: [0] },
          { t: 'data', members: [1] },
        ],
        values: [
          { fieldIndex: 2, agg: 'sum' },
          { fieldIndex: 1, agg: 'count' },
        ],
      })
    expect(await partOf(matrix,'xl/pivotTables/pivotTable1.xml')).toContain('<field x="-2"/>')
  })
})
