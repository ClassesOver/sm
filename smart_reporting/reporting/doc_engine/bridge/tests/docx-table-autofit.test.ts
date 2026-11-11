import assert from 'node:assert/strict'
import {test} from 'node:test'
import JSZip from 'jszip'
import {parseDocx,saveDocx} from '../../packages/docx-engine/src/index.ts'
import {buildDocx} from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import {tableAutoFitAvailability,editTableAutoFit,verifyTableAutoFitResult} from '../docx-table-autofit.ts'
const p='<w:p w:rsidR="ABCD1234"><w:pPr><w:keepNext/></w:pPr><w:r><w:rPr><w:b/><w:color w:val="FF0000"/></w:rPr><w:t>中文😀</w:t></w:r></w:p>'
const cell=(pr='',body=p)=>`<w:tc><w:tcPr>${pr}<w:shd w:themeFill="accent2"/></w:tcPr>${body}</w:tc>`
const xml=`<w:tbl><w:tblPr><w:tblW w:w='4001' w:type="dxa"/><w:tblLayout w:type="fixed"/><w:tblCaption w:val="keep"/></w:tblPr><w:tblGrid><w:gridCol w:w="2000"/><w:gridCol w:w="2001"/></w:tblGrid><w:tr><w:trPr><w:trHeight w:val="300" w:hRule="exact"/><w:cantSplit/></w:trPr>${cell('<w:tcW w:w="2000" w:type="dxa"/>')}${cell('<w:tcW w:w="2001" w:type="dxa"/>')}</w:tr></w:tbl>`
const open=async(value=xml)=>{const bytes=await buildDocx({bodyXml:value});const parsed=await parseDocx(bytes);return{bytes,parsed,block:parsed.blocks.find(b=>b.type==='table')!}}
const mask=(value:string)=>value.replace(/<w:(?:tblW|tblLayout|gridCol|tcW)\b[^>]*\/>/g,'')
test('real DOCX three modes preserve source integer widths and every nongeometry XML/ZIP part',async()=>{
 const {bytes,parsed,block}=await open()
 assert.equal(tableAutoFitAvailability(block,9000).autoFitEditable,true)
 for(const mode of ['contents','window','fixed'] as const){const result=editTableAutoFit(block,9000,[{mode}]);assert.deepEqual(result.widthsTwips,mode==='contents'?[4680,4680]:[2000,2001]);assert.equal(mask(result.xml),mask(block.originalXml!));const out=await saveDocx(parsed,[{kind:'xml',xml:result.xml}]);verifyTableAutoFitResult((await parseDocx(out)).blocks.find(b=>b.type==='table')!,result);const before=await JSZip.loadAsync(bytes),after=await JSZip.loadAsync(out);for(const name of Object.keys(before.files))if(!before.files[name].dir&&name!=='word/document.xml')assert.deepEqual(await before.file(name)!.async('uint8array'),await after.file(name)!.async('uint8array'))}
 const chained=editTableAutoFit(block,9000,[{mode:'contents'},{mode:'window'},{mode:'fixed'}]);assert.deepEqual(chained.widthsTwips,[4500,4500]);assert.equal(mask(chained.xml),mask(block.originalXml!))
})
test('independent capability accepts auto/pct/missing widths and inserts only missing geometry',async()=>{
 for(const width of ['<w:tblW w:w="0" w:type="auto"/>','<w:tblW w:w="2500" w:type="pct"/>','']){const value=xml.replace(/<w:tblW[^>]*\/>/,width).replace('<w:tblLayout w:type="fixed"/>','').replace(/<w:tcW[^>]*\/>/g,'');const{block}=await open(value);assert.equal(tableAutoFitAvailability(block,9000).autoFitEditable,true);for(const mode of ['contents','window','fixed'] as const){const result=editTableAutoFit(block,9000,[{mode}]);assert.equal(mask(result.xml),mask(block.originalXml!));verifyTableAutoFitResult((await open(result.xml)).block,result)}}
 const{block}=await open(xml.replace(/<w:tblPr>[\s\S]*?<\/w:tblPr>/,'').replace(/<w:tcPr>[\s\S]*?<\/w:tcPr>/g,''));const result=editTableAutoFit(block,9000,[{mode:'window'}]);assert.ok(result.xml.includes('<w:tblPr>'));assert.ok(result.xml.includes('<w:tcPr>'));verifyTableAutoFitResult((await open(result.xml)).block,result)
})
test('merged continuation opaque content and nested tables survive all modes',async()=>{
 const nested='<w:tbl><w:tblPr><w:tblW w:w="111" w:type="dxa"/></w:tblPr><w:tblGrid><w:gridCol w:w="111"/></w:tblGrid><w:tr>'+cell()+'</w:tr></w:tbl>'
 const value=xml.replace(/<w:tr>[\s\S]*<\/w:tr>/,`<w:tr>${cell('<w:gridSpan w:val="2"/><w:vMerge w:val="restart"/>',p+nested+p)}</w:tr><w:tr>${cell('<w:gridSpan w:val="2"/><w:vMerge/>',p.replace('中文😀','hidden'))}</w:tr>`)
 const{block}=await open(value)
 for(const mode of ['contents','window','fixed'] as const){const result=editTableAutoFit(block,9000,[{mode}]);assert.ok(result.xml.includes(nested));assert.ok(result.xml.includes('hidden'));verifyTableAutoFitResult((await open(result.xml)).block,result);assert.equal(result.cells.length,1);assert.equal(result.cells[0].bottom,2)}
})
test('rejects ambiguous geometry, revision, float, malformed steps and forged verification',async()=>{
 for(const value of [xml.replace('<w:tblLayout','<w:tblLayout w:unknown="1"'),xml.replace('</w:tblPr>','<w:tblW w:w="0" w:type="auto"/></w:tblPr>'),xml.replace('</w:tblPr>','<w:tblpPr/></w:tblPr>'),xml.replace('</w:tblPr>','<w:tblPrChange/></w:tblPr>'),xml.replace('<w:tblGrid>','<w:tblGrid w:unknown="1">')])assert.equal(tableAutoFitAvailability((await open(value)).block,9000).autoFitEditable,false)
 const{block}=await open();for(const steps of [[],[{mode:'no'}],[{mode:'contents',xml:'forged'}]])assert.throws(()=>editTableAutoFit(block,9000,steps as any))
 const result=editTableAutoFit(block,9000,[{mode:'window'}]);assert.throws(()=>verifyTableAutoFitResult(block,result))
})

