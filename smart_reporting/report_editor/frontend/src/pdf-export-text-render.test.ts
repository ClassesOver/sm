import {expect,it,afterEach,beforeEach,vi} from 'vitest'
import {buildDocx} from '../../../reporting/doc_engine/packages/docx-engine/tests/helpers/build-docx'
import {renderPdfTextExport} from './pdf-export-text-render'
const picture='<w:p><w:r><w:drawing><wp:inline><wp:extent cx="190500" cy="95250"/><wp:docPr id="1" name="Scan image"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:nvPicPr><pic:cNvPr id="1" name="Scan image"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="rId10"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="190500" cy="95250"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
beforeEach(()=>vi.stubGlobal('CSS',{escape:(value:string)=>value}))
afterEach(()=>{document.body.replaceChildren();vi.unstubAllGlobals()})
it.each(['markdown','html'] as const)('actual fixed-source serializer exports text table and embedded image to %s',async format=>{
 const bytes=await buildDocx({withImage:true,bodyXml:'<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Editable report</w:t></w:r></w:p><w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="2000"/></w:tblGrid><w:tr><w:tc><w:p><w:r><w:t>Revenue 123</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'+picture})
 const output=await renderPdfTextExport(bytes,format)
 expect(output.text).toContain('Editable report');expect(output.text).toContain('Revenue 123');expect(output.text).toContain('data:image/png;base64,');expect(output.text).not.toContain('__genoffice_media__');expect(output.text).not.toContain('genoffice-docx-media://');expect(output.warnings.join('')).toContain('人工核对');expect(document.querySelector('.docx-native')).toBeNull()
 if(format==='html'){const parsed=new DOMParser().parseFromString(output.text,'text/html');expect(parsed.querySelector('script')).toBeNull();expect(parsed.querySelector('img')!.src).toMatch(/^data:/)}
})
