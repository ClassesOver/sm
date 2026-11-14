import { expect, it } from 'vitest'
import { assemblePackage, createBlankWorkbook, createBufferEntrySource, readWorkbook, readWorkbookHeaderFooterPictures } from '@sheets-web/xlsx-engine'
import { pageBreakPreviewSetup } from './workbook-page-break-context'
import { buildSheetPrintHtml, printSourceFromSnapshotSheet } from './workbook-print'

const PNG = Uint8Array.from(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j2ioAAAAASUVORK5CYII=', 'base64'))

it('prints real XLSX odd, even and first header pictures in their VML slots and leaves empty slots blank', async () => {
  const blank = await createBlankWorkbook(), entries = await createBufferEntrySource(blank)
  const path = 'xl/worksheets/sheet1.xml', xml = await entries.readText(path)
  const suffix = '<headerFooter differentFirst="1" differentOddEven="1"><oddHeader>&amp;L&amp;G&amp;P&amp;F&amp;C&amp;G</oddHeader><evenHeader>&amp;R&amp;G</evenHeader><firstHeader>&amp;C&amp;G</firstHeader></headerFooter><legacyDrawingHF r:id="rIdHF"/>'
  const bytes = (await assemblePackage(blank, {
    replaced: new Map([[path, xml.replace('</worksheet>', `${suffix}</worksheet>`)]]),
    added: new Map([['xl/worksheets/_rels/sheet1.xml.rels', '<Relationships><Relationship Id="rIdHF" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/vmlDrawing" Target="../drawings/vmlDrawingHF.vml"/></Relationships>'],
      ['xl/drawings/vmlDrawingHF.vml', '<xml xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office"><v:shape id="LH" style="width:72pt;height:18pt"><v:imagedata o:relid="rId1"/></v:shape><v:shape id="RHEVEN" style="width:24pt;height:36pt"><v:imagedata o:relid="rId1"/></v:shape><v:shape id="CHFIRST" style="width:1in;height:12px"><v:imagedata o:relid="rId1"/></v:shape></xml>'],
      ['xl/drawings/_rels/vmlDrawingHF.vml.rels', '<Relationships><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/logo.png"/></Relationships>']]),
    addedBinary: new Map([['xl/media/logo.png', PNG]]), removedEntries: [], addedEntries: ['xl/worksheets/_rels/sheet1.xml.rels', 'xl/drawings/vmlDrawingHF.vml', 'xl/drawings/_rels/vmlDrawingHF.vml.rels', 'xl/media/logo.png'], touchedEntries: [path],
  })).buffer
  const workbook = await readWorkbook(bytes), sheet = workbook.sheets[0]!
  const pictures = (await readWorkbookHeaderFooterPictures(bytes)).get(sheet.name)!
  const source = printSourceFromSnapshotSheet({ name: sheet.name, cellData: { 0: { 0: { v: 'Report' } } } }, {}, pictures)
  const setup = pageBreakPreviewSetup(sheet, {})
  const html = (pageOffset: number, selectedSetup = setup) => buildSheetPrintHtml(source, selectedSetup, { pageOffset, totalPages: 3, fileName: 'annual.xlsx', now: new Date('2026-11-13T00:00:00Z') })!
  const repeatedSetup = { ...setup, headerFooter: { ...setup.headerFooter!, differentFirst: false } }

  expect(setup.headerFooter?.differentFirst).toBe(true)
  expect(html(0)).toContain('width:72pt;height:9pt')
  expect(html(1, repeatedSetup)).toContain('width:24pt;height:36pt')
  expect(html(2, repeatedSetup)).toContain('width:72pt;height:18pt')
  const odd = html(2, repeatedSetup)
  expect(odd.match(/<img /g)).toHaveLength(1)
  expect(odd).toContain('3annual.xlsx')
})
