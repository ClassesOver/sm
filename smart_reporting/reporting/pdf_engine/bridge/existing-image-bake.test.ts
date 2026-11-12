import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createHash} from 'node:crypto'
import {deflateSync} from 'node:zlib'
import {PDFDocument,degrees} from 'pdf-lib'
import {inspectExistingImages,transformExistingImage} from './existing-image'
import {listExistingEngineImages,renderExistingImageBgra} from './existing-image-engine'
import {inspectNativeText} from './text-operations'

const hash=(value:Uint8Array|string)=>createHash('sha256').update(value).digest('hex')
/** 8×8 RGBA PNG with four solid quadrants: TL red, TR green, BL blue, BR white. */
function quadrantPng(){
 const color=(x:number,y:number)=>y<4?(x<4?[255,0,0,255]:[0,200,0,255]):(x<4?[0,0,255,255]:[255,255,255,255])
 const raw=Buffer.concat(Array.from({length:8},(_,y)=>Buffer.from([0,...Array.from({length:8},(_,x)=>color(x,y)).flat()])))
 const crc=(buffer:Buffer)=>{let c=~0;for(const byte of buffer){c^=byte;for(let k=0;k<8;k++)c=c&1?(c>>>1)^0xedb88320:c>>>1}return ~c>>>0}
 const chunk=(type:string,data:Buffer)=>{const length=Buffer.alloc(4);length.writeUInt32BE(data.length);const body=Buffer.concat([Buffer.from(type,'ascii'),data]);const sum=Buffer.alloc(4);sum.writeUInt32BE(crc(body));return Buffer.concat([length,body,sum])}
 const header=Buffer.alloc(13);header.writeUInt32BE(8,0);header.writeUInt32BE(8,4);header[8]=8;header[9]=6
 return Buffer.concat([Buffer.from([0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a]),chunk('IHDR',header),chunk('IDAT',deflateSync(raw)),chunk('IEND',Buffer.alloc(0))])
}
const green=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEBgIApD5fRAAAAABJRU5ErkJggg==','base64')
async function fixture(options:{rotateImage?:boolean;share?:boolean}={}){
 const pdf=await PDFDocument.create(),page=pdf.addPage([400,500])
 const quad=await pdf.embedPng(quadrantPng()),other=await pdf.embedPng(green)
 page.drawText('original body',{x:30,y:450,size:12})
 page.drawImage(quad,{x:60,y:90,width:100,height:80,...(options.rotateImage?{rotate:degrees(30)}:{})})
 page.drawImage(options.share?quad:other,{x:250,y:300,width:60,height:60})
 return pdf.save()
}
/** BGRA → [r,g,b,a] at the centre of a quadrant of the rendered output image */
async function corner(bytes:Uint8Array,rect:[number,number,number,number],fx:number,fy:number){
 const image=await renderExistingImageBgra(bytes,0,rect,1),x=Math.floor(fx*image.width),y=Math.floor(fy*image.height),i=(y*image.width+x)*4
 return [image.bgra[i+2]!,image.bgra[i+1]!,image.bgra[i]!,image.bgra[i+3]!]
}
const close=(actual:number[],expected:number[],tol=12)=>assert.ok(actual.every((value,i)=>Math.abs(value-expected[i]!)<=tol),`${actual} ≉ ${expected}`)
async function bake(source:Uint8Array,bake:unknown,rect?:[number,number,number,number]){
 const sha=hash(source),target=(await inspectExistingImages(source)).existingImages[0]!
 return {target,result:await transformExistingImage(source,{kind:'transformExistingImage',sourceSha256:sha,pageId:target.pageId,imageId:target.imageId,expectedImageSha256:target.expectedImageSha256,rect:rect??target.rect,bake},sha)}
}

