import { describe, expect, it } from 'vitest'
import { createBlankWorkbook } from '../src'
import { applyProtectedRanges, setSheetEditableRanges } from '../src/protection'
import { readProtectedRanges } from '../src/protection-read'
import { createBufferEntrySource } from '../src/zip'

const sheet = '<worksheet><sheetData/><sheetProtection sheet="1"></sheetProtection><autoFilter ref="A1:C9"/></worksheet>'

describe('allow-edit ranges', () => {
  it('writes standard OOXML after the complete protection element and reads names and multi-area refs', () => {
    const xml = applyProtectedRanges(sheet, [{ name: '输入 & 校验', sqref: '$B$2:$C$4 E2:E4' }])
    expect(xml).toContain('</sheetProtection><protectedRanges>')
    expect(readProtectedRanges(xml)).toEqual([{ name: '输入 & 校验', sqref: 'B2:C4 E2:E4' }])
  })
  it('writes and reopens the actual worksheet package', async () => {
    const bytes = await setSheetEditableRanges(await createBlankWorkbook(), 'Sheet1', [{ name: 'Input', sqref: 'B2:C4' }])
    const source = await createBufferEntrySource(bytes)
    expect(readProtectedRanges(await source.readText('xl/worksheets/sheet1.xml'))).toEqual([{ name: 'Input', sqref: 'B2:C4' }])
  })
  it('refuses invalid bounds, empty or duplicate names and preserves unsupported restrictions', () => {
    for (const ranges of [[{ name: '', sqref: 'A1' }], [{ name: 'Input', sqref: 'XFE1' }], [{ name: 'Input', sqref: 'A0' }], [{ name: 'Input', sqref: 'A1' }, { name: 'INPUT', sqref: 'B1' }]])
      expect(() => applyProtectedRanges(sheet, ranges)).toThrow()
    for (const attrs of ["password='AB12'", 'hashValue="x"', 'securityDescriptor="x"', 'algorithmName="SHA-512"']) {
      const xml = `<worksheet><sheetData/><protectedRanges><protectedRange name="Secret" sqref="A1" ${attrs}/></protectedRanges></worksheet>`
      expect(readProtectedRanges(xml)[0]?.readonlyReason).toBeTruthy()
      expect(() => applyProtectedRanges(xml, [])).toThrow(/not supported/)
    }
  })
  it('refuses rewriting unsupported section attributes and child elements', () => {
    for (const xml of [
      '<worksheet><sheetData/><protectedRanges custom="x"><protectedRange name="Input" sqref="A1"/></protectedRanges></worksheet>',
      '<worksheet><sheetData/><protectedRanges><custom/></protectedRanges></worksheet>',
      '<x:worksheet><x:sheetData/><x:protectedRanges><x:protectedRange name="Input" sqref="A1" password="x"/></x:protectedRanges></x:worksheet>',
    ]) expect(() => applyProtectedRanges(xml, [])).toThrow(/not supported/)
  })
})
