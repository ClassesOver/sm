import { describe, expect, it } from 'vitest'
import JSZip from 'jszip'

import { createBlankWorkbook } from '../src/blank'
import { applyCellEdits } from '../src/workbook-write'
import { readWorkbook } from '../src/workbook-read'

const MACRO_MIME = 'application/vnd.ms-excel.sheet.macroEnabled.12'
const MACRO_BYTES = new Uint8Array([0x56, 0x42, 0x41, 0x50, 0x01, 0x02, 0x03, 0x04])

/// A minimal "xlsm": blank workbook + a fake vbaProject.bin + the macro-enabled
/// workbook content type. The engine never interprets the macro stream; the
/// contract is that it must survive every surgical patch byte-identically.
async function macroEnabledBlank(): Promise<Uint8Array> {
  const zip = await JSZip.loadAsync(await createBlankWorkbook())
  zip.file('xl/vbaProject.bin', MACRO_BYTES, { createFolders: false })
  const types = (await zip.file('[Content_Types].xml')!.async('string')).replace(
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml',
    MACRO_MIME,
  )
  zip.file('[Content_Types].xml', types)
  return zip.generateAsync({ type: 'uint8array' })
}

describe('xlsm macro passthrough', () => {
  it('reads a macro-enabled package and keeps vbaProject.bin through cell edits', async () => {
    const bytes = await macroEnabledBlank()
    const model = await readWorkbook(bytes)
    expect(model.sheets.map((sheet) => sheet.name)).toContain('Sheet1')

    const saved = await applyCellEdits(bytes, [
      { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 5 } },
    ])

    const zipAfter = await JSZip.loadAsync(saved)
    const macroAfter = await zipAfter.file('xl/vbaProject.bin')!.async('uint8array')
    expect([...macroAfter]).toEqual([...MACRO_BYTES])
    expect(await zipAfter.file('[Content_Types].xml')!.async('string')).toContain(MACRO_MIME)

    const reread = await readWorkbook(saved)
    expect(reread.sheets[0]?.cells.A1?.value).toBe(5)
  })

  it('keeps vbaProject.bin when the package gains a new worksheet', async () => {
    const bytes = await macroEnabledBlank()
    const { applySheetEdits } = await import('../src/sheet-ops')
    const saved = await applySheetEdits(bytes, {
      renames: [],
      additions: [{ name: 'Data' }],
      removals: [],
      order: ['Sheet1', 'Data'],
    })
    const zipAfter = await JSZip.loadAsync(saved)
    const macroAfter = await zipAfter.file('xl/vbaProject.bin')!.async('uint8array')
    expect([...macroAfter]).toEqual([...MACRO_BYTES])
    const model = await readWorkbook(saved)
    expect(model.sheets.map((sheet) => sheet.name)).toEqual(['Sheet1', 'Data'])
  })
})
