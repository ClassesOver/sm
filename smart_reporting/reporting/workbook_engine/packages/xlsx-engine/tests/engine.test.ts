import { describe, expect, it } from 'vitest'

import { createBlankWorkbook } from '../src/blank'
import { applyCellEdits, type CellEdit } from '../src/workbook-write'
import { createBufferEntrySource, inventoryXlsx } from '../src/zip'
import { readWorkbook } from '../src/workbook-read'

async function sheetXmlOf(bytes: Uint8Array, path = 'xl/worksheets/sheet1.xml'): Promise<string> {
  const source = await createBufferEntrySource(bytes)
  return source.readText(path)
}

describe('engine round-trip', () => {
  it('creates a blank workbook the reader understands', async () => {
    const bytes = await createBlankWorkbook('Budget')
    const model = await readWorkbook(bytes)
    expect(model.sheets.map((sheet) => sheet.name)).toEqual(['Budget'])
    expect(model.sheets[0]?.cells).toEqual({})
  })

  it('writes and reads back values, text, booleans, and formulas', async () => {
    const bytes = await createBlankWorkbook()
    const saved = await applyCellEdits(bytes, [
      { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 42 } },
      { sheetName: 'Sheet1', row: 1, column: 1, writeValue: true, cell: { value: 'hello world' } },
      { sheetName: 'Sheet1', row: 2, column: 2, writeValue: true, cell: { value: true } },
      {
        sheetName: 'Sheet1',
        row: 3,
        column: 0,
        writeValue: true,
        cell: { value: null, formula: '=SUM(A1:A3)' },
      },
      // missing row/column insertion order
      { sheetName: 'Sheet1', row: 20, column: 5, writeValue: true, cell: { value: 'far away' } },
    ])
    const model = await readWorkbook(saved)
    const cells = model.sheets[0]!.cells
    expect(cells.A1?.value).toBe(42)
    expect(cells.B2?.value).toBe('hello world')
    expect(cells.C3?.value).toBe(true)
    expect(cells.A4?.formula).toBe('=SUM(A1:A3)')
    expect(cells.F21?.value).toBe('far away')

    // formulas flip fullCalcOnLoad so Excel recalculates on open
    const workbook = await sheetXmlOf(saved, 'xl/workbook.xml')
    expect(workbook).toContain('fullCalcOnLoad="1"')
  })

  it('escapes XML-hostile text and preserves it through a round trip', async () => {
    const bytes = await createBlankWorkbook()
    const nasty = 'a<b>&"c"\n_x001A_价'
    const saved = await applyCellEdits(bytes, [
      { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: nasty } },
    ])
    const model = await readWorkbook(saved)
    expect(model.sheets[0]?.cells.A1?.value).toBe(nasty)
  })

  it('writes future-function markers so Excel does not repair the call', async () => {
    const bytes = await createBlankWorkbook()
    const saved = await applyCellEdits(bytes, [
      {
        sheetName: 'Sheet1',
        row: 0,
        column: 0,
        writeValue: true,
        cell: { value: null, formula: '=XLOOKUP(1,B:B,C:C)' },
      },
    ])
    const xml = await sheetXmlOf(saved)
    expect(xml).toContain('_xlfn.XLOOKUP')
  })

  it('applies style edits through the copy-on-write stylesheet', async () => {
    const bytes = await createBlankWorkbook()
    const before = await readWorkbook(bytes)
    const saved = await applyCellEdits(bytes, [
      {
        sheetName: 'Sheet1',
        row: 0,
        column: 0,
        writeValue: true,
        cell: { value: 'Total' },
        style: { bold: true, fillColor: '#FF0000' },
      },
      {
        sheetName: 'Sheet1',
        row: 1,
        column: 0,
        writeValue: false,
        cell: { value: null },
        style: { numberFormat: '#,##0.00' },
      },
    ])
    const model = await readWorkbook(saved)
    const styles = model.styles
    const headerIndex = model.sheets[0]?.cells.A1?.styleIndex
    const bodyIndex = model.sheets[0]?.cells.A2?.styleIndex
    expect(headerIndex).toBeDefined()
    expect(bodyIndex).toBeDefined()
    expect(styles.fonts[styles.cellXfs[headerIndex!]!.fontId]?.bold).toBe(true)
    const headerFill = styles.fills[styles.cellXfs[headerIndex!]!.fillId]
    expect(headerFill && 'pattern' in headerFill ? headerFill.pattern : undefined).toBe('solid')
    // '#,##0.00' is builtin numFmtId 4 — no custom numFmt section entry
    expect(styles.cellXfs[bodyIndex!]!.numFmtId).toBe(4)

    const customSaved = await applyCellEdits(bytes, [
      {
        sheetName: 'Sheet1',
        row: 1,
        column: 0,
        writeValue: false,
        cell: { value: null },
        style: { numberFormat: '0.000" kg"' },
      },
    ])
    const customModel = await readWorkbook(customSaved)
    const customIndex = customModel.sheets[0]?.cells.A2?.styleIndex
    const customXf = customModel.styles.cellXfs[customIndex!]!
    expect(customModel.styles.numFmts.get(customXf.numFmtId)).toBe('0.000" kg"')
    // untouched xf 0 survives verbatim (dedupe: the new xfs are appended)
    expect(styles.cellXfs.length).toBeGreaterThan(before.styles.cellXfs.length)
  })

  it('keeps every untouched package entry byte-identical', async () => {
    const bytes = await createBlankWorkbook()
    const beforeEntries = await inventoryXlsx(bytes)
    const saved = await applyCellEdits(bytes, [
      { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 1 } },
      {
        sheetName: 'Sheet1',
        row: 1,
        column: 0,
        writeValue: true,
        cell: { value: null, formula: '=A1*2' },
      },
    ])
    const afterEntries = await inventoryXlsx(saved)
    const touched = new Set([
      'xl/worksheets/sheet1.xml',
      'xl/workbook.xml',
      'xl/styles.xml',
      '[Content_Types].xml',
      'xl/_rels/workbook.xml.rels',
    ])
    const afterByPath = new Map(afterEntries.map((entry) => [entry.path, entry.sha256]))
    for (const entry of beforeEntries) {
      if (touched.has(entry.path)) continue
      expect(afterByPath.get(entry.path)).toBe(entry.sha256)
    }
    expect(afterByPath.size).toBe(beforeEntries.length)
  })

  it('updates an existing cell in place without duplicating it', async () => {
    const bytes = await createBlankWorkbook()
    const once = await applyCellEdits(bytes, [
      { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 1 } },
    ])
    const twice = await applyCellEdits(once, [
      { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 99 } },
      { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 'new' } },
    ])
    const xml = await sheetXmlOf(twice)
    expect(xml.match(/<c r="A1"/g)).toHaveLength(1)
    const model = await readWorkbook(twice)
    expect(model.sheets[0]?.cells.A1?.value).toBe(99)
    expect(model.sheets[0]?.cells.B1?.value).toBe('new')
  })

  it('clears a cell back to empty', async () => {
    const bytes = await createBlankWorkbook()
    const filled = await applyCellEdits(bytes, [
      { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'x' } },
    ])
    const cleared = await applyCellEdits(filled, [
      { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: null } },
    ])
    const model = await readWorkbook(cleared)
    expect(model.sheets[0]?.cells.A1).toBeUndefined()
  })

  it('rejects edits naming an unknown sheet', async () => {
    const bytes = await createBlankWorkbook()
    const edit: CellEdit = { sheetName: 'Nope', row: 0, column: 0, writeValue: true, cell: { value: 1 } }
    await expect(applyCellEdits(bytes, [edit])).rejects.toThrow(/not found/)
  })

  it('rejects non-finite numbers instead of writing invalid OOXML', async () => {
    const bytes = await createBlankWorkbook()
    for (const bad of [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY]) {
      const edit: CellEdit = { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: bad } }
      // NaN/Infinity would serialize as <v>NaN</v> — a corrupt file in Excel
      await expect(applyCellEdits(bytes, [edit])).rejects.toThrow(/有限数值/)
    }
    // finite extremes stay writable (OOXML accepts E-notation)
    const ok = await applyCellEdits(bytes, [
      { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 1e308 } },
      { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 5e-324 } },
    ])
    const model = await readWorkbook(ok)
    expect(model.sheets[0]?.cells.A1?.value).toBe(1e308)
  })
})
