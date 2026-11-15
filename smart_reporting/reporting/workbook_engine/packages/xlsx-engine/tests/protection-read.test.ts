import { describe, expect, it } from 'vitest'

import { createBlankWorkbook, protectSheet, protectWorkbookStructure, readWorkbook } from '../src'
import { readSheetProtection, readWorkbookProtection } from '../src/protection-read'

describe('protection readback', () => {
  it('projects sheet and workbook protection written by the engine', async () => {
    const blank = await createBlankWorkbook()
    const plain = await readWorkbook(blank)
    expect(plain.sheets[0]!.protection).toBeUndefined()
    expect(plain.workbookProtection).toBeUndefined()
    const locked = await protectWorkbookStructure(await protectSheet(blank, 'Sheet1', true), true)
    const model = await readWorkbook(locked)
    expect(model.sheets[0]!.protection).toMatchObject({
      protected: true, hasPassword: false,
      allow: { selectLockedCells: true, selectUnlockedCells: true, autoFilter: false, sort: false, objects: false },
    })
    expect(model.workbookProtection).toEqual({ lockStructure: true, hasPassword: false })
    const unlocked = await readWorkbook(await protectWorkbookStructure(await protectSheet(locked, 'Sheet1', false), false))
    expect(unlocked.sheets[0]!.protection).toBeUndefined()
    expect(unlocked.workbookProtection).toBeUndefined()
  })

  it('flags passwords and non-protecting elements', () => {
    const modern = readSheetProtection('<sheetData/><sheetProtection algorithmName="SHA-512" hashValue="x" sheet="1"/>')
    expect(modern).toMatchObject({ protected: true, hasPassword: true })
    expect(modern).not.toHaveProperty('hashValue')
    expect(readSheetProtection("<sheetProtection password='CC3D' sheet='true' sort='0' selectLockedCells='1'/>"))
      .toMatchObject({ protected: true, hasPassword: true, allow: { sort: true, selectLockedCells: false } })
    expect(readSheetProtection('<sheetProtection objects="1"/>')).toMatchObject({ protected: false, hasPassword: false })
    expect(readWorkbookProtection('<workbookProtection workbookPassword="CC3D" lockStructure="1"/>')).toEqual({ lockStructure: true, hasPassword: true })
    expect(readWorkbookProtection('<workbookProtection lockWindows="1"/>')).toEqual({ lockStructure: false, hasPassword: false })
  })
})
