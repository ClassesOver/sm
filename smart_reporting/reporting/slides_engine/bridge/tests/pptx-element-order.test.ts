import assert from 'node:assert/strict'
import {test} from 'node:test'
import {addElement,createBlankPptx,openPptx,savePptx} from '@genoffice/pptx-engine'
import {applyElementOrders,validateElementOrders} from '../pptx-element-order.ts'
async function fixture(){
 const o=await openPptx(await createBlankPptx())
 for(const text of ['甲','乙','丙'])addElement(o.deck.slides[0]!,{kind:'textbox',offset:{x:100,y:100,cx:1000,cy:1000},paragraphs:[{runs:[{text}]}]})
 return openPptx(await savePptx(o))
}
test('真实PPTX仅用引擎重排来源对象，内容、媒体和其他部件保持',async()=>{
 const o=await fixture(),slide=o.deck.slides[0]!,ids=slide.elements.map(e=>e.id),before=new Map([...o.archive.entries.keys()].map(p=>[p,o.archive.readBytes(p)])),xml=slide.elements.map(e=>e.anchor.originalXml)
 applyElementOrders(o,[{slideIndex:0,elementIds:[ids[2]!,ids[0]!,ids[1]!]}])
 assert.deepEqual(slide.elements.map(e=>e.id),[ids[2],ids[0],ids[1]])
 assert.deepEqual(slide.elements.map(e=>e.anchor.originalXml),[xml[2],xml[0],xml[1]])
 const reopened=await openPptx(await savePptx(o))
 assert.deepEqual(reopened.deck.slides[0]!.elements.map(e=>e.type==='text'?e.text?.paragraphs[0]?.runs[0]?.text:''),['丙','甲','乙'])
 for(const [path,bytes] of before)if(path!==slide.path)assert.deepEqual(reopened.archive.readBytes(path),bytes,path)
})
test('整批先验证全排列与冲突，错误不会更改前页且相同顺序不标脏',async()=>{
 const o=await fixture(),slide=o.deck.slides[0]!,ids=slide.elements.map(e=>e.id),valid={slideIndex:0,elementIds:ids}
 applyElementOrders(o,[valid]);assert.notEqual(slide.structureDirty,true)
 for(const bad of [null,{},[valid,valid],[{...valid,extra:true}],[{slideIndex:0,elementIds:ids.slice(1)}],[{slideIndex:0,elementIds:[ids[0],ids[0],ids[2]]}],[{slideIndex:0,elementIds:[...ids.slice(0,2),'unknown']}],[{slideIndex:99,elementIds:ids}]])assert.throws(()=>validateElementOrders(o,bad))
 assert.throws(()=>validateElementOrders(o,[valid],{deletedSlides:[0]}))
 assert.throws(()=>applyElementOrders(o,[{slideIndex:0,elementIds:[...ids].reverse()},{slideIndex:1,elementIds:[]}]))
 assert.deepEqual(slide.elements.map(e=>e.id),ids)
})
test('拒绝交换只读对象相对顺序，安全对象允许跨越只读对象',async()=>{
 const o=await fixture(),slide=o.deck.slides[0]!,ids=slide.elements.map(e=>e.id)
 slide.elements[0]!.anchor.originalXml='<p:cxnSp/>'
 slide.elements[2]!.anchor.originalXml='<p:cxnSp/>'
 assert.throws(()=>validateElementOrders(o,[{slideIndex:0,elementIds:[...ids].reverse()}]),/readonly/)
 applyElementOrders(o,[{slideIndex:0,elementIds:[ids[1]!,ids[0]!,ids[2]!]}])
 assert.deepEqual(slide.elements.map(e=>e.id),[ids[1],ids[0],ids[2]])
})
test('多个安全对象跨越只读目标时能够完成排序',async()=>{
 const o=await fixture(),slide=o.deck.slides[0]!,ids=slide.elements.map(e=>e.id)
 slide.elements[2]!.anchor.originalXml='<p:cxnSp/>'
 applyElementOrders(o,[{slideIndex:0,elementIds:[ids[2]!,ids[0]!,ids[1]!]}])
 assert.deepEqual(slide.elements.map(e=>e.id),[ids[2],ids[0],ids[1]])
})
test('每页最多500对象且ID最多200字符，空页顺序允许为空',async()=>{
 const o=await fixture(),slide=o.deck.slides[0]!,base=slide.elements[0]!
 slide.elements=Array.from({length:500},(_,i)=>({...base,id:String(i)}))
 assert.equal(validateElementOrders(o,[{slideIndex:0,elementIds:slide.elements.map(e=>e.id)}]).length,1)
 slide.elements.push({...base,id:'500'})
 assert.throws(()=>validateElementOrders(o,[{slideIndex:0,elementIds:slide.elements.map(e=>e.id)}]))
 for(const length of [200,201]){
  const id='x'.repeat(length);slide.elements=[{...base,id}]
  const validate=()=>validateElementOrders(o,[{slideIndex:0,elementIds:[id]}])
  if(length===200)assert.equal(validate().length,1);else assert.throws(validate)
 }
 slide.elements=[]
 assert.deepEqual(validateElementOrders(o,[{slideIndex:0,elementIds:[]}]),[{slideIndex:0,elementIds:[]}])
})
