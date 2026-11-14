import assert from 'node:assert/strict'
import {test} from 'node:test'
import {PDFDocument, PDFName, PDFNumber, degrees} from 'pdf-lib'
import {inspectPdf,patchPdfWithReceipt,sha256} from './operations'
import {loadPdfium,inspectTextObjects} from '../src/main/text-edit'
import {insertStaticText,verifyStaticTextOutput,staticTextAvailability} from './static-text'
import {spawnSync} from 'node:child_process'
import {mkdtemp,writeFile,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join,resolve} from 'node:path'
async function fixture(rotation=0) {const pdf=await PDFDocument.create();const page=pdf.addPage([400,500]);page.setCropBox(10,20,380,460);page.setRotation(degrees(rotation));page.drawText('original body',{x:30,y:450,size:12});return pdf.save()}
async function operation(bytes:Uint8Array,extra={}){const model=await inspectPdf(bytes);return {kind:'insertText',sourceSha256:model.sourceSha256,pageId:model.pages[0].pageId,origin:[200,250],text:'Searchable insert 123',fontSize:12,color:[.2,.4,.6],align:'left',...extra}}
test('styled multiline insertion uses actual embedded face and native right alignment',async()=>{
 const bytes=await fixture(),op=await operation(bytes,{text:'Wide line\n\nShort',font:'times',bold:true,italic:true,align:'right',lineLeading:19})
 const result=await insertStaticText(bytes,op as Parameters<typeof insertStaticText>[1],sha256(bytes))
 assert.deepEqual(result.skippedOperations,[])
 const added=(await inspectTextObjects(result.bytes))[0].filter(item=>item.text!=='original body')
 assert.deepEqual(added.map(item=>item.text),['Wide line','Short'])
 assert.ok(added.every(item=>/LiberationSerif.*BoldItalic/i.test(item.fontName)),JSON.stringify(added))
 assert.ok(added.every(item=>item.rect[2]<=200.5),JSON.stringify(added))
 assert.ok(Math.abs((added[0].rect[1]-added[1].rect[1])-38)<.1)
 assert.equal((await insertStaticText(bytes,op as Parameters<typeof insertStaticText>[1],sha256(bytes))).previewDigest,result.previewDigest)
})
test('static text advertises availability and writes extractable output with a deterministic actual-byte receipt',async()=>{
 const bytes=await fixture(),model=await inspectPdf(bytes)
 assert.equal(model.capabilities.insertText,true)
 const op=await operation(bytes),receipt=await patchPdfWithReceipt(bytes,[op],sha256(bytes))
 assert.deepEqual(receipt.appliedOperationIndices,[0]);assert.deepEqual(receipt.skippedOperations,[])
 assert.equal(receipt.sha256,sha256(receipt.bytes));assert.equal(receipt.size,receipt.bytes.length)
 const text=(await inspectTextObjects(receipt.bytes))[0].map(obj=>obj.text).join('|')
 assert.match(text,/Searchable insert 123/);assert.match(text,/original body/)
 assert.equal((await patchPdfWithReceipt(bytes,[op],sha256(bytes))).previewDigest,receipt.previewDigest)
})
test('static text derives all four rotations from the immutable source',async()=>{
 for(const rotation of [0,90,180,270]){
  const bytes=await fixture(rotation)
  const result=await patchPdfWithReceipt(bytes,[await operation(bytes)],sha256(bytes))
  assert.deepEqual(result.skippedOperations,[])
  const object=(await inspectTextObjects(result.bytes))[0].find(obj=>obj.text==='Searchable insert 123')!
  assert.ok(object)
  if(rotation===0||rotation===180)assert.ok(object.rect[2]-object.rect[0]>object.rect[3]-object.rect[1])
  else assert.ok(object.rect[3]-object.rect[1]>object.rect[2]-object.rect[0])
 }
})
test('static text refuses forged source/page, mixed drafts, invalid values and unsupported source structures',async()=>{
 const bytes=await fixture(),op=await operation(bytes)
 for(const extra of [{sourceSha256:'0'.repeat(64)},{pageId:'forged'},{origin:[0,0]},{fontSize:5},{text:' '},{text:'a\u0000b'},{rotate:90},{font:'Arial'},{color:[2,0,0]}])await assert.rejects(patchPdfWithReceipt(bytes,[{...op,...extra}],sha256(bytes)))
 await assert.rejects(patchPdfWithReceipt(bytes,[op,{kind:'rotatePage',pageId:op.pageId,delta:90}],sha256(bytes)))
 await assert.rejects(patchPdfWithReceipt(bytes,[op],'0'.repeat(64)))
 for(const mode of ['form','annotation','unit','signature','rotation','perms']){
  const pdf=await PDFDocument.load(bytes),page=pdf.getPage(0)
  if(mode==='form')pdf.getForm()
  if(mode==='annotation')page.node.set(PDFName.of('Annots'),pdf.context.obj([{}]))
  if(mode==='unit')page.node.set(PDFName.of('UserUnit'),PDFNumber.of(2))
  if(mode==='signature')pdf.catalog.set(PDFName.of('Sig'),pdf.context.obj({Type:'Sig',ByteRange:[0,1,2,3]}))
  if(mode==='rotation')page.node.set(PDFName.of('Rotate'),PDFNumber.of(45))
  if(mode==='perms')pdf.catalog.set(PDFName.of('Perms'),pdf.context.obj({}))
  assert.equal(staticTextAvailability(pdf).insertText,false,mode)
  if(mode==='annotation')continue // malformed annotation fixture is rejected before other editor census
  const protectedBytes=await pdf.save(),model=await inspectPdf(protectedBytes)
  assert.equal(model.capabilities.insertText,false,mode);assert.ok(model.capabilities.insertTextReason)
  await assert.rejects(patchPdfWithReceipt(protectedBytes,[await operation(protectedBytes)],sha256(protectedBytes)))
 }
})

