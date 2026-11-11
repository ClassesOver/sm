import { describe, expect, it } from 'vitest'
import { readDataValidations } from '../src/data-validation-read'
import { applyDvRules } from '../src/data-validation'
import { createBlankWorkbook, readWorkbook } from '../src'
import { applyDvRules as appendRules } from '../src/rules'
import { applyStructuralOp, shiftQualifiedFormulas } from '../src/structural'
import { renameSheetReferencesInWorksheet, worksheetReferencesSheet } from '../src/sheets-edit'

describe('data validation file projection', () => {
  it('projects the OOXML default between operator explicitly for Univer', () => {
    const model = readDataValidations('<worksheet><dataValidations><dataValidation type="whole" sqref="A1"><formula1>1</formula1><formula2>10</formula2></dataValidation></dataValidations></worksheet>')
    expect(model.rules[0]?.rule.operator).toBe('between')
  })
  it('renames x14 sources and removes empty validation extensions after deleting their last target', () => {
    const xml = '<worksheet><sheetData></sheetData><extLst><ext uri="{CCE6A557-97BC-4b89-ADB6-D9C93CAAB3DF}"><x14:dataValidations count="1"><x14:dataValidation type="list"><x14:formula1><xm:f>Other!$A$1:$A$3</xm:f></x14:formula1><xm:sqref>C2</xm:sqref></x14:dataValidation></x14:dataValidations></ext></extLst></worksheet>'
    const renamed = readDataValidations(renameSheetReferencesInWorksheet(xml, 'Other', 'Renamed'))
    expect(worksheetReferencesSheet(xml, 'Other')).toBe(true)
    expect(renamed.rules[0]?.rule.formula1).toBe('=Renamed!$A$1:$A$3')
    const deleted = applyStructuralOp(xml, { kind: 'remove-rows', index: 1, count: 1 }, 'Sheet1')
    expect(deleted).not.toContain('<ext')
  })
  it('moves x14 targets and validation formula references during structural edits', () => {
    const xml = '<worksheet><sheetData></sheetData><dataValidations count="1"><dataValidation type="whole" sqref="B2"><formula1>A2</formula1></dataValidation></dataValidations><extLst><ext><x14:dataValidations count="1"><x14:dataValidation type="list"><x14:formula1><xm:f>Other!$A$2:$A$4</xm:f></x14:formula1><xm:sqref>C2:C4</xm:sqref></x14:dataValidation></x14:dataValidations></ext></extLst></worksheet>'
    const moved = applyStructuralOp(xml, { kind: 'insert-rows', index: 1, count: 1 }, 'Sheet1')
    const model = readDataValidations(moved)
    expect(model.readOnlyReason).toBeUndefined()
    expect(model.rules[0]?.rule.formula1).toBe('=A3')
    expect(model.rules[1]?.ranges[0]).toMatchObject({ startRow: 2, endRow: 4 })
    expect(model.rules[1]?.rule.formula1).toBe('=Other!$A$2:$A$4')
    const other = readDataValidations(shiftQualifiedFormulas(xml, { axis: 'row', start: 1, delta: 1 }, 'Other'))
    expect(other.rules[1]?.rule.formula1).toBe('=Other!$A$3:$A$5')
  })
  it.each(['whole', 'decimal', 'date', 'time', 'textLength'])('projects %s reference formulas for Univer while preserving numeric constants', (type) => {
    const xml = `<worksheet><dataValidations><dataValidation type="${type}" operator="between" sqref="B2:B5"><formula1>$A$1</formula1><formula2>1.25E+2</formula2></dataValidation></dataValidations></worksheet>`
    const model = readDataValidations(xml)
    expect(model.readOnlyReason).toBeUndefined()
    expect(model.rules[0]?.rule).toMatchObject({ formula1: '=$A$1', formula2: '1.25E+2' })
    const saved = applyDvRules('<worksheet><sheetData/></worksheet>', model.rules)
    expect(saved).toContain('<formula1>$A$1</formula1>')
    expect(saved).toContain('<formula2>1.25E+2</formula2>')
  })

  it('preserves whitespace in literal list entries', () => {
    const model = readDataValidations('<worksheet><dataValidations><dataValidation type="list" sqref="A1"><formula1>" a , b "</formula1></dataValidation></dataValidations></worksheet>')
    expect(model.rules[0]?.rule.formula1).toBe(' a , b ')
    expect(applyDvRules('<worksheet><sheetData/></worksheet>', model.rules)).toContain('<formula1>" a , b "</formula1>')
  })
  it('exposes file rules through the workbook importer', async () => {
    const bytes = await appendRules(await createBlankWorkbook(), [{ sheet: 'Sheet1', sqref: 'B2:B5', type: 'decimal', operator: 'greaterThan', formula1: '0' }])
    const model = await readWorkbook(bytes)
    expect(model.sheets[0]?.dataValidations?.rules[0]).toMatchObject({
      ranges: [{ startRow: 1, endRow: 4, startColumn: 1, endColumn: 1 }],
      rule: { type: 'decimal', operator: 'greaterThan', formula1: '0' },
    })
  })
  it('reads multiple areas, messages and inverted dropdown without changing formulas', () => {
    const model = readDataValidations('<worksheet><dataValidations count="1"><dataValidation type="list" sqref="$A$1:A3 C4" allowBlank="true" showDropDown="1" showErrorMessage="1" errorStyle="warning" promptTitle="选择&amp;确认" error="重选"><formula1>&quot;是,否&quot;</formula1></dataValidation></dataValidations></worksheet>')
    expect(model.readOnlyReason).toBeUndefined()
    expect(model.rules).toEqual([{ ranges: [
      { startRow: 0, endRow: 2, startColumn: 0, endColumn: 0 },
      { startRow: 3, endRow: 3, startColumn: 2, endColumn: 2 },
    ], rule: { type: 'list', allowBlank: true, showDropDown: false, showInputMessage: false, showErrorMessage: true, errorStyle: 2, promptTitle: '选择&确认', error: '重选', formula1: '是,否' } }])
    const saved = applyDvRules('<worksheet><sheetData/></worksheet>', model.rules)
    expect(saved).toContain('<formula1>"是,否"</formula1>')
    expect(saved).toContain('promptTitle="选择&amp;确认"')
  })

  it('reads x14 cross-sheet sources alongside legacy rules', () => {
    const model = readDataValidations('<worksheet><dataValidations count="1"><dataValidation type="custom" sqref="B2"><formula1>A1&gt;0</formula1></dataValidation></dataValidations><extLst><ext><x14:dataValidations count="1"><x14:dataValidation type="list"><x14:formula1><xm:f>&apos;来源&apos;!$A$1:$A$3</xm:f></x14:formula1><xm:sqref>C2:C9</xm:sqref></x14:dataValidation></x14:dataValidations></ext></extLst></worksheet>')
    expect(model.readOnlyReason).toBeUndefined()
    expect(model.rules).toHaveLength(2)
    expect(model.rules[0]?.rule.formula1).toBe('=A1>0')
    expect(model.rules[1]?.rule.formula1).toBe("='来源'!$A$1:$A$3")
    expect(applyDvRules('<worksheet><sheetData/></worksheet>', model.rules)).toContain("<xm:f>'来源'!$A$1:$A$3</xm:f>")
  })

  it.each([
    '<dataValidations disablePrompts="1"><dataValidation sqref="A1"/></dataValidations>',
    '<dataValidations xWindow="10"><dataValidation sqref="A1"/></dataValidations>',
    '<dataValidations><dataValidation type="list" sqref="A1"><formula1>"=foo,bar"</formula1></dataValidation></dataValidations>',
    '<dataValidations count="2"><dataValidation sqref="A1"/></dataValidations>',
    '<dataValidations><dataValidation type="future" sqref="A1"/></dataValidations>',
    '<dataValidations><dataValidation sqref="XFE1"/></dataValidations>',
    '<dataValidations><dataValidation sqref="A1"><extLst/></dataValidation></dataValidations>',
  ])('marks incompletely modeled sources read-only: %s', (section) => {
    expect(readDataValidations(`<worksheet>${section}</worksheet>`).readOnlyReason).toBeTruthy()
  })

  it('handles whole-column/row rules without expanding cells and an empty sheet', () => {
    expect(readDataValidations('<worksheet><sheetData/></worksheet>')).toEqual({ rules: [] })
    const model = readDataValidations('<worksheet><dataValidations><dataValidation sqref="A:A 2:2"/></dataValidations></worksheet>')
    expect(model.readOnlyReason).toBeUndefined()
    expect(model.rules[0]?.ranges).toEqual([
      { startRow: 0, endRow: 1048575, startColumn: 0, endColumn: 0 },
      { startRow: 1, endRow: 1, startColumn: 0, endColumn: 16383 },
    ])
  })
})
