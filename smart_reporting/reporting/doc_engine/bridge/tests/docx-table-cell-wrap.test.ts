import assert from 'node:assert/strict'
import {test} from 'node:test'
import JSZip from 'jszip'
import {parseDocx,saveDocx} from '../../packages/docx-engine/src/index.ts'
import {buildDocx} from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import {tableCellWrapAvailability,editTableCellWrap,verifyTableCellWrapResult} from '../docx-table-cell-wrap.ts'
const cell=(text:string,pr='')=>`<w:tc><w:tcPr><w:tcW w:w="2000" w:type="dxa"/>${pr}<w:tcFitText/><w:textDirection w:val="tbRl"/><w:unknown w:val="keep"/></w:tcPr><w:p w:rsidR="AABB"><w:r><w:t>${text}</w:t></w:r></w:p></w:tc>`
const xml='<w:tbl><w:tblPr><w:bidiVisual/></w:tblPr><w:tblGrid><w:gridCol w:w="2000"/><w:gridCol w:w="2000"/></w:tblGrid><w:tr>'+cell('owner','<w:vMerge w:val="restart"/><w:noWrap></w:noWrap>')+cell('other')+'</w:tr><w:tr>'+cell('hidden','<w:vMerge/><w:noWrap w:val="false"/>')+cell('last')+'</w:tr></w:tbl>'
const open=async(value=xml)=>{const bytes=await buildDocx({bodyXml:value});const parsed=await parseDocx(bytes);return{bytes,parsed,block:parsed.blocks.find(b=>b.type==='table')!}}
const step={top:1,left:0,bottom:2,right:1,wrap:true},mask=(s:string)=>s.replace(/<w:noWrap\b[^>]*\/>|<w:noWrap\b[^>]*>[\s\S]*?<\/w:noWrap>/g,'')
test('signed direct source distinguishes owner raw and hidden physical declarations',async()=>{const{block,parsed}=await open(),a=tableCellWrapAvailability(block,parsed);assert.equal(a.tableCellWrapEditable,true);assert.deepEqual(a.tableCellWrapSource!.cells[0],{top:0,left:0,bottom:2,right:1,rawPresent:true,hasPhysicalNoWrap:true,raw:'<w:noWrap></w:noWrap>',noWrap:true,resetNoWrap:false})})
test('ordered edits preserve hidden content tcFitText unknown siblings and every other ZIP part',async()=>{const{block,parsed,bytes}=await open(),r=editTableCellWrap(block,[{...step,wrap:false},step],parsed);assert.equal(mask(r.xml),mask(block.originalXml!));assert.ok(r.xml.includes('hidden'));assert.equal((r.xml.match(/<w:tcFitText/g)||[]).length,4);const out=await saveDocx(parsed,[{kind:'xml',docxIndex:block.docxIndex,xml:r.xml}]),reopen=await parseDocx(out);verifyTableCellWrapResult(reopen.blocks.find(b=>b.type==='table')!,r);const a=await JSZip.loadAsync(bytes),b=await JSZip.loadAsync(out);for(const n of Object.keys(a.files))if(!a.files[n].dir&&n!=='word/document.xml')assert.deepEqual(await a.file(n)!.async('uint8array'),await b.file(n)!.async('uint8array'))})
test('false values canonicalize, absent props insert before tcFitText and malformed declarations refuse atomically',async()=>{for(const value of ['0','false','off','none','1','true','on']){const{block,parsed}=await open(xml.replace('<w:noWrap></w:noWrap>',`<w:noWrap w:val="${value}"/>`));assert.equal(tableCellWrapAvailability(block,parsed).tableCellWrapEditable,true);const r=editTableCellWrap(block,[{...step,wrap:false}],parsed);assert.equal((r.xml.match(/<w:noWrap\/>/g)||[]).length,2)}for(const value of ['<w:noWrap w:val="maybe"/>','<w:noWrap w:extra="1"/>','<w:noWrap><w:x/></w:noWrap>','<w:noWrap/><w:noWrap/>']){const{block,parsed}=await open(xml.replace('<w:noWrap></w:noWrap>',value));assert.equal(tableCellWrapAvailability(block,parsed).tableCellWrapEditable,false)}const{block,parsed}=await open();assert.throws(()=>editTableCellWrap(block,[step,{...step,bottom:3}],parsed));assert.throws(()=>editTableCellWrap({...block},[step],parsed))})
test('canonical insertion handles absent/self-closing tcPr and preserves schema order',async()=>{
 for(const container of ['', '<w:tcPr/>']){
  const input=xml.replace(/<w:tcPr>[\s\S]*?<\/w:tcPr>/g,container),{block,parsed}=await open(input)
  const r=editTableCellWrap(block,[{top:0,left:1,bottom:1,right:2,wrap:false}],parsed)
  assert.ok(r.xml.includes('<w:tcPr><w:noWrap/></w:tcPr>'));verifyTableCellWrapResult((await open(r.xml)).block,r)
 }
 const{block,parsed}=await open(),r=editTableCellWrap(block,[{top:0,left:1,bottom:1,right:2,wrap:false}],parsed)
 assert.ok(r.xml.includes('<w:noWrap/><w:tcFitText/>'));assert.equal(mask(r.xml),mask(block.originalXml!))
})
test('owner absent but hidden continuation declaration is represented and cleared; final verification detects non-target tamper',async()=>{
 const{block,parsed}=await open(xml.replace('<w:noWrap></w:noWrap>','')),cap=tableCellWrapAvailability(block,parsed),owner=cap.tableCellWrapSource!.cells[0]
 assert.equal(owner.rawPresent,false);assert.equal(owner.noWrap,false);assert.equal(owner.hasPhysicalNoWrap,true)
 const result=editTableCellWrap(block,[step],parsed);assert.equal(result.xml.includes('<w:noWrap'),false);assert.equal(mask(result.xml),mask(block.originalXml!));verifyTableCellWrapResult((await open(result.xml)).block,result)
 assert.throws(()=>verifyTableCellWrapResult((block),{...result,xml:result.xml.replace('hidden','changed')}))
})
