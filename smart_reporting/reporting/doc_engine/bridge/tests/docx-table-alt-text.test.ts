import assert from 'node:assert/strict'
import {test} from 'node:test'
import JSZip from 'jszip'
import {XMLParser} from 'fast-xml-parser'
import {parseDocx,saveDocx} from '../../packages/docx-engine/src/index.ts'
import {buildDocx} from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import {tableAltTextAvailability,editTableAltText,verifyTableAltTextResult} from '../docx-table-alt-text.ts'
const cell=(t:string,merge:string)=>`<w:tc><w:tcPr>${merge}<w:tcFitText/><w:noWrap w:val="false"/></w:tcPr><w:p w:rsidR="AABB"><w:r><w:t>${t}</w:t></w:r></w:p></w:tc>`
const xml='<w:tbl><w:tblPr><w:bidiVisual/><w:tblW w:w="2500" w:type="pct"/><w:tblInd w:w="-109"/><w:tblLook w:val="04A0"/><w:tblCaption w:val="old"></w:tblCaption><w:tblDescription w:val="old desc"/><w:custom w:val="keep"/></w:tblPr><w:tblGrid><w:gridCol w:w="2001"/></w:tblGrid><w:tr>'+cell('owner','<w:vMerge w:val="restart"/>')+'</w:tr><w:tr>'+cell('hidden','<w:vMerge/>')+'</w:tr></w:tbl>'
const open=async(value=xml)=>{const bytes=await buildDocx({bodyXml:value}),parsed=await parseDocx(bytes);return{bytes,parsed,block:parsed.blocks.find(b=>b.type==='table')!}}
const mask=(s:string)=>s.replace(/<w:tbl(?:Caption|Description)\b[^>]*\/>|<w:tbl(?:Caption|Description)\b[^>]*>[\s\S]*?<\/w:tbl(?:Caption|Description)>/g,'')
test('changes only both direct alt tags, preserves hidden cells and package parts, encodes whitespace references',async()=>{
 const{bytes,parsed,block}=await open();assert.equal(tableAltTextAvailability(block).tableAltTextEditable,true)
 const value={title:' 中文 & <标题> "A" ',description:'第一行\n第二行\r\n\t&B'},result=editTableAltText(block,value)
 assert.equal(mask(result.xml),mask(block.originalXml!));assert.ok(result.xml.includes('&#10;'));assert.ok(result.xml.includes('&#13;'));assert.ok(result.xml.includes('&#9;'))
 const output=await saveDocx(parsed,[{kind:'xml',docxIndex:block.docxIndex!,xml:result.xml}]),reopened=(await parseDocx(output)).blocks.find(b=>b.type==='table')!;verifyTableAltTextResult(reopened,result)
 assert.equal(tableAltTextAvailability(reopened).tableAltTextSource!.title,value.title.trim());assert.equal(tableAltTextAvailability(reopened).tableAltTextSource!.description,value.description)
 const independent=new XMLParser({ignoreAttributes:false,attributeNamePrefix:'',parseAttributeValue:false,htmlEntities:true}).parse(result.xml);assert.equal(independent['w:tbl']['w:tblPr']['w:tblDescription']['w:val'],value.description)
 const a=await JSZip.loadAsync(bytes),b=await JSZip.loadAsync(output);for(const n of Object.keys(a.files))if(!a.files[n].dir&&n!=='word/document.xml')assert.deepEqual(await a.file(n)!.async('uint8array'),await b.file(n)!.async('uint8array'))
 const clear=editTableAltText(block,{title:' ',description:'\n'});assert.equal(mask(clear.xml),clear.xml);assert.equal(mask(clear.xml),mask(block.originalXml!))
})
test('creates schema ordered tags with missing or selfclosing properties and inserts before property revision boundary',async()=>{
 for(const pr of ['', '<w:tblPr/>','<w:tblPr><w:tblLook w:val="04A0"/><w:custom/></w:tblPr>']){
  const{block}=await open(xml.replace(/<w:tblPr>[\s\S]*?<\/w:tblPr>/,pr)),r=editTableAltText(block,{title:'a',description:'b'})
  assert.ok(r.xml.includes('<w:tblCaption w:val="a"/><w:tblDescription w:val="b"/>'));verifyTableAltTextResult((await open(r.xml)).block,r)
 }
})
test('refuses ambiguous raw, revisions namespaces forged parser values and invalid payload before producing XML',async()=>{
 for(const tag of ['<w:tblCaption/>','<w:tblCaption w:val="a" w:x="1"/>','<w:tblCaption w:val="a"><w:x/></w:tblCaption>','<w:tblCaption w:val="a"/><w:tblCaption w:val="b"/>'])assert.equal(tableAltTextAvailability((await open(xml.replace('<w:tblCaption w:val="old"></w:tblCaption>',tag))).block).tableAltTextEditable,false)
 assert.equal(tableAltTextAvailability((await open(xml.replace('</w:tblPr>','<w:tblPrChange/></w:tblPr>'))).block).tableAltTextEditable,false)
 const{block}=await open();assert.equal(tableAltTextAvailability({...block,table:{...block.table!,caption:'forged'}}).tableAltTextEditable,false)
 assert.throws(()=>editTableAltText(block,{title:'a',description:'bad\u0001'}));assert.throws(()=>verifyTableAltTextResult(block,editTableAltText(block,{title:'a',description:'b'})))
})

test('literal numeric-looking user text stays literal after XML save and both parsers',async()=>{
 const{block,parsed}=await open(),value={title:'literal &#10;',description:'&#xA; &lt; literal'},r=editTableAltText(block,value),read=(await parseDocx(await saveDocx(parsed,[{kind:'xml',docxIndex:block.docxIndex!,xml:r.xml}]))).blocks.find(b=>b.type==='table')!
 verifyTableAltTextResult(read,r);assert.equal(read.table!.caption,value.title);assert.equal(read.table!.description,value.description)
})
