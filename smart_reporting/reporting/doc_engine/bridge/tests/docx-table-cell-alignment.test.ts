import {tableModelToPmNode} from '../../../../report_editor/frontend/src/vendor/genoffice-docs/apps/docs/src/renderer/editor/convert.ts'
import assert from 'node:assert/strict'
import {test} from 'node:test'
import JSZip from 'jszip'
import {parseDocx,saveDocx} from '../../packages/docx-engine/src/index.ts'
import {buildDocx} from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import {tableCellAlignmentAvailability,editTableCellAlignment,verifyTableCellAlignmentResult} from '../docx-table-cell-alignment.ts'
const para=(text:string,pr='')=>`<w:p w:rsidR="ABCDEF00"><w:pPr><w:keepNext/>${pr}</w:pPr><w:r><w:rPr><w:b/></w:rPr><w:t>${text}</w:t></w:r></w:p>`
const body=para('LTR')+para('שלום','<w:bidi/>')+para('שלום inferred')+para('inherited','<w:pStyle w:val="RtlStyle"/>')+para('list','<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>')+para('heading','<w:pStyle w:val="Heading1"/>')
const cell=(pr='',text=body)=>`<w:tc><w:tcPr><w:tcW w:w="2000" w:type="dxa"/>${pr}<w:shd w:themeFill="accent2"/></w:tcPr>${text}</w:tc>`
const xml=`<w:tbl><w:tblPr><w:tblW w:w="4000" w:type="dxa"/><w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid><w:gridCol w:w="2000"/><w:gridCol w:w="2000"/></w:tblGrid><w:tr><w:trPr><w:trHeight w:val="333" w:hRule="exact"/></w:trPr>${cell()}${cell('',para('other'))}</w:tr></w:tbl>`
const open=async(value=xml)=>{const bytes=await buildDocx({bodyXml:value,withNumbering:true,extraStylesXml:'<w:style w:type="paragraph" w:styleId="RtlStyle"><w:name w:val="RTL"/><w:pPr><w:bidi/></w:pPr></w:style>'});const parsed=await parseDocx(bytes);return{bytes,parsed,block:parsed.blocks.find(b=>b.type==='table')!}}
const mask=(s:string)=>s.replace(/<w:(?:vAlign|jc)\b[^>]*\/>/g,'').replace(/<w:pPr><\/w:pPr>/g,'')
test('real DOCX nine combinations use trusted explicit/inferred/style bidi and preserve every unrelated XML/part',async()=>{
 const{bytes,parsed,block}=await open(),cap=tableCellAlignmentAvailability(block);assert.equal(cap.cellAlignmentEditable,true);assert.equal(cap.cellAlignmentParagraphs[0][1].bidi,true);assert.equal(cap.cellAlignmentParagraphs[0][2].bidiInferred,true);assert.equal(cap.cellAlignmentParagraphs[0][3].bidiInherited,true);assert.equal(cap.cellAlignmentParagraphs[0][4].type,'docListItem');assert.equal(cap.cellAlignmentParagraphs[0][5].type,'docParagraph')
 for(const vertical of ['top','center','bottom'] as const)for(const horizontal of ['left','center','right'] as const){const result=editTableCellAlignment(block,[{top:0,left:0,bottom:1,right:1,vertical,horizontal}]);assert.equal(mask(result.xml),mask(block.originalXml!));assert.deepEqual(result.alignments,[vertical==='top'?null:vertical,null]);const output=await saveDocx(parsed,[{kind:'xml',xml:result.xml}]);verifyTableCellAlignmentResult((await parseDocx(output)).blocks.find(b=>b.type==='table')!,result);const before=await JSZip.loadAsync(bytes),after=await JSZip.loadAsync(output);for(const name of Object.keys(before.files))if(!before.files[name].dir&&name!=='word/document.xml')assert.deepEqual(await before.file(name)!.async('uint8array'),await after.file(name)!.async('uint8array'))}
})
test('merged owner vertical propagates but hidden continuation paragraphs and nested table stay byte identical',async()=>{
 const nested='<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="100"/></w:tblGrid><w:tr>'+cell('',para('nested','<w:jc w:val="right"/>'))+'</w:tr></w:tbl>'
 const hidden=para('hidden','<w:jc w:val="right"/>'),value=xml.replace(/<w:tr>[\s\S]*<\/w:tr>/,`<w:tr>${cell('<w:gridSpan w:val="2"/><w:vMerge w:val="restart"/>',para('owner')+nested+para('after'))}</w:tr><w:tr>${cell('<w:gridSpan w:val="2"/><w:vMerge/><w:vAlign w:val="bottom"/>',hidden)}</w:tr>`)
 const{block}=await open(value),result=editTableCellAlignment(block,[{top:1,left:1,bottom:2,right:2,vertical:'center',horizontal:'center'}]);assert.ok(result.xml.includes(hidden));assert.ok(result.xml.includes(nested));assert.deepEqual(result.physicalAlignments,['center','center']);assert.equal(mask(result.xml),mask(block.originalXml!));verifyTableCellAlignmentResult((await open(result.xml)).block,result)
})
test('missing tcPr/pPr insert safely, ordered clear removes only alignment and invalid controls refuse',async()=>{
 const{block}=await open(xml.replace(/<w:tcPr>[\s\S]*?<\/w:tcPr>/g,'').replace(/<w:pPr>[\s\S]*?<\/w:pPr>/g,''));const result=editTableCellAlignment(block,[{top:0,left:0,bottom:1,right:1,vertical:'center',horizontal:'center'},{top:0,left:0,bottom:1,right:1,vertical:'top',horizontal:'left'}]);verifyTableCellAlignmentResult((await open(result.xml)).block,result)
 for(const raw of ['<w:vAlign w:val="bad"/>','<w:vAlign w:val="center"/><w:vAlign w:val="bottom"/>','<w:shd><w:vAlign w:val="center"/></w:shd>'])assert.equal(tableCellAlignmentAvailability((await open(xml.replace('<w:shd w:themeFill="accent2"/>',raw))).block).cellAlignmentEditable,false)
 for(const raw of ['<w:jc w:val="center"/><w:jc w:val="right"/>','<w:jc w:val="center" w:foreign="1"/>','<w:keepNext><w:jc w:val="center"/></w:keepNext>'])assert.equal(tableCellAlignmentAvailability((await open(xml.replace('<w:keepNext/>',raw))).block).cellAlignmentEditable,false)
 assert.throws(()=>editTableCellAlignment(block,[{top:0,left:0,bottom:1,right:1,vertical:'center',horizontal:'center',xml:'fake'} as any]))
})

