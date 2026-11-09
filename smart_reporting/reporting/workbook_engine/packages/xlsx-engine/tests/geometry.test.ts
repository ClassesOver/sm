import { describe, expect, it } from 'vitest'
import JSZip from 'jszip'

import { createBlankWorkbook } from '../src/blank'
import { applyCellEdits } from '../src/workbook-write'
import { applyColumnWidths, applyRowHeights } from '../src/geometry'
import { createBufferEntrySource, inventoryXlsx } from '../src/zip'

const SHEET = 'xl/worksheets/sheet1.xml'

const sheetXmlOf = async (bytes: Uint8Array): Promise<string> =>
  (await createBufferEntrySource(bytes)).readText(SHEET)

async function patchSheet(bytes: Uint8Array, xml: string): Promise<Uint8Array> {
  const zip = await JSZip.loadAsync(bytes)
  zip.file(SHEET, xml)
  return zip.generateAsync({ type: 'uint8array' })
}

describe('geometry writers（列宽/行高落盘）', () => {
  it('sets explicit column widths and reads them back through the model', async () => {
    const saved = await applyColumnWidths(await createBlankWorkbook(), 'Sheet1', [
      { index: 1, widthChars: 18.5 },
      { index: 3, widthChars: 30 },
    ])
    const xml = await sheetXmlOf(saved)
    expect(xml).toContain('<col min="2" max="2" width="18.5000" customWidth="1"/>')
    expect(xml).toContain('<col min="4" max="4" width="30.0000" customWidth="1"/>')
    // only the worksheet part changed
    const before = await inventoryXlsx(await createBlankWorkbook())
    const after = await inventoryXlsx(saved)
    const changed = after.filter(
      (entry, index) => before[index]?.path === entry.path && before[index]?.sha256 !== entry.sha256,
    )
    expect(changed.map((entry) => entry.path)).toEqual([SHEET])
  })

  it('splits an existing spanning <col> range around the requested column', async () => {
    const base = await patchSheet(
      await createBlankWorkbook(),
      (await sheetXmlOf(await createBlankWorkbook())).replace(
        '<sheetData/>',
        '<cols><col min="1" max="5" width="9" customWidth="1"/></cols><sheetData/>',
      ),
    )
    const saved = await applyColumnWidths(base, 'Sheet1', [{ index: 2, widthChars: 20 }])
    const xml = await sheetXmlOf(saved)
    // 1-5 splits into 1-2 and 4-5 keeping their attrs, plus the 20-wide single
    expect(xml).toContain('<col min="1" max="2" width="9" customWidth="1"/>')
    expect(xml).toContain('<col min="3" max="3" width="20.0000" customWidth="1"/>')
    expect(xml).toContain('<col min="4" max="5" width="9" customWidth="1"/>')
  })

  it('updates an existing row height in place and creates missing rows in order', async () => {
    const seeded = await applyCellEdits(await createBlankWorkbook(), [
      { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'b' } },
      { sheetName: 'Sheet1', row: 4, column: 0, writeValue: true, cell: { value: 'e' } },
    ])
    const saved = await applyRowHeights(seeded, 'Sheet1', [
      { index: 1, heightPoints: 30 }, // existing row
      { index: 2, heightPoints: 24 }, // missing row between them
      { index: 9, heightPoints: 40 }, // missing row after the last
    ])
    const xml = await sheetXmlOf(saved)
    const row2Open = xml.match(/<row\b[^>]*\br="2"[^>]*>/)?.[0] ?? ''
    expect(row2Open).toContain('ht="30.0000"')
    expect(row2Open).toContain('customHeight="1"')
    // the row's cell content survived the attribute rewrite
    expect(xml).toMatch(new RegExp(`${row2Open.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}<c r="A2"`))
    // created row 3 (0-based 2) sits between rows 2 and 5 in document order
    const rowOrder = [...xml.matchAll(/<row\b[^>]*\br="([0-9]+)"/g)].map((m) => Number(m[1]))
    expect(rowOrder).toEqual([2, 3, 5, 10])
    expect(xml).toContain('<row r="3" ht="24.0000" customHeight="1"/>')
    expect(xml).toContain('<row r="10" ht="40.0000" customHeight="1"/>')
  })

  it('expands a self-closing sheetData for row heights on an empty sheet', async () => {
    const saved = await applyRowHeights(await createBlankWorkbook(), 'Sheet1', [
      { index: 0, heightPoints: 22 },
    ])
    const xml = await sheetXmlOf(saved)
    expect(xml).toContain('<row r="1" ht="22.0000" customHeight="1"/>')
    expect(xml).toContain('<sheetData>')
  })

  it('round-trips through the model reader (width chars + height points)', async () => {
    const { readWorkbook } = await import('../src/workbook-read')
    const withCells = await applyCellEdits(await createBlankWorkbook(), [
      { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'x' } },
    ])
    const saved = await applyColumnWidths(
      await applyRowHeights(withCells, 'Sheet1', [{ index: 0, heightPoints: 28.5 }]),
      'Sheet1',
      [{ index: 0, widthChars: 22.25 }],
    )
    const model = await readWorkbook(saved)
    const sheet = model.sheets[0]!
    expect(sheet.columns.find((column) => column.start === 1)?.width).toBeCloseTo(22.25, 3)
    expect(sheet.rows.find((row) => row.row === 1)?.height).toBeCloseTo(28.5, 3)
  })

  it('rejects out-of-range values instead of writing them', async () => {
    const bytes = await createBlankWorkbook()
    await expect(
      applyColumnWidths(bytes, 'Sheet1', [{ index: 0, widthChars: 999 }]),
    ).rejects.toThrow('0–255')
    await expect(
      applyRowHeights(bytes, 'Sheet1', [{ index: 0, heightPoints: 0 }]),
    ).rejects.toThrow('0–409')
  })
})

describe('row height reset to automatic', () => {
  it('drops ht/customHeight on an existing row and keeps its cells and other attributes', async () => {
    let bytes = await applyCellEdits(await createBlankWorkbook(), [
      { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: 'keep' } },
    ])
    bytes = await applyRowHeights(bytes, 'Sheet1', [{ index: 1, heightPoints: 45 }, { index: 3, heightPoints: 20 }])
    const sized = await (await JSZip.loadAsync(bytes)).file('xl/worksheets/sheet1.xml')!.async('string')
    expect(sized.match(/<row\b[^>]*\br="2"[^>]*>/)![0]).toContain('customHeight="1"')
    bytes = await applyRowHeights(bytes, 'Sheet1', [{ index: 1, heightPoints: null }, { index: 7, heightPoints: null }])
    const xml = await (await JSZip.loadAsync(bytes)).file('xl/worksheets/sheet1.xml')!.async('string')
    const row2 = xml.match(/<row\b[^>]*\br="2"[^>]*>[\s\S]*?<\/row>/)![0]
    expect(row2).not.toMatch(/\bht=|customHeight=/)
    expect(row2).toContain('keep')
    expect(xml.match(/<row\b[^>]*\br="4"[^>]*>/)![0]).toContain('ht="20')
    expect(xml).not.toMatch(/r="8"/)
    await expect(applyRowHeights(bytes, 'Sheet1', [{ index: 1, heightPoints: 0 }])).rejects.toThrow('行高')
  })
})
