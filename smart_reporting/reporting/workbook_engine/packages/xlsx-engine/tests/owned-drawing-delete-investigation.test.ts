import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { expect, it } from 'vitest'
import JSZip from 'jszip'
import { applySheetEdits, readWorkbook } from '../src'
import { assemblePackage, createBufferEntrySource } from '../src/zip'

function fixture(sharedImage = false): Uint8Array {
  return new Uint8Array(execFileSync(fileURLToPath(new URL('../../../../../../.venv/bin/python', import.meta.url)), ['-c', `
import sys,base64
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
from openpyxl import Workbook
from openpyxl.chart import BarChart,Reference
from openpyxl.drawing.image import Image
b=Workbook();s=b.active;s.title='Source';other=b.create_sheet('Other')
for i in range(1,6):s.cell(i,1,i);other.cell(i,2,i)
chart=BarChart();chart.add_data(Reference(s,min_col=1,min_row=1,max_row=5));s.add_chart(chart,'D2')
png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aV1cAAAAASUVORK5CYII=')
s.add_image(Image(BytesIO(png)),'J2')
if ${sharedImage ? 'True' : 'False'}:other.add_image(Image(BytesIO(png)),'D2')
f=BytesIO();b.save(f)
if ${sharedImage ? 'True' : 'False'}:
 source=ZipFile(BytesIO(f.getvalue()));out=BytesIO()
 with ZipFile(out,'w',ZIP_DEFLATED) as target:
  for entry in source.infolist():
   if entry.filename=='xl/media/image2.png':continue
   data=source.read(entry.filename)
   if entry.filename=='xl/drawings/_rels/drawing2.xml.rels':data=data.replace(b'/xl/media/image2.png',b'/xl/media/image1.png')
   target.writestr(entry,data)
 sys.stdout.buffer.write(out.getvalue())
else:sys.stdout.buffer.write(f.getvalue())
`]))
}
const plan = { renames: [], additions: [], removals: ['Source'], order: ['Other'] }
it('cascade-deletes exclusively owned chart, image, drawing and relationship parts with overrides', async () => {
  const bytes = fixture(), before = await createBufferEntrySource(bytes)
  expect(await before.has('xl/charts/chart1.xml')).toBe(true)
  expect(await before.has('xl/media/image1.png')).toBe(true)
  const edited = await applySheetEdits(bytes, plan), after = await createBufferEntrySource(edited)
  expect((await readWorkbook(edited)).sheets.map(sheet => sheet.name)).toEqual(['Other'])
  for (const path of ['xl/worksheets/sheet1.xml', 'xl/worksheets/_rels/sheet1.xml.rels', 'xl/drawings/drawing1.xml', 'xl/drawings/_rels/drawing1.xml.rels', 'xl/charts/chart1.xml', 'xl/media/image1.png']) {
    expect(await after.has(path), path).toBe(false)
    expect(await after.readText('[Content_Types].xml')).not.toContain(`PartName="/${path}"`)
  }
  expect(await after.readText('[Content_Types].xml')).toContain('Extension="png"')
  expect(await after.readText('xl/worksheets/sheet2.xml')).toBe(await before.readText('xl/worksheets/sheet2.xml'))
  expect(await after.readText('xl/styles.xml')).toBe(await before.readText('xl/styles.xml'))
})
it('preserves an image and surviving drawing wiring reached by another sheet', async () => {
  const bytes = fixture(true), before = await createBufferEntrySource(bytes)
  expect(await before.readText('xl/drawings/_rels/drawing2.xml.rels')).toContain('/xl/media/image1.png')
  const edited = await applySheetEdits(bytes, plan), after = await createBufferEntrySource(edited)
  for (const path of ['xl/media/image1.png', 'xl/drawings/drawing2.xml', 'xl/drawings/_rels/drawing2.xml.rels', 'xl/worksheets/sheet2.xml', 'xl/worksheets/_rels/sheet2.xml.rels', 'xl/styles.xml']) {
    expect(await after.has(path), path).toBe(true)
    expect(await (await JSZip.loadAsync(edited)).file(path)!.async('uint8array'), path).toEqual(await (await JSZip.loadAsync(bytes)).file(path)!.async('uint8array'))
  }
  expect(await after.has('xl/drawings/drawing1.xml')).toBe(false)
  expect(await after.has('xl/charts/chart1.xml')).toBe(false)
})
it('keeps shared drawing closure alive and rejects its surviving chart dependency', async () => {
  const bytes = fixture(), source = await createBufferEntrySource(bytes)
  const rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="/xl/drawings/drawing1.xml"/></Relationships>'
  const other = (await source.readText('xl/worksheets/sheet2.xml')).replace('</worksheet>', '<drawing xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rId1"/></worksheet>')
  const patched = (await assemblePackage(bytes, { replaced: new Map([['xl/worksheets/sheet2.xml', other]]), added: new Map([['xl/worksheets/_rels/sheet2.xml.rels', rels]]), addedBinary: new Map(), removedEntries: [], addedEntries: ['xl/worksheets/_rels/sheet2.xml.rels'], touchedEntries: ['xl/worksheets/sheet2.xml'] })).buffer
  await expect(applySheetEdits(patched, plan)).rejects.toThrow(/图表.*引用|chart.*reads/)
})

it('preserves the entire shared drawing subtree when its chart reads only the surviving sheet', async () => {
  const bytes = fixture(), source = await createBufferEntrySource(bytes)
  const rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="/xl/drawings/drawing1.xml"/></Relationships>'
  const other = (await source.readText('xl/worksheets/sheet2.xml')).replace('</worksheet>', '<drawing xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rId1"/></worksheet>')
  const chart = (await source.readText('xl/charts/chart1.xml')).replaceAll("'Source'!", "'Other'!")
  const patched = (await assemblePackage(bytes, { replaced: new Map([['xl/worksheets/sheet2.xml', other], ['xl/charts/chart1.xml', chart]]), added: new Map([['xl/worksheets/_rels/sheet2.xml.rels', rels]]), addedBinary: new Map(), removedEntries: [], addedEntries: ['xl/worksheets/_rels/sheet2.xml.rels'], touchedEntries: ['xl/worksheets/sheet2.xml', 'xl/charts/chart1.xml'] })).buffer
  const edited = await applySheetEdits(patched, plan), after = await createBufferEntrySource(edited)
  for (const path of ['xl/drawings/drawing1.xml', 'xl/drawings/_rels/drawing1.xml.rels', 'xl/charts/chart1.xml', 'xl/media/image1.png']) {
    expect(await after.has(path), path).toBe(true)
    expect(await (await JSZip.loadAsync(edited)).file(path)!.async('uint8array'), path).toEqual(await (await JSZip.loadAsync(patched)).file(path)!.async('uint8array'))
  }
  const types = await after.readText('[Content_Types].xml')
  expect(types).toContain('PartName="/xl/drawings/drawing1.xml"')
  expect(types).toContain('PartName="/xl/charts/chart1.xml"')
})

it('combines survivor rename with owned deletion without rewriting removed chart parts', async () => {
  const bytes = fixture(), edited = await applySheetEdits(bytes, { renames: [{ sheetName: 'Other', newName: 'Kept' }], additions: [], removals: ['Source'], order: ['Kept'] })
  const after = await createBufferEntrySource(edited)
  expect((await readWorkbook(edited)).sheets.map(sheet => sheet.name)).toEqual(['Kept'])
  expect(await after.has('xl/charts/chart1.xml')).toBe(false)
  expect(await after.has('xl/drawings/drawing1.xml')).toBe(false)
})
