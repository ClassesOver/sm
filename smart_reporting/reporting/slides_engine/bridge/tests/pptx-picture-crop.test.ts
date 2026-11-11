import assert from 'node:assert/strict'
import {test} from 'node:test'
import {addPicture,createBlankPptx,duplicateSlide,openPptx,savePptx} from '@genoffice/pptx-engine'
import {inspectPictureImages} from '../pptx-images.ts'
import {inspectPictureCrop,validatePictureCrops,applyPictureCrops} from '../pptx-picture-crop.ts'
const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
async function fixture(){
 const o=await openPptx(await createBlankPptx())
 addPicture(o,o.deck.slides[0]!,{bytes:Buffer.from(png,'base64'),ext:'png',offset:{x:952500,y:952500,cx:3810000,cy:1905000}})
 duplicateSlide(o,0)
 return openPptx(await savePptx(o))
}
function edit(o:Awaited<ReturnType<typeof fixture>>){const p=inspectPictureImages(o)[0]!;return {slideIndex:0,elementId:p.elementId,expectedSha256:p.sha256!,expectedSize:p.size!,srcRect:{l:.25,t:0,r:0,b:0},geometry:{x:200,y:100,width:300,height:200}}}
test('真实裁切原子更新srcRect与frame，原媒体和其他页部件字节保持',async()=>{
 const o=await fixture(),item=edit(o),other=o.archive.readBytes(o.deck.slides[1]!.path),media=o.deck.slides[0]!.elements[0]!
 assert.equal(inspectPictureCrop(o,0,item.elementId).pictureCropEditable,true)
 const original=new Map([...o.archive.entries.keys()].map(path=>[path,o.archive.readBytes(path)]))
 applyPictureCrops(o,[item])
 assert.equal(o.deck.slides[0]!.elements[0]!.id,item.elementId)
 assert.deepEqual(o.deck.slides[0]!.elements[0]!.transform.offset,{x:1905000,y:952500,cx:2857500,cy:1905000})
 const restored=await openPptx(await savePptx(o))
 assert.deepEqual(inspectPictureCrop(restored,0,restored.deck.slides[0]!.elements[0]!.id).srcRect,item.srcRect)
 assert.deepEqual(restored.archive.readBytes(restored.deck.slides[1]!.path),other)
 for(const [path,bytes] of original)if(path!==o.deck.slides[0]!.path)assert.deepEqual(restored.archive.readBytes(path),bytes,path)
 assert.equal(inspectPictureImages(restored)[0]!.sha256,item.expectedSha256)
})
test('重复、过期、删除或替换冲突整批拒绝，保留原框与裁切',async()=>{
 const o=await fixture(),item=edit(o),before=structuredClone(o.deck.slides[0]!.elements[0])
 assert.throws(()=>applyPictureCrops(o,[item,{...item,slideIndex:1,elementId:o.deck.slides[1]!.elements[0]!.id,expectedSha256:'0'.repeat(64)}]),/identity/)
 assert.deepEqual(o.deck.slides[0]!.elements[0],before)
 assert.throws(()=>validatePictureCrops(o,[item,item]),/conflict/)
 assert.throws(()=>validatePictureCrops(o,[item],{deletedSlides:[0]}),/conflict/)
 assert.throws(()=>validatePictureCrops(o,[item],{pictureReplacements:[item]}),/conflict/)
 assert.throws(()=>validatePictureCrops(o,[{...item,srcRect:{l:.5,t:0,r:.5,b:0}}]),/invalid/)
})
test('旋转、翻转和非普通图片保持只读，null移除裁切同时还原框',async()=>{
 const o=await fixture(),item=edit(o),picture=o.deck.slides[0]!.elements[0]!
 picture.transform.rot=60000
 assert.equal(inspectPictureCrop(o,0,item.elementId).pictureCropEditable,false)
 picture.transform.rot=0;picture.transform.flipH=true
 assert.equal(inspectPictureCrop(o,0,item.elementId).pictureCropEditable,false)
 picture.transform.flipH=false
 applyPictureCrops(o,[item])
 applyPictureCrops(o,[{...item,srcRect:null,geometry:{x:100,y:100,width:400,height:200}}])
 assert.equal(inspectPictureCrop(o,0,item.elementId).srcRect,null)
 assert.equal(picture.transform.offset.cx,3810000)
})
