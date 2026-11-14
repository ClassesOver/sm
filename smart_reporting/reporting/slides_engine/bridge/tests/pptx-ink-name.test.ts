import assert from 'node:assert/strict'
import {test} from 'node:test'
import {addPicture,createBlankPptx,openPptx,savePptx} from '@genoffice/pptx-engine'
import {validatePictureInsertions,pictureInsertionName} from '../pptx-images.ts'
const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='
const descr=JSON.stringify({v:1,tool:'pen',color:'C00000',width:2,points:[[2,2],[20,10]]})
test('编辑墨迹沿原图片writer保存name与vector descr，拒绝假墨迹身份',async()=>{
 const opened=await openPptx(await createBlankPptx())
 const item={slideIndex:0,extension:'png' as const,bytesBase64:png,geometry:{x:-1,y:-1,width:30,height:20},name:'aislides-ink sample',descr}
 validatePictureInsertions(opened,[item]);assert.equal(pictureInsertionName(item),'aislides-ink sample')
 addPicture(opened,opened.deck.slides[0]!,{bytes:Buffer.from(png,'base64'),ext:'png',offset:{x:-9525,y:-9525,cx:285750,cy:190500},name:pictureInsertionName(item),descr:item.descr})
 const saved=await openPptx(await savePptx(opened));const xml=saved.deck.slides[0]!.elements[0]!.anchor.originalXml;assert.match(xml,/aislides-ink sample/);assert.match(xml,/&quot;points&quot;/)
 for(const patch of [{name:'arbitrary'}, {name:'aislides-ink sample',descr:'broken'}, {name:'aislides-ink sample',extension:'jpg'}, {name:undefined}])assert.throws(()=>validatePictureInsertions(opened,[{...item,...patch}]))
 assert.equal(pictureInsertionName({...item,name:undefined,geometry:{x:1,y:1,width:2,height:2},descr:'普通图片'}),'插入的图片')
})
