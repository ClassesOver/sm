import { describe, expect, it } from 'vitest'
import JSZip from 'jszip'

import { createBlankWorkbook } from '../src/blank'
import { applyCellEdits } from '../src/workbook-write'
import { createBufferEntrySource } from '../src/zip'

/// Regress #25: packages carrying explicit folder entries ("xl/") — emitted
/// by many zip toolchains and by any JSZip loadAsync→generateAsync round
/// trip — must keep every child entry loadable.
describe('zip loading with folder entries (#25)', () => {
  it('keeps children of folder entries readable', async () => {
    const base = await createBlankWorkbook()
    // re-adding a file materializes folder entries (JSZip createFolders default)
    const zip = await JSZip.loadAsync(base)
    zip.file('xl/worksheets/sheet1.xml', await zip.file('xl/worksheets/sheet1.xml')!.async('string'))
    const regenerated = await zip.generateAsync({ type: 'uint8array' })
    const reloaded = await JSZip.loadAsync(regenerated)
    expect(Object.keys(reloaded.files).some((path) => reloaded.files[path]!.dir)).toBe(true)

    const source = await createBufferEntrySource(regenerated)
    expect(await source.has('xl/workbook.xml')).toBe(true)
    expect(await source.has('xl/worksheets/sheet1.xml')).toBe(true)
    expect((await source.readText('xl/workbook.xml')).includes('<sheets')).toBe(true)
  })

  it('still folds non-canonical file paths (backslash producer quirk)', async () => {
    const base = await createBlankWorkbook()
    const zip = await JSZip.loadAsync(base)
    // rename a file entry to a backslash path, as some producers do
    const sheetXml = await zip.file('xl/worksheets/sheet1.xml')!.async('string')
    zip.remove('xl/worksheets/sheet1.xml')
    zip.file('xl\\worksheets\\sheet1.xml', sheetXml)
    const quirky = await zip.generateAsync({ type: 'uint8array' })

    const source = await createBufferEntrySource(quirky)
    expect(await source.has('xl/worksheets/sheet1.xml')).toBe(true)
  })

  it('edits still apply on a folder-carrying package', async () => {
    const base = await createBlankWorkbook()
    const regenerated = await (await JSZip.loadAsync(base)).generateAsync({ type: 'uint8array' })
    const saved = await applyCellEdits(regenerated, [
      { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 7 } },
    ])
    const { readWorkbook } = await import('../src/workbook-read')
    expect((await readWorkbook(saved)).sheets[0]?.cells.A1?.value).toBe(7)
  })
})
