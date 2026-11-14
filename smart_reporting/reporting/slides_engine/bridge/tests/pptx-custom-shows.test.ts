import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createBlankPptx,openPptx,savePptx,insertBlankSlide,moveSlide,deleteSlide} from '@genoffice/pptx-engine'
import * as custom from '../pptx-custom-shows.ts'
function put(o:any,p:string,s:string){o.archive.entries.set(p,new Uint8Array(Buffer.from(s)))}
async function deck(){const o=await openPptx(await createBlankPptx());insertBlankSlide(o,0);insertBlankSlide(o,1);return o}
test('完整自定义列表持久化真实presentation关系，重复页/已有show保留，重排不改引用',async()=>{
 const o=await deck(),paths=o.deck.slides.map(s=>s.path),before=o.archive.readText('ppt/_rels/presentation.xml.rels')
 const bound=custom.prepareCustomShows(o,[{id:'cs-new',name:'重点 <&>😀',slideIndices:[2,0,2]},{id:'cs-other',name:'保留',slideIndices:[1]}])
 await custom.applyCustomShows(o,bound);const saved=await openPptx(await savePptx(o))
 assert.deepEqual(custom.inspectCustomShows(saved).customShows.map(s=>({name:s.name,slideIndices:s.slideIndices})),[{name:'重点 <&>😀',slideIndices:[2,0,2]},{name:'保留',slideIndices:[1]}]);assert.equal(saved.archive.readText('ppt/_rels/presentation.xml.rels'),before)
 moveSlide(saved,2,0);await custom.applyCustomShows(saved,custom.prepareCustomShows(saved,undefined));const reordered=await openPptx(await savePptx(saved));assert.deepEqual(custom.inspectCustomShows(reordered).customShows[0]!.slideIndices,[0,1,0]);assert.equal(reordered.deck.slides[0]!.path,paths[2])
 const next=custom.prepareCustomShows(reordered,undefined);deleteSlide(reordered,0);await custom.applyCustomShows(reordered,next);const deleted=await openPptx(await savePptx(reordered));assert.deepEqual(custom.inspectCustomShows(deleted).customShows.map(s=>s.slideIndices),[[0],[1]])
})
test('未知扩展和未修改show原XML保留，客户端路径/非法身份拒绝，引用show不能删除',async()=>{
 const o=await deck();await custom.applyCustomShows(o,custom.prepareCustomShows(o,[{id:'cs-a',name:'A',slideIndices:[0]},{id:'cs-b',name:'B',slideIndices:[1]}]));const shows=custom.inspectCustomShows(o).customShows
 const p='ppt/presentation.xml',xml=o.archive.readText(p)!;put(o,p,xml.replace('</p:custShow>','<p:extLst><p:ext uri="keep"/></p:extLst></p:custShow>'))
 const plan=custom.prepareCustomShows(o,shows.map((s,i)=>({...s,name:i?'新B':s.name})));await custom.applyCustomShows(o,plan);assert.match(o.archive.readText(p)!,/uri="keep"/)
 for(const bad of [[{...shows[0],mediaPath:'/tmp/x'}],[{...shows[0],slideIndices:[99]}],[{...shows[0],id:'999'}],[{...shows[0],name:'bad\u0000'}]])assert.throws(()=>custom.prepareCustomShows(o,bad))
 const slide=o.deck.slides[0]!.path;put(o,slide,o.archive.readText(slide)!.replace('</p:sld>','<p:extLst><p:ext uri="ref"><a:hlinkClick action="ppaction://customshow?id='+shows[0]!.id+'"/></p:ext></p:extLst></p:sld>'));assert.throws(()=>custom.prepareCustomShows(o,[shows[1]!]),/referenced/)
})
test('空列表/空放映及美元名称可写，未知XML保留，损坏关系不伪装可编辑',async()=>{
 const o=await deck();await custom.applyCustomShows(o,custom.prepareCustomShows(o,[{id:'cs-a',name:'$& $1 <&>',slideIndices:[]}]))
 const saved=await openPptx(await savePptx(o));assert.equal(custom.inspectCustomShows(saved).customShows[0]!.name,'$& $1 <&>');assert.deepEqual(custom.inspectCustomShows(saved).customShows[0]!.slideIndices,[])
 await custom.applyCustomShows(saved,custom.prepareCustomShows(saved,[]));assert.deepEqual(custom.inspectCustomShows(saved).customShows,[])
 const xml=saved.archive.readText('ppt/presentation.xml')!;put(saved,'ppt/presentation.xml',xml.replace('</p:presentation>','<p:custShowLst><p:custShow name="bad" id="3"><p:sldLst><p:sld r:id="rId9999"/></p:sldLst></p:custShow></p:custShowLst></p:presentation>'));assert.equal(custom.inspectCustomShows(saved).customShowsEditable,false);assert.throws(()=>custom.prepareCustomShows(saved,[]),/relationship/)
})
test('已有show重命名美元序列不被String.replace当替换表达式',async()=>{
 const o=await deck();await custom.applyCustomShows(o,custom.prepareCustomShows(o,[{id:'cs-a',name:'旧',slideIndices:[0]}]));const list=custom.inspectCustomShows(o).customShows;list[0]!.name='$& $1';await custom.applyCustomShows(o,custom.prepareCustomShows(o,list));assert.equal(custom.inspectCustomShows(o).customShows[0]!.name,'$& $1')
})

test('空源列表可编辑，命名空间伪装/重复关系拒绝，默认放映引用不能悬空',async()=>{
 const o=await deck(),p='ppt/presentation.xml',base=o.archive.readText(p)!
 put(o,p,base.replace('</p:presentation>','<p:custShowLst/></p:presentation>'));assert.equal(custom.inspectCustomShows(o).customShowsEditable,true)
 await custom.applyCustomShows(o,custom.prepareCustomShows(o,[{id:'cs-active',name:'默认',slideIndices:[0]}]));const shows=custom.inspectCustomShows(o).customShows
 put(o,'ppt/presProps.xml','<p:presentationPr xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:showPr><p:custShow id="'+shows[0]!.id+'"/></p:showPr></p:presentationPr>');assert.throws(()=>custom.prepareCustomShows(o,[]),/referenced/)
 const xml=o.archive.readText(p)!;put(o,p,xml.replace('<p:custShow ', '<p:custShow xmlns:p="urn:foreign" '));assert.equal(custom.inspectCustomShows(o).customShowsEditable,false);put(o,p,xml)
 const rel='ppt/_rels/presentation.xml.rels',rels=o.archive.readText(rel)!,first=rels.match(/<Relationship\b[^>]*\/>/)![0];put(o,rel,rels.replace('</Relationships>',first+'</Relationships>'));assert.equal(custom.inspectCustomShows(o).customShowsEditable,false)
})
