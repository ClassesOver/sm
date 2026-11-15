import {test} from 'node:test'
import assert from 'node:assert/strict'
import JSZip from 'jszip'
import {parseDocx,saveDocx} from '../packages/docx-engine/src/index'
import {buildDocx} from '../packages/docx-engine/tests/helpers/build-docx'
import {editTableStyle,tableStyleAvailability,verifyTableStyleResult} from './docx-table-style'
import {normalizeTableStylePatch,DEFAULT_TABLE_LOOK} from '../../../report_editor/frontend/src/docx-table-style-core'
const cell='<w:tc><w:tcPr>\n<w:tcW w:w="1111"/> <!-- keep -->\n<w:shd w:fill="ABCDEF"/><w:noWrap/><w:tcMar><w:left w:w="45"/></w:tcMar></w:tcPr><w:p><w:r><w:t>Keep</w:t></w:r></w:p></w:tc>'
const table=`<w:tbl><w:tblPr>\n<w:tblW w:w="2222" w:type="dxa"/> <!-- keep table -->\n<w:tblCaption w:val="Caption"/></w:tblPr><w:tr>${cell}</w:tr></w:tbl>`
test('strict runtime validator rejects conflicting preset identity and prototype-bearing values',()=>{
 assert.throws(()=>normalizeTableStylePatch({style:{kind:'preset',id:'grid'},preset:'green-header'}))
 assert.throws(()=>normalizeTableStylePatch(JSON.parse('{"look":{"__proto__":true}}')))
 assert.throws(()=>normalizeTableStylePatch({look:Object.create(DEFAULT_TABLE_LOOK)}))
})
test('source writer patch keeps comments, widths, margins and body; inserts cell borders/shading in schema order',async()=>{
 const parsed=await parseDocx(await buildDocx({bodyXml:table})),block=parsed.blocks[0]
 assert.equal(tableStyleAvailability(block,parsed).tableStyleEditable,true)
 const result=editTableStyle(block,{style:{kind:'preset',id:'green-header'},look:DEFAULT_TABLE_LOOK},parsed)
 assert.ok(result.xml.includes('<!-- keep -->'));assert.ok(result.xml.includes('<!-- keep table -->'));assert.ok(result.xml.includes('<w:tcW w:w="1111"/>'));assert.ok(result.xml.includes('<w:left w:w="45"/>'))
 assert.ok(result.xml.indexOf('<w:tcBorders>')>result.xml.indexOf('<w:tcW'))
 assert.ok(result.xml.indexOf('<w:tcBorders>')<result.xml.indexOf('<w:shd'))
 assert.ok(result.xml.indexOf('<w:shd')<result.xml.indexOf('<w:noWrap'))
 const saved=await saveDocx(parsed,[{kind:'xml',docxIndex:0,xml:result.xml}])
 // Source saveDocx appends raw comments a second time; the native bridge uses exact original-body replacement.
 const zip=await JSZip.loadAsync(saved);assert.ok(parsed.internal.documentXml.includes(block.originalXml!));zip.file('word/document.xml',parsed.internal.documentXml.replace(block.originalXml!,result.xml))
 const surgical=await zip.generateAsync({type:'uint8array'});verifyTableStyleResult((await parseDocx(surgical)).blocks[0],result)
})
test('table without properties stays byte identical on no style and gets properties before rows on look edits',async()=>{
 const xml='<w:tbl><w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl>',parsed=await parseDocx(await buildDocx({bodyXml:xml})),block=parsed.blocks[0]
 assert.equal(editTableStyle(block,{style:{kind:'none'}},parsed).xml,xml)
 const result=editTableStyle(block,{look:{...DEFAULT_TABLE_LOOK,firstRow:false}},parsed)
 assert.match(result.xml,/^<w:tbl><w:tblPr>/)
 verifyTableStyleResult((await parseDocx(await saveDocx(parsed,[{kind:'xml',docxIndex:0,xml:result.xml}]))).blocks[0],result)
})