test("writer resource failure returns source bytes and honest skips",()=>{const script="import assert from 'node:assert/strict';import {PDFDocument} from 'pdf-lib';import {inspectPdf,patchPdfWithReceipt,sha256} from './bridge/operations.ts';const pdf=await PDFDocument.create();pdf.addPage([400,500]);const bytes=await pdf.save(),m=await inspectPdf(bytes);process.env.AGENT_REPORTING_PDF_WASM_DIR='/tmp/pdf-static-text-missing-resources';const r=await patchPdfWithReceipt(bytes,[{kind:'insertText',sourceSha256:m.sourceSha256,pageId:m.pages[0].pageId,origin:[30,200],text:'resource failure',fontSize:12,color:[0,0,0],align:'left'}],m.sourceSha256);assert.deepEqual(r.bytes,bytes);assert.deepEqual(r.appliedOperationIndices,[]);assert.equal(r.skippedOperations.length,1);assert.equal(r.sha256,sha256(bytes))";const r=spawnSync(process.execPath,["--import","tsx","--input-type=module","-e",script],{encoding:"utf8"});assert.equal(r.status,0,r.stderr)})
test('actual output verification detects changed original geometry and inserted font or origin',async()=>{
 const bytes=await fixture(),op=await operation(bytes),before=await inspectTextObjects(bytes)
 const result=await patchPdfWithReceipt(bytes,[op],sha256(bytes)),after=await inspectTextObjects(result.bytes)
 const geometry={rotation:0,cropBox:{x:10,y:20,width:380,height:460}}
 assert.equal(verifyStaticTextOutput(before,after,op,0,geometry),null)
 const changed=structuredClone(after);changed[0][0].rect[0]+=2
 assert.match(verifyStaticTextOutput(before,changed,op,0,geometry)!,/original/)
 const inserted=after[0].findIndex(item=>item.text===op.text)
 const font=structuredClone(after);font[0][inserted].fontSize+=2
 assert.match(verifyStaticTextOutput(before,font,op,0,geometry)!,/font/)
 const moved=structuredClone(after);moved[0][inserted].rect=moved[0][inserted].rect.map(value=>value+80)
 assert.match(verifyStaticTextOutput(before,moved,op,0,geometry)!,/geometry/)
})
test('overflow returns an honest warning while retaining actual generated bytes',async()=>{
 const bytes=await fixture(),op=await operation(bytes,{origin:[389,250]})
 const result=await patchPdfWithReceipt(bytes,[op],sha256(bytes))
 assert.notEqual(result.sha256,sha256(bytes));assert.equal(result.sha256,sha256(result.bytes))
 assert.match(result.skippedOperations[0]?.reason??'',/overflow/)
 assert.ok((await inspectTextObjects(result.bytes))[0].some(item=>item.text===op.text))
})
test('independent pypdf verifies actual inserted baseline matrices font sizes and colors',async()=>{
 const directory=await mkdtemp(join(tmpdir(),'pdf-static-text-style-'))
 try{
  for(const rotation of [0,90,180,270]){const bytes=await fixture(rotation);const result=await patchPdfWithReceipt(bytes,[await operation(bytes)],sha256(bytes));await writeFile(join(directory,rotation+'.pdf'),result.bytes)}
  const script=[
   'import sys,json',
   'from pypdf import PdfReader',
   'for angle in [0,90,180,270]:',
   ' r=PdfReader(sys.argv[1]+str(angle)+".pdf");found=[]',
   ' r.pages[0].extract_text(visitor_text=lambda text,cm,tm,font,size:found.append((text,cm,tm,size)))',
   ' text,cm,tm,size=next(v for v in found if "Searchable insert 123" in v[0])',
   ' expected={0:[1,0,0,1],90:[0,1,-1,0],180:[-1,0,0,-1],270:[0,-1,1,0]}[angle]',
   ' effective=[tm[0]*cm[0]+tm[1]*cm[2],tm[0]*cm[1]+tm[1]*cm[3],tm[2]*cm[0]+tm[3]*cm[2],tm[2]*cm[1]+tm[3]*cm[3],tm[4]*cm[0]+tm[5]*cm[2]+cm[4],tm[4]*cm[1]+tm[5]*cm[3]+cm[5]]',
   ' assert all(abs(effective[i]-expected[i])<0.001 for i in range(4)),(angle,effective,cm,tm)',
   ' assert abs(effective[4]-200)<0.001 and abs(effective[5]-250)<0.001 and abs(size-12)<0.001',
   ' from pypdf.generic import ContentStream',
   ' colors=[args for args,op in ContentStream(r.pages[0].get_contents(),r).operations if op==b"rg"]',
   ' assert any(all(abs(float(v)-e)<0.001 for v,e in zip(c,[.2,.4,.6])) for c in colors)',
   'print(json.dumps({"ok":True,"rotations":[0,90,180,270],"fontSize":12,"color":[.2,.4,.6],"baseline":[200,250]}))',
  ].join('\n')
  const result=spawnSync(resolve('../../../.venv/bin/python'),['-c',script,directory+'/'],{encoding:'utf8'})
  assert.equal(result.status,0,result.stderr);assert.equal(JSON.parse(result.stdout).ok,true)
 }finally{await rm(directory,{recursive:true,force:true})}
})
test('independent pypdf reads styled multiline center and right baselines in every rotation',async()=>{
 const directory=await mkdtemp(join(tmpdir(),'pdf-static-text-multiline-'))
 try{
  for(const rotation of [0,90,180,270])for(const align of ['center','right'] as const){
   const bytes=await fixture(rotation),op=await operation(bytes,{text:'Align\n\nNext',font:'courier',bold:true,italic:true,align,lineLeading:20})
   const result=await insertStaticText(bytes,op as Parameters<typeof insertStaticText>[1],sha256(bytes))
   assert.deepEqual(result.skippedOperations,[]);assert.equal(result.sha256,sha256(result.bytes))
   await writeFile(join(directory,rotation+'-'+align+'.pdf'),result.bytes)
  }
  for(const font of ['arial','times','courier'] as const){
   const bytes=await fixture(),op=await operation(bytes,{text:'Face check',font,bold:true,italic:true})
   const result=await insertStaticText(bytes,op as Parameters<typeof insertStaticText>[1],sha256(bytes))
   assert.deepEqual(result.skippedOperations,[]);await writeFile(join(directory,font+'.pdf'),result.bytes)
  }
  const script=String.raw`import json,sys
from pypdf import PdfReader
from pathlib import Path
root=Path(sys.argv[1])
for angle in [0,90,180,270]:
 for align in ['center','right']:
  reader=PdfReader(root/(str(angle)+'-'+align+'.pdf')); found=[]
  reader.pages[0].extract_text(visitor_text=lambda text,cm,tm,font,size:found.append((text,cm,tm,font,size)))
  a,b,c,d={0:[1,0,0,1],90:[0,1,-1,0],180:[-1,0,0,-1],270:[0,-1,1,0]}[angle]
  for line,chars,drop in [('Align',5,0),('Next',4,40)]:
   text,cm,tm,font,size=next(value for value in found if line in value[0])
   effective=[tm[0]*cm[0]+tm[1]*cm[2],tm[0]*cm[1]+tm[1]*cm[3],tm[2]*cm[0]+tm[3]*cm[2],tm[2]*cm[1]+tm[3]*cm[3],tm[4]*cm[0]+tm[5]*cm[2]+cm[4],tm[4]*cm[1]+tm[5]*cm[3]+cm[5]]
   offset=chars*12*.6*(-.5 if align=='center' else -1)
   expected=[a,b,c,d,200+a*offset-c*drop,250+b*offset-d*drop]
   assert all(abs(float(x)-y)<.002 for x,y in zip(effective,expected)),(angle,align,line,effective,expected)
   assert abs(size-12)<.001 and 'LiberationMono-BoldItalic' in str(font['/BaseFont'])
for name,family in [('arial','LiberationSans'),('times','LiberationSerif'),('courier','LiberationMono')]:
 reader=PdfReader(root/(name+'.pdf'));found=[]
 reader.pages[0].extract_text(visitor_text=lambda text,cm,tm,font,size:found.append((text,font)))
 font=next(font for text,font in found if 'Face check' in text)
 assert family+'-BoldItalic' in str(font['/BaseFont']),font
 descendants=font['/DescendantFonts'];descriptor=descendants[0].get_object()['/FontDescriptor'].get_object()
 assert len(descriptor['/FontFile2'].get_object().get_data())>100
print(json.dumps({'ok':True,'rotations':4,'alignments':2,'embeddedFaces':3,'blankLineLeading':40}))`
  const result=spawnSync(resolve('../../../.venv/bin/python'),['-c',script,directory],{encoding:'utf8'})
  assert.equal(result.status,0,result.stderr);assert.equal(JSON.parse(result.stdout).ok,true)
 }finally{await rm(directory,{recursive:true,force:true})}
})