test('flip mirrors the image pixels in place and keeps footprint, other image and body text',async()=>{
 const source=await fixture(),before=await listExistingEngineImages(source)
 const model=await inspectExistingImages(source)
 assert.deepEqual(model.existingImages.map(image=>image.bakeable),[true,true])
 for(const [axis,expected] of [['h',[[0,200,0,255],[255,0,0,255],[255,255,255,255],[0,0,255,255]]],['v',[[0,0,255,255],[255,255,255,255],[255,0,0,255],[0,200,0,255]]]] as const){
  const {target,result}=await bake(source,{kind:'flip',axis})
  assert.deepEqual(result.skippedOperations,[]);assert.deepEqual(result.appliedOperationIndices,[0])
  const after=await listExistingEngineImages(result.bytes)
  assert.deepEqual([after[0]!.width,after[0]!.height],[300,240],'baked at BAKE_SCALE 3 over the 100×80pt footprint')
  assert.ok(after[0]!.rect.every((value,i)=>Math.abs(value-target.rect[i]!)<.05))
  assert.deepEqual([after[1]!.pixelsSha256,after[1]!.rect],[before[1]!.pixelsSha256,before[1]!.rect])
  const quadrants=[[.25,.25],[.75,.25],[.25,.75],[.75,.75]] as const
  for(const [index,[fx,fy]] of quadrants.entries())close(await corner(result.bytes,after[0]!.rect,fx,fy),expected[index]!)
  assert.equal((await inspectNativeText(result.bytes,hash(result.bytes)))[0]!.map(item=>item.text).join(''),'original body')
 }
})

test('crop keeps the chosen fraction and shrinks the footprint by the pinned cropRect; opacity scales alpha',async()=>{
 const source=await fixture(),target=(await inspectExistingImages(source)).existingImages[0]!
 const [x1,y1,x2,y2]=target.rect,rect:[number,number,number,number]=[x1,y2-.5*(y2-y1),x1+.5*(x2-x1),y2]
 const {result}=await bake(source,{kind:'crop',crop:{l:0,t:0,r:.5,b:.5}},rect)
 assert.deepEqual(result.skippedOperations,[])
 const after=await listExistingEngineImages(result.bytes)
 assert.deepEqual([after[0]!.width,after[0]!.height],[150,120])
 assert.ok(after[0]!.rect.every((value,i)=>Math.abs(value-rect[i]!)<.05),'footprint = top-left quarter of the old rect')
 for(const [fx,fy] of [[.1,.1],[.9,.9]])close(await corner(result.bytes,after[0]!.rect,fx,fy),[255,0,0,255])
 const faded=(await bake(source,{kind:'opacity',alpha:.5})).result
 assert.deepEqual(faded.skippedOperations,[])
 const pixel=await corner(faded.bytes,target.rect,.25,.25)
 assert.ok(Math.abs(pixel[3]!-128)<=3,`alpha ${pixel[3]}`)
 // 同一来源与操作的输出可复现（预览确认摘要依赖于此）
 assert.equal((await bake(source,{kind:'flip',axis:'h'})).result.sha256,(await bake(source,{kind:'flip',axis:'h'})).result.sha256)
})

test('bake is refused for rotated or shared images, moved rects, bad fractions and image+bake',async()=>{
 const rotated=await inspectExistingImages(await fixture({rotateImage:true}))
 assert.equal(rotated.existingImages[0]!.bakeable,false);assert.match(rotated.existingImages[0]!.bakeReason!,/旋转、镜像/)
 await assert.rejects(bake(await fixture({rotateImage:true}),{kind:'flip',axis:'h'}),/旋转、镜像/)
 const shared=await inspectExistingImages(await fixture({share:true}))
 assert.equal(shared.existingImages[0]!.bakeable,false);assert.match(shared.existingImages[0]!.bakeReason!,/多处引用/)
 const source=await fixture(),target=(await inspectExistingImages(source)).existingImages[0]!
 await assert.rejects(bake(source,{kind:'flip',axis:'h'},[target.rect[0]+10,target.rect[1],target.rect[2]+10,target.rect[3]]),/不能同时移动/)
 await assert.rejects(bake(source,{kind:'crop',crop:{l:0,t:0,r:.5,b:.5}}),/保留比例/)
 for(const bad of [{kind:'flip',axis:'d'},{kind:'opacity',alpha:1},{kind:'opacity',alpha:.333},{kind:'crop',crop:{l:.5,t:0,r:.5,b:1}},{kind:'crop',crop:{l:0,t:0,r:1,b:1}},{kind:'crop',crop:{l:0,t:0,r:1.2,b:1}},{kind:'flip',axis:'h',extra:1}])
  await assert.rejects(bake(source,bad),JSON.stringify(bad))
 const sha=hash(source)
 await assert.rejects(transformExistingImage(source,{kind:'transformExistingImage',sourceSha256:sha,pageId:target.pageId,imageId:target.imageId,expectedImageSha256:target.expectedImageSha256,rect:target.rect,image:quadrantPng().toString('base64'),bake:{kind:'flip',axis:'h'}},sha))
})
