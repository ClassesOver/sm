import { describe, expect, it } from 'vitest'

import { applyCellEdits, applyCellShift, applySheetNotes, applySheetEdits, createBlankWorkbook, readWorkbook, StructuralShiftError } from '../src'
import { applyDefinedNames, readDefinedNames } from '../src/defined-names'
import { assemblePackage, createBufferEntrySource } from '../src/zip'

const partOf = async (bytes: Uint8Array, path: string) => (await createBufferEntrySource(bytes)).readText(path)

async function replacePart(bytes: Uint8Array, path: string, edit: (xml: string) => string): Promise<Uint8Array> {
  const xml = edit(await partOf(bytes, path))
  return (await assemblePackage(bytes, { replaced: new Map([[path, xml]]), added: new Map(), addedBinary: new Map(), removedEntries: [], addedEntries: [], touchedEntries: [path] })).buffer
}

/// Sheet1: A1:C3 grid of values (A1=a1 …), D1 =SUM(B1:C1), D2 =B2, D3 =SUM(B1:B3);
/// Data!A1 =Sheet1!B2.
async function grid(): Promise<Uint8Array> {
  const withData = await applySheetEdits(await createBlankWorkbook(), { renames: [], additions: [{ name: 'Data' }], removals: [], order: ['Sheet1', 'Data'] })
  const edits = []
  for (let row = 0; row < 3; row++) for (let column = 0; column < 3; column++) {
    edits.push({ sheetName: 'Sheet1', row, column, writeValue: true, cell: { value: `${'ABC'[column]}${row + 1}`.toLowerCase() } })
  }
  edits.push(
    { sheetName: 'Sheet1', row: 0, column: 3, writeValue: true, cell: { value: null, formula: '=SUM(B1:C1)' } },
    { sheetName: 'Sheet1', row: 1, column: 3, writeValue: true, cell: { value: null, formula: '=B2' } },
    { sheetName: 'Sheet1', row: 2, column: 3, writeValue: true, cell: { value: null, formula: '=SUM(B1:B3)' } },
    { sheetName: 'Data', row: 0, column: 0, writeValue: true, cell: { value: null, formula: '=Sheet1!B2' } },
  )
  return applyCellEdits(withData, edits)
}

const values = async (bytes: Uint8Array, sheet = 'Sheet1') => {
  const model = (await readWorkbook(bytes)).sheets.find(entry => entry.name === sheet)!
  return Object.fromEntries(Object.entries(model.cells).map(([address, cell]) => [address, cell.formula ?? cell.value]))
}

