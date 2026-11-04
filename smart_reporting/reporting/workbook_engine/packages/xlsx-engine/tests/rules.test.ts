import { describe, expect, it } from 'vitest'

import { createBlankWorkbook, applyCellEdits, readWorkbook } from '../src'
import { applyCfRules, applyDvRules } from '../src/rules'
import { createBufferEntrySource } from '../src/zip'

async function partOf(bytes: Uint8Array, path: string): Promise<string> {
  const source = await createBufferEntrySource(bytes)
  return source.readText(path)
}

describe('data validation rules', () => {
  it('creates the dataValidations section and writes a list rule', async () => {
    const bytes = await createBlankWorkbook()
    const edited = await applyDvRules(bytes, [
      {
        sheet: 'Sheet1',
        sqref: 'B2:B10',
        type: 'list',
        formula1: '"是,否"',
        promptTitle: '选择',
        prompt: '请从下拉列表选择',
      },
    ])
    const xml = await partOf(edited, 'xl/worksheets/sheet1.xml')
    expect(xml).toContain('<dataValidations count="1">')
    expect(xml).toContain('sqref="B2:B10" type="list"')
    expect(xml).toContain('<formula1>"是,否"</formula1>')
    expect(xml).toContain('showInputMessage="1"')
  })

  it('appends to an existing section and bumps the count', async () => {
    const bytes = await createBlankWorkbook()
    const once = await applyDvRules(bytes, [
      { sheet: 'Sheet1', sqref: 'A1:A5', type: 'whole', operator: 'between', formula1: '1', formula2: '100' },
    ])
    const twice = await applyDvRules(once, [
      { sheet: 'Sheet1', sqref: 'C1:C5', type: 'decimal', operator: 'greaterThan', formula1: '0.5' },
    ])
    const xml = await partOf(twice, 'xl/worksheets/sheet1.xml')
    expect(xml).toContain('count="2"')
    expect(xml).toContain('sqref="A1:A5" type="whole" operator="between"')
    expect(xml).toContain('sqref="C1:C5" type="decimal" operator="greaterThan"')
  })

  it('rejects malformed sqref and unknown sheets', async () => {
    const bytes = await createBlankWorkbook()
    await expect(
      applyDvRules(bytes, [{ sheet: 'Sheet1', sqref: 'A1:', type: 'whole' }]),
    ).rejects.toThrow(/非法区域/)
    await expect(
      applyDvRules(bytes, [{ sheet: 'Nope', sqref: 'A1', type: 'whole' }]),
    ).rejects.toThrow(/不存在/)
  })
})

describe('conditional format rules', () => {
  it('writes a cellIs rule with an interned highlight dxf', async () => {
    const bytes = await createBlankWorkbook()
    const seeded = await applyCellEdits(bytes, [
      { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'v' } },
    ])
    const edited = await applyCfRules(seeded, [
      {
        sheet: 'Sheet1',
        sqref: 'A1:A10',
        operator: 'greaterThan',
        formula1: '100',
        fillColor: '#FFC7CE',
        fontColor: '#9C0006',
      },
    ])
    const xml = await partOf(edited, 'xl/worksheets/sheet1.xml')
    expect(xml).toContain('<conditionalFormatting sqref="A1:A10">')
    expect(xml).toContain('type="cellIs" dxfId="0" priority="1" operator="greaterThan"')
    expect(xml).toContain('<formula>100</formula>')
    const styles = await partOf(edited, 'xl/styles.xml')
    expect(styles).toContain('<dxfs count="1">')
    expect(styles).toContain('FFFFC7CE')
    expect(styles).toContain('FF9C0006')
  })

  it('accepts formulas and dedupes identical dxfs', async () => {
    const bytes = await createBlankWorkbook()
    const edited = await applyCfRules(bytes, [
      {
        sheet: 'Sheet1',
        sqref: 'B1:B9',
        operator: 'lessThan',
        formula1: '=B10',
        fillColor: '#EEEEEE',
      },
      {
        sheet: 'Sheet1',
        sqref: 'C1:C9',
        operator: 'greaterThanOrEqual',
        formula1: '=C10',
        fillColor: '#EEEEEE',
      },
    ])
    const xml = await partOf(edited, 'xl/worksheets/sheet1.xml')
    expect(xml).toContain('<formula>B10</formula>')
    expect(xml).toContain('<formula>C10</formula>')
    const styles = await partOf(edited, 'xl/styles.xml')
    expect(styles).toContain('<dxfs count="1">') // same highlight → one dxf
    expect((xml.match(/dxfId="0"/g) ?? []).length).toBe(2)
  })

  it('survives a reopen through the importer (readable workbook)', async () => {
    const bytes = await createBlankWorkbook()
    const edited = await applyCfRules(bytes, [
      { sheet: 'Sheet1', sqref: 'A1:A5', operator: 'equal', formula1: '42', fillColor: '#FF0000' },
    ])
    const model = await readWorkbook(edited)
    expect(model.sheets[0]?.name).toBe('Sheet1')
  })
})
