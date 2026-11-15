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
test('special column names preserve own values and IF branches resolve',async()=>{
 const special=field.replace('&quot;Last Name&quot;','&quot;__proto__&quot;'),bytes=await buildDocx({bodyXml:special+field.replace('&quot;Last Name&quot;','&quot;constructor&quot;')}),hash=(value:Uint8Array)=>createHash('sha256').update(value).digest('hex')
 const output=await patchDocxMailMerge(bytes,{kind:'mailMergeSingle',documentSha256:hash(bytes),fields:['__proto__','constructor'],records:[JSON.parse('{"__proto__":"Ada","constructor":"kept"}')]})
 const xml=await(await JSZip.loadAsync(output)).file('word/document.xml')!.async('string');assert.ok(xml.includes('Ada'));assert.ok(xml.includes('kept'));assert.doesNotMatch(xml,/Object|MERGEFIELD/)
 const control=await buildDocx({bodyXml:field+field.replace('MERGEFIELD &quot;Last Name&quot;','IF 1 = 1 &quot;yes&quot; &quot;no&quot;')})
 const resolved=await patchDocxMailMerge(control,{kind:'mailMergeSingle',documentSha256:hash(control),fields:['Last Name'],records:[{'Last Name':'Ada'}]});const resolvedXml=await(await JSZip.loadAsync(resolved)).file('word/document.xml')!.async('string');assert.match(resolvedXml,/yes/);assert.doesNotMatch(resolvedXml,/OLD|STALE|instrText/)
})
test('table-only templates get a body-level page break before the second table',async()=>{
 const table='<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="9000"/></w:tblGrid><w:tr><w:tc><w:tcPr/>'+field+'</w:tc></w:tr></w:tbl>',bytes=await buildDocx({bodyXml:table}),hash=createHash('sha256').update(bytes).digest('hex')
 const output=await patchDocxMailMerge(bytes,{kind:'mailMergeSingle',documentSha256:hash,fields:['Last Name'],records:[{'Last Name':'Ada'},{'Last Name':'Grace'}]}),xml=await(await JSZip.loadAsync(output)).file('word/document.xml')!.async('string')
 assert.ok(xml.includes('</w:tbl><w:p><w:r><w:br w:type="page"/></w:r></w:p><w:tbl>'))
 assert.equal(xml.split('MERGEFIELD').length,1)
})
test('per-record output is collision-safe DOCX files preserving headers and source identity',async()=>{
 const {buildDocxMailMergeFiles}=await import('../docx-mail-merge.ts')
 const bytes=await buildDocx({bodyXml:field,headerXml:'<w:p><w:r><w:t>Header</w:t></w:r></w:p>'}),documentSha256=createHash('sha256').update(bytes).digest('hex')
 const op={kind:'mailMergeOutput',mode:'perRecord',documentSha256,namePattern:'{Last Name}',fields:['Last Name'],records:[{'Last Name':'A/B'},{'Last Name':'A/B'}]}
 const files=await buildDocxMailMergeFiles(bytes,op)
 assert.deepEqual(files.map(f=>f.name),['A_B.docx','A_B (2).docx'])
 for(const file of files){const zip=await JSZip.loadAsync(file.bytes);assert.match(await zip.file('word/document.xml')!.async('string'),/A\/B/);assert.match(await zip.file('word/header1.xml')!.async('string'),/Header/);assert.ok((await parseDocx(file.bytes)).blocks.length)}
 await assert.rejects(buildDocxMailMergeFiles(bytes,{...op,documentSha256:'0'.repeat(64)}),/source_changed/)
})
test('labels generate Avery gutters and custom A4 cells; envelopes change actual section paper',async()=>{
 const {buildDocxMailMergeFiles}=await import('../docx-mail-merge.ts')
 const bytes=await buildDocx({bodyXml:field}),documentSha256=createHash('sha256').update(bytes).digest('hex'),op={kind:'mailMergeOutput',documentSha256,namePattern:'Last Name',fields:['Last Name'],records:[{'Last Name':'Ada'},{'Last Name':'Grace'}]}
 const [label]=await buildDocxMailMergeFiles(bytes,{...op,mode:'labels',layout:{stock:'avery5160'}}),xml=await(await JSZip.loadAsync(label!.bytes)).file('word/document.xml')!.async('string')
 assert.match(xml,/<w:tbl>/);assert.match(xml,/<w:gridCol w:w="180"\/>/);assert.match(xml,/w:val="1440"/);assert.match(xml,/Ada/);assert.match(xml,/Grace/);assert.doesNotMatch(xml,/MERGEFIELD/);await parseDocx(label!.bytes)
 const [custom]=await buildDocxMailMergeFiles(bytes,{...op,mode:'labels',layout:{stock:'custom',paper:'a4',columns:2,rows:4}}),customXml=await(await JSZip.loadAsync(custom!.bytes)).file('word/document.xml')!.async('string');assert.match(customXml,/w:w="11906"/)
 const envelopes=await buildDocxMailMergeFiles(bytes,{...op,mode:'envelopes',layout:{envelope:'dl'}})
 assert.equal(envelopes.length,2);const envelopeXml=await(await JSZip.loadAsync(envelopes[0]!.bytes)).file('word/document.xml')!.async('string');assert.match(envelopeXml,/<w:pgSz w:w="12472" w:h="6236" w:orient="landscape"\/>/)
 await assert.rejects(buildDocxMailMergeFiles(bytes,{...op,mode:'labels',layout:{stock:'custom',paper:'a4',columns:0,rows:4}}),/layout_invalid/)
 await assert.rejects(buildDocxMailMergeFiles(bytes,{...op,mode:'envelopes',layout:{envelope:'constructor'}}),/layout_invalid/)
})

