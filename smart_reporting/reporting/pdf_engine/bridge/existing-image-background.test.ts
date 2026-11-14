import assert from 'node:assert/strict'
import {test} from 'node:test'
import {mkdtemp,readFile,rm,writeFile} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import {degrees,PDFDocument,rgb} from 'pdf-lib'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {spawnSync} from 'node:child_process'
import {encodeRgbaPng} from '../vendor/pdf2docx/src/extract/png'
import {inspectExistingImages,readExistingImageBackground} from './existing-image'
import {decodePngBgra} from './existing-image-engine'

const hash=(bytes:Uint8Array)=>createHash('sha256').update(bytes).digest('hex')
const png=(color:[number,number,number])=>{const pixels=new Uint8Array(16*16*4);for(let i=0;i<pixels.length;i+=4)pixels.set([...color,255],i);return encodeRgbaPng(pixels,16,16)}

async function fixture({background,rotation=0,crop}:{background:[number,number,number];rotation?:number;crop?:[number,number,number,number]}){
 const pdf=await PDFDocument.create(),page=pdf.addPage([240,320])
 if(crop)page.setCropBox(...crop)
 if(rotation)page.setRotation(degrees(rotation))
 page.drawRectangle({x:40,y:90,width:80,height:80,color:rgb(background[0]/255,background[1]/255,background[2]/255)})
 page.drawText('under image',{x:45,y:125,size:10,color:rgb(0,0,0)})
 const image=await pdf.embedPng(png([220,20,20]));page.drawImage(image,{x:40,y:90,width:80,height:80})
 const source=await pdf.save(),sourceSha256=hash(source),target=(await inspectExistingImages(source)).existingImages[0]!
 return {source,sourceSha256,target}
}

test('returns source-bound background pixels with the original page content beneath the target image',async()=>{
 for(const background of [[255,255,255],[40,120,210]] as const){
  const {source,sourceSha256,target}=await fixture({background})
  const result=await readExistingImageBackground(source,{sourceSha256,pageId:target.pageId,imageId:target.imageId,expectedImageSha256:target.expectedImageSha256,clip:{x:target.rect[0],y:320-target.rect[3],width:target.rect[2]-target.rect[0],height:target.rect[3]-target.rect[1]},pxWidth:160})
  const image=decodePngBgra(result.image)
  assert.equal(result.sourceSha256,sourceSha256);assert.equal(result.pageId,target.pageId);assert.equal(result.imageId,target.imageId);assert.equal(result.expectedImageSha256,target.expectedImageSha256)
  assert.equal(result.sha256,hash(Buffer.from(result.image,'base64')))
  const expected=[background[2],background[1],background[0]],matches=[]
  for(let i=0;i<image.bgra.length;i+=4)if(expected.every((channel,index)=>Math.abs(image.bgra[i+index]!-channel)<=2))matches.push(i)
  assert.ok(matches.length>500,`expected original background color beneath the image, found ${matches.length} matching pixels`)
  let textPixels=0
  for(let i=0;i<image.bgra.length;i+=4)if(image.bgra[i]!<80&&image.bgra[i+1]!<80&&image.bgra[i+2]!<80)textPixels++
  assert.ok(textPixels>5,`expected the underlying text to remain visible, found ${textPixels} dark pixels`)
 }
})

test('CLI imageBackground returns the same identity-bound PNG contract',async()=>{
 const {source,sourceSha256,target}=await fixture({background:[220,235,245]})
 const directory=await mkdtemp(join(tmpdir(),'pdf-image-background-'))
 try{
  const input=join(directory,'input.pdf'),requestPath=join(directory,'request.json')
  await writeFile(input,source)
  await writeFile(requestPath,JSON.stringify({kind:'imageBackground',input,target:{sourceSha256,pageId:target.pageId,imageId:target.imageId,expectedImageSha256:target.expectedImageSha256,clip:{x:0,y:0,width:240,height:320},pxWidth:240}}))
  const result=spawnSync(process.execPath,['--import','tsx','bridge/cli.ts',requestPath],{encoding:'utf8'})
  assert.equal(result.status,0,result.stderr)
  const receipt=JSON.parse(result.stdout.trim())
  assert.deepEqual([receipt.sourceSha256,receipt.pageId,receipt.imageId,receipt.expectedImageSha256],[sourceSha256,target.pageId,target.imageId,target.expectedImageSha256])
  assert.equal(receipt.sha256,hash(Buffer.from(receipt.image,'base64')))
 }finally{await rm(directory,{recursive:true,force:true})}
})

