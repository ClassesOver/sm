import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createHash} from 'node:crypto'
import {deflateSync} from 'node:zlib'
import {PDFDocument} from 'pdf-lib'
import {inspectExistingImages,transformExistingImage} from './existing-image'
import {listExistingEngineImages,renderExistingImageBgra} from './existing-image-engine'
import {inspectNativeText} from './text-operations'

const hash=(value:Uint8Array|string)=>createHash('sha256').update(value).digest('hex')
/** 12×12 RGBA PNG：白色背景，中心 4×4 红块（与边缘不相连）。 */
function badgePng(){
 const color=(x:number,y:number)=>x>=4&&x<8&&y>=4&&y<8?[220,30,30,255]:[255,255,255,255]
 const raw=Buffer.concat(Array.from({length:12},(_,y)=>Buffer.from([0,...Array.from({length:12},(_,x)=>color(x,y)).flat()])))
 const crc=(buffer:Buffer)=>{let c=~0;for(const byte of buffer){c^=byte;for(let k=0;k<8;k++)c=c&1?(c>>>1)^0xedb88320:c>>>1}return ~c>>>0}
 const chunk=(type:string,data:Buffer)=>{const length=Buffer.alloc(4);length.writeUInt32BE(data.length);const body=Buffer.concat([Buffer.from(type,'ascii'),data]);const sum=Buffer.alloc(4);sum.writeUInt32BE(crc(body));return Buffer.concat([length,body,sum])}
 const header=Buffer.alloc(13);header.writeUInt32BE(12,0);header.writeUInt32BE(12,4);header[8]=8;header[9]=6
 return Buffer.concat([Buffer.from([0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a]),chunk('IHDR',header),chunk('IDAT',deflateSync(raw)),chunk('IEND',Buffer.alloc(0))])
}
const green=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEBgIApD5fRAAAAABJRU5ErkJggg==','base64')
async function fixture(){
 const pdf=await PDFDocument.create(),page=pdf.addPage([400,500])
 page.drawText('original body',{x:30,y:450,size:12})
 page.drawImage(await pdf.embedPng(badgePng()),{x:60,y:90,width:120,height:120})
 page.drawImage(await pdf.embedPng(green),{x:250,y:300,width:60,height:60})
 return pdf.save()
}
async function pixel(bytes:Uint8Array,rect:[number,number,number,number],fx:number,fy:number){
 const image=await renderExistingImageBgra(bytes,0,rect,1),x=Math.floor(fx*image.width),y=Math.floor(fy*image.height),i=(y*image.width+x)*4
 return [image.bgra[i+2]!,image.bgra[i+1]!,image.bgra[i]!,image.bgra[i+3]!]
}
async function cutout(source:Uint8Array,patch:Record<string,unknown>={}){
 const target=(await inspectExistingImages(source)).existingImages[0]!
 return {target,result:await transformExistingImage(source,{kind:'transformExistingImage',sourceSha256:hash(source),pageId:target.pageId,imageId:target.imageId,expectedImageSha256:target.expectedImageSha256,rect:target.rect,bake:{kind:'cutout',tolerance:30},...patch},hash(source))}
}

test('cutout removes the edge-connected background via the pinned removeBackground and keeps the subject, other image and text',async()=>{
 const source=await fixture(),before=await listExistingEngineImages(source)
 const {target,result}=await cutout(source)
 assert.deepEqual(result.skippedOperations,[]);assert.deepEqual(result.appliedOperationIndices,[0])
 const after=await listExistingEngineImages(result.bytes)
 assert.deepEqual([after[0]!.width,after[0]!.height],[360,360],'baked at BAKE_SCALE 3 over the 120×120pt footprint')
 assert.ok(after[0]!.rect.every((value,i)=>Math.abs(value-target.rect[i]!)<.05))
 // 渲染到白色页面上看不出透明：直接读输出图像的 alpha（PDFium 把 alpha 拆为 SMask）
 for(const [fx,fy] of [[.05,.05],[.95,.05],[.05,.95],[.95,.95],[.2,.5]] as const)assert.equal((await pixel(result.bytes,after[0]!.rect,fx,fy))[3],0,`background ${fx},${fy}`)
 const centre=await pixel(result.bytes,after[0]!.rect,.5,.5)
 assert.ok(centre[3]===255&&Math.abs(centre[0]!-220)<=12&&centre[1]!<=45&&centre[2]!<=45,String(centre))
 assert.deepEqual([after[1]!.pixelsSha256,after[1]!.rect],[before[1]!.pixelsSha256,before[1]!.rect])
 assert.equal((await inspectNativeText(result.bytes,hash(result.bytes)))[0]!.map(item=>item.text).join(''),'original body')
 // 同一来源与操作输出可复现（预览确认摘要依赖于此）
 assert.equal((await cutout(source)).result.sha256,result.sha256)
})

test('cutout rejects invalid tolerance, extra fields, moving in the same batch and combining with a replacement',async()=>{
 const source=await fixture()
 for(const bake of [{kind:'cutout',tolerance:101},{kind:'cutout',tolerance:-1},{kind:'cutout',tolerance:12.5},{kind:'cutout'},{kind:'cutout',tolerance:30,extra:1}])
  await assert.rejects(cutout(source,{bake}),JSON.stringify(bake))
 const target=(await inspectExistingImages(source)).existingImages[0]!
 await assert.rejects(cutout(source,{rect:[target.rect[0]+10,target.rect[1],target.rect[2]+10,target.rect[3]]}),/不能同时移动/)
 await assert.rejects(cutout(source,{image:green.toString('base64')}))
})
