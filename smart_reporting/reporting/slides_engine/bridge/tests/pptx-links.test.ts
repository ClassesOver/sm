import assert from 'node:assert/strict'
import {test} from 'node:test'
import {addElement,addPicture,createBlankPptx,duplicateSlide,elementSpid,ensureRunLinkRels,getElementLink,getRunLinks,moveSlide,openPptx,savePptx,setElementLink} from '@genoffice/pptx-engine'
import {relsPathFor} from '../../packages/pptx-engine/src/zip.ts'
import {applyLinkEdits,inspectLinkCapabilities,prepareLinkEdits} from '../pptx-links.ts'
async function fixture(){const o=await openPptx(await createBlankPptx());for(const text of ['甲','乙'])addElement(o.deck.slides[0]!,{kind:'textbox',offset:{x:100,y:200,cx:300,cy:400},paragraphs:[{runs:[{text}]}]});duplicateSlide(o,0);return openPptx(await savePptx(o))}
test('同页多对象链接经ID重建、页面重排和真实保存仍定位正确，未触及部件保持',async()=>{
 const o=await fixture(),source=o.deck.slides[0]!,ids=source.elements.map(e=>e.id),spids=source.elements.map(elementSpid),parts=new Map([...o.archive.entries.keys()].map(p=>[p,o.archive.readBytes(p)]))
 const prepared=prepareLinkEdits(o,[{slideIndex:0,elementId:ids[0],target:{kind:'url',url:' https://example.com/?a=1&b=2 '}},{slideIndex:0,elementId:ids[1],target:{kind:'slide',slideIndex:1}}])
 const text=source.elements[0]!;if(text.type!=='text')throw Error('fixture');text.text!.paragraphs[0]!.runs[0]!.text='内容修改';text.dirty=true;text.transform.offset.x=2000;text.dirtyTransform=true
 moveSlide(o,0,1);applyLinkEdits(o,prepared)
 const again=await openPptx(await savePptx(o)),slide=again.deck.slides[1]!
 assert.deepEqual(getElementLink(again,1,slide.elements.find(e=>elementSpid(e)===spids[0])!.id),{kind:'url',url:'https://example.com/?a=1&b=2'})
 assert.deepEqual(getElementLink(again,1,slide.elements.find(e=>elementSpid(e)===spids[1])!.id),{kind:'slide',slideIndex:0})
 const changed=slide.elements.find(e=>elementSpid(e)===spids[0])!;assert.equal(changed.transform.offset.x,2000);if(changed.type!=='text')throw Error('fixture');assert.equal(changed.text!.paragraphs[0]!.runs[0]!.text,'内容修改')
 for(const [path,bytes] of parts)if(![source.path,relsPathFor(source.path),'ppt/presentation.xml'].includes(path))assert.deepEqual(again.archive.readBytes(path),bytes,path)
})
test('替换/移除保留ScreenTip、hover与仍共用的关系，空操作不重建',async()=>{
 let o=await fixture(),id=o.deck.slides[0]!.elements[0]!.id
 setElementLink(o,0,id,{kind:'url',url:'https://old.example/',tooltip:'A & B <提示>'})
 let slide=o.deck.slides[0]!,target=slide.elements[0]!,rid=/r:id="([^"]+)"/.exec(target.anchor.originalXml)![1]!
 target.anchor.originalXml=target.anchor.originalXml.replace('</p:cNvPr>','<a:hlinkHover r:id="'+rid+'" tooltip="hover"/></p:cNvPr>')
 slide.structureDirty=true;o=await openPptx(await savePptx(o));slide=o.deck.slides[0]!;id=slide.elements[0]!.id
 assert.equal(inspectLinkCapabilities(o,0,id).linkEditable,true)
 applyLinkEdits(o,prepareLinkEdits(o,[{slideIndex:0,elementId:id,target:{kind:'url',url:'https://new.example/'}}]))
 slide=o.deck.slides[0]!;assert.deepEqual(getElementLink(o,0,slide.elements[0]!.id),{kind:'url',url:'https://new.example/',tooltip:'A & B <提示>'});assert.ok(slide.elements[0]!.anchor.originalXml.includes('<a:hlinkHover r:id="'+rid+'" tooltip="hover"/>'));assert.ok(o.archive.readRels(slide.path).has(rid))
 const same=slide;applyLinkEdits(o,prepareLinkEdits(o,[{slideIndex:0,elementId:slide.elements[0]!.id,target:{kind:'url',url:'https://new.example/'}}]));assert.equal(o.deck.slides[0],same)
 applyLinkEdits(o,prepareLinkEdits(o,[{slideIndex:0,elementId:slide.elements[0]!.id,target:null}]));assert.equal(getElementLink(o,0,o.deck.slides[0]!.elements[0]!.id),null);assert.ok(o.archive.readRels(slide.path).has(rid))
})
test('含段内链接只读，不能删除或误认文字链接为对象链接',async()=>{
 let o=await fixture(),e=o.deck.slides[0]!.elements[0]!
 if(e.type!=='text')throw Error('fixture');const run=e.text!.paragraphs[0]!.runs[0]!;run.hyperlink='https://run.example/';delete run.hyperlinkRId;ensureRunLinkRels(o,0,e.text!.paragraphs);e.dirty=true
 o=await openPptx(await savePptx(o));e=o.deck.slides[0]!.elements[0]!
 const capability=inspectLinkCapabilities(o,0,e.id);assert.equal(capability.linkEditable,false);assert.equal(capability.elementLink,null);assert.ok(capability.linkReason)
 assert.throws(()=>prepareLinkEdits(o,[{slideIndex:0,elementId:e.id,target:null}]));assert.equal(getRunLinks(o,0).length,1)
})
test('整批拒绝非法schema、危险网址、来源删除/复制/组合冲突，绝不先改前项',async()=>{
 const o=await fixture(),ids=o.deck.slides[0]!.elements.map(e=>e.id),valid={slideIndex:0,elementId:ids[0]!,target:{kind:'url',url:'https://example.com/'}}
 assert.deepEqual(prepareLinkEdits(o,undefined),[])
 for(const input of [null,{},[valid,valid],Array(51).fill(valid),[{...valid,extra:1}],[{...valid,target:{kind:'url',url:'file:///tmp/x'}}],[{...valid,target:{kind:'url',url:'https://exa\nmple.com'}}],[{...valid,target:{kind:'slide',slideIndex:99}}],[{...valid,target:{kind:'action',action:'endshow'}}],[{...valid,target:{kind:'url',url:'https://x/',tooltip:'x'}}],[valid,{...valid,elementId:'missing'}]])assert.throws(()=>prepareLinkEdits(o,input))
 for(const conflicts of [{deletedSlides:[0]},{deletions:[{slideIndex:0,elementId:ids[0]!}]},{groupEdits:[{slideIndex:0}]},{newSlides:[{duplicateOf:0}]}])assert.throws(()=>prepareLinkEdits(o,[valid],conflicts))
 assert.throws(()=>prepareLinkEdits(o,[{...valid,target:{kind:'slide',slideIndex:1}}],{deletedSlides:[1]}))
 assert.equal(getElementLink(o,0,ids[0]!),null)
 const prepared=prepareLinkEdits(o,[valid,{...valid,elementId:ids[1]!,target:null}]);o.deck.slides[0]!.elements.pop();assert.throws(()=>applyLinkEdits(o,prepared));assert.equal(getElementLink(o,0,ids[0]!),null)
})
test('复杂链接、命名动作、namespace重绑定和损坏/非标准关系保持只读',async()=>{
 let o=await fixture();setElementLink(o,0,o.deck.slides[0]!.elements[0]!.id,{kind:'url',url:'https://old.example/'})
 const slide=o.deck.slides[0]!,e=slide.elements[0]!,original=e.anchor.originalXml,path=relsPathFor(slide.path),rels=o.archive.readText(path)!
 for(const xml of [original.replace('<a:hlinkClick ','<a:hlinkClick history="1" '),original.replace(/<a:hlinkClick\b[^>]*\/>/,match=>match.slice(0,-2)+'><a:snd r:embed="rId1"/></a:hlinkClick>'),original.replace('<a:hlinkClick ','<a:hlinkClick xmlns:a="urn:foreign" '),original.replace(/r:id="rId\d+"/,'r:id="custom"')]){assert.notEqual(xml,original);e.anchor.originalXml=xml;assert.equal(inspectLinkCapabilities(o,0,e.id).linkEditable,false)}
 e.anchor.originalXml=original
 for(const xml of [rels.replace('</Relationships>',''),rels.replace('TargetMode="External"','TargetMode="Internal"'),rels.replace('http://schemas.openxmlformats.org/package/2006/relationships','urn:foreign'),rels.replace('</Relationships>','<Relationship Id="rId1" Type="x" Target="x"/></Relationships>')]){o.archive.entries.set(path,Buffer.from(xml));assert.equal(inspectLinkCapabilities(o,0,e.id).linkEditable,false)}
 o.archive.entries.set(path,Buffer.from(rels));setElementLink(o,0,e.id,{kind:'action',action:'nextslide'});assert.equal(inspectLinkCapabilities(o,0,o.deck.slides[0]!.elements[0]!.id).linkEditable,false)
})
test('网址拒绝所有C0/C1和反斜杠，不误拒合法u/0/7/f',async()=>{
 const opened=await fixture(),elementId=opened.deck.slides[0]!.elements[0]!.id
 for(const code of [...Array.from({length:32},(_,i)=>i),...Array.from({length:33},(_,i)=>127+i),92])assert.throws(()=>prepareLinkEdits(opened,[{slideIndex:0,elementId,target:{kind:'url',url:'https://example.com/a'+String.fromCharCode(code)+'z'}}]))
 for(const value of ['https://u07f.example/a?u=007f&x=%20','http://example.com/','mailto:u07f@example.com'])assert.deepEqual(prepareLinkEdits(opened,[{slideIndex:0,elementId,target:{kind:'url',url:value}}])[0]!.target,{kind:'url',url:value})
})
test('静态形状和裁剪图片链接往返保留非链接XML及媒体字节',async()=>{
 let opened=await openPptx(await createBlankPptx()),slide=opened.deck.slides[0]!
 addElement(slide,{kind:'rect',offset:{x:100,y:200,cx:700,cy:800},paragraphs:[{runs:[{text:'形状链接'}]}]})
 addPicture(opened,slide,{bytes:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=','base64'),ext:'png',offset:{x:1200,y:300,cx:900,cy:600},descr:'裁剪原图'})
 const picture=slide.elements[1]!,crop='<a:srcRect l="1200" t="2300" r="3400" b="4500"/>'
 assert.ok(picture.anchor.originalXml.includes('<a:stretch>'))
 picture.anchor.originalXml=picture.anchor.originalXml.replace('<a:stretch>',crop+'<a:stretch>');slide.structureDirty=true
 opened=await openPptx(await savePptx(opened));slide=opened.deck.slides[0]!
 const strip=(xml:string)=>xml.replace(/<p:cNvPr\b[^>]*(?:\/>|>[\s\S]*?<\/p:cNvPr>)/,'')
 const before=slide.elements.map(e=>({type:e.type,transform:structuredClone(e.transform),descr:e.descr,xml:strip(e.anchor.originalXml)})),media=new Map([...opened.archive.entries.keys()].filter(path=>path.startsWith('ppt/media/')).map(path=>[path,opened.archive.readBytes(path)]))
 assert.deepEqual(slide.elements.map(e=>e.type),['shape','picture'])
 for(const e of slide.elements)assert.equal(inspectLinkCapabilities(opened,0,e.id).linkEditable,true)
 applyLinkEdits(opened,prepareLinkEdits(opened,slide.elements.map((e,i)=>({slideIndex:0,elementId:e.id,target:{kind:'url',url:'https://example.com/'+i}}))))
 const again=await openPptx(await savePptx(opened)),after=again.deck.slides[0]!.elements
 assert.deepEqual(after.map(e=>({type:e.type,transform:e.transform,descr:e.descr,xml:strip(e.anchor.originalXml)})),before)
 assert.ok(after[1]!.anchor.originalXml.includes(crop))
 for(const [i,e] of after.entries())assert.deepEqual(getElementLink(again,0,e.id),{kind:'url',url:'https://example.com/'+i})
 for(const [path,bytes] of media)assert.deepEqual(again.archive.readBytes(path),bytes,path)
})
