import assert from 'node:assert/strict'
import {test} from 'node:test'
import {addElement,addPicture,copyElementData,createBlankPptx,deleteElement,duplicateSlide,openPptx,pasteElements,savePptx} from '@genoffice/pptx-engine'
const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='
async function fixture(){
 const opened=await openPptx(await createBlankPptx()),slide=opened.deck.slides[0]!
 for(const [i,text] of ['甲','乙'].entries())addElement(slide,{kind:i?'rect':'textbox',offset:{x:9525*(30+i*100),y:9525*40,cx:9525*80,cy:9525*60},paragraphs:[{runs:[{text,bold:true}]}]})
 addPicture(opened,slide,{bytes:Buffer.from(png,'base64'),ext:'png',offset:{x:9525*300,y:9525*40,cx:9525*80,cy:9525*60}})
 duplicateSlide(opened,0)
 return openPptx(await savePptx(opened))
}
test('固定源捕获后先删除唯一来源图片再粘贴可恢复相同媒体路径和bytes',async()=>{
 const opened=await fixture(),source=opened.deck.slides[0]!,picture=source.elements.find(e=>e.type==='picture')!
 if(picture.type!=='picture')throw Error('fixture picture missing')
 // 删除副本图片，保证源图片是媒体最后一个使用者。
 const duplicate=opened.deck.slides[1]!,other=duplicate.elements.find(e=>e.type==='picture')!
 assert.equal(deleteElement(opened,duplicate,other.id),true)
 const item=copyElementData(opened,source,picture),path=picture.mediaRef,bytes=opened.archive.readBytes(path)
 assert.equal(deleteElement(opened,source,picture.id),true)
 assert.equal(opened.archive.readBytes(path),null)
 const pasted=pasteElements(opened,1,[item],{dx:0,dy:0})!
 assert.ok(pasted)
 const reopened=await openPptx(await savePptx(opened)),copy=reopened.deck.slides[1]!.elements.at(-1)!
 assert.equal(copy.type,'picture')
 if(copy.type==='picture'){assert.equal(copy.mediaRef,path);assert.deepEqual(reopened.archive.readBytes(copy.mediaRef),bytes)}
})
import {applyClipboardPastes,inspectClipboardCapabilities,prepareClipboardPastes} from '../pptx-clipboard.ts'
import {relsPathFor} from '../../packages/pptx-engine/src/zip.ts'
test('目标关系合法空白闭标签在prepare和apply前拒绝，不能静默生成悬空图片',async()=>{
 const opened=await fixture(),source=opened.deck.slides[0]!,target=opened.deck.slides[1]!,picture=source.elements.find(e=>e.type==='picture')!,targetPicture=target.elements.find(e=>e.type==='picture')!
 assert.equal(deleteElement(opened,target,targetPicture.id),true)
 const request={sourceSlideIndex:0,elementIds:[picture.id],slideIndex:1,dx:0,dy:0},prepared=prepareClipboardPastes(opened,[request]),path=relsPathFor(target.path),xml=opened.archive.readText(path)!
 assert.ok(xml.includes('</Relationships>'))
 opened.archive.entries.set(path,Buffer.from(xml.replace('</Relationships>','</Relationships >')))
 const elements=target.elements.map(e=>e.anchor.originalXml),parts=new Map([...opened.archive.entries].map(([path,bytes])=>[path,bytes]))
 assert.throws(()=>prepareClipboardPastes(opened,[request]),/clipboard_paste_target_relationships_invalid/)
 assert.throws(()=>applyClipboardPastes(opened,prepared),/clipboard_paste_target_relationships_invalid/)
 assert.deepEqual(target.elements.map(e=>e.anchor.originalXml),elements)
 assert.deepEqual(opened.archive.entries,parts)
})
test('prepare捕获来源顺序及copy-at-time，末尾按目标part定位追加并换新身份',async()=>{
 const opened=await fixture(),source=opened.deck.slides[0]!,ids=source.elements.map(e=>e.id),before=source.elements.map(e=>e.anchor.originalXml),targetPath=opened.deck.slides[1]!.path
 const request={sourceSlideIndex:0,elementIds:[...ids].reverse(),slideIndex:1,dx:20,dy:10}
 assert.equal(inspectClipboardCapabilities(opened,0,ids[0]!).clipboardEditable,true)
 const prepared=prepareClipboardPastes(opened,[request])
 source.elements[0]!.anchor.originalXml=source.elements[0]!.anchor.originalXml.replace('甲','后来修改')
 opened.deck.slides.reverse()
 applyClipboardPastes(opened,prepared)
 const reopened=await openPptx(await savePptx(opened)),target=reopened.deck.slides.find(s=>s.path===targetPath)!,copies=target.elements.slice(-3)
 assert.deepEqual(copies.map(e=>e.type),['text','shape','picture'])
 assert.ok(copies[0]!.anchor.originalXml.includes('甲'));assert.ok(!copies[0]!.anchor.originalXml.includes('后来修改'))
 for(const [i,copy] of copies.entries()){
  assert.equal(copy.transform.offset.x,source.elements[i]!.transform.offset.x+20*9525)
  assert.equal(copy.transform.offset.y,source.elements[i]!.transform.offset.y+10*9525)
  assert.notEqual(copy.anchor.originalXml,before[i])
 }
 assert.deepEqual(request.elementIds,[...ids].reverse())
})
test('prepare内存媒体快照支持所有来源对象先删除再paste，保留媒体身份',async()=>{
 const opened=await fixture(),source=opened.deck.slides[0]!,ids=source.elements.map(e=>e.id),picture=source.elements.find(e=>e.type==='picture')!
 if(picture.type!=='picture')throw Error('missing image')
 const media=opened.archive.readBytes(picture.mediaRef),path=picture.mediaRef
 const other=opened.deck.slides[1]!,otherPicture=other.elements.find(e=>e.type==='picture')!
 deleteElement(opened,other,otherPicture.id)
 const prepared=prepareClipboardPastes(opened,[{sourceSlideIndex:0,elementIds:ids,slideIndex:1,dx:0,dy:0}],{deletions:ids.map(elementId=>({slideIndex:0,elementId}))})
 for(const id of ids)assert.equal(deleteElement(opened,source,id),true)
 assert.equal(opened.archive.readBytes(path),null)
 applyClipboardPastes(opened,prepared)
 const reopened=await openPptx(await savePptx(opened)),copy=reopened.deck.slides[1]!.elements.at(-1)!
 assert.equal(reopened.deck.slides[0]!.elements.length,0)
 if(copy.type!=='picture')throw Error('missing pasted image')
 assert.equal(copy.mediaRef,path);assert.deepEqual(reopened.archive.readBytes(path),media)
})
test('请求严格完整校验schema、ID、限额与像素偏移，拒绝整批而非部分成功',async()=>{
 const opened=await fixture(),ids=opened.deck.slides[0]!.elements.map(e=>e.id),valid={sourceSlideIndex:0,elementIds:ids,slideIndex:1,dx:20,dy:20}
 assert.deepEqual(prepareClipboardPastes(opened,undefined),[])
 for(const bad of [null,{},[null],[{...valid,xml:'<p:sp/>'}],[{...valid,sourceSlideIndex:true}],[{...valid,slideIndex:99}],[{...valid,elementIds:[]}],[{...valid,elementIds:[ids[0],ids[0]]}],[{...valid,elementIds:[ids[0],'unknown']}],[{...valid,dx:NaN}],[{...valid,dy:Infinity}],[{...valid,dx:100001}],Array(51).fill(valid),Array.from({length:50},()=>({...valid,elementIds:Array.from({length:11},(_,i)=>String(i))}))])assert.throws(()=>prepareClipboardPastes(opened,bad))
 const before=opened.deck.slides.map(s=>s.elements.map(e=>e.anchor.originalXml))
 assert.throws(()=>prepareClipboardPastes(opened,[valid,{...valid,elementIds:['unknown']}]))
 assert.deepEqual(opened.deck.slides.map(s=>s.elements.map(e=>e.anchor.originalXml)),before)
})
test('涉及来源和目标页的结构修改互斥，但cut删除和其他页修改不阻断',async()=>{
 const opened=await fixture(),ids=opened.deck.slides[0]!.elements.map(e=>e.id),record={sourceSlideIndex:0,elementIds:ids,slideIndex:1,dx:0,dy:0}
 for(const conflicts of [{deletedSlides:[0]},{deletedSlides:[1]},{groupEdits:[{slideIndex:1}]},{resetLayouts:[0]},{slideLayouts:[{slideIndex:1}]},{newSlides:[{duplicateOf:0}]},{newSlides:[{layoutFrom:1}]},{theme:'modern'},{slideSize:{}},{headerFooter:{}}])assert.throws(()=>prepareClipboardPastes(opened,[record],conflicts))
 assert.equal(prepareClipboardPastes(opened,[record],{deletions:[{slideIndex:0,elementId:ids[0]}],resetLayouts:[9]}).length,1)
})
test('不安全来源只读，全部目标part在写前检查，其他part保持字节身份',async()=>{
 const opened=await fixture(),source=opened.deck.slides[0]!,id=source.elements[0]!.id,record={sourceSlideIndex:0,elementIds:[id],slideIndex:1,dx:0,dy:0}
 for(const change of [()=>{source.elements[0]!.placeholder='body'},()=>{source.elements[0]!.transform.rot=60000},()=>{source.elements[0]!.anchor.originalXml=source.elements[0]!.anchor.originalXml.replace('</p:cNvPr>','<a:hlinkClick r:id="rId9"/></p:cNvPr>')},()=>{source.elements[0]!.dirty=true}]){
  const before=structuredClone(source);change();assert.equal(inspectClipboardCapabilities(opened,0,id).clipboardEditable,false);assert.throws(()=>prepareClipboardPastes(opened,[record]));Object.assign(source,before)
 }
 const prepared=prepareClipboardPastes(opened,[record]),before=new Map([...opened.archive.entries].map(([path,bytes])=>[path,bytes]))
 const target=opened.deck.slides[1]!.path
 opened.deck.slides[1]!.path='ppt/slides/missing.xml'
 assert.throws(()=>applyClipboardPastes(opened,prepared))
 opened.deck.slides[1]!.path=target
 applyClipboardPastes(opened,prepared)
 const reopened=await openPptx(await savePptx(opened))
 for(const [path,bytes] of before)if(path!==target)assert.deepEqual(reopened.archive.readBytes(path),bytes,path)
})
test('跨页来源与目标母版或主题链不同必须拒绝',async()=>{
 const opened=await fixture(),source=opened.deck.slides[0]!,target=opened.deck.slides[1]!,chain=opened.archive.resolveSlideChain(target.path),rels='ppt/slides/_rels/'+target.path.split('/').at(-1)+'.rels'
 assert.ok(chain.layoutPath&&chain.masterPath&&chain.themePath)
 const layoutPath='ppt/slideLayouts/clipboard-alt-layout.xml',masterPath='ppt/slideMasters/clipboard-alt-master.xml'
 const layoutRels='ppt/slideLayouts/_rels/'+chain.layoutPath.split('/').at(-1)+'.rels',masterRels='ppt/slideMasters/_rels/'+chain.masterPath.split('/').at(-1)+'.rels'
 opened.archive.entries.set(layoutPath,opened.archive.readBytes(chain.layoutPath)!)
 opened.archive.entries.set('ppt/slideLayouts/_rels/clipboard-alt-layout.xml.rels',Buffer.from(opened.archive.readText(layoutRels)!.replace('../slideMasters/'+chain.masterPath.split('/').at(-1),'../slideMasters/clipboard-alt-master.xml')))
 opened.archive.entries.set(masterPath,opened.archive.readBytes(chain.masterPath)!)
 opened.archive.entries.set('ppt/slideMasters/_rels/clipboard-alt-master.xml.rels',Buffer.from(opened.archive.readText(masterRels)!))
 opened.archive.entries.set(rels,Buffer.from(opened.archive.readText(rels)!.replace('../slideLayouts/'+chain.layoutPath.split('/').at(-1),'../slideLayouts/clipboard-alt-layout.xml')))
 assert.notEqual(opened.archive.resolveSlideChain(source.path).masterPath,opened.archive.resolveSlideChain(target.path).masterPath)
 assert.throws(()=>prepareClipboardPastes(opened,[{sourceSlideIndex:0,elementIds:[source.elements[0]!.id],slideIndex:1,dx:20,dy:20}]))
})
