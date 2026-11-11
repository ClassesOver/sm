import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createHash} from 'node:crypto'
import {PDFDocument,degrees} from 'pdf-lib'
import {inspectExistingImages,transformExistingImage} from './existing-image'
import {decodePngBgra,listExistingEngineImages} from './existing-image-engine'
import {inspectNativeText} from './text-operations'

const hash=(value:Uint8Array|string)=>createHash('sha256').update(value).digest('hex')
// 1×1 red source and a 3×2 replacement (blue / half-transparent green / white) built with pdf-lib-compatible PNG encoders
const red=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==','base64')
async function replacementPng(){
 // Encode with the same zlib path PNGs use: a tiny RGBA PNG assembled by hand
 const {deflateSync}=await import('node:zlib')
 const width=3,height=2,rows=[[0,0,255,255,0,200,0,128,255,255,255,255],[0,0,255,255,0,200,0,128,255,255,255,255]]
 const raw=Buffer.concat(rows.map(row=>Buffer.from([0,...row])))
 const crc=(buffer:Buffer)=>{let c=~0;for(const byte of buffer){c^=byte;for(let k=0;k<8;k++)c=c&1?(c>>>1)^0xedb88320:c>>>1}return ~c>>>0}
 const chunk=(type:string,data:Buffer)=>{const length=Buffer.alloc(4);length.writeUInt32BE(data.length);const body=Buffer.concat([Buffer.from(type,'ascii'),data]);const sum=Buffer.alloc(4);sum.writeUInt32BE(crc(body));return Buffer.concat([length,body,sum])}
 const header=Buffer.alloc(13);header.writeUInt32BE(width,0);header.writeUInt32BE(height,4);header[8]=8;header[9]=6
 return Buffer.concat([Buffer.from([0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a]),chunk('IHDR',header),chunk('IDAT',deflateSync(raw)),chunk('IEND',Buffer.alloc(0))]).toString('base64')
}
const green=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEBgIApD5fRAAAAABJRU5ErkJggg==','base64')
const blue=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPj/HwADBwIAMCbHYQAAAABJRU5ErkJggg==','base64')
/** Distinct pixel streams per placement; `shareTarget` draws the target's stream a second time on page 2. */
async function fixture(rotation=0,shareTarget=false){
 const pdf=await PDFDocument.create(),page=pdf.addPage([400,500]),second=pdf.addPage([400,500])
 const [first,other,third]=[await pdf.embedPng(red),await pdf.embedPng(green),await pdf.embedPng(blue)]
 page.setRotation(degrees(rotation))
 page.drawText('original body',{x:30,y:450,size:12})
 page.drawImage(first,{x:60,y:90,width:100,height:80})
 page.drawImage(other,{x:250,y:300,width:60,height:60})
 second.drawImage(shareTarget?first:third,{x:50,y:60,width:50,height:50})
 return pdf.save()
}

test('decodes PNG into straight-alpha BGRA and rejects non-PNG or invalid input',async()=>{
 const decoded=decodePngBgra(await replacementPng())
 assert.equal(decoded.width,3);assert.equal(decoded.height,2)
 assert.deepEqual(Array.from(decoded.bgra.slice(0,12)),[255,0,0,255,0,200,0,128,255,255,255,255])
 assert.throws(()=>decodePngBgra(Buffer.from('not a png at all').toString('base64')),/PNG/)
 assert.throws(()=>decodePngBgra('%%%%'),/PNG/)
})