describe('Insert/Delete Cells with shift', () => {
  it('inserts cells shifting right only inside the band and rewrites in-band references', async () => {
    const shifted = await applyCellShift(await grid(), 'Sheet1', { range: 'B2', shift: 'right' })
    const cells = await values(shifted)
    expect([cells.A2, cells.B2, cells.C2, cells.D2]).toEqual(['a2', undefined, 'b2', 'c2'])
    expect([cells.B1, cells.B3]).toEqual(['b1', 'b3'])
    // D2's formula moved to E2 and follows its target; out-of-band ranges stay
    expect(cells.E2).toBe('=C2')
    expect([cells.D1, cells.D3]).toEqual(['=SUM(B1:C1)', '=SUM(B1:B3)'])
    expect((await values(shifted, 'Data')).A1).toBe('=Sheet1!C2')
  })

  it('deletes cells shifting up, turning deleted targets into #REF! and shrinking in-band ranges', async () => {
    const bytes = await applyCellEdits(await grid(), [
      { sheetName: 'Sheet1', row: 4, column: 1, writeValue: true, cell: { value: null, formula: '=SUM(B1:B3)' } },
      { sheetName: 'Sheet1', row: 5, column: 0, writeValue: true, cell: { value: null, formula: '=B1' } },
    ])
    const shifted = await applyCellShift(bytes, 'Sheet1', { range: 'B1', shift: 'up' })
    const cells = await values(shifted)
    expect([cells.B1, cells.B2, cells.B3]).toEqual(['b2', 'b3', undefined])
    expect(cells.B4).toBe('=SUM(B1:B2)')
    expect(cells.A6).toBe('=#REF!')
    expect([cells.A1, cells.C1]).toEqual(['a1', 'c1'])
  })

  it('moves notes and defined names that lie in the band, leaving others', async () => {
    let bytes = await applySheetNotes(await grid(), 'Sheet1', [
      { row: 1, column: 1, author: 'A', text: 'moves' }, { row: 0, column: 1, author: 'A', text: 'stays' },
    ])
    bytes = await applyDefinedNames(bytes, { sets: [{ name: 'Inside', refersTo: 'Sheet1!$B$2' }, { name: 'Across', refersTo: 'Sheet1!$B$1:$B$3' }] })
    const shifted = await applyCellShift(bytes, 'Sheet1', { range: 'B2:C2', shift: 'right' })
    const notes = (await readWorkbook(shifted)).sheets[0]!.notes!.notes.map(note => [note.text, note.row, note.column])
    expect(notes).toEqual(expect.arrayContaining([['moves', 1, 3], ['stays', 0, 1]]))
    const names = Object.fromEntries(readDefinedNames(await partOf(shifted, 'xl/workbook.xml')).map(entry => [entry.name, entry.refersTo]))
    expect(names).toEqual({ Inside: 'Sheet1!$D$2', Across: 'Sheet1!$B$1:$B$3' })
  })

  it('shifts merges inside the band and refuses merges straddling it', async () => {
    const withMerge = (ref: string) => async (bytes: Uint8Array) =>
      replacePart(bytes, 'xl/worksheets/sheet1.xml', xml => xml.replace('</sheetData>', `</sheetData><mergeCells count="1"><mergeCell ref="${ref}"/></mergeCells>`))
    const inside = await applyCellShift(await withMerge('B2:C2')(await grid()), 'Sheet1', { range: 'A2', shift: 'right' })
    expect((await readWorkbook(inside)).sheets[0]!.merges).toEqual(['C2:D2'])
    await expect(applyCellShift(await withMerge('B1:B2')(await grid()), 'Sheet1', { range: 'A2', shift: 'right' })).rejects.toThrow(/合并单元格跨越/)
    await expect(applyCellShift(await withMerge('B2:C2')(await grid()), 'Sheet1', { range: 'C2', shift: 'right' })).rejects.toThrow(/合并单元格内部/)
    await expect(applyCellShift(await withMerge('B2:C2')(await grid()), 'Sheet1', { range: 'C2', shift: 'left' })).rejects.toThrow(/拆分合并单元格/)
    const removed = await applyCellShift(await withMerge('B2:C2')(await grid()), 'Sheet1', { range: 'B2:C2', shift: 'left' })
    expect((await readWorkbook(removed)).sheets[0]!.merges ?? []).toEqual([])
  })

  it('fails closed on ranged features and shared formulas touching the shifted region', async () => {
    const validated = await replacePart(await grid(), 'xl/worksheets/sheet1.xml', xml =>
      xml.replace('</sheetData>', '</sheetData><dataValidations count="1"><dataValidation type="whole" sqref="C2"><formula1>1</formula1></dataValidation></dataValidations>'))
    await expect(applyCellShift(validated, 'Sheet1', { range: 'B2', shift: 'right' })).rejects.toBeInstanceOf(StructuralShiftError)
    // clear of the region: allowed and untouched
    const clear = await applyCellShift(validated, 'Sheet1', { range: 'B1', shift: 'right' })
    expect(await partOf(clear, 'xl/worksheets/sheet1.xml')).toContain('sqref="C2"')
    const shared = await replacePart(await grid(), 'xl/worksheets/sheet1.xml', xml =>
      xml.replace(/<c r="D1"([^>]*)>[\s\S]*?<\/c>/, '<c r="D1"$1><f t="shared" ref="D1:D2" si="0">B1</f></c>'))
    await expect(applyCellShift(shared, 'Sheet1', { range: 'B1', shift: 'down' })).rejects.toThrow(/共享公式/)
  })

  it('refuses pushing values off the sheet and invalid input', async () => {
    const edge = await applyCellEdits(await createBlankWorkbook(), [{ sheetName: 'Sheet1', row: 0, column: 16383, writeValue: true, cell: { value: 'edge' } }])
    await expect(applyCellShift(edge, 'Sheet1', { range: 'A1', shift: 'right' })).rejects.toThrow(/边界/)
    await expect(applyCellShift(edge, 'Sheet1', { range: 'Data!A1', shift: 'right' })).rejects.toThrow(/范围无效/)
    await expect(applyCellShift(edge, 'Sheet1', { range: 'A1', shift: 'sideways' as never })).rejects.toThrow(/方向无效/)
  })
})