test('missing table properties insert width before layout and leave existing property bytes intact',async()=>{
 for(const pr of ['<w:tblPr/>','<w:tblPr><w:tblStyle w:val="keep"/></w:tblPr>']){
  const{block}=await open(xml.replace(/<w:tblPr>[\s\S]*?<\/w:tblPr>/,pr))
  const result=editTableAutoFit(block,9000,[{mode:'window'}])
  assert.ok(result.xml.indexOf('<w:tblW')<result.xml.indexOf('<w:tblLayout'))
  if(pr.includes('tblStyle'))assert.ok(result.xml.includes('<w:tblStyle w:val="keep"/>'))
 }
})
test('capability uses source effective modes and refuses forged model mode independently',async()=>{
 for(const [width,layout,mode] of [['<w:tblW w:w="0" w:type="nil"/>','','fixed'],['<w:tblW w:w="7500" w:type="pct"/>','','fixed'],['<w:tblW w:w="0" w:type="pct"/>','','fixed'],['<w:tblW w:w="0" w:type="dxa"/>','','contents'],['<w:tblW w:w="0" w:type="auto"/>','','contents'],['<w:tblW w:w="5000" w:type="pct"/>','','window'],['<w:tblW w:w="2500" w:type="pct"/>','','contents'],['<w:tblW w:w="4001" w:type="dxa"/>','','fixed'],['<w:tblW w:w="5000" w:type="pct"/>','<w:tblLayout w:type="fixed"/>','fixed']]){
  const {block}=await open(xml.replace(/<w:tblW[^>]*\/>/,width).replace(/<w:tblLayout[^>]*\/>/,layout));assert.equal(tableAutoFitAvailability(block,9000).autoFitMode,mode);assert.equal(tableAutoFitAvailability({...block,table:{...block.table!,autoFit:mode==='fixed'?'contents':'fixed'}},9000).autoFitEditable,false)
 }
})
