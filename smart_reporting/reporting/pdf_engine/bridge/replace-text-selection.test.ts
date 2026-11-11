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
import {replaceStyledText,type StyledReplaceTextOperation} from './replace-text-style'
import {replacementMetrics} from './replace-text-layout'
const hash=(bytes:Uint8Array)=>createHash('sha256').update(bytes).digest('hex')
async function fixture(){const pdf=await PDFDocument.create(),page=pdf.addPage([500,500]);page.drawText('Original target',{x:250,y:350,size:14});page.drawText('Untouched neighbor',{x:50,y:450,size:12});return pdf.save()}
async function operation(bytes:Uint8Array,extra={}):Promise<StyledReplaceTextOperation>{const sourceSha256=hash(bytes),target=(await inspectNativeText(bytes,sourceSha256))[0]!.find(item=>item.text==='Original target')!;return {kind:'replaceText',sourceSha256,pageId:'sha256:'+sourceSha256+':page:0',objectId:target.objectId,expectedTextSha256:target.expectedTextSha256,newText:'AABBCC',font:'courier',fontSize:12,align:'right',styleRuns:[{start:2,end:4,font:'times',size:18,bold:true,italic:true,color:[1,0,0]}],...extra} as StyledReplaceTextOperation}
test('selected range writes distinct native font size color and mixed advances aligned as one line',async()=>{
 const bytes=await fixture(),op=await operation(bytes),result=await replaceStyledText(bytes,[op],hash(bytes))
 assert.deepEqual(result.skippedOperations,[])
 const added=(await inspectTextObjects(result.bytes))[0]!.filter(item=>item.text.trimEnd()!=='Untouched neighbor')
 assert.deepEqual(added.map(item=>item.text.trimEnd()),['AA','BB','CC'])
 assert.match(added[1]!.fontName,/LiberationSerif-BoldItalic/);assert.equal(added[1]!.fontSize,18)
 const metrics=await replacementMetrics(result.bytes,0,added.map((item,i)=>({...item,measureText:['AA','BB','CC'][i]!})))
 assert.deepEqual(metrics[1]!.color,[255,0,0]);assert.ok(Math.abs(metrics[0]!.matrix[4]+metrics.reduce((sum,item)=>sum+item.width,0)-250)<.01)
 assert.ok(Math.abs(metrics[1]!.matrix[4]-metrics[0]!.matrix[4]-metrics[0]!.width)<.01)
 assert.ok(Math.abs(metrics[2]!.matrix[4]-metrics[1]!.matrix[4]-metrics[1]!.width)<.01)
 assert.equal(result.sha256,hash(result.bytes));assert.equal((await replaceStyledText(bytes,[op],hash(bytes))).previewDigest,result.previewDigest)
})
test('style ranges enforce sorted disjoint UTF16 whole scalar bounds and meaningful strict fields',async()=>{
 const bytes=await fixture(),base=await operation(bytes,{newText:'A😀BC'})
 for(const styleRuns of [[{start:0,end:0,bold:true}],[{start:-1,end:1,bold:true}],[{start:0,end:6,bold:true}],[{start:1.5,end:3,bold:true}],[{start:2,end:3,bold:true}],[{start:1,end:2,bold:true}],[{start:3,end:4,bold:true},{start:0,end:1,italic:true}],[{start:0,end:3,bold:true},{start:1,end:4,italic:true}],[{start:0,end:1}],[{start:0,end:1,size:5}],[{start:0,end:1,color:[2,0,0]}],[{start:0,end:1,font:'unknown'}],[{start:0,end:1,bold:'true'}],[{start:0,end:1,hidden:true}]])await assert.rejects(replaceStyledText(bytes,[{...base,styleRuns} as StyledReplaceTextOperation],hash(bytes)),undefined,JSON.stringify(styleRuns))
})
test('cross newline selection uses actual mixed face advances for each centered line',async()=>{
 const bytes=await fixture(),op=await operation(bytes,{newText:'AA BB\nCC DD',align:'center',lineLeading:24,styleRuns:[{start:3,end:8,font:'times',size:18,bold:true,italic:true,color:[1,0,0]}]}),result=await replaceStyledText(bytes,[op],hash(bytes))
 assert.deepEqual(result.skippedOperations,[])
 const added=(await inspectTextObjects(result.bytes))[0]!.filter(item=>item.text.trimEnd()!=='Untouched neighbor'),logical=['AA ','BB','CC ','DD'],metrics=await replacementMetrics(result.bytes,0,added.map((item,i)=>({...item,measureText:logical[i]!})))
 assert.deepEqual(added.map(item=>item.text.trimEnd()),['AA','BB','CC','DD'])
 for(const start of [0,2]){assert.ok(Math.abs(metrics[start]!.matrix[4]+(metrics[start]!.width+metrics[start+1]!.width)*.5-250)<.01);assert.ok(Math.abs(metrics[start+1]!.matrix[4]-metrics[start]!.matrix[4]-metrics[start]!.width)<.01)}
 assert.ok(Math.abs(metrics[0]!.matrix[5]-metrics[2]!.matrix[5]-24)<.01)
})
test('selected glyph fallback and overflow remain actual generated artifacts with explicit warnings',async()=>{
 const bytes=await fixture()
 const fallback=await replaceStyledText(bytes,[await operation(bytes,{newText:'AA中文CC',styleRuns:[{start:2,end:4,font:'times',size:18,color:[1,0,0]}]})],hash(bytes))
 assert.notEqual(fallback.sha256,hash(bytes));assert.equal(fallback.sha256,hash(fallback.bytes));assert.deepEqual(fallback.appliedOperationIndices,[]);assert.match(fallback.skippedOperations[0]!.reason,/requested_font_fallback_generated_bytes_retained/)
 assert.ok((await inspectTextObjects(fallback.bytes))[0]!.some(item=>item.text.trimEnd()==='中文'&&/NotoSansCJK/.test(item.fontName)))
 const overflow=await replaceStyledText(bytes,[await operation(bytes,{newText:'A'.repeat(50),align:'left',styleRuns:[{start:0,end:50,font:'courier',size:72,bold:true}]})],hash(bytes))
 assert.notEqual(overflow.sha256,hash(bytes));assert.equal(overflow.sha256,hash(overflow.bytes));assert.deepEqual(overflow.appliedOperationIndices,[]);assert.match(overflow.skippedOperations[0]!.reason,/overflow_page_or_neighbor_generated_bytes_retained/)
})
test('native segment measurement degradation never falsely passes selected styling',async()=>{
 const bytes=await fixture(),op=await operation(bytes,{newText:'AZB',styleRuns:[{start:1,end:2,font:'times',color:[1,0,0]}]}),m=await loadPdfium(),original=m._FPDFFont_GetGlyphWidth
 try{m._FPDFFont_GetGlyphWidth=(font,glyph,size,width)=>glyph===90?0:original(font,glyph,size,width);const result=await replaceStyledText(bytes,[op],hash(bytes));assert.notEqual(result.sha256,hash(bytes));assert.equal(result.sha256,hash(result.bytes));assert.deepEqual(result.appliedOperationIndices,[]);assert.match(result.skippedOperations[0]!.reason,/output_review_failed/);assert.ok((await inspectTextObjects(result.bytes))[0]!.some(item=>item.text.trimEnd()==='AZB'))}finally{m._FPDFFont_GetGlyphWidth=original}
})
test('selected style post-write review exception retains actual bytes and source bound digest',async()=>{
 const bytes=await fixture(),op=await operation(bytes),m=await loadPdfium(),save=m._PDFiumExt_SaveAsCopy,matrix=m._FPDFPageObj_GetMatrix;let saved=false
 try{m._PDFiumExt_SaveAsCopy=(doc,writer)=>{const result=save(doc,writer);saved=!!result;return result};m._FPDFPageObj_GetMatrix=(object,pointer)=>saved?0:matrix(object,pointer);const result=await replaceStyledText(bytes,[op],hash(bytes));assert.notEqual(result.sha256,hash(bytes));assert.equal(result.sha256,hash(result.bytes));assert.deepEqual(result.appliedOperationIndices,[]);assert.match(result.skippedOperations[0]!.reason,/output_review_failed.*matrix_unreadable/)}finally{m._PDFiumExt_SaveAsCopy=save;m._FPDFPageObj_GetMatrix=matrix}
})
test('independent pypdf reads selected font size color and whole mixed line right anchor',async()=>{
 const directory=await mkdtemp(join(tmpdir(),'pdf-text-selection-'))
 try{
  const bytes=await fixture(),op=await operation(bytes),result=await replaceStyledText(bytes,[op],hash(bytes));assert.deepEqual(result.skippedOperations,[]);await writeFile(join(directory,'output.pdf'),result.bytes)
  const script=String.raw`import sys,json
from pypdf import PdfReader
from pypdf.generic import ContentStream
reader=PdfReader(sys.argv[1]);found=[]
reader.pages[0].extract_text(visitor_text=lambda text,cm,tm,font,size:found.append((text,cm,tm,font,size)))
rows=[]
for segment,family,size in [('AA','LiberationMono',12),('BB','LiberationSerif-BoldItalic',18),('CC','LiberationMono',12)]:
 text,cm,tm,font,pt=next(value for value in found if value[0].strip()==segment)
 assert family in str(font['/BaseFont']) and abs(pt-size)<.002
 x=tm[4]*cm[0]+tm[5]*cm[2]+cm[4];y=tm[4]*cm[1]+tm[5]*cm[3]+cm[5]
 assert abs(y-350)<.002
 descriptor=font['/DescendantFonts'][0].get_object()['/FontDescriptor'].get_object();assert len(descriptor['/FontFile2'].get_object().get_data())>100
 rows.append({'text':segment,'font':str(font['/BaseFont']),'size':pt,'baseline':[x,y]})
assert abs(rows[1]['baseline'][0]-rows[0]['baseline'][0]-14.4)<.002
assert abs(rows[2]['baseline'][0]+14.4-250)<.002
colors=[args for args,operator in ContentStream(reader.pages[0].get_contents(),reader).operations if operator==b'rg'];assert any(list(map(float,color))==[1,0,0] for color in colors)
assert any('Untouched neighbor' in value[0] for value in found) and not any('Original target' in value[0] for value in found)
print(json.dumps({'ok':True,'rows':rows,'selectionColor':[1,0,0],'rightAnchor':250,'sourceNeighborPreserved':True}))`
  const checked=spawnSync(resolve('../../../.venv/bin/python'),['-c',script,join(directory,'output.pdf')],{encoding:'utf8'});assert.equal(checked.status,0,checked.stderr);assert.equal(JSON.parse(checked.stdout).ok,true)
 }finally{await rm(directory,{recursive:true,force:true})}
})
test('selected large glyphs overlapping their next line report nonblocking actual output overflow',async()=>{
 const bytes=await fixture(),op=await operation(bytes,{newText:'gg\ngg',align:'left',styleRuns:[{start:0,end:5,font:'courier',size:72}]}),result=await replaceStyledText(bytes,[op],hash(bytes))
 assert.notEqual(result.sha256,hash(bytes));assert.equal(result.sha256,hash(result.bytes));assert.deepEqual(result.appliedOperationIndices,[]);assert.match(result.skippedOperations[0]!.reason,/overflow_page_or_neighbor_generated_bytes_retained/)
})
test('explicit false selection bold and italic overrides whole object styles',async()=>{
 const bytes=await fixture(),op=await operation(bytes,{bold:true,italic:true,styleRuns:[{start:2,end:4,bold:false,italic:false}]}),result=await replaceStyledText(bytes,[op],hash(bytes))
 assert.deepEqual(result.skippedOperations,[])
 const added=(await inspectTextObjects(result.bytes))[0]!.filter(item=>item.text.trimEnd()!=='Untouched neighbor')
 assert.deepEqual(added.map(item=>item.text.trimEnd()),['AA','BB','CC'])
 assert.match(added[0]!.fontName,/BoldItalic/);assert.doesNotMatch(added[1]!.fontName,/Bold|Italic|Oblique/);assert.match(added[2]!.fontName,/BoldItalic/)
})
