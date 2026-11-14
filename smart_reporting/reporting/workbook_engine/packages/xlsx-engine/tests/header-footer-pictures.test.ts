import JSZip from 'jszip'
import { expect, it } from 'vitest'
import { createBlankWorkbook } from '../src/blank'
import { readWorkbookHeaderFooterPictures } from '../src/header-footer-pictures'

const PNG = Uint8Array.from(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j2ioAAAAASUVORK5CYII=', 'base64'))

async function workbookWithHeaderFooterPictures() {
  const zip = await JSZip.loadAsync(await createBlankWorkbook())
  const sheetPath = 'xl/worksheets/sheet1.xml'
  const sheet = await zip.file(sheetPath)!.async('text')
  zip.file(sheetPath, sheet.replace('</worksheet>', '<legacyDrawingHF r:id="rIdHF"/></worksheet>'))
  zip.file('xl/worksheets/_rels/sheet1.xml.rels', '<Relationships><Relationship Id="rIdHF" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/vmlDrawing" Target="../drawings/vmlDrawingHF.vml"/></Relationships>')
  zip.file('xl/drawings/vmlDrawingHF.vml', '<xml xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office"><v:shape id="LH" style="width:72pt;height:18pt"><v:imagedata o:relid="rId1"/></v:shape><v:shape id="CFFIRST" style="width:1in;height:12px"><v:imagedata o:relid="rId2"/></v:shape><v:shape id="RHEVEN" style="width:24pt;height:36pt"><v:imagedata o:relid="missing"/></v:shape><v:shape id="_x0000_s123" style="width:3pt;height:3pt"><v:imagedata o:relid="rId1"/></v:shape></xml>')
  zip.file('xl/drawings/_rels/vmlDrawingHF.vml.rels', '<Relationships><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/logo.png"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/logo.png"/></Relationships>')
  zip.file('xl/media/logo.png', PNG)
  return zip.generateAsync({ type: 'uint8array' })
}

it('reads only linked header/footer VML slots with validated image bytes and physical dimensions', async () => {
  const pictures = await readWorkbookHeaderFooterPictures(await workbookWithHeaderFooterPictures())
  expect([...pictures.keys()]).toEqual(['Sheet1'])
  const sheet = pictures.get('Sheet1')!
  expect([...sheet.keys()]).toEqual(['LH', 'CFFIRST'])
  expect(sheet.get('LH')).toMatchObject({ position: 'LH', widthPt: 72, heightPt: 18, mediaType: 'image/png', bytes: PNG })
  expect(sheet.get('CFFIRST')).toMatchObject({ position: 'CFFIRST', widthPt: 72, heightPt: 9, mediaType: 'image/png', bytes: PNG })
  expect(sheet.has('RHEVEN')).toBe(false)
})
