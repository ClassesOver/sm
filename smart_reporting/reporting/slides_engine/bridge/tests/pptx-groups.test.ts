import assert from 'node:assert/strict'
import {test} from 'node:test'
import {addElement,addPicture,createBlankPptx,groupElements,openPptx,reorderElement,savePptx,type GroupElement,type SlideElement} from '@genoffice/pptx-engine'
import {applyGroupEdits,inspectGroupCapabilities,validateGroupEdits} from '../pptx-groups.ts'
const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='
async function fixture(){
 const opened=await openPptx(await createBlankPptx()),slide=opened.deck.slides[0]!
 for(const [i,text] of ['之前','文字','形状'].entries())addElement(slide,{kind:i===2?'rect':'textbox',offset:{x:100+i*1000,y:200,cx:700,cy:800},paragraphs:[{runs:[{text}]}]})
 addPicture(opened,slide,{bytes:Buffer.from(png,'base64'),ext:'png',offset:{x:3300,y:300,cx:500,cy:600}})
 addElement(slide,{kind:'textbox',offset:{x:4100,y:100,cx:500,cy:500},paragraphs:[{runs:[{text:'之后'}]}]})
 return openPptx(await savePptx(opened))
}
async function grouped(){
 const opened=await fixture(),ids=opened.deck.slides[0]!.elements.slice(1,4).map(e=>e.id),result=groupElements(opened,0,ids)!
 while(result.slide.elements[1]!.id!==result.groupId)assert.equal(reorderElement(result.slide,result.groupId,'backward'),true)
 return openPptx(await savePptx(opened))
}
function state(e:SlideElement):unknown{return {type:e.type,transform:e.transform,...(e.type==='picture'?{mediaRef:e.mediaRef}:{text:e.type==='text'||e.type==='shape'?e.text:undefined})}}
test('真实PPTX组合保留连续来源槽位、子顺序、几何和其他部件',async()=>{
 const opened=await fixture(),slide=opened.deck.slides[0]!,elements=slide.elements,ids=elements.slice(1,4).map(e=>e.id),children=elements.slice(1,4).map(state),parts=new Map([...opened.archive.entries.keys()].map(p=>[p,opened.archive.readBytes(p)]))
 assert.equal(inspectGroupCapabilities(opened,0,ids[0]!).groupEditable,true)
 const clicked=[...ids].reverse()
 applyGroupEdits(opened,[{slideIndex:0,kind:'group',elementIds:clicked}])
 assert.deepEqual(clicked,[...ids].reverse())
 const reopened=await openPptx(await savePptx(opened)),actual=reopened.deck.slides[0]!.elements,group=actual[1] as GroupElement
 assert.deepEqual(actual.map(e=>e.type),['text','group','text'])
 assert.deepEqual(group.children.map(state),children)
 assert.equal(actual[0]!.anchor.originalXml,elements[0]!.anchor.originalXml)
 assert.equal(actual[2]!.anchor.originalXml,elements[4]!.anchor.originalXml)
 for(const [path,bytes] of parts)if(path!==slide.path)assert.deepEqual(reopened.archive.readBytes(path),bytes,path)
})
test('真实PPTX取消组合恢复组所在槽位、子顺序与几何',async()=>{
 const opened=await grouped(),slide=opened.deck.slides[0]!,group=slide.elements[1] as GroupElement,children=group.children.map(state),untouched=[slide.elements[0]!.anchor.originalXml,slide.elements[2]!.anchor.originalXml],parts=new Map([...opened.archive.entries.keys()].map(p=>[p,opened.archive.readBytes(p)]))
 assert.equal(inspectGroupCapabilities(opened,0,group.id).ungroupEditable,true)
 applyGroupEdits(opened,[{slideIndex:0,kind:'ungroup',elementId:group.id}])
 const reopened=await openPptx(await savePptx(opened)),actual=reopened.deck.slides[0]!.elements
 assert.deepEqual(actual.slice(1,4).map(state),children)
 assert.equal(actual[0]!.anchor.originalXml,untouched[0])
 assert.equal(actual[4]!.anchor.originalXml,untouched[1])
 for(const [path,bytes] of parts)if(path!==slide.path)assert.deepEqual(reopened.archive.readBytes(path),bytes,path)
})
test('组合请求严格验证schema、来源连续顺序、限额、删除冲突且整批先验证',async()=>{
 const opened=await fixture(),slide=opened.deck.slides[0]!,ids=slide.elements.map(e=>e.id),valid={slideIndex:0,kind:'group' as const,elementIds:ids.slice(1,3)},before=slide.elements.map(e=>e.anchor.originalXml)
 assert.deepEqual(validateGroupEdits(opened,undefined),[])
 assert.deepEqual(validateGroupEdits(opened,[valid]),[valid])
 assert.deepEqual(validateGroupEdits(opened,[{...valid,elementIds:[...valid.elementIds].reverse()}]),[valid])
 for(const input of [null,{},[valid,valid],[{...valid,extra:true}],[{...valid,elementIds:[ids[1]]}],[{...valid,elementIds:[ids[1],ids[1]]}],[{...valid,elementIds:[ids[1],ids[3]]}],[{...valid,elementIds:[ids[1],'unknown']}],[{...valid,elementIds:Array(501).fill(ids[1])}],[{...valid,elementIds:['x'.repeat(201),ids[1]]}],Array(51).fill(valid),[{slideIndex:true,kind:'group',elementIds:ids.slice(1,3)}],[{slideIndex:0,kind:'ungroup',elementId:ids[0],elementIds:[]}]] )assert.throws(()=>validateGroupEdits(opened,input))
 assert.throws(()=>validateGroupEdits(opened,[valid],{deletedSlides:[0]}))
 assert.throws(()=>applyGroupEdits(opened,[valid,{slideIndex:1,kind:'ungroup',elementId:'missing'}]))
 assert.deepEqual(slide.elements.map(e=>e.anchor.originalXml),before)
})
test('页面timing和connector、占位符、旋转翻转与复杂媒体仅可读',async()=>{
 const opened=await fixture(),slide=opened.deck.slides[0]!,targetId=slide.elements[1]!.id,valid={slideIndex:0,kind:'group' as const,elementIds:slide.elements.slice(1,3).map(e=>e.id)}
 for(const change of [()=>{slide.bodySuffix+='<p:timing/>'},()=>{slide.elements[4]!.anchor.originalXml='<p:cxnSp/>'},()=>{slide.elements[1]!.placeholder='body'},()=>{slide.elements[1]!.transform.rot=60000},()=>{slide.elements[1]!.transform.flipH=true},()=>{slide.elements[1]!.dirty=true}]){
  const before=structuredClone(slide);change();const cap=inspectGroupCapabilities(opened,0,targetId)
  assert.equal(cap.groupEditable,false);assert.ok(cap.groupReason);assert.throws(()=>validateGroupEdits(opened,[valid]))
  Object.assign(slide,before)
 }
 const picture=slide.elements[3]!
 if(picture.type==='picture'){picture.media={kind:'video'};assert.equal(inspectGroupCapabilities(opened,0,picture.id).groupEditable,false)}
 assert.equal(inspectGroupCapabilities(opened,99,'missing').groupEditable,false)
})
test('取消组合拒绝缩放坐标、嵌套、组级样式和未完整识别孩子',async()=>{
 const opened=await grouped(),slide=opened.deck.slides[0]!,group=slide.elements[1] as GroupElement
 for(const change of [()=>{group.childOffset!.cx+=1},()=>{group.transform.rot=60000},()=>{group.transform.flipV=true},()=>{group.children[0]!.type='group'},()=>{group.children.pop()},()=>{group.children[0]!.nvId='missing'},()=>{group.children[0]!.transform.flipH=true},()=>{group.anchor.originalXml=group.anchor.originalXml.replace('</p:grpSpPr>','<a:solidFill><a:srgbClr val="FF0000"/></a:solidFill></p:grpSpPr>')},()=>{group.anchor.originalXml=group.anchor.originalXml.replace('</p:grpSp>','<mc:AlternateContent/></p:grpSp>')}]){
  const before=structuredClone(group);change();const cap=inspectGroupCapabilities(opened,0,group.id)
  assert.equal(cap.ungroupEditable,false);assert.ok(cap.ungroupReason);assert.throws(()=>validateGroupEdits(opened,[{slideIndex:0,kind:'ungroup',elementId:group.id}]))
  Object.assign(group,before)
 }
})
test('来源命名空间重绑定不能被当作普通组合对象',async()=>{
 const opened=await fixture(),slide=opened.deck.slides[0]!,namespace='http://schemas.openxmlformats.org/presentationml/2006/main'
 slide.originalXml=slide.originalXml.replace(namespace,'urn:unsupported')
 slide.bodyPrefix=slide.bodyPrefix.replace(namespace,'urn:unsupported')
 const capability=inspectGroupCapabilities(opened,0,slide.elements[1]!.id)
 assert.equal(capability.groupEditable,false)
 assert.ok(capability.groupReason)
})