test('uses display-page clip coordinates for rotated pages with non-default crop boxes',async()=>{
 for(const rotation of [0,90,180,270]){
  const {source,sourceSha256,target}=await fixture({background:[35,145,80],rotation,crop:[20,30,190,250]})
  const pageSize=rotation%180===0?{width:190,height:250}:{width:250,height:190}
  const result=await readExistingImageBackground(source,{sourceSha256,pageId:target.pageId,imageId:target.imageId,expectedImageSha256:target.expectedImageSha256,clip:{x:0,y:0,...pageSize},pxWidth:220})
  const image=decodePngBgra(result.image)
  assert.equal(result.width,220);assert.ok(image.height>0)
  const expected=[80,145,35],matches=[]
  for(let i=0;i<image.bgra.length;i+=4)if(expected.every((channel,index)=>Math.abs(image.bgra[i+index]!-channel)<=2))matches.push(i)
  assert.ok(matches.length>500,`rotation ${rotation} should preserve the colored page background, found ${matches.length} matching pixels`)
 }
})

test('maps nonzero target clips to the same colored source region at every page rotation',async()=>{
 const cropX=20,cropY=30,cropWidth=190,cropHeight=250
 for(const rotation of [0,90,180,270]){
  const {source,sourceSha256,target}=await fixture({background:[35,145,80],rotation,crop:[cropX,cropY,cropWidth,cropHeight]})
  const [left,bottom,right,top]=target.rect,w=right-left,h=top-bottom
  const clip=rotation===0?{x:left-cropX,y:cropY+cropHeight-top,width:w,height:h}
   :rotation===90?{x:bottom-cropY,y:left-cropX,width:h,height:w}
    :rotation===180?{x:cropX+cropWidth-right,y:bottom-cropY,width:w,height:h}
     :{x:cropY+cropHeight-top,y:cropX+cropWidth-right,width:h,height:w}
  assert.ok(clip.x>0&&clip.y>0,`rotation ${rotation} must exercise nonzero clip offsets`)
  const result=await readExistingImageBackground(source,{sourceSha256,pageId:target.pageId,imageId:target.imageId,expectedImageSha256:target.expectedImageSha256,clip,pxWidth:160})
  const image=decodePngBgra(result.image),expected=[80,145,35]
  let matches=0
  for(let i=0;i<image.bgra.length;i+=4)if(expected.every((channel,index)=>Math.abs(image.bgra[i+index]!-channel)<=2))matches++
  assert.ok(matches>500,`rotation ${rotation} target-local clip should contain the original background, found ${matches}`)
 }
})

test('uses Python-compatible rounding order at a half-pixel raster height',async()=>{
 const {source,sourceSha256,target}=await fixture({background:[255,255,255]})
 const clip={x:0,y:0,width:219.22606738068345,height:108.1149056672391}
 const result=await readExistingImageBackground(source,{sourceSha256,pageId:target.pageId,imageId:target.imageId,expectedImageSha256:target.expectedImageSha256,clip,pxWidth:439})
 assert.equal(result.height,217)
})

test('rejects foreign source, target identity, invalid clip, and excessive raster dimensions',async()=>{
 const {source,sourceSha256,target}=await fixture({background:[240,240,240]})
 const request={sourceSha256,pageId:target.pageId,imageId:target.imageId,expectedImageSha256:target.expectedImageSha256,clip:{x:0,y:0,width:240,height:320},pxWidth:240}
 for(const key of ['sourceSha256','pageId','imageId','expectedImageSha256'] as const)await assert.rejects(()=>readExistingImageBackground(source,{...request,[key]:key==='pageId'?'foreign':'0'.repeat(64)}))
 await assert.rejects(()=>readExistingImageBackground(source,{...request,clip:{x:-1,y:0,width:20,height:20}}))
 await assert.rejects(()=>readExistingImageBackground(source,{...request,pxWidth:2401}))
 await assert.rejects(()=>readExistingImageBackground(source,{...request,pxWidth:2000}))
})
