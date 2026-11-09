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
    expect(model.sheets[0]!.protection).toEqual({ protected: true, hasPassword: false })
    expect(model.workbookProtection).toEqual({ lockStructure: true, hasPassword: false })
    const unlocked = await readWorkbook(await protectWorkbookStructure(await protectSheet(locked, 'Sheet1', false), false))
    expect(unlocked.sheets[0]!.protection).toBeUndefined()
    expect(unlocked.workbookProtection).toBeUndefined()
  })

  it('flags passwords and non-protecting elements', () => {
    expect(readSheetProtection('<sheetData/><sheetProtection algorithmName="SHA-512" hashValue="x" sheet="1"/>')).toEqual({ protected: true, hasPassword: true })
    expect(readSheetProtection('<sheetProtection password="CC3D" sheet="true"/>')).toEqual({ protected: true, hasPassword: true })
    expect(readSheetProtection('<sheetProtection objects="1"/>')).toEqual({ protected: false, hasPassword: false })
    expect(readWorkbookProtection('<workbookProtection workbookPassword="CC3D" lockStructure="1"/>')).toEqual({ lockStructure: true, hasPassword: true })
    expect(readWorkbookProtection('<workbookProtection lockWindows="1"/>')).toEqual({ lockStructure: false, hasPassword: false })
  })
})
