import { describe, expect, it } from 'vitest'

import { applyCellEdits, applyChartAdditions, createBlankWorkbook, readWorkbook } from '../src'
import { applyRowColumnOps, applySheetEdits } from '../src/sheet-ops'
import { createBufferEntrySource } from '../src/zip'

async function sheetXmlOf(bytes: Uint8Array, path = 'xl/worksheets/sheet1.xml'): Promise<string> {
  const source = await createBufferEntrySource(bytes)
  return source.readText(path)
}

async function partTextOf(bytes: Uint8Array, path: string): Promise<string> {
  const source = await createBufferEntrySource(bytes)
  return source.readText(path)
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
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 10 } },
    { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 20 } },
    { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: 30 } },
    {
      sheetName: 'Sheet1',
      row: 0,
      column: 1,
      writeValue: true,
      cell: { value: null, formula: '=SUM(A1:A3)' },
    },
    {
      sheetName: 'Data',
      row: 0,
      column: 0,
      writeValue: true,
      cell: { value: null, formula: '=Sheet1!A1*2' },
    },
  ])
}

describe('sheet management', () => {
  it('adds a sheet and makes it editable immediately', async () => {
    const bytes = await createBlankWorkbook()
    const edited = await applySheetEdits(bytes, {
      renames: [],
      additions: [{ name: 'Q2' }],
      removals: [],
      order: ['Sheet1', 'Q2'],
    })
    const model = await readWorkbook(edited)
    expect(model.sheets.map((sheet) => sheet.name)).toEqual(['Sheet1', 'Q2'])
    const written = await applyCellEdits(edited, [
      { sheetName: 'Q2', row: 0, column: 0, writeValue: true, cell: { value: 'hello' } },
    ])
    const reopened = await readWorkbook(written)
    expect(reopened.sheets[1]?.cells.A1?.value).toBe('hello')
  })

  it('rejects invalid and duplicate sheet names', async () => {
    const bytes = await createBlankWorkbook()
    await expect(
      applySheetEdits(bytes, { renames: [], additions: [{ name: 'a[b' }], removals: [], order: ['Sheet1', 'a[b'] }),
    ).rejects.toThrow(/forbidden character/)
    await expect(
      applySheetEdits(bytes, { renames: [], additions: [{ name: 'Sheet1' }], removals: [], order: ['Sheet1'] }),
    ).rejects.toThrow(/已存在名为/)
  })

  it('renames a sheet and rewrites qualified references in formulas and defined names', async () => {
    const bytes = await buildTwoSheetWorkbook()
    const renamed = await applySheetEdits(bytes, {
      renames: [{ sheetName: 'Sheet1', newName: 'Total' }],
      additions: [],
      removals: [],
      order: ['Total', 'Data'],
    })
    const model = await readWorkbook(renamed)
    expect(model.sheets.map((sheet) => sheet.name)).toEqual(['Total', 'Data'])
    // the other sheet's qualified formula followed the rename
    expect(model.sheets[1]?.cells.A1?.formula).toBe('=Total!A1*2')
  })

  it('refuses to delete a sheet that formulas still reference', async () => {
    const bytes = await buildTwoSheetWorkbook()
    await expect(
      applySheetEdits(bytes, { renames: [], additions: [], removals: ['Sheet1'], order: ['Data'] }),
    ).rejects.toThrow(/已拒绝删除/)
  })

  it('deletes an unreferenced sheet cleanly', async () => {
    const bytes = await buildTwoSheetWorkbook()
    const withoutFormula = await applyCellEdits(bytes, [
      { sheetName: 'Data', row: 0, column: 0, writeValue: true, cell: { value: 5 } },
    ])
    const edited = await applySheetEdits(withoutFormula, {
      renames: [],
      additions: [],
      removals: ['Data'],
      order: ['Sheet1'],
    })
    const model = await readWorkbook(edited)
    expect(model.sheets.map((sheet) => sheet.name)).toEqual(['Sheet1'])
  })
})

