import { describe, expect, it } from 'vitest'

import { applyCellEdits, createBlankWorkbook, type PivotAddition } from '../src'
import { addPivotTable } from '../src/pivot-add'
import { applyPivotLayoutExpansions } from '../src/pivot-expand'
import { createBufferEntrySource } from '../src/zip'

async function partOf(bytes: Uint8Array, path: string): Promise<string> {
  const source = await createBufferEntrySource(bytes)
  return source.readText(path)
}

async function buildSourceWorkbook(): Promise<Uint8Array> {
  return applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'Region' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 'Amount' } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'East' } },
    { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: 10 } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: 'West' } },
    { sheetName: 'Sheet1', row: 2, column: 1, writeValue: true, cell: { value: 20 } },
  ])
}

function singleLevelPivot(): PivotAddition {
  return {
    worksheetSheetName: 'Sheet1',
    sourceSheetName: 'Sheet1',
    sourceArea: { startRow: 0, startColumn: 0, endRow: 2, endColumn: 1 },
    location: { startRow: 4, startColumn: 4, endRow: 7, endColumn: 6 },
    name: 'ByRegion',
    fieldNames: ['Region', 'Amount'],
    rowFieldIndices: [0],
    rowLevelItems: [['East', 'West']],
    rowLines: [
      { t: 'data', members: [0] },
      { t: 'data', members: [1] },
    ],
    values: [{ fieldIndex: 1, agg: 'sum' }],
  }
}

async function cellText(bytes: Uint8Array, ref: string): Promise<string> {
  const sheet = await partOf(bytes, 'xl/worksheets/sheet1.xml')
  return sheet.match(new RegExp(`<c r="${ref}"[^>]*(?:/>|>([\\s\\S]*?)</c>)`))?.[1]
    ?.replace(/<[^>]+>/g, '')
    .trim() ?? ''
}

