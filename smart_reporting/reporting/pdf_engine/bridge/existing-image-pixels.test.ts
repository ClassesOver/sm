import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createHash} from 'node:crypto'
import {PDFDocument} from 'pdf-lib'
import {encodeRgbaPng} from '../vendor/pdf2docx/src/extract/png'
import {inspectExistingImages,readExistingImagePixels} from './existing-image'
import {decodePngBgra} from './existing-image-engine'
const hash=(b:Uint8Array)=>createHash('sha256').update(b).digest('hex')
test('reads identified image pixels and rejects changed source without mutation',async()=>{
 const pdf=await PDFDocument.create(),page=pdf.addPage([400,500]),rgba=new Uint8Array(20*20*4)
 for(let i=0;i<rgba.length;i+=4)rgba.set([255,0,0,255],i)
 const red=await pdf.embedPng(encodeRgbaPng(rgba,20,20));page.drawImage(red,{x:30,y:40,width:80,height:80});page.drawText('unchanged body',{x:10,y:450})
 const source=await pdf.save(),sha=hash(source),target=(await inspectExistingImages(source)).existingImages[0]!
 const request={sourceSha256:sha,pageId:target.pageId,imageId:target.imageId,expectedImageSha256:target.expectedImageSha256}
 const result=await readExistingImagePixels(source,request),pixels=decodePngBgra(result.image)
 assert.equal(result.sourceSha256,sha);assert.equal(result.imageId,target.imageId);assert.equal(result.sha256,hash(Buffer.from(result.image,'base64')))
 assert.deepEqual([...pixels.bgra.slice(0,4)],[0,0,255,255]);assert.equal(hash(source),sha)
 for(const key of ['sourceSha256','imageId','expectedImageSha256'])await assert.rejects(()=>readExistingImagePixels(source,{...request,[key]:'0'.repeat(64)}))
 await assert.rejects(()=>readExistingImagePixels(source,{...request,pageId:target.pageId+':foreign'}))
})
