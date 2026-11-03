import { describe, expect, it } from 'vitest'

import { createBlankWorkbook, applyCellEdits, readWorkbook } from '../src'
import { csvToWorkbook, parseCsv, typedCsvValue, workbookToCsv } from '../src/csv'

describe('parseCsv', () => {
  it('parses RFC4180 quoting, embedded newlines, and CRLF', () => {
    expect(parseCsv('a,b,c', ',')).toEqual([['a', 'b', 'c']])
    expect(parseCsv('a,"b,x",c', ',')).toEqual([['a', 'b,x', 'c']])
    expect(parseCsv('"say ""hi""",2', ',')).toEqual([['say "hi"', '2']])
    expect(parseCsv('a,b\r\nc,d', ',')).toEqual([
      ['a', 'b'],
      ['c', 'd'],
    ])
    expect(parseCsv('"multi\nline",1', ',')).toEqual([['multi\nline', '1']])
  })

  it('drops one trailing empty line but keeps intentional blanks', () => {
    expect(parseCsv('a,b\n', ',')).toEqual([['a', 'b']])
    expect(parseCsv('a,\n,2', ',')).toEqual([
      ['a', ''],
      ['', '2'],
    ])
  })
})

describe('typedCsvValue', () => {
  it('types numbers, booleans, and leaves text alone', () => {
    expect(typedCsvValue('42')).toBe(42)
    expect(typedCsvValue('-3.5')).toBe(-3.5)
  })

  it('keeps leading-zero digit strings as text', () => {
    // identifiers like account codes would lose digits on conversion
    expect(typedCsvValue('00123')).toBe('00123')
    expect(typedCsvValue('-007')).toBe('-007')
    expect(typedCsvValue('00')).toBe('00')
    // ordinary numbers still convert
    expect(typedCsvValue('0.5')).toBe(0.5)
    expect(typedCsvValue('0')).toBe(0)
  })
})

describe('csv round-trip', () => {
  it('imports typed values into a workbook', async () => {
    const bytes = await csvToWorkbook('名称,数量,启用\r\nWidget,12.5,TRUE\r\nGadget,3,FALSE')
    const model = await readWorkbook(bytes)
    const cells = model.sheets[0]!.cells
    expect(cells.A1?.value).toBe('名称')
    expect(cells.B2?.value).toBe(12.5)
    expect(cells.C2?.value).toBe(true)
    expect(cells.C3?.value).toBe(false)
    expect(cells.A3?.value).toBe('Gadget')
  })

  it('sniffs semicolon and tab delimiters', async () => {
    const semis = await csvToWorkbook('a;b\n1;2')
    expect((await readWorkbook(semis)).sheets[0]?.cells.A2?.value).toBe(1)
    const tabs = await csvToWorkbook('a\tb\n1\t2')
    expect((await readWorkbook(tabs)).sheets[0]?.cells.B2?.value).toBe(2)
  })

  it('exports a sheet back to CSV with quoting', async () => {
    const bytes = await createBlankWorkbook()
    const seeded = await applyCellEdits(bytes, [
      { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'a,"b"' } },
      { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 7 } },
      { sheetName: 'Sheet1', row: 1, column: 0, writeValue: true, cell: { value: null, formula: '=B1*2' } },
    ])
    const csv = await workbookToCsv(seeded, 'Sheet1')
    expect(csv).toBe('"a,""b""",7\r\n=B1*2,')
  })

  it('reimports its own export losslessly for plain data', async () => {
    const original = await csvToWorkbook('x,y\r\n1,hello\r\n2,world')
    const exported = await workbookToCsv(original, 'Sheet1')
    const reimported = await csvToWorkbook(exported)
    const first = (await readWorkbook(original)).sheets[0]!.cells
    const second = (await readWorkbook(reimported)).sheets[0]!.cells
    expect(second.A1?.value).toBe(first.A1?.value)
    expect(second.B2?.value).toBe(first.B2?.value)
    expect(second.A3?.value).toBe(first.A3?.value)
  })

  it('exports booleans as TRUE/FALSE so they reimport as booleans', async () => {
    const bytes = await createBlankWorkbook()
    const seeded = await applyCellEdits(bytes, [
      { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: true } },
      { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: false } },
    ])
    const csv = await workbookToCsv(seeded, 'Sheet1')
    expect(csv).toBe('TRUE,FALSE')
    const reimported = await readWorkbook(await csvToWorkbook(csv))
    expect(reimported.sheets[0]?.cells.A1?.value).toBe(true)
    expect(reimported.sheets[0]?.cells.B1?.value).toBe(false)
  })
})