describe('pivot output-area expansion', () => {
  it('widens the location ref and skips no-ops', async () => {
    const base = await buildSourceWorkbook()
    const withPivot = await addPivotTable(base, singleLevelPivot())
    // creation normalizes to the computed 2-column matrix before any growth
    expect(await partOf(withPivot, 'xl/pivotTables/pivotTable1.xml')).toContain(
      '<location ref="E5:F8"',
    )
    expect(await cellText(withPivot, 'F5')).toBe('Sum of Amount')
    expect(await cellText(withPivot, 'F8')).toBe('30')
    const cachePath = 'xl/pivotCache/pivotCacheDefinition1.xml'

    // growth by one row, then one more row + one column
    const grownOnce = await applyPivotLayoutExpansions(withPivot, [
      { cachePath, newOutputRef: 'E5:G9' },
    ])
    expect(await partOf(grownOnce, 'xl/pivotTables/pivotTable1.xml')).toContain(
      '<location ref="E5:G9"',
    )
    const grown = await applyPivotLayoutExpansions(grownOnce, [
      { cachePath, newOutputRef: 'E5:H9' },
    ])
    expect(await partOf(grown, 'xl/pivotTables/pivotTable1.xml')).toContain(
      '<location ref="E5:H9"',
    )

    // same ref → no-op (bytes unchanged)
    const touched = await applyPivotLayoutExpansions(grown, [{ cachePath, newOutputRef: 'E5:H9' }])
    expect(touched).toBe(grown)

    // shrinking refs are silently skipped
    const shrunk = await applyPivotLayoutExpansions(grown, [{ cachePath, newOutputRef: 'E5:G9' }])
    expect(await partOf(shrunk, 'xl/pivotTables/pivotTable1.xml')).toContain(
      '<location ref="E5:H9"',
    )
  })

  it('fails closed when grown cells already hold worksheet content', async () => {
    const base = await buildSourceWorkbook()
    const withPivot = await addPivotTable(base, singleLevelPivot())
    // row 10 (index 9) sits in the growth band E5:H9... row index 8 is the
    // newly added row; put a value in A9 → outside; put one in F9 (row 9,
    // col 5) which is inside the added band
    const blocked = await applyCellEdits(withPivot, [
      { sheetName: 'Sheet1', row: 8, column: 5, writeValue: true, cell: { value: '占用' } },
    ])
    await expect(
      applyPivotLayoutExpansions(blocked, [
        { cachePath: 'xl/pivotCache/pivotCacheDefinition1.xml', newOutputRef: 'E5:G9' },
      ]),
    ).rejects.toThrow(/conflicts with existing worksheet content/)
  })

  it('refuses a moved origin and tolerates an unlinked cache', async () => {
    const base = await buildSourceWorkbook()
    const withPivot = await addPivotTable(base, singleLevelPivot())
    await expect(
      applyPivotLayoutExpansions(withPivot, [
        { cachePath: 'xl/pivotCache/pivotCacheDefinition1.xml', newOutputRef: 'F6:G9' },
      ]),
    ).rejects.toThrow(/top-left cell/)
    // an unknown cache path is skipped silently
    const untouched = await applyPivotLayoutExpansions(withPivot, [
      { cachePath: 'xl/pivotCache/pivotCacheDefinition99.xml', newOutputRef: 'E5:H9' },
    ])
    expect(untouched).toBe(withPivot)
  })

  it('relayout regenerates both definitions keeping name/cacheId/records rel', async () => {
    const base = await buildSourceWorkbook()
    const withPivot = await addPivotTable(base, singleLevelPivot())
    const cachePath = 'xl/pivotCache/pivotCacheDefinition1.xml'

    const relaid = await applyPivotLayoutExpansions(withPivot, [
      {
        cachePath,
        newOutputRef: 'E5:H9',
        relayout: {
          sourceSheetName: 'Sheet1',
          sourceArea: { startRow: 0, startColumn: 0, endRow: 2, endColumn: 1 },
          fieldNames: ['Region', 'Amount'],
          rowFieldIndices: [0],
          rowLevelItems: [['East', 'West']],
          rowLines: [
            { t: 'data', members: [0] },
            { t: 'data', members: [1] },
          ],
          values: [{ fieldIndex: 1, agg: 'count' }],
        },
      },
    ])
    const table = await partOf(relaid, 'xl/pivotTables/pivotTable1.xml')
    expect(table).toContain('name="ByRegion"') // original name kept
    expect(table).toContain('cacheId="1"')
    expect(table).toContain('<location ref="E5:H9"')
    expect(table).toContain('Count of Amount') // regenerated from the new layout
    const definition = await partOf(relaid, cachePath)
    expect(definition).toContain('r:id="rId1"') // records rel id kept
    const records = await partOf(relaid, 'xl/pivotCache/pivotCacheRecords1.xml')
    expect(records).toContain('count="2"') // rebuilt from the relayout source
    expect(records).toContain('<r><x v="0"/><n v="10"/></r>')
    expect(records).toContain('<r><x v="1"/><n v="20"/></r>')
    // the worksheet carries the new aggregation, not just the XML parts
    expect(await cellText(relaid, 'F5')).toBe('Count of Amount')
    expect(await cellText(relaid, 'F6')).toBe('1')
    expect(await cellText(relaid, 'F7')).toBe('1')
    expect(await cellText(relaid, 'F8')).toBe('2')
  })

  it('clears stale output cells when a relayout shrinks the matrix', async () => {
    const base = await buildSourceWorkbook()
    const withPivot = await addPivotTable(base, singleLevelPivot())
    const grown = await applyPivotLayoutExpansions(withPivot, [
      { cachePath: 'xl/pivotCache/pivotCacheDefinition1.xml', newOutputRef: 'E5:H9' },
    ])
    const relaid = await applyPivotLayoutExpansions(grown, [
      {
        cachePath: 'xl/pivotCache/pivotCacheDefinition1.xml',
        newOutputRef: 'E5:H9',
        relayout: {
          sourceSheetName: 'Sheet1',
          sourceArea: { startRow: 0, startColumn: 0, endRow: 1, endColumn: 1 },
          fieldNames: ['Region', 'Amount'],
          rowFieldIndices: [0],
          rowLevelItems: [['East']],
          rowLines: [{ t: 'data', members: [0] }],
          values: [{ fieldIndex: 1, agg: 'count' }],
        },
      },
    ])
    // the reserved ref survives, but the shrunken matrix vacates its old cells
    expect(await partOf(relaid, 'xl/pivotTables/pivotTable1.xml')).toContain('<location ref="E5:H9"')
    expect(await cellText(relaid, 'E5')).toBe('Region')
    expect(await cellText(relaid, 'F5')).toBe('Count of Amount')
    expect(await cellText(relaid, 'E7')).toBe('Grand Total')
    expect(await cellText(relaid, 'F7')).toBe('1')
    expect(await cellText(relaid, 'E8')).toBe('') // old West row cleared
    expect(await cellText(relaid, 'F8')).toBe('') // old grand-total row cleared
  })
})
