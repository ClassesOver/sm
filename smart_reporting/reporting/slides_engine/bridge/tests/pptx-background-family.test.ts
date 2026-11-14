import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createHash} from 'node:crypto'
import {addElement, createBlankPptx, insertBlankSlide, openPptx, savePptx} from '@genoffice/pptx-engine'
import * as images from '../pptx-background-image.ts'
import * as ops from '../pptx-background-ops.ts'
const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
async function deck(){const o=await openPptx(await createBlankPptx());insertBlankSlide(o,0);insertBlankSlide(o,1);images.applyBackgroundImages(o,o.deck.slides,images.validateBackgroundImages(o,[{slideIndices:[0],bytesBase64:png,extension:'png',tile:false}]));return openPptx(await savePptx(o))}
test('既有背景媒体按实际SHA/size复用，平铺和应用全部不再新增媒体',async()=>{
 const o=await deck(),sha=createHash('sha256').update(Buffer.from(png,'base64')).digest('hex'),size=Buffer.from(png,'base64').length
 const source=(images.inspectBackgroundImage(o,0) as any).backgroundImageSource
 assert.deepEqual(source,{sha256:sha,size})
 const input=[{sourceSlideIndex:0,expectedSha256:sha,expectedSize:size,slideIndices:[0,1,2],tile:true}]
 for(const bad of [{...input[0],expectedSha256:'0'.repeat(64)},{...input[0],expectedSize:size+1},{...input[0],mediaPath:'/tmp/foreign.png'},{...input[0],sourceSlideIndex:1}])assert.throws(()=>(images as any).validateBackgroundImageReuses(o,[bad]))
 assert.throws(()=>(images as any).validateBackgroundImageReuses(o,input,{fillSlides:new Set([1])}))
 const reused=(images as any).validateBackgroundImageReuses(o,input)
 const media=[...o.archive.entries.keys()].filter(p=>p.startsWith('ppt/media/'))
 ;(images as any).applyBackgroundImageReuses(o,o.deck.slides,reused)
 const saved=await openPptx(await savePptx(o))
 assert.deepEqual([...saved.archive.entries.keys()].filter(p=>p.startsWith('ppt/media/')),media)
 assert.deepEqual(saved.deck.slides.map((_,i)=>images.inspectBackgroundImage(saved,i).backgroundImage),[{mode:'tile'},{mode:'tile'},{mode:'tile'}])

})
test('纯色规范操作同步真实全幅底板',async()=>{
 const o=await deck(),s=o.deck.slides[0]!,size=o.deck.size
 addElement(s,{kind:'rect',offset:{x:0,y:0,cx:size.cx,cy:size.cy},fillColor:'#EEEEEE'})
 ;(ops as any).applyBackgroundColors(o,o.deck.slides,[{slideIndex:0,color:'#123456'}])
 assert.deepEqual(s.elements.find(e=>e.type==='shape')!.fill,{type:'solid',color:'#123456'})
})