test('post-write glyph measurement failure retains generated bytes and honest actual-byte receipt',async()=>{
 const bytes=await fixture(),op=await operation(bytes,{align:'center'}),m=await loadPdfium(),original=m._FPDFFont_GetGlyphWidth
 try{
  m._FPDFFont_GetGlyphWidth=()=>0
  const result=await insertStaticText(bytes,op as Parameters<typeof insertStaticText>[1],sha256(bytes))
  assert.notEqual(result.sha256,sha256(bytes));assert.equal(result.sha256,sha256(result.bytes))
  assert.deepEqual(result.appliedOperationIndices,[]);assert.match(result.skippedOperations[0]!.reason,/glyph_width_unavailable/)
  assert.ok((await inspectTextObjects(result.bytes))[0].some(item=>item.text===op.text))
 }finally{m._FPDFFont_GetGlyphWidth=original}
})

test('automatic font bold insertion verifies actual synthetic stroke instead of requiring bold face name',async()=>{
 const bytes=await fixture(),op=await operation(bytes,{bold:true}),result=await insertStaticText(bytes,op as Parameters<typeof insertStaticText>[1],sha256(bytes))
 assert.deepEqual(result.skippedOperations,[]);assert.deepEqual(result.appliedOperationIndices,[0])
})
test('same baseline insertion ignores only PDFium synthesized trailing page spaces',async()=>{
 const bytes=await fixture(),op=await operation(bytes,{origin:[200,450],text:'Z',font:'courier',fontSize:14,align:'right'}),result=await insertStaticText(bytes,op as Parameters<typeof insertStaticText>[1],sha256(bytes))
 assert.deepEqual(result.skippedOperations,[])
})