test('NEXT advances table/body fields and SKIPIF omits an entire matching record',async()=>{
 const hash=(value:Uint8Array)=>createHash('sha256').update(value).digest('hex'),next=field.replace('MERGEFIELD &quot;Last Name&quot;','NEXT'),skip=field.replace('MERGEFIELD &quot;Last Name&quot;','SKIPIF «Last Name» = &quot;Ada&quot;')
 const bytes=await buildDocx({bodyXml:field+next+field}),op={kind:'mailMergeSingle',fields:['Last Name'],records:[{'Last Name':'Ada'},{'Last Name':'Grace'},{'Last Name':'Lin'}]}
 const output=await patchDocxMailMerge(bytes,{...op,documentSha256:hash(bytes)}),xml=await(await JSZip.loadAsync(output)).file('word/document.xml')!.async('string')
 assert.equal(xml.split('Ada').length-1,1);assert.equal(xml.split('Grace').length-1,1);assert.equal(xml.split('Lin').length-1,1);assert.equal(xml.split('w:type="page"').length-1,1);assert.doesNotMatch(xml,/instrText|OLD|STALE/)
 const skipped=await buildDocx({bodyXml:skip+field}),skippedOutput=await patchDocxMailMerge(skipped,{...op,documentSha256:hash(skipped)}),skippedXml=await(await JSZip.loadAsync(skippedOutput)).file('word/document.xml')!.async('string');assert.doesNotMatch(skippedXml,/Ada/);assert.match(skippedXml,/Grace/);assert.equal(skippedXml.split('w:type="page"').length-1,1)
})
test('native export CLI writes independently readable ZIP of DOCX files',async()=>{
 const {mkdtemp,writeFile,readFile,rm}=await import('node:fs/promises'),{tmpdir}=await import('node:os'),{join}=await import('node:path'),{execFile}=await import('node:child_process'),{promisify}=await import('node:util'),run=promisify(execFile)
 const dir=await mkdtemp(join(tmpdir(),'mail-merge-export-'))
 try{
  const bytes=await buildDocx({bodyXml:field}),input=join(dir,'source.docx'),output=join(dir,'result.zip'),request=join(dir,'request.json')
  await writeFile(input,bytes);await writeFile(request,JSON.stringify({kind:'mailMergeOutput',mode:'perRecord',documentSha256:createHash('sha256').update(bytes).digest('hex'),namePattern:'Last Name',fields:['Last Name'],records:[{'Last Name':'Ada'},{'Last Name':'Grace'}]}))
  const result=await run(process.execPath,['--import','tsx','bridge/export-docx-mail-merge.ts','--input',input,'--output',output,'--request',request])
  const info=JSON.parse(result.stdout),archive=await JSZip.loadAsync(await readFile(output));assert.equal(info.format,'zip');assert.deepEqual(info.files.map((f:{name:string})=>f.name),['Ada.docx','Grace.docx'])
  for(const name of ['Ada','Grace']){const parsed=await parseDocx(await archive.file(name+'.docx')!.async('uint8array'));assert.ok(parsed.blocks.some(block=>block.runs?.some(run=>run.text===name)))}
 }finally{await rm(dir,{recursive:true,force:true})}
})
test('labels reject unsupported tables instead of silently losing source content',async()=>{
 const {buildDocxMailMergeFiles}=await import('../docx-mail-merge.ts'),bytes=await buildDocx({bodyXml:'<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="9000"/></w:tblGrid><w:tr><w:tc>'+field+'</w:tc></w:tr></w:tbl>'})
 await assert.rejects(buildDocxMailMergeFiles(bytes,{kind:'mailMergeOutput',mode:'labels',layout:{stock:'avery5160'},documentSha256:createHash('sha256').update(bytes).digest('hex'),namePattern:'',fields:['Last Name'],records:[{'Last Name':'Ada'}]}),/label_content_unsupported/)
})
test('split field instructions and IF-only templates evaluate from the complete instruction',async()=>{
 const hash=(value:Uint8Array)=>createHash('sha256').update(value).digest('hex'),split=field.replace('MERGEFIELD &quot;Last Name&quot;','MERGEFIELD &quot;Last</w:instrText></w:r><w:r><w:instrText> Name&quot;'),op={kind:'mailMergeSingle',fields:['Last Name'],records:[{'Last Name':'Ada'}]}
 const bytes=await buildDocx({bodyXml:split}),output=await patchDocxMailMerge(bytes,{...op,documentSha256:hash(bytes)});assert.match(await(await JSZip.loadAsync(output)).file('word/document.xml')!.async('string'),/Ada/)
 const onlyIf=await buildDocx({bodyXml:field.replace('MERGEFIELD &quot;Last Name&quot;','IF «Last Name» = &quot;Ada&quot; &quot;Hello&quot; &quot;Bye&quot;')}),resolved=await patchDocxMailMerge(onlyIf,{...op,documentSha256:hash(onlyIf)});assert.match(await(await JSZip.loadAsync(resolved)).file('word/document.xml')!.async('string'),/Hello/)
})
test('envelope layout preserves section child order and header/footer distances',async()=>{
 const {buildDocxMailMergeFiles}=await import('../docx-mail-merge.ts'),bytes=await buildDocx({bodyXml:field,sectPrXml:'<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="360" w:gutter="90"/><w:cols w:space="720"/><w:docGrid w:linePitch="360"/></w:sectPr>'})
 const [file]=await buildDocxMailMergeFiles(bytes,{kind:'mailMergeOutput',mode:'envelopes',layout:{envelope:'c6'},documentSha256:createHash('sha256').update(bytes).digest('hex'),namePattern:'',fields:['Last Name'],records:[{'Last Name':'Ada'}]}),xml=await(await JSZip.loadAsync(file!.bytes)).file('word/document.xml')!.async('string')
 assert.ok(xml.indexOf('<w:pgSz')<xml.indexOf('<w:pgMar'));assert.ok(xml.indexOf('<w:pgMar')<xml.indexOf('<w:cols'));assert.match(xml,/w:header="720"/);assert.match(xml,/w:footer="360"/);assert.match(xml,/w:gutter="90"/)
})
test('native simple MERGEFIELD and IF forms substitute without leaving live fields',async()=>{
 const bytes=await buildDocx({bodyXml:'<w:p><w:fldSimple w:instr=" MERGEFIELD &quot;Last Name&quot; "><w:r><w:rPr><w:b/></w:rPr><w:t>OLD</w:t></w:r></w:fldSimple><w:fldSimple w:instr=" IF «Last Name» = &quot;Ada&quot; &quot; yes&quot; &quot; no&quot; "><w:r><w:t>STALE</w:t></w:r></w:fldSimple></w:p>'})
 const output=await patchDocxMailMerge(bytes,{kind:'mailMergeSingle',documentSha256:createHash('sha256').update(bytes).digest('hex'),fields:['Last Name'],records:[{'Last Name':'Ada'}]}),xml=await(await JSZip.loadAsync(output)).file('word/document.xml')!.async('string')
 assert.match(xml,/Ada/);assert.match(xml,/ yes/);assert.doesNotMatch(xml,/fldSimple|instrText|OLD|STALE/);assert.match(xml,/<w:b\/>/)
})
test('file-per-recipient modes reject cursor controls rather than silently blanking later fields',async()=>{
 const {buildDocxMailMergeFiles}=await import('../docx-mail-merge.ts'),bytes=await buildDocx({bodyXml:field+field.replace('MERGEFIELD &quot;Last Name&quot;','NEXT')+field})
 await assert.rejects(buildDocxMailMergeFiles(bytes,{kind:'mailMergeOutput',mode:'perRecord',documentSha256:createHash('sha256').update(bytes).digest('hex'),namePattern:'',fields:['Last Name'],records:[{'Last Name':'Ada'}]}),/control_output_mode_unsupported/)
})
