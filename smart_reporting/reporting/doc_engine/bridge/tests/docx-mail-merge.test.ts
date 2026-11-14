import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createHash} from 'node:crypto'
import JSZip from 'jszip'
import {buildDocx} from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import {patchDocxMailMerge} from '../docx-mail-merge.ts'
import {parseDocx} from '../../packages/docx-engine/src/parse.ts'
const field='<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> MERGEFIELD &quot;Last Name&quot; </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:rPr><w:b/></w:rPr><w:t>OLD</w:t></w:r><w:r><w:t>STALE</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
test('quoted fields clear stale runs, escape values and preserve parts',async()=>{
 const bytes=await buildDocx({bodyXml:field,headerXml:'<w:p><w:r><w:t>Header</w:t></w:r></w:p>'}),documentSha256=createHash('sha256').update(bytes).digest('hex')
 const op={kind:'mailMergeSingle',documentSha256,fields:['Last Name'],records:[{'Last Name':'Ada & <A>'},{'Last Name':''}]}
 const output=await patchDocxMailMerge(bytes,op),zip=await JSZip.loadAsync(output),xml=await zip.file('word/document.xml')!.async('string'),original=await JSZip.loadAsync(bytes)
 assert.ok(xml.includes('Ada &amp; &lt;A&gt;'));assert.doesNotMatch(xml,/OLD|STALE|MERGEFIELD|fldChar/);assert.equal(xml.split('<w:br w:type="page"/>').length-1,1);assert.equal(xml.split('<w:sectPr').length-1,1);assert.ok(xml.includes('<w:b/>'))
 for(const file of Object.values(original.files))if(!file.dir&&file.name!=='word/document.xml')assert.deepEqual(await zip.file(file.name)!.async('uint8array'),await file.async('uint8array'))
 await assert.rejects(patchDocxMailMerge(bytes,{...op,documentSha256:'0'.repeat(64)}),/source_changed/)
 await assert.rejects(patchDocxMailMerge(bytes,{...op,fields:['Missing']}),/source_invalid|field_source_missing/)
})
test('inserts a native MERGEFIELD in a source-bound paragraph and independently reads it',async()=>{
 const bytes=await buildDocx({bodyXml:'<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Hello World</w:t></w:r></w:p>'}),parsed=await parseDocx(bytes),block=parsed.blocks[0]!,hash=(value:string|Uint8Array)=>createHash('sha256').update(value).digest('hex')
 const op={kind:'insertMailMergeField',documentSha256:hash(bytes),docxIndex:block.docxIndex,expectedObjectSha256:hash(block.originalXml!),offset:6,name:'Last Name'}
 const output=await patchDocxMailMerge(bytes,op),read=await parseDocx(output)
 assert.equal(read.blocks[0]!.runs!.map(run=>run.text).join(''),'Hello «Last Name»World')
 assert.ok(read.blocks[0]!.runs!.some(run=>run.instrField?.includes('"Last Name"')))
 await assert.rejects(patchDocxMailMerge(bytes,{...op,name:'Bad"Name'}),/field_name_invalid/)
 const merged=await patchDocxMailMerge(output,{kind:'mailMergeSingle',documentSha256:hash(output),fields:['Last Name'],records:[{'Last Name':'Ada'},{'Last Name':'Grace'}]})
 const letters=(await parseDocx(merged)).blocks.map(b=>b.runs?.map(r=>r.text).join(''))
 assert.ok(letters.includes('Hello AdaWorld'));assert.ok(letters.includes('Hello GraceWorld'))
})
test('special column names preserve own values and control templates are rejected',async()=>{
 const special=field.replace('&quot;Last Name&quot;','&quot;__proto__&quot;'),bytes=await buildDocx({bodyXml:special+field.replace('&quot;Last Name&quot;','&quot;constructor&quot;')}),hash=(value:Uint8Array)=>createHash('sha256').update(value).digest('hex')
 const output=await patchDocxMailMerge(bytes,{kind:'mailMergeSingle',documentSha256:hash(bytes),fields:['__proto__','constructor'],records:[JSON.parse('{"__proto__":"Ada","constructor":"kept"}')]})
 const xml=await(await JSZip.loadAsync(output)).file('word/document.xml')!.async('string');assert.ok(xml.includes('Ada'));assert.ok(xml.includes('kept'));assert.doesNotMatch(xml,/Object|MERGEFIELD/)
 const control=await buildDocx({bodyXml:field+field.replace('MERGEFIELD &quot;Last Name&quot;','IF 1 = 1 &quot;yes&quot; &quot;no&quot;')})
 await assert.rejects(patchDocxMailMerge(control,{kind:'mailMergeSingle',documentSha256:hash(control),fields:['Last Name'],records:[{'Last Name':'Ada'}]}),/control_field_unsupported/)
})
test('table-only templates get a body-level page break before the second table',async()=>{
 const table='<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="9000"/></w:tblGrid><w:tr><w:tc><w:tcPr/>'+field+'</w:tc></w:tr></w:tbl>',bytes=await buildDocx({bodyXml:table}),hash=createHash('sha256').update(bytes).digest('hex')
 const output=await patchDocxMailMerge(bytes,{kind:'mailMergeSingle',documentSha256:hash,fields:['Last Name'],records:[{'Last Name':'Ada'},{'Last Name':'Grace'}]}),xml=await(await JSZip.loadAsync(output)).file('word/document.xml')!.async('string')
 assert.ok(xml.includes('</w:tbl><w:p><w:r><w:br w:type="page"/></w:r></w:p><w:tbl>'))
 assert.equal(xml.split('MERGEFIELD').length,1)
})