test('multiple inserts retain all source text across pages and original receipt identities',async()=>{
 const doc=await PDFDocument.load(await fixture());doc.addPage([400,500]).drawText('second page body',{x:30,y:450,size:12})
 const bytes=await doc.save(),model=await inspectPdf(bytes),first=await operation(bytes,{text:'First inserted',font:'times',bold:true})
 const second={...first,pageId:model.pages[1].pageId,text:'Second inserted',origin:[220,200],align:'right',font:'courier',bold:false}
 const ops=[first,second],snapshot=JSON.stringify(ops),result=await patchPdfWithReceipt(bytes,ops,sha256(bytes))
 assert.deepEqual(result.appliedOperationIndices,[0,1]);assert.deepEqual(result.skippedOperations,[])
 assert.equal(result.sourceSha256,sha256(bytes));assert.equal(result.sha256,sha256(result.bytes));assert.equal(JSON.stringify(ops),snapshot)
 const text=await inspectTextObjects(result.bytes)
 assert.deepEqual(text.map(items=>items.map(item=>item.text)),[['original body','First inserted'],['second page body','Second inserted']])
 assert.equal((await patchPdfWithReceipt(bytes,ops,sha256(bytes))).previewDigest,result.previewDigest)
 assert.notEqual((await patchPdfWithReceipt(bytes,[first],sha256(bytes))).previewDigest,result.previewDigest)
 for(const patch of [{sourceSha256:'0'.repeat(64)},{pageId:'forged'},{origin:[-1,0]}])await assert.rejects(patchPdfWithReceipt(bytes,[first,{...second,...patch}],sha256(bytes)))
})

