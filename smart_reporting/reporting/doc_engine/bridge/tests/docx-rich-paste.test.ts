import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createHash} from 'node:crypto'
import JSZip from 'jszip'
import {buildDocx} from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import {patchDocxRichPaste} from '../docx-rich-paste.ts'
import {parseDocx} from '../../packages/docx-engine/src/parse.ts'
const p=(text:string)=>'<w:p><w:pPr><w:keepNext/></w:pPr><w:r><w:rPr><w:b/></w:rPr><w:t>'+text+'</w:t></w:r></w:p>'
test('rich cross-paragraph paste preserves untouched native XML/parts and writes runs, list and merged table',async()=>{
 const source=await buildDocx({bodyXml:p('A😀B')+p('Tail')+'<w:sdt><w:sdtPr><w:tag w:val="retained"/></w:sdtPr><w:sdtContent>'+p('Protected')+'</w:sdtContent></w:sdt>',headerXml:p('header')})
 const cell={type:'docTableCell',attrs:{colspan:2},content:[{type:'docParagraph',content:[{type:'text',text:'Cell',marks:[{type:'bold'}]}]}]}
 const table={type:'docTable',content:[{type:'docTableRow',content:[cell]}]}
 const op:any={kind:'pasteRichContent',sourceSha256:createHash('sha256').update(source).digest('hex'),start:{docxIndex:0,offset:3},end:{docxIndex:1,offset:1},blocks:[
  {type:'docParagraph',content:[{type:'text',text:'Red',marks:[{type:'docTextStyle',attrs:{color:'FF0000'}},{type:'italic'}]}]},
  {type:'docListItem',attrs:{kind:'ordered',ilvl:1},content:[{type:'text',text:'Item'}]},table]}

 const output=await patchDocxRichPaste(source,op),zip=await JSZip.loadAsync(output),xml=await zip.file('word/document.xml')!.async('string'),original=await JSZip.loadAsync(source)
 assert.match(xml,/w:val="FF0000"/);assert.match(xml,/<w:i\/>/);assert.match(xml,/<w:numPr>/);assert.match(xml,/<w:gridSpan w:val="2"\/>/);assert.match(xml,/<w:tag w:val="retained"\/>/)
 const parsed=await parseDocx(output);assert.equal(parsed.blocks[0].runs?.map(r=>r.text).join(''),'A😀Red');assert.ok(parsed.blocks.some(b=>b.runs?.map(r=>r.text).join('')==='ail'),JSON.stringify(parsed.blocks.map(b=>({type:b.type,text:b.runs?.map(r=>r.text).join('')}))))
 for(const file of Object.values(original.files))if(!file.dir&&!['word/document.xml','word/numbering.xml','word/_rels/document.xml.rels','[Content_Types].xml'].includes(file.name))assert.deepEqual(await zip.file(file.name)!.async('uint8array'),await file.async('uint8array'))
 for(const bad of [{sourceSha256:'0'.repeat(64)},{start:{docxIndex:0,offset:2}},{blocks:[{type:'docParagraph',attrs:{rawPPr:'<w:pPr/>'}}]}])await assert.rejects(patchDocxRichPaste(source,{...op,...bad}))
})
test('writes data PNG media and same-list nested numbering; rejects unknown source inline and content fields',async()=>{
 const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==',source=await buildDocx({bodyXml:p('abc')}),op:any={kind:'pasteRichContent',sourceSha256:createHash('sha256').update(source).digest('hex'),start:{docxIndex:0,offset:1},end:{docxIndex:0,offset:2},blocks:[{type:'docListItem',attrs:{kind:'ordered',ilvl:0},content:[{type:'text',text:'Outer'}]},{type:'docListItem',attrs:{kind:'ordered',ilvl:1},content:[{type:'text',text:'Inner'},{type:'docInlineImage',attrs:{dataUrl:'data:image/png;base64,'+png,widthPx:1,heightPx:1}}]}]}
 const bytes=await patchDocxRichPaste(source,op),zip=await JSZip.loadAsync(bytes),xml=await zip.file('word/document.xml')!.async('string');assert.equal(Object.keys(zip.files).filter(n=>n.startsWith('word/media/')&&!zip.files[n].dir).length,1);assert.match(xml,/<w:drawing>/);assert.equal(new Set([...xml.matchAll(/<w:numId w:val="(\d+)"/g)].map(m=>m[1])).size,1);assert.match(xml,/<w:ilvl w:val="1"/)
 for(const bad of [{type:'text',text:'x',attrs:{nativeIdentity:'forged'}},{type:'text',text:'x',content:[]},{type:'text',text:'x',marks:[{type:'link',attrs:{href:'javascript:alert(1)'}}]}])await assert.rejects(patchDocxRichPaste(source,{...op,blocks:[{type:'docParagraph',content:[bad]}]}))
 const unknown=await buildDocx({bodyXml:'<w:p><w:r><w:unknown/><w:t>abc</w:t></w:r></w:p>'});await assert.rejects(patchDocxRichPaste(unknown,{...op,sourceSha256:createHash('sha256').update(unknown).digest('hex')}),/target_unsupported/)
 const second={...op,sourceSha256:createHash('sha256').update(bytes).digest('hex'),start:{docxIndex:0,offset:0},end:{docxIndex:0,offset:3},blocks:[{type:'docParagraph',content:[{type:'docInlineImage',attrs:{dataUrl:'data:image/png;base64,'+png,widthPx:1,heightPx:1}}]}]},twice=await patchDocxRichPaste(bytes,second),twiceZip=await JSZip.loadAsync(twice),twiceXml=await twiceZip.file('word/document.xml')!.async('string'),docPrIds=[...twiceXml.matchAll(/<wp:docPr\b[^>]*\bid="(\d+)"/g)].map(m=>m[1]);assert.equal(new Set(docPrIds).size,docPrIds.length,docPrIds.join(','))
})
test('retains nested table reading order between cell paragraphs',async()=>{
 const source=await buildDocx({bodyXml:p('abc')}),para=(text:string)=>({type:'docParagraph',content:[{type:'text',text}]}),nested={type:'docTable',content:[{type:'docTableRow',content:[{type:'docTableCell',content:[para('NESTED')]}]}]},op={kind:'pasteRichContent',sourceSha256:createHash('sha256').update(source).digest('hex'),start:{docxIndex:0,offset:0},end:{docxIndex:0,offset:3},blocks:[{type:'docTable',content:[{type:'docTableRow',content:[{type:'docTableCell',content:[para('BEFORE'),nested,para('AFTER')]}]}]}]}
 const zip=await JSZip.loadAsync(await patchDocxRichPaste(source,op)),xml=await zip.file('word/document.xml')!.async('string');assert.ok(xml.indexOf('BEFORE')<xml.indexOf('NESTED'));assert.ok(xml.indexOf('NESTED')<xml.indexOf('AFTER'))
})
test('retains pasted list and heading semantics when both source boundaries keep original pPr',async()=>{
 const source=await buildDocx({bodyXml:p('PREFIX')+p('SUFFIX')}),base={kind:'pasteRichContent',sourceSha256:createHash('sha256').update(source).digest('hex'),start:{docxIndex:0,offset:3},end:{docxIndex:1,offset:3}}
 for(const type of ['docListItem','docHeading']){const blocks=[{type,attrs:type==='docListItem'?{kind:'ordered',ilvl:0}:{level:2},content:[{type:'text',text:'FIRST'}]},{type,attrs:type==='docListItem'?{kind:'ordered',ilvl:1}:{level:3},content:[{type:'text',text:'LAST'}]}],zip=await JSZip.loadAsync(await patchDocxRichPaste(source,{...base,blocks})),xml=await zip.file('word/document.xml')!.async('string');const parsed=await parseDocx(await zip.generateAsync({type:'uint8array'}));assert.equal(parsed.blocks[0].runs?.map(r=>r.text).join(''),'PREFIRST');assert.equal(parsed.blocks[1].runs?.map(r=>r.text).join(''),'LASTFIX');assert.equal((xml.match(type==='docListItem'?/<w:numPr>/g:/<w:(?:pStyle|outlineLvl)\b/g)??[]).length,2);assert.equal((xml.match(/<w:keepNext\/>/g)??[]).length,2)}
})