describe('structural row/column ops', () => {
  it('inserting a row shifts values, formulas, and the dimension down', async () => {
    const bytes = await buildTwoSheetWorkbook()
    const edited = await applyRowColumnOps(bytes, 'Sheet1', [
      { kind: 'insert-rows', index: 1, count: 1 },
    ])
    const model = await readWorkbook(edited)
    const cells = model.sheets[0]!.cells
    expect(cells.A1?.value).toBe(10)
    expect(cells.A2).toBeUndefined() // the new blank row
    expect(cells.A3?.value).toBe(20)
    expect(cells.A4?.value).toBe(30)
    expect(cells.B1?.formula).toBe('=SUM(A1:A4)')
    expect(model.sheets[0]?.dimension).toBe('A1')
  })

  it('deleting a row shrinks ranges and drops deleted cells', async () => {
    const bytes = await buildTwoSheetWorkbook()
    const edited = await applyRowColumnOps(bytes, 'Sheet1', [
      { kind: 'remove-rows', index: 1, count: 1 },
    ])
    const model = await readWorkbook(edited)
    const cells = model.sheets[0]!.cells
    expect(cells.A1?.value).toBe(10)
    expect(cells.A2?.value).toBe(30) // the old A3 moved up
    expect(cells.A3).toBeUndefined()
    expect(cells.B1?.formula).toBe('=SUM(A1:A2)')
  })

  it('inserting a column shifts cells and column references right', async () => {
    const bytes = await buildTwoSheetWorkbook()
    const edited = await applyRowColumnOps(bytes, 'Sheet1', [
      { kind: 'insert-cols', index: 1, count: 1 },
    ])
    const model = await readWorkbook(edited)
    const cells = model.sheets[0]!.cells
    expect(cells.A1?.value).toBe(10)
    expect(cells.B1).toBeUndefined() // the inserted blank column
    expect(cells.C1?.formula).toBe('=SUM(A1:A3)')
  })

  it('references into a deleted region become #REF!', async () => {
    const bytes = await buildTwoSheetWorkbook()
    // a survivor formula below the deleted rows must keep running after its range dies
    const withObserver = await applyCellEdits(bytes, [
      {
        sheetName: 'Sheet1',
        row: 3,
        column: 0,
        writeValue: true,
        cell: { value: null, formula: '=SUM(A1:A3)' },
      },
    ])
    const edited = await applyRowColumnOps(withObserver, 'Sheet1', [
      { kind: 'remove-rows', index: 0, count: 3 },
    ])
    const model = await readWorkbook(edited)
    expect(model.sheets[0]?.cells.A1?.formula).toBe('=SUM(#REF!)')
  })

  it("shifts other sheets' qualified formulas", async () => {
    const bytes = await buildTwoSheetWorkbook()
    const edited = await applyRowColumnOps(bytes, 'Sheet1', [
      { kind: 'insert-rows', index: 0, count: 1 },
    ])
    const model = await readWorkbook(edited)
    expect(model.sheets[1]?.cells.A1?.formula).toBe('=Sheet1!A2*2')
  })

  it('unqualified refs on other sheets stay untouched', async () => {
    const bytes = await buildTwoSheetWorkbook()
    const edited = await applyCellEdits(bytes, [
      {
        sheetName: 'Data',
        row: 1,
        column: 0,
        writeValue: true,
        cell: { value: null, formula: '=SUM(A1:A3)' },
      },
    ])
    const shifted = await applyRowColumnOps(edited, 'Sheet1', [
      { kind: 'insert-rows', index: 0, count: 1 },
    ])
    const model = await readWorkbook(shifted)
    expect(model.sheets[1]?.cells.A2?.formula).toBe('=SUM(A1:A3)')
  })

  it('refuses to shift around pivot parts, but shifts OLE object anchors', async () => {
    const bytes = await buildTwoSheetWorkbook()
    // pivotTable on the worksheet → fail closed
    const withPivot = await (async () => {
      const xml = await sheetXmlOf(bytes)
      const patched = xml.replace('<sheetData', '<pivotSelection pivot="A1"/><sheetData')
      const { assemblePackage } = await import('../src/zip')
      const mutation = await assemblePackage(bytes, {
        replaced: new Map([['xl/worksheets/sheet1.xml', patched]]),
        added: new Map(),
        addedBinary: new Map(),
        removedEntries: [],
        addedEntries: [],
        touchedEntries: ['xl/worksheets/sheet1.xml'],
      })
      return mutation.buffer
    })()
    await expect(
      applyRowColumnOps(withPivot, 'Sheet1', [{ kind: 'insert-rows', index: 0, count: 1 }]),
    ).rejects.toThrow(/cannot shift around/)

    // OLE objects: the worksheet-local anchor block shifts with the op now
    const withOle = await (async () => {
      const xml = await sheetXmlOf(bytes)
      const ole =
        '<oleObjects><oleObject progId="X" shapeId="1">' +
        '<objectPr><anchor><from><xdr:col>0</xdr:col><xdr:row>2</xdr:row></from><to><xdr:col>1</xdr:col><xdr:row>4</xdr:row></to></anchor></objectPr>' +
        '</oleObject></oleObjects>'
      const patched = xml.replace('<sheetData', `${ole}<sheetData`)
      const { assemblePackage } = await import('../src/zip')
      const mutation = await assemblePackage(bytes, {
        replaced: new Map([['xl/worksheets/sheet1.xml', patched]]),
        added: new Map(),
        addedBinary: new Map(),
        removedEntries: [],
        addedEntries: [],
        touchedEntries: ['xl/worksheets/sheet1.xml'],
      })
      return mutation.buffer
    })()
    const edited = await applyRowColumnOps(withOle, 'Sheet1', [
      { kind: 'insert-rows', index: 1, count: 2 },
    ])
    const xml = await sheetXmlOf(edited)
    expect(xml).toContain('<xdr:row>4</xdr:row>')
    expect(xml).toContain('<xdr:row>6</xdr:row>')
  })

  it('shifts autoFilter / dataValidation / conditionalFormatting ranges', async () => {
    const bytes = await buildTwoSheetWorkbook()
    const withFeatures = await (async () => {
      const xml = await sheetXmlOf(bytes)
      const patched = xml.replace(
        '<sheetData',
        '<autoFilter ref="A1:B3"/><dataValidations count="1"><dataValidation sqref="A2:B4" allowBlank="1"/></dataValidations><conditionalFormatting sqref="B1:B3"><cfRule type="cellIs"/></conditionalFormatting><sheetData',
      )
      const { assemblePackage } = await import('../src/zip')
      const mutation = await assemblePackage(bytes, {
        replaced: new Map([['xl/worksheets/sheet1.xml', patched]]),
        added: new Map(),
        addedBinary: new Map(),
        removedEntries: [],
        addedEntries: [],
        touchedEntries: ['xl/worksheets/sheet1.xml'],
      })
      return mutation.buffer
    })()
    const edited = await applyRowColumnOps(withFeatures, 'Sheet1', [
      { kind: 'insert-rows', index: 1, count: 1 },
    ])
    const xml = await sheetXmlOf(edited)
    expect(xml).toContain('<autoFilter ref="A1:B4"/>')
    expect(xml).toContain('sqref="A3:B5"')
    expect(xml).toContain('<conditionalFormatting sqref="B1:B4">')
  })

  it('drops range features whose rows were fully deleted', async () => {
    const bytes = await buildTwoSheetWorkbook()
    const withFeatures = await (async () => {
      const xml = await sheetXmlOf(bytes)
      const patched = xml.replace(
        '<sheetData',
        '<autoFilter ref="A1:B3"/><dataValidations count="1"><dataValidation sqref="A2:B3" allowBlank="1"/></dataValidations><sheetData',
      )
      const { assemblePackage } = await import('../src/zip')
      const mutation = await assemblePackage(bytes, {
        replaced: new Map([['xl/worksheets/sheet1.xml', patched]]),
        added: new Map(),
        addedBinary: new Map(),
        removedEntries: [],
        addedEntries: [],
        touchedEntries: ['xl/worksheets/sheet1.xml'],
      })
      return mutation.buffer
    })()
    const edited = await applyRowColumnOps(withFeatures, 'Sheet1', [
      { kind: 'remove-rows', index: 0, count: 3 },
    ])
    const xml = await sheetXmlOf(edited)
    expect(xml).not.toContain('<autoFilter')
    expect(xml).not.toContain('<dataValidation ')
  })

  it('shifts drawing anchors with the sheet', async () => {
    const bytes = await buildTwoSheetWorkbook()
    const drawingXml =
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
      '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">' +
      '<xdr:twoCellAnchor><xdr:from><xdr:col>0</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>2</xdr:row><xdr:rowOff>5000</xdr:rowOff></xdr:from>' +
      '<xdr:to><xdr:col>1</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>4</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to></xdr:twoCellAnchor>' +
      '</xdr:wsDr>'
    const relsXml =
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing1.xml"/>' +
      '</Relationships>'
    const withDrawing = await (async () => {
      const xml = await sheetXmlOf(bytes)
      const patched = xml.replace('<sheetData', '<drawing r:id="rId1"/><sheetData')
      const { assemblePackage } = await import('../src/zip')
      const mutation = await assemblePackage(bytes, {
        replaced: new Map([
          ['xl/worksheets/sheet1.xml', patched],
          ['xl/worksheets/_rels/sheet1.xml.rels', relsXml],
        ]),
        added: new Map([['xl/drawings/drawing1.xml', drawingXml]]),
        addedBinary: new Map(),
        removedEntries: [],
        addedEntries: ['xl/drawings/drawing1.xml'],
        touchedEntries: [
          'xl/worksheets/sheet1.xml',
          'xl/worksheets/_rels/sheet1.xml.rels',
          'xl/drawings/drawing1.xml',
        ],
      })
      return mutation.buffer
    })()
    const edited = await applyRowColumnOps(withDrawing, 'Sheet1', [
      { kind: 'insert-rows', index: 1, count: 2 },
    ])
    const shifted = await sheetXmlOf(edited, 'xl/drawings/drawing1.xml')
    // anchor from row 2 → 4, to row 4 → 6; cols untouched
    expect(shifted).toContain('<xdr:row>4</xdr:row><xdr:rowOff>5000</xdr:rowOff>')
    expect(shifted).toContain('<xdr:col>1</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>6</xdr:row>')
    // the worksheet's own drawing element survives untouched
    expect(await sheetXmlOf(edited)).toContain('<drawing r:id="rId1"/>')
  })

  it('keeps untouched package entries byte-identical', async () => {
    const bytes = await buildTwoSheetWorkbook()
    const { inventoryXlsx } = await import('../src/zip')
    const before = await inventoryXlsx(bytes)
    const edited = await applyRowColumnOps(bytes, 'Sheet1', [
      { kind: 'insert-rows', index: 1, count: 1 },
    ])
    const after = await inventoryXlsx(edited)
    const afterByPath = new Map(after.map((entry) => [entry.path, entry.sha256]))
    for (const entry of before) {
      if (entry.path === 'xl/worksheets/sheet1.xml' || entry.path === 'xl/workbook.xml') continue
      expect(afterByPath.get(entry.path)).toBe(entry.sha256)
    }
  })
})

