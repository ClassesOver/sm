import assert from 'node:assert/strict'
import {test} from 'node:test'
import JSZip from 'jszip'
import {parseDocx,saveDocx} from '../../packages/docx-engine/src/index.ts'
import {buildDocx} from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import {tableCellTextDirectionAvailability,editTableCellTextDirection,verifyTableCellTextDirectionResult} from '../docx-table-cell-text-direction.ts'
const p='<w:p w:rsidR="ABCD1234"><w:pPr><w:keepNext/></w:pPr><w:r><w:rPr><w:b/><w:color w:val="FF0000"/></w:rPr><w:t>中文😀</w:t></w:r></w:p>'
const cell=(pr='',body=p)=>`<w:tc><w:tcPr><w:tcW w:w="2000" w:type="dxa"/>${pr}<w:shd w:themeFill="accent2"/></w:tcPr>${body}</w:tc>`
const xml=`<w:tbl><w:tblPr><w:tblW w:w="4000" w:type="dxa"/><w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid><w:gridCol w:w="2000"/><w:gridCol w:w="2000"/></w:tblGrid><w:tr><w:trPr><w:trHeight w:val="300" w:hRule="exact"/><w:cantSplit/></w:trPr>${cell('<w:textDirection w:val = \'tbRlV\'/>')}${cell('<w:textDirection w:val="btLrV"/>')}</w:tr></w:tbl>`
const open=async(value=xml)=>{const bytes=await buildDocx({bodyXml:value});const parsed=await parseDocx(bytes);return{bytes,parsed,block:parsed.blocks.find(b=>b.type==='table')!}}
const mask=(s:string)=>s.replace(/<w:textDirection\b[^>]*\/>/g,'')
test('real DOCX direction aliases normalize but untouched owner bytes and all other XML/parts survive',async()=>{
 const{bytes,parsed,block}=await open();const cap=tableCellTextDirectionAvailability(block);assert.equal(cap.cellTextDirectionEditable,true);assert.deepEqual(cap.cellTextDirections,['tbRl','btLr'])
 for(const direction of ['lrTb','tbRl','btLr'] as const){const result=editTableCellTextDirection(block,[{top:0,left:0,bottom:1,right:1,direction}]);assert.equal(mask(result.xml),mask(block.originalXml!));assert.ok(result.xml.includes('<w:textDirection w:val="btLrV"/>'));assert.deepEqual(result.directions,[direction==='lrTb'?null:direction,'btLr']);const output=await saveDocx(parsed,[{kind:'xml',xml:result.xml}]);verifyTableCellTextDirectionResult((await parseDocx(output)).blocks.find(b=>b.type==='table')!,result);const before=await JSZip.loadAsync(bytes),after=await JSZip.loadAsync(output);for(const name of Object.keys(before.files))if(!before.files[name].dir&&name!=='word/document.xml')assert.deepEqual(await before.file(name)!.async('uint8array'),await after.file(name)!.async('uint8array'))}
})
test('merged logical owner updates all physical continuation directions and preserves hidden/nested content',async()=>{
 const nested='<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="100"/></w:tblGrid><w:tr>'+cell('<w:textDirection w:val="btLr"/>')+'</w:tr></w:tbl>'
 const value=xml.replace(/<w:tr>[\s\S]*<\/w:tr>/,`<w:tr>${cell('<w:gridSpan w:val="2"/><w:vMerge w:val="restart"/>',p+nested+p)}</w:tr><w:tr>${cell('<w:gridSpan w:val="2"/><w:vMerge/><w:textDirection w:val="btLrV"/>',p.replace('中文😀','hidden'))}</w:tr>`)
 const{block}=await open(value),result=editTableCellTextDirection(block,[{top:1,left:1,bottom:2,right:2,direction:'tbRl'}]);assert.deepEqual(result.directions,['tbRl']);assert.equal(result.cells[0].bottom,2);assert.ok(result.xml.includes(nested));assert.ok(result.xml.includes('hidden'));assert.equal(mask(result.xml),mask(block.originalXml!));verifyTableCellTextDirectionResult((await open(result.xml)).block,result)
 const clear=editTableCellTextDirection(block,[{top:0,left:0,bottom:2,right:2,direction:'tbRl'},{top:1,left:1,bottom:2,right:2,direction:'lrTb'}]);assert.equal(mask(clear.xml),mask(block.originalXml!));assert.ok(clear.xml.includes(nested));assert.deepEqual(clear.directions,[null]);verifyTableCellTextDirectionResult((await open(clear.xml)).block,clear)
})
test('supports missing tcPr and inherited/default direction without a fixed-dxa capability gate',async()=>{
 const{block}=await open(xml.replace(/<w:tblPr>[\s\S]*?<\/w:tblPr>/,'<w:tblPr><w:tblW w:w="3500" w:type="pct"/></w:tblPr>').replace(/<w:tcPr>[\s\S]*?<\/w:tcPr>/g,''));assert.equal(tableCellTextDirectionAvailability(block).cellTextDirectionEditable,true)
 const result=editTableCellTextDirection(block,[{top:0,left:0,bottom:1,right:2,direction:'tbRl'}]);assert.equal((result.xml.match(/<w:tcPr>/g)??[]).length,2);assert.equal((result.xml.match(/<w:textDirection/g)??[]).length,2);verifyTableCellTextDirectionResult((await open(result.xml)).block,result)
})
test('refuses unknown/duplicate/nested direction or forged model, steps and result',async()=>{
 for(const direction of ['<w:textDirection w:val="unknown"/>','<w:textDirection w:val="tbRl"/><w:textDirection w:val="btLr"/>','<w:shd><w:textDirection w:val="tbRl"/></w:shd>','<w:textDirection w:val="tbRl" w:extra="1"/>','<w:textDirection w:val="tbRl"><w:textDirection w:val="btLr"/></w:textDirection>']){const{block}=await open(xml.replace(/<w:textDirection w:val = 'tbRlV'\/>/,direction));assert.equal(tableCellTextDirectionAvailability(block).cellTextDirectionEditable,false)}
 const{block}=await open();assert.equal(tableCellTextDirectionAvailability({...block,table:{...block.table!,rows:block.table!.rows.map(row=>row.map(c=>({...c,textDirection:undefined})))}}).cellTextDirectionEditable,false)
 assert.throws(()=>editTableCellTextDirection(block,[{top:0,left:0,bottom:1,right:1,direction:'tbRl',xml:'forged'} as any]));assert.throws(()=>verifyTableCellTextDirectionResult(block,editTableCellTextDirection(block,[{top:0,left:0,bottom:1,right:1,direction:'lrTb'}])))
})
test('unselected merged owners retain disagreeing physical continuation direction bytes',async()=>{
 const value=xml.replace(/<w:tr>[\s\S]*<\/w:tr>/,`<w:tr>${cell('<w:vMerge w:val="restart"/><w:textDirection w:val="tbRlV"/>')}${cell()}</w:tr><w:tr>${cell('<w:vMerge/><w:textDirection w:val="btLrV"/>',p.replace('中文😀','hidden'))}${cell()}</w:tr>`)
 const{block}=await open(value),result=editTableCellTextDirection(block,[{top:0,left:1,bottom:2,right:2,direction:'btLr'}]);assert.deepEqual(result.directions,['tbRl','btLr','btLr']);assert.deepEqual(result.physicalDirections,['tbRl','btLr','btLr','btLr']);assert.ok(result.xml.includes('<w:vMerge w:val="restart"/><w:textDirection w:val="tbRlV"/>'));assert.ok(result.xml.includes('<w:vMerge/><w:textDirection w:val="btLrV"/>'));assert.equal(mask(result.xml),mask(block.originalXml!));verifyTableCellTextDirectionResult((await open(result.xml)).block,result)
})