test('signed paragraph semantics match actual fixed-source converter including inherited bidi and list/style types',async()=>{
 const{block}=await open(),cap=tableCellAlignmentAvailability(block),pm=tableModelToPmNode(block.table!,block.docxIndex)
 const paragraphs:any[][]=[];for(const row of pm.content??[])for(const cell of row.content??[])paragraphs.push((cell.content??[]).filter(p=>['docParagraph','docListItem','docHeading'].includes(p.type)).map(p=>({type:p.type,align:p.attrs?.align??null,bidi:p.attrs?.bidi===true,bidiInherited:p.attrs?.bidiInherited===true,bidiInferred:p.attrs?.bidiInferred===true})))
 assert.deepEqual(cap.cellAlignmentParagraphs,paragraphs)
})
test('new vAlign precedes retained cell insertion revision according to source tcPr order',async()=>{
 const revision='<w:cellIns w:id="42" w:author="kept"/>',value=xml.replace('<w:shd w:themeFill="accent2"/>',revision),{block}=await open(value)
 const result=editTableCellAlignment(block,[{top:0,left:0,bottom:1,right:1,vertical:'center',horizontal:'center'}]);assert.ok(result.xml.indexOf('<w:vAlign')<result.xml.indexOf('<w:cellIns'));assert.ok(result.xml.includes(revision));verifyTableCellAlignmentResult((await open(result.xml)).block,result)
})
test('self-closing empty owner paragraph receives jc inside the paragraph and survives real save',async()=>{
 const {parsed,block}=await open(xml.replace(body,'<w:p w:rsidR="ABCDEF00"/>'))
 assert.equal(tableCellAlignmentAvailability(block).cellAlignmentEditable,true)
 const result=editTableCellAlignment(block,[{top:0,left:0,bottom:1,right:1,vertical:'center',horizontal:'center'}])
 assert.ok(result.xml.includes('<w:p w:rsidR="ABCDEF00"><w:pPr><w:jc w:val="center"/></w:pPr></w:p>'))
 const saved=await saveDocx(parsed,[{kind:'xml',xml:result.xml}])
 verifyTableCellAlignmentResult((await parseDocx(saved)).blocks.find(b=>b.type==='table')!,result)
})
test('source jc aliases start/end preserve untouched bytes and normalize selected paragraphs through all horizontal modes',async()=>{
 const value=xml.replace('<w:keepNext/>','<w:keepNext/><w:jc w:val="start"/>').replace('other','other end').replace('<w:t>other end</w:t>','<w:t>other end</w:t>'),{block}=await open(value)
 const cap=tableCellAlignmentAvailability(block),pm=tableModelToPmNode(block.table!,block.docxIndex);assert.equal(cap.cellAlignmentEditable,true);assert.equal(cap.cellAlignmentParagraphs[0][0].align,pm.content![0].content![0].content![0].attrs!.align)
 for(const horizontal of ['left','center','right'] as const){const result=editTableCellAlignment(block,[{top:0,left:0,bottom:1,right:1,vertical:'top',horizontal}]);assert.equal(mask(result.xml),mask(block.originalXml!));verifyTableCellAlignmentResult((await open(result.xml)).block,result)}
 const end=(await open(xml.replace('<w:keepNext/>','<w:keepNext/><w:jc w:val="end"/>'))).block;assert.equal(tableCellAlignmentAvailability(end).cellAlignmentEditable,true);verifyTableCellAlignmentResult((await open(editTableCellAlignment(end,[{top:0,left:0,bottom:1,right:1,vertical:'bottom',horizontal:'left'}]).xml)).block,editTableCellAlignment(end,[{top:0,left:0,bottom:1,right:1,vertical:'bottom',horizontal:'left'}]))
})