describe('chart series references shift with structural ops', () => {
  async function workbookWithChart(): Promise<Uint8Array> {
    // seed the very rows the chart references — structural ops need real
    // sheetData content, and the realistic scenario is data + chart over it
    const seeded = await applyCellEdits(await createBlankWorkbook(), [
      { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: '一' } },
      { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: 1 } },
      { sheetName: 'Sheet1', row: 2, column: 0, writeValue: true, cell: { value: '二' } },
      { sheetName: 'Sheet1', row: 2, column: 1, writeValue: true, cell: { value: 2 } },
      { sheetName: 'Sheet1', row: 3, column: 0, writeValue: true, cell: { value: '三' } },
      { sheetName: 'Sheet1', row: 3, column: 1, writeValue: true, cell: { value: 3 } },
    ])
    return applyChartAdditions(seeded, [
      {
        worksheetSheetName: 'Sheet1',
        anchor: {
          fromRow: 0, fromColumn: 4, fromRowOffset: 0, fromColumnOffset: 0,
          toRow: 8, toColumn: 10, toRowOffset: 0, toColumnOffset: 0,
        },
        chart: {
          chartType: 'column',
          title: 'T',
          series: [
            {
              name: 'S',
              categories: ['一', '二', '三'],
              values: [1, 2, 3],
              valuesRef: 'Sheet1!$B$2:$B$4',
              categoriesRef: 'Sheet1!$A$2:$A$4',
            },
          ],
        },
      },
    ])
  }

  it('shrinks the series reference when rows inside the range are deleted', async () => {
    const edited = await applyRowColumnOps(await workbookWithChart(), 'Sheet1', [
      { kind: 'remove-rows', index: 2, count: 1 }, // delete sheet row 3 (0-based 2)
    ])
    const chartXml = await partTextOf(edited, 'xl/charts/chart1.xml')
    expect(chartXml).toContain('Sheet1!$B$2:$B$3')
    expect(chartXml).toContain('Sheet1!$A$2:$A$3')
    expect(chartXml).not.toContain('$B$2:$B$4')
  })

  it('moves the reference below an insertion and collapses fully-deleted ranges to #REF!', async () => {
    const inserted = await applyRowColumnOps(await workbookWithChart(), 'Sheet1', [
      { kind: 'insert-rows', index: 0, count: 2 },
    ])
    const insertedXml = await partTextOf(inserted, 'xl/charts/chart1.xml')
    expect(insertedXml).toContain('Sheet1!$B$4:$B$6')

    const deleted = await applyRowColumnOps(await workbookWithChart(), 'Sheet1', [
      { kind: 'remove-rows', index: 1, count: 3 }, // rows 2-4 gone: the whole range
    ])
    const deletedXml = await partTextOf(deleted, 'xl/charts/chart1.xml')
    expect(deletedXml).toContain('Sheet1!#REF!')
  })

  it('leaves references into other sheets untouched', async () => {
    const seeded = await applyCellEdits(await createBlankWorkbook(), [
      { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: '表头' } },
    ])
    const two = await applySheetEdits(seeded, {
      renames: [],
      additions: [{ name: 'Data' }],
      removals: [],
      order: ['Sheet1', 'Data'],
    })
    const withChart = await applyChartAdditions(two, [
      {
        worksheetSheetName: 'Sheet1',
        anchor: {
          fromRow: 0, fromColumn: 4, fromRowOffset: 0, fromColumnOffset: 0,
          toRow: 8, toColumn: 10, toRowOffset: 0, toColumnOffset: 0,
        },
        chart: {
          chartType: 'column',
          title: 'T',
          series: [
            {
              name: 'S',
              categories: ['一', '二'],
              values: [1, 2],
              valuesRef: 'Data!$B$2:$B$3',
            },
          ],
        },
      },
    ])
    const edited = await applyRowColumnOps(withChart, 'Sheet1', [
      { kind: 'remove-rows', index: 2, count: 1 },
    ])
    const chartXml = await partTextOf(edited, 'xl/charts/chart1.xml')
    expect(chartXml).toContain('Data!$B$2:$B$3')
  })
})