test('replaces the pixels of one existing image in place, keeps its footprint, other images and text',async()=>{
 for(const rotation of [0,90]){
  const source=await fixture(rotation),sha=hash(source),model=await inspectExistingImages(source),target=model.existingImages[0]!
  const before=await listExistingEngineImages(source),image=await replacementPng()
  const result=await transformExistingImage(source,{kind:'transformExistingImage',sourceSha256:sha,pageId:target.pageId,imageId:target.imageId,expectedImageSha256:target.expectedImageSha256,rect:target.rect,image},sha)
  assert.deepEqual(result.skippedOperations,[]);assert.deepEqual(result.appliedOperationIndices,[0])
  const after=await listExistingEngineImages(result.bytes)
  assert.equal(after.length,3)
  assert.deepEqual([after[0]!.width,after[0]!.height],[3,2],'target now holds the replacement bitmap')
  assert.ok(after[0]!.rect.every((value,i)=>Math.abs(value-target.rect[i]!)<.05),'footprint kept')
  assert.notEqual(after[0]!.pixelsSha256,before[0]!.pixelsSha256)
  assert.deepEqual(after.slice(1).map(item=>[item.pageIndex,item.pixelsSha256,item.rect]),before.slice(1).map(item=>[item.pageIndex,item.pixelsSha256,item.rect]))
  const text=await inspectNativeText(result.bytes,hash(result.bytes))
  assert.equal(text[0]!.map(item=>item.text).join(''),'original body')
  const output=await PDFDocument.load(result.bytes)
  assert.equal(output.getPage(0).getRotation().angle,rotation);assert.equal(output.getPageCount(),2)
  assert.equal(hash(source),sha)
 }
})

test('replacement may also move and resize; preview digest binds the image bytes',async()=>{
 const source=await fixture(),sha=hash(source),target=(await inspectExistingImages(source)).existingImages[0]!,image=await replacementPng()
 const op={kind:'transformExistingImage',sourceSha256:sha,pageId:target.pageId,imageId:target.imageId,expectedImageSha256:target.expectedImageSha256,rect:[80,110,230,210] as [number,number,number,number],image}
 const result=await transformExistingImage(source,op,sha)
 assert.deepEqual(result.skippedOperations,[])
 assert.deepEqual((await listExistingEngineImages(result.bytes))[0]!.rect,[80,110,230,210])
 const moved=await transformExistingImage(source,{...op,image:undefined},sha)
 assert.notEqual(moved.previewDigest,result.previewDigest)
 assert.notEqual(moved.sha256,result.sha256)
})

test('rejects undecodable replacement, stale identity, extra fields and shared/ambiguous targets before writing',async()=>{
 const source=await fixture(),sha=hash(source),target=(await inspectExistingImages(source)).existingImages[0]!,image=await replacementPng()
 const op={kind:'transformExistingImage',sourceSha256:sha,pageId:target.pageId,imageId:target.imageId,expectedImageSha256:target.expectedImageSha256,rect:target.rect,image}
 for(const patch of [{image:Buffer.from('GIF89a........').toString('base64')},{image:'iVBORw0KGgo='},{expectedImageSha256:'0'.repeat(64)},{imageId:'0'.repeat(64)},{rect:[0,0,500,100]},{layer:'aboveText'}])
  await assert.rejects(transformExistingImage(source,{...op,...patch},sha),JSON.stringify(Object.keys(patch)))
 // 同一图像流被第 2 页再次引用：可移动但不可替换，桥接在写入前拒绝
 const shared=await fixture(0,true),sharedSha=hash(shared),sharedModel=await inspectExistingImages(shared),sharedTarget=sharedModel.existingImages[0]!
 assert.equal(sharedTarget.editable,true);assert.equal(sharedTarget.replaceable,false);assert.match(sharedTarget.replaceReason!,/多处引用/)
 await assert.rejects(transformExistingImage(shared,{...op,sourceSha256:sharedSha,pageId:sharedTarget.pageId,imageId:sharedTarget.imageId,expectedImageSha256:sharedTarget.expectedImageSha256},sharedSha),/多处引用/)
 assert.equal((await inspectExistingImages(source)).existingImages[0]!.replaceable,true)
 const pdf=await PDFDocument.load(source),dup=await PDFDocument.create(),page=dup.addPage([400,500]),embedded=await dup.embedPng(red)
 page.drawImage(embedded,{x:60,y:90,width:100,height:80});page.drawImage(embedded,{x:60,y:90,width:100,height:80})
 const ambiguous=await inspectExistingImages(await dup.save())
 assert.ok(ambiguous.existingImages.every(item=>!item.editable))
 assert.equal(pdf.getPageCount(),2)
})
