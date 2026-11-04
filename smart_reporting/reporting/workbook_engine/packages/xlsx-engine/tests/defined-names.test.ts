import { describe, expect, it } from 'vitest'

import { createBlankWorkbook } from '../src/blank'
import {
  applyDefinedNames,
  DefinedNameError,
  isValidDefinedName,
  readDefinedNames,
} from '../src/defined-names'
import { createBufferEntrySource } from '../src/zip'

const workbookXmlOf = async (bytes: Uint8Array): Promise<string> =>
  (await createBufferEntrySource(bytes)).readText('xl/workbook.xml')

describe('defined names (名称管理器)', () => {
  it('validates Excel name rules', () => {
    expect(isValidDefinedName('SalesData')).toBe(true)
    expect(isValidDefinedName('销售额区域')).toBe(true)
    expect(isValidDefinedName('_x')).toBe(true)
    expect(isValidDefinedName('A1')).toBe(false) // cell-shaped
    expect(isValidDefinedName('R1C1')).toBe(false)
    expect(isValidDefinedName('1Sales')).toBe(false) // starts with a digit
    expect(isValidDefinedName('has space')).toBe(false)
    expect(isValidDefinedName('_xlnm.Print_Area')).toBe(false) // reserved
  })

  it('adds, replaces, and removes global names round-trip through the model', async () => {
    const bytes = await createBlankWorkbook()
    const added = await applyDefinedNames(bytes, {
      sets: [
        { name: 'SalesData', refersTo: 'Sheet1!$A$1:$B$10' },
        { name: '税率', refersTo: 'Sheet1!$D$1' },
      ],
    })
    const sorted = (entries: ReadonlyArray<{ name: string; refersTo: string }>) =>
      [...entries].sort((left, right) => left.name.localeCompare(right.name))
    expect(sorted(readDefinedNames(await workbookXmlOf(added)))).toEqual(
      sorted([
        { name: 'SalesData', refersTo: 'Sheet1!$A$1:$B$10' },
        { name: '税率', refersTo: 'Sheet1!$D$1' },
      ]),
    )

    const replaced = await applyDefinedNames(added, {
      sets: [{ name: 'SalesData', refersTo: 'Sheet1!$A$1:$B$20' }],
    })
    const afterReplace = readDefinedNames(await workbookXmlOf(replaced))
    expect(afterReplace.find((entry) => entry.name === 'SalesData')?.refersTo).toBe(
      'Sheet1!$A$1:$B$20',
    )
    expect(afterReplace).toHaveLength(2)

    const removed = await applyDefinedNames(replaced, { removes: ['税率'] })
    const afterRemove = readDefinedNames(await workbookXmlOf(removed))
    expect(afterRemove.map((entry) => entry.name)).toEqual(['SalesData'])
  })

  it('drops an emptied section and leaves other workbook.xml content intact', async () => {
    const bytes = await createBlankWorkbook()
    const added = await applyDefinedNames(bytes, {
      sets: [{ name: 'Temp', refersTo: 'Sheet1!$A$1' }],
    })
    const removed = await applyDefinedNames(added, { removes: ['Temp'] })
    const xml = await workbookXmlOf(removed)
    expect(xml).not.toContain('<definedNames')
    expect(xml).toContain('<sheets')
  })

  it('rejects invalid names, duplicates in one payload, and set/remove conflicts', async () => {
    const bytes = await createBlankWorkbook()
    await expect(
      applyDefinedNames(bytes, { sets: [{ name: 'A1', refersTo: 'Sheet1!$A$1' }] }),
    ).rejects.toThrow(DefinedNameError)
    await expect(
      applyDefinedNames(bytes, {
        sets: [
          { name: 'X', refersTo: 'Sheet1!$A$1' },
          { name: 'x', refersTo: 'Sheet1!$A$2' }, // case-insensitive duplicate
        ],
      }),
    ).rejects.toThrow('重复定义')
    await expect(
      applyDefinedNames(bytes, {
        sets: [{ name: 'X', refersTo: 'Sheet1!$A$1' }],
        removes: ['X'],
      }),
    ).rejects.toThrow('同时出现')
  })

  it('coexists with sheet-scoped names owned by page setup', async () => {
    const { applyPageSetups } = await import('../src/page-setup')
    const bytes = await createBlankWorkbook()
    const withPrintArea = await applyPageSetups(bytes, [
      { sheetName: 'Sheet1', printArea: 'A1:B10' },
    ])
    const both = await applyDefinedNames(withPrintArea, {
      sets: [{ name: 'Global1', refersTo: 'Sheet1!$A$1' }],
    })
    const xml = await workbookXmlOf(both)
    expect(xml).toContain('localSheetId') // Print_Area untouched
    const globals = readDefinedNames(xml)
    expect(globals.map((entry) => entry.name)).toEqual(['Global1'])
    // removing the global name must not touch the sheet-scoped one
    const cleaned = await applyDefinedNames(both, { removes: ['Global1'] })
    const xmlAfter = await workbookXmlOf(cleaned)
    expect(xmlAfter).toContain('localSheetId')
  })
})
