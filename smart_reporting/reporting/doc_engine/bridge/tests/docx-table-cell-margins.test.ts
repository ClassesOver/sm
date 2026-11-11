import assert from 'node:assert/strict'
import {test} from 'node:test'
import JSZip from 'jszip'
import {parseDocx,saveDocx} from '../../packages/docx-engine/src/index.ts'
import {buildDocx} from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import {tableModelToPmNode} from '../../../../report_editor/frontend/src/vendor/genoffice-docs/apps/docs/src/renderer/editor/convert.ts'
import {tableCellMarginsAvailability,editTableCellMargins,verifyTableCellMarginsResult} from '../docx-table-cell-margins.ts'
const p='<w:p w:rsidR="AABBCCDD"><w:pPr><w:keepNext/></w:pPr><w:r><w:t>原文😀</w:t></w:r></w:p>'
const cell=(pr='',body=p)=>`<w:tc><w:tcPr><w:tcW w:w="2001" w:type="dxa"/>${pr}</w:tcPr>${body}</w:tc>`
const xml=`<w:tbl><w:tblPr><w:tblStyle w:val="Margins"/><w:bidiVisual/><w:tblCellMar><w:left w:w='108' w:type="dxa"/></w:tblCellMar><w:tblLook w:firstRow="1"/><w:tblCaption w:val="opaque"/></w:tblPr><w:tblGrid><w:gridCol w:w="2001"/><w:gridCol w:w="1999"/></w:tblGrid><w:tr><w:tblPrEx><w:tblCellMar><w:bottom w:w="17" w:type="dxa"/></w:tblCellMar></w:tblPrEx>${cell('<w:vMerge w:val="restart"/><w:tcMar><w:right w:w="0" w:type="dxa"/></w:tcMar>')}${cell()}</w:tr><w:tr>${cell('<w:vMerge/><w:tcMar><w:left w:w="71" w:type="dxa"/></w:tcMar>',p.replace('原文','hidden'))}${cell()}</w:tr></w:tbl>`
const style='<w:style w:type="table" w:styleId="Margins"><w:name w:val="Margins"/><w:tblPr><w:tblCellMar><w:top w:w="13" w:type="dxa"/><w:right w:w="109" w:type="dxa"/></w:tblCellMar></w:tblPr><w:tblStylePr w:type="firstRow"><w:tcPr><w:tcMar><w:left w:w="41" w:type="dxa"/></w:tcMar></w:tcPr></w:tblStylePr></w:style>'
const open=async(value=xml)=>{const bytes=await buildDocx({bodyXml:value,extraStylesXml:style});const parsed=await parseDocx(bytes);return{bytes,parsed,block:parsed.blocks.find(b=>b.type==='table')!}}
const margins={top:0,right:130,bottom:96,left:176}
test('real styled RTL/row-exception/merged DOCX edits only defaults; converter matches reopened cell semantics',async()=>{
 const{bytes,parsed,block}=await open(),cap=tableCellMarginsAvailability(block);assert.equal(cap.tableCellMarginsEditable,true)
 const before=tableModelToPmNode(block.table!,block.docxIndex),result=editTableCellMargins(block,margins)
 const mask=(value:string)=>value.replace(/<w:tblCellMar>[\s\S]*?<\/w:tblCellMar>/,'')
 assert.equal(mask(result.xml),mask(block.originalXml!));assert.ok(result.xml.includes('hidden'))
 const output=await saveDocx(parsed,[{kind:'xml',xml:result.xml}]),reopened=(await parseDocx(output)).blocks.find(b=>b.type==='table')!
 verifyTableCellMarginsResult(reopened,result)
 const after=tableModelToPmNode(reopened.table!,reopened.docxIndex),cells=(t:any)=>t.content.flatMap((r:any)=>r.content.map((c:any)=>c.attrs.cellMar))
 assert.deepEqual(after.attrs!.cellMar,margins);assert.deepEqual(cells(after),cells(before));assert.deepEqual(cap.tableCellMarginsSource!.cells,cells(before))
 const a=await JSZip.loadAsync(bytes),b=await JSZip.loadAsync(output)
 for(const name of Object.keys(a.files))if(!a.files[name].dir&&name!=='word/document.xml')assert.deepEqual(await a.file(name)!.async('uint8array'),await b.file(name)!.async('uint8array'))
})
test('inserts missing/selfclosing containers in schema order, preserves zero and rejects malformed inputs',async()=>{
 for(const pr of ['', '<w:tblPr/>','<w:tblPr><w:tblLook w:firstRow="1"/></w:tblPr>']){const{block}=await open(xml.replace(/<w:tblPr>[\s\S]*?<\/w:tblPr>/,pr));const result=editTableCellMargins(block,{top:0,right:0,bottom:0,left:0});if(pr.includes('tblLook'))assert.ok(result.xml.indexOf('<w:tblCellMar>')<result.xml.indexOf('<w:tblLook'));verifyTableCellMarginsResult((await open(result.xml)).block,result)}
 const{block}=await open();for(const bad of [{...margins,left:-1},{...margins,left:28351},{...margins,left:0.2},{top:0},{...margins,xml:'fake'}])assert.throws(()=>editTableCellMargins(block,bad as any))
})
test('refuses ambiguous default margin controls and forged verification',async()=>{
 for(const control of ['<w:left w:w="1"/><w:left w:w="2"/>','<w:left w:w="1" w:type="pct"/>','<w:left w:w="1" w:unknown="1"/>','<w:unknown><w:left w:w="1"/></w:unknown>','<w:start w:w="1"/><w:left w:w="2"/>'])assert.equal(tableCellMarginsAvailability((await open(xml.replace(/<w:tblCellMar>[\s\S]*?<\/w:tblCellMar>/,`<w:tblCellMar>${control}</w:tblCellMar>`))).block).tableCellMarginsEditable,false)
 const{block}=await open();assert.throws(()=>verifyTableCellMarginsResult(block,editTableCellMargins(block,margins)))
})
test('single start/end aliases and opaque cell XML remain preserved outside the default target',async()=>{
 const value=xml.replace("<w:left w:w='108' w:type=\"dxa\"/>",'<w:start w:w="108"/><w:end w:w="109"/>').replace('<w:tcW w:w="2001" w:type="dxa"/>','<w:tcW w:w="2001" w:type="dxa"/><w:unknown w:val="opaque"/>')
 const{block}=await open(value),cap=tableCellMarginsAvailability(block)
 assert.equal(cap.tableCellMarginsEditable,true);assert.deepEqual(cap.tableCellMarginsSource!.defaults,{right:109,left:108})
 const result=editTableCellMargins(block,margins);assert.ok(result.xml.includes('<w:unknown w:val="opaque"/>'));verifyTableCellMarginsResult((await open(result.xml)).block,result)
})
test('default revisions, duplicate containers, namespaces and forged parsed defaults cannot be issued as safe',async()=>{
 const values=[xml.replace('</w:tblPr>','<w:tblPrChange w:id="1"><w:tblPr/></w:tblPrChange></w:tblPr>'),xml.replace('</w:tblPr>','<w:tblCellMar/></w:tblPr>'),xml.replace('<w:tblPr>','<w:tblPr w:unknown="1">'),xml.replace('<w:tblPr>','<w:tblPr xmlns:x="urn:foreign">')]
 for(const value of values)assert.equal(tableCellMarginsAvailability((await open(value)).block).tableCellMarginsEditable,false)
 const{block}=await open();assert.equal(tableCellMarginsAvailability({...block,table:{...block.table!,cellMarTwips:{left:999}}}).tableCellMarginsEditable,false)
})
test('single quoted unknown table-property sibling stays byte-identical while target defaults change',async()=>{
 const opaque="<w:custom w:value='opaque &gt; value'><w:child w:val='kept'/></w:custom>",value=xml.replace('<w:tblCaption w:val="opaque"/>',opaque)
 const{block}=await open(value);assert.equal(tableCellMarginsAvailability(block).tableCellMarginsEditable,true)
 const result=editTableCellMargins(block,margins);assert.ok(result.xml.includes(opaque));verifyTableCellMarginsResult((await open(result.xml)).block,result)
})
