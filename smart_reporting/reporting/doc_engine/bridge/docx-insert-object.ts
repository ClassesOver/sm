/** GenOffice f8c17004 ribbon-tabs.tsx insertTextboxAt/insertShapeAt/insertWordArtAt.
 * Server reconstructs OOXML exclusively with the fixed-source engine builders. */
import {buildTextboxParagraphXml,buildShapeParagraphXml,buildWordArtParagraphXml,buildLineParagraphXml,LINE_KINDS} from '../packages/docx-engine/src/generate.ts'
import {escapeXmlText} from '../packages/docx-engine/src/xml-utils.ts'
import {WORDART_PRESETS,wordArtSolidColor} from '../../../report_editor/frontend/src/vendor/genoffice-docs/packages/ui/src/wordart-presets.ts'
import {normalizeDocxInsertObject} from '../../../report_editor/frontend/src/docx-insert-object-params.ts'
export function buildDocxInsertObject(value:unknown,id:number):string {
 const v=normalizeDocxInsertObject(value), dimensions={widthEmu:v.widthEmu,heightEmu:v.heightEmu,id}
 if(v.type==='wordArt') {const p=WORDART_PRESETS.find(p=>p.id===v.preset)!;return buildWordArtParagraphXml({...dimensions,text:v.text??'艺术字',colorHex:wordArtSolidColor(p).replace('#',''),italic:p.italic})}
 if(v.type==='shape'&&v.preset! in LINE_KINDS)return buildLineParagraphXml({...dimensions,kind:v.preset!,heightEmu:['line','lineArrow','lineArrowDouble'].includes(v.preset!)?114300:v.heightEmu??1080000,colorHex:'000000'})
 let xml=v.type==='textbox'?buildTextboxParagraphXml(dimensions):buildShapeParagraphXml({...dimensions,prst:v.preset!,fillHex:'4472C4',borderHex:'2F5496',withTextbox:true})
 if(v.text!==undefined)xml=xml.replace(/<w:txbxContent>[\s\S]*?<\/w:txbxContent>/g,`<w:txbxContent><w:p>${v.type==='shape'?'<w:pPr><w:jc w:val="center"/></w:pPr>':''}<w:r><w:t xml:space="preserve">${escapeXmlText(v.text)}</w:t></w:r></w:p></w:txbxContent>`)
 return xml
}
