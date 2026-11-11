import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createHash} from 'node:crypto'
import {mkdtemp,writeFile,rm} from 'node:fs/promises'
import {spawnSync} from 'node:child_process'
import {tmpdir} from 'node:os'
import {join,resolve} from 'node:path'
import {PDFDocument} from 'pdf-lib'
import {inspectNativeText} from './text-operations'
import {loadPdfium,inspectTextObjects} from '../src/main/text-edit'
import {replacementMetrics} from './replace-text-layout'
import {replaceStyledText} from './replace-text-style'
const hash=(value:Uint8Array)=>createHash('sha256').update(value).digest('hex')
async function fixture(){const pdf=await PDFDocument.create(),page=pdf.addPage([500,500]);page.drawText('Original target',{x:250,y:350,size:14});page.drawText('Untouched neighbor',{x:50,y:450,size:12});return pdf.save()}
async function operation(bytes:Uint8Array,extra={}){const sourceSha256=hash(bytes),objects=await inspectNativeText(bytes,sourceSha256),target=objects[0]!.find(item=>item.text==='Original target')!;return {kind:'replaceText' as const,sourceSha256,pageId:'sha256:'+sourceSha256+':page:0',objectId:target.objectId,expectedTextSha256:target.expectedTextSha256,newText:'Styled first\n\nSecond',font:'times' as const,bold:true,italic:true,fontSize:18,color:[.2,.4,.6] as [number,number,number],align:'right' as const,lineLeading:24,...extra}}
test('styled replacement uses source identity and native multiline face alignment',async()=>{
 const bytes=await fixture(),op=await operation(bytes),result=await replaceStyledText(bytes,[op],hash(bytes))
 assert.deepEqual(result.skippedOperations,[]);assert.deepEqual(result.appliedOperationIndices,[0]);assert.equal(result.sha256,hash(result.bytes))
 const after=(await inspectTextObjects(result.bytes))[0]!
 assert.ok(after.some(item=>item.text==='Untouched neighbor'));assert.ok(!after.some(item=>item.text==='Original target'))
 const added=after.filter(item=>item.text!=='Untouched neighbor')
 assert.deepEqual(added.map(item=>item.text),['Styled first','Second']);assert.ok(added.every(item=>item.fontSize===18&&/LiberationSerif-BoldItalic/.test(item.fontName)))
 const metrics=await replacementMetrics(result.bytes,0,added);assert.ok(Math.abs(metrics[0]!.matrix[5]-metrics[1]!.matrix[5]-48)<.01)
 assert.equal((await replaceStyledText(bytes,[op],hash(bytes))).previewDigest,result.previewDigest)
})
test('styled replacement output overflow is an honest warning retaining actual generated text',async()=>{
 const bytes=await fixture(),op=await operation(bytes,{newText:'Very long replacement '.repeat(20),align:'left' as const})
 const result=await replaceStyledText(bytes,[op],hash(bytes))
 assert.notEqual(result.sha256,hash(bytes));assert.equal(result.sha256,hash(result.bytes));assert.deepEqual(result.appliedOperationIndices,[])
 assert.match(result.skippedOperations[0]!.reason,/overflow/);assert.ok((await inspectTextObjects(result.bytes))[0]!.some(item=>item.text.includes('Very long replacement')))
})
test('styled batch resolves all objects against one immutable source and preserves unrelated text',async()=>{
 const pdf=await PDFDocument.load(await fixture());pdf.getPage(0).drawText('Other target',{x:250,y:180,size:14});const bytes=await pdf.save(),op=await operation(bytes),objects=(await inspectNativeText(bytes,hash(bytes)))[0]!,target=objects.find(item=>item.text==='Other target')!
 const other={...op,objectId:target.objectId,expectedTextSha256:target.expectedTextSha256,newText:'Batch two',font:'arial' as const,align:'center' as const}
 const result=await replaceStyledText(bytes,[op,other],hash(bytes))
 assert.deepEqual(result.skippedOperations,[]);assert.deepEqual(result.appliedOperationIndices,[0,1])
 assert.equal((await inspectTextObjects(result.bytes))[0]!.filter(item=>item.text==='Untouched neighbor').length,1)
 const duplicate=await replaceStyledText(bytes,[op,op],hash(bytes));assert.ok(duplicate.skippedOperations.some(item=>item.operationIndex===1&&/repeated/.test(item.reason)))
 for(const patch of [{objectId:'stale'},{expectedTextSha256:'0'.repeat(64)},{pageId:'foreign'}]){const r=await replaceStyledText(bytes,[{...op,...patch}],hash(bytes));assert.equal(r.sha256,hash(bytes));assert.match(r.skippedOperations[0]!.reason,/identity/)}
 await assert.rejects(replaceStyledText(bytes,[{...op,sourceSha256:'0'.repeat(64)}],hash(bytes)))
 await assert.rejects(replaceStyledText(bytes,[op], '0'.repeat(64)))
})
test('native matcher edits an exclusive Form but refuses shared template mutation',async()=>{
 for(const shared of [false,true]){
  const source=await fixture(),pdf=await PDFDocument.create(),[embedded]=await pdf.embedPdf(source),page=pdf.addPage([1000,500]);page.drawPage(embedded!,{x:0,y:0});if(shared)page.drawPage(embedded!,{x:500,y:0})
  const bytes=await pdf.save(),op=await operation(bytes),result=await replaceStyledText(bytes,[op],hash(bytes))
  if(shared){assert.equal(result.sha256,hash(bytes));assert.match(result.skippedOperations[0]!.reason,/template|drawn more than once/)}else{assert.deepEqual(result.skippedOperations,[]);assert.ok((await inspectTextObjects(result.bytes))[0]!.some(item=>item.text==='Styled first'))}
 }
})
test('post-write native review failure retains generated replacement bytes and actual digest',async()=>{
 const bytes=await fixture(),op=await operation(bytes,{newText:'ZZZ',align:'left' as const}),m=await loadPdfium(),original=m._FPDFFont_GetGlyphWidth
 try{
  m._FPDFFont_GetGlyphWidth=(font,glyph,size,width)=>glyph===90?0:original(font,glyph,size,width)
  const result=await replaceStyledText(bytes,[op],hash(bytes))
  assert.notEqual(result.sha256,hash(bytes));assert.equal(result.sha256,hash(result.bytes));assert.deepEqual(result.appliedOperationIndices,[])
  assert.match(result.skippedOperations[0]!.reason,/output_review_failed.*glyph_width/);assert.ok((await inspectTextObjects(result.bytes))[0]!.some(item=>item.text==='ZZZ'))
 }finally{m._FPDFFont_GetGlyphWidth=original}
})
test('independent pypdf reads actual styled replacement font color baselines and unchanged source neighbor',async()=>{
 const directory=await mkdtemp(join(tmpdir(),'pdf-styled-replacement-'))
 try{
  const bytes=await fixture(),op=await operation(bytes,{newText:'First\n\nNext',font:'courier' as const}),result=await replaceStyledText(bytes,[op],hash(bytes))
  assert.deepEqual(result.skippedOperations,[]);await writeFile(join(directory,'output.pdf'),result.bytes)
  const script=String.raw`import sys,json
from pypdf import PdfReader
from pypdf.generic import ContentStream
reader=PdfReader(sys.argv[1]);found=[]
reader.pages[0].extract_text(visitor_text=lambda text,cm,tm,font,size:found.append((text,cm,tm,font,size)))
assert not any('Original target' in value[0] for value in found)
assert any('Untouched neighbor' in value[0] for value in found)
for line,origin in [('First',[196,350]),('Next',[206.8,302])]:
 text,cm,tm,font,size=next(value for value in found if line in value[0])
 x=tm[4]*cm[0]+tm[5]*cm[2]+cm[4];y=tm[4]*cm[1]+tm[5]*cm[3]+cm[5]
 assert abs(x-origin[0])<.002 and abs(y-origin[1])<.002 and abs(size-18)<.002,(line,x,y,size)
 assert 'LiberationMono-BoldItalic' in str(font['/BaseFont'])
 descriptor=font['/DescendantFonts'][0].get_object()['/FontDescriptor'].get_object()
 assert len(descriptor['/FontFile2'].get_object().get_data())>100
colors=[args for args,operator in ContentStream(reader.pages[0].get_contents(),reader).operations if operator==b'rg']
assert any(all(abs(float(value)-expected)<.002 for value,expected in zip(color,[.2,.4,.6])) for color in colors)
print(json.dumps({'ok':True,'font':'LiberationMono-BoldItalic','size':18,'baselines':[[196,350],[206.8,302]],'color':[.2,.4,.6]}))`
  const checked=spawnSync(resolve('../../../.venv/bin/python'),['-c',script,join(directory,'output.pdf')],{encoding:'utf8'})
  assert.equal(checked.status,0,checked.stderr);assert.equal(JSON.parse(checked.stdout).ok,true)
 }finally{await rm(directory,{recursive:true,force:true})}
})
test('partial native writer failure still reviews and retains another generated overflowing edit',async()=>{
 const pdf=await PDFDocument.load(await fixture());pdf.getPage(0).drawText('Other target',{x:250,y:180,size:14});const bytes=await pdf.save(),op=await operation(bytes,{newText:'Overflow '.repeat(30),align:'left' as const}),objects=(await inspectNativeText(bytes,hash(bytes)))[0]!,target=objects.find(item=>item.text==='Other target')!,other={...op,objectId:target.objectId,expectedTextSha256:target.expectedTextSha256,newText:'BAD write'},m=await loadPdfium(),original=m._FPDFText_SetText
 try{
  m._FPDFText_SetText=(object,pointer)=>m.HEAPU8[pointer]===66&&m.HEAPU8[pointer+2]===65?0:original(object,pointer)
  const result=await replaceStyledText(bytes,[op,other],hash(bytes))
  assert.notEqual(result.sha256,hash(bytes));assert.equal(result.sha256,hash(result.bytes));assert.deepEqual(result.appliedOperationIndices,[])
  assert.match(result.skippedOperations.find(item=>item.operationIndex===0)!.reason,/overflow/)
  assert.match(result.skippedOperations.find(item=>item.operationIndex===1)!.reason,/SetText/)
  assert.ok((await inspectTextObjects(result.bytes))[0]!.some(item=>item.text==='Other target'))
 }finally{m._FPDFText_SetText=original}
})
test('actual selected font glyph fallback warns while retaining generated searchable Chinese text',async()=>{
 const bytes=await fixture(),op=await operation(bytes,{newText:'中文替换',font:'times' as const,bold:false,italic:false,align:'left' as const}),result=await replaceStyledText(bytes,[op],hash(bytes))
 assert.notEqual(result.sha256,hash(bytes));assert.equal(result.sha256,hash(result.bytes));assert.deepEqual(result.appliedOperationIndices,[])
 assert.match(result.skippedOperations[0]!.reason,/requested_font_fallback_generated_bytes_retained/)
 assert.ok((await inspectTextObjects(result.bytes))[0]!.some(item=>item.text==='中文替换'&&/NotoSansCJK/.test(item.fontName)))
})
test('keep original synthetic bold and explicit empty deletion use upstream object editing',async()=>{
 const bytes=await fixture(),base=await operation(bytes),{font,italic,...bold}=base
 const styled=await replaceStyledText(bytes,[{...bold,newText:'Bold original',align:'left' as const}],hash(bytes))
 assert.deepEqual(styled.skippedOperations,[])
 const deleted=await replaceStyledText(bytes,[{...base,newText:''}],hash(bytes))
 assert.deepEqual(deleted.skippedOperations,[]);assert.deepEqual(deleted.appliedOperationIndices,[0])
 assert.deepEqual((await inspectTextObjects(deleted.bytes))[0]!.map(item=>item.text),['Untouched neighbor'])
})
test('right alignment measures logical line glyphs without PDFium page synthesized trailing spaces',async()=>{
 const pdf=await PDFDocument.create(),page=pdf.addPage([500,500]);page.drawText('Original target',{x:250,y:350,size:14});page.drawText('Side neighbor',{x:300,y:302,size:12});page.drawText('Untouched neighbor',{x:50,y:450,size:12});const bytes=await pdf.save(),op=await operation(bytes,{newText:'AAAA\n\nBB',font:'courier' as const,fontSize:14,lineLeading:24}),result=await replaceStyledText(bytes,[op],hash(bytes))
 assert.deepEqual(result.skippedOperations,[])
 const added=(await inspectTextObjects(result.bytes))[0]!.filter(item=>['AAAA','BB'].includes(item.text.trimEnd())),metrics=await replacementMetrics(result.bytes,0,added)
 assert.ok(Math.abs(metrics.find((_,i)=>added[i]!.text.trimEnd()==='AAAA')!.matrix[4]-(250-4*14*.6))<.002)
 assert.ok(Math.abs(metrics.find((_,i)=>added[i]!.text.trimEnd()==='BB')!.matrix[4]-(250-2*14*.6))<.002,JSON.stringify({added,metrics}))
})