test('later insert overflow preserves generated bytes earlier inserts and original skip indices',async()=>{
 const bytes=await fixture(),first=await operation(bytes,{text:'First retained'}),overflow=await operation(bytes,{text:'W'.repeat(150),origin:[380,200]}),last=await operation(bytes,{text:'Last retained',origin:[100,150]})
 const result=await patchPdfWithReceipt(bytes,[first,overflow,last],sha256(bytes))
 assert.deepEqual(result.appliedOperationIndices,[0,2]);assert.equal(result.skippedOperations.length,1)
 assert.equal(result.skippedOperations[0].operationIndex,1);assert.equal(result.skippedOperations[0].pageId,first.pageId)
 assert.match(result.skippedOperations[0].reason,/overflow/)
 const text=(await inspectTextObjects(result.bytes))[0].map(item=>item.text).join('|')
 assert.match(text,/First retained/);assert.match(text,/Last retained/);assert.match(text,/WWWW/)
 assert.equal(result.sha256,sha256(result.bytes));assert.equal(result.sourceSha256,sha256(bytes))
})
test('later intermediate load failure retains the first inserted bytes and original failure index',async(t)=>{
 const bytes=await fixture(),first=await operation(bytes,{text:'First retained'}),second=await operation(bytes,{text:'Second not written',origin:[100,150]})
 const expected=await patchPdfWithReceipt(bytes,[first],sha256(bytes)),load=PDFDocument.load
 t.mock.method(PDFDocument,'load',async function(content:Parameters<typeof PDFDocument.load>[0],...args:Parameters<typeof PDFDocument.load> extends [unknown,...infer Rest]?Rest:never){
  if(content instanceof Uint8Array&&sha256(content)===expected.sha256)throw Error('injected intermediate load failure')
  return load.call(PDFDocument,content,...args)
 })
 const result=await patchPdfWithReceipt(bytes,[first,second],sha256(bytes))
 assert.deepEqual(result.bytes,expected.bytes);assert.deepEqual(result.appliedOperationIndices,[0])
 assert.deepEqual(result.skippedOperations,[{operationIndex:1,kind:'insertText',pageId:first.pageId,reason:'pdf_insert_text_failed: injected intermediate load failure'}])
 assert.equal(result.sha256,expected.sha256);assert.equal(result.sourceSha256,sha256(bytes))
})
