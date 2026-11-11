import assert from 'node:assert/strict'
import {test} from 'node:test'
import {addPicture,createBlankPptx,duplicateSlide,getSlideNotes,moveSlide,notesPathForSlide,openPptx,savePptx,setSlideNotes} from '@genoffice/pptx-engine'
import {relsPathFor} from '../../packages/pptx-engine/src/zip.ts'
import {applyNotesEdits,inspectSlideNotes,prepareNotesEdits} from '../pptx-notes.ts'
async function fixture(){
 const opened=await openPptx(await createBlankPptx())
 addPicture(opened,opened.deck.slides[0]!,{bytes:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=','base64'),ext:'png',offset:{x:100,y:200,cx:300,cy:400}})
 duplicateSlide(opened,0)
 return openPptx(await savePptx(opened))
}
test('创建备注规范化换行并保留实体字面值、空格、emoji和未改slide及媒体',async()=>{
 const opened=await fixture(),before=new Map([...opened.archive.entries].filter(([path])=>/^ppt\/(?:slides\/[^/]+\.xml|media\/)/.test(path)))
 assert.deepEqual(inspectSlideNotes(opened,0),{notesText:'',notesEditable:true,notesReason:null})
 const input=[{slideIndex:0,text:' 甲 $& <>& " \' &#10; 😀\r\n\r乙\t \n\n'},{slideIndex:1,text:'第二页'}],copy=structuredClone(input)
 applyNotesEdits(opened,prepareNotesEdits(opened,input))
 assert.deepEqual(input,copy)
 const again=await openPptx(await savePptx(opened))
 assert.equal(inspectSlideNotes(again,0).notesText,' 甲 $& <>& " \' &#10; 😀\n\n乙\t ')
 assert.equal(inspectSlideNotes(again,1).notesText,'第二页')
 assert.equal(inspectSlideNotes(again,0).notesEditable,true)
 for(const [path,bytes] of before)assert.deepEqual(again.archive.readBytes(path),bytes,path)
})
test('替换和清空保留已有非正文占位，空操作不新增或重写包部件',async()=>{
 const opened=await fixture();setSlideNotes(opened,0,'旧备注')
 const path=notesPathForSlide(opened.archive,opened.deck.slides[0]!.path)!,xml=opened.archive.readText(path)!,extra='<p:sp><p:nvSpPr><p:cNvPr id="8" name="页脚"/><p:cNvSpPr/><p:nvPr><p:ph type="ftr"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr b="1"/><a:t>保留页脚</a:t></a:r></a:p></p:txBody></p:sp>'
 opened.archive.entries.set(path,Buffer.from(xml.replace('</p:spTree>',extra+'</p:spTree>')))
 assert.equal(inspectSlideNotes(opened,0).notesEditable,true)
 applyNotesEdits(opened,prepareNotesEdits(opened,[{slideIndex:0,text:'新备注'}]))
 assert.ok(opened.archive.readText(path)!.includes(extra))
 applyNotesEdits(opened,prepareNotesEdits(opened,[{slideIndex:0,text:''}]))
 assert.equal(getSlideNotes(opened.archive,opened.deck.slides[0]!.path),'')
 assert.ok(opened.archive.readText(path)!.includes(extra))
 const parts=new Map(opened.archive.entries)
 applyNotesEdits(opened,prepareNotesEdits(opened,[{slideIndex:0,text:'\n'},{slideIndex:1,text:''}]))
 assert.deepEqual(opened.archive.entries,parts)
})
test('来源part在重排后仍唯一映射，整批预检后项失效不得先写前项',async()=>{
 const opened=await fixture(),paths=opened.deck.slides.map(s=>s.path),prepared=prepareNotesEdits(opened,[{slideIndex:0,text:'原第一页'},{slideIndex:1,text:'原第二页'}])
 moveSlide(opened,0,1);applyNotesEdits(opened,prepared)
 assert.equal(getSlideNotes(opened.archive,opened.deck.slides[0]!.path),'原第二页')
 assert.equal(getSlideNotes(opened.archive,opened.deck.slides[1]!.path),'原第一页')
 const again=prepareNotesEdits(opened,[{slideIndex:0,text:'不应写入'},{slideIndex:1,text:'失效'}]),before=new Map(opened.archive.entries)
 opened.deck.slides[1]!.path=paths[1]!
 assert.throws(()=>applyNotesEdits(opened,again));assert.deepEqual(opened.archive.entries,before)
})
test('拒绝无效schema、预算、XML字符及来源删除复制冲突，保留内部空行',async()=>{
 const opened=await fixture(),valid={slideIndex:0,text:'甲\n\n乙\n'}
 assert.deepEqual(prepareNotesEdits(opened,undefined),[])
 assert.deepEqual(prepareNotesEdits(opened,[valid]),[{sourcePath:opened.deck.slides[0]!.path,text:'甲\n\n乙'}])
 const invalid=[null,{},[null],[{...valid,extra:1}],[{...valid,'#text':' '}],[{slideIndex:0,text:2}],[{slideIndex:true,text:''}],[{slideIndex:2,text:''}],[valid,valid],Array(201).fill(valid),[{slideIndex:0,text:'x'.repeat(20001)}]]
 for(const input of invalid)assert.throws(()=>prepareNotesEdits(opened,input))
 for(const code of [...Array.from({length:32},(_,i)=>i).filter(i=>![9,10,13].includes(i)),0xd800,0xdc00,0xfffe,0xffff])assert.throws(()=>prepareNotesEdits(opened,[{slideIndex:0,text:'a'+String.fromCharCode(code)+'b'}]))
 for(const conflicts of [{deletedSlides:[0]},{newSlides:[{duplicateOf:0}]}])assert.throws(()=>prepareNotesEdits(opened,[valid],conflicts))
 assert.equal(prepareNotesEdits(opened,[valid],{deletedSlides:[1],newSlides:[{layoutFrom:0},{duplicateOf:1}]}).length,1)
 // 原始字符预算先于换行裁剪；总预算按原始UTF-16长度统计。
 const many=await fixture();while(many.deck.slides.length<11)duplicateSlide(many,0)
 assert.throws(()=>prepareNotesEdits(many,Array.from({length:11},(_,slideIndex)=>({slideIndex,text:'\n'.repeat(20000)}))))
})
test('共享notes或畸形关系和namespace只读，不把实际备注伪装为空且不写包',async()=>{
 const opened=await fixture();setSlideNotes(opened,0,'可显示备注');setSlideNotes(opened,1,'另一页')
 const source=opened.deck.slides[0]!,target=opened.deck.slides[1]!,path=notesPathForSlide(opened.archive,source.path)!,targetPath=notesPathForSlide(opened.archive,target.path)!,relsPath=relsPathFor(target.path),rels=opened.archive.readText(relsPath)!
 opened.archive.entries.set(relsPath,Buffer.from(rels.replace(targetPath.split('/').at(-1)!,path.split('/').at(-1)!)))
 assert.equal(inspectSlideNotes(opened,0).notesEditable,false);assert.equal(inspectSlideNotes(opened,0).notesText,'可显示备注')
 assert.throws(()=>prepareNotesEdits(opened,[{slideIndex:0,text:'禁止'}]))
 opened.archive.entries.set(relsPath,Buffer.from(rels))
 const notesXml=opened.archive.readText(path)!,sourceRelsPath=relsPathFor(source.path),sourceRels=opened.archive.readText(sourceRelsPath)!
 for(const broken of [sourceRels.replace('</Relationships>','</Relationships >'),sourceRels.replace('</Relationships>',''),sourceRels.replace(/Id="rId\d+"/,'Id="foreign"')]){opened.archive.entries.set(sourceRelsPath,Buffer.from(broken));assert.equal(inspectSlideNotes(opened,0).notesEditable,false)}
 opened.archive.entries.set(sourceRelsPath,Buffer.from(sourceRels))
 for(const broken of [notesXml.replace('http://schemas.openxmlformats.org/presentationml/2006/main','urn:foreign'),notesXml.replace('</p:notes>',''),notesXml.replace('<p:txBody>','<p:txBody extra="1">')]){opened.archive.entries.set(path,Buffer.from(broken));assert.equal(inspectSlideNotes(opened,0).notesEditable,false)}
})
test('正文富文本、链接、换行字段和重复body保持只读且可展示原生读取内容',async()=>{
 const opened=await fixture();setSlideNotes(opened,0,'原文')
 const path=notesPathForSlide(opened.archive,opened.deck.slides[0]!.path)!,xml=opened.archive.readText(path)!
 const body=/<p:sp>[\s\S]*?<p:ph type="body"[\s\S]*?<\/p:sp>/.exec(xml)!
 for(const changed of [xml.replace('lang="zh-CN" dirty="0"','lang="zh-CN" b="1"'),xml.replace('<a:t>原文</a:t>','<a:t>原文</a:t><a:br/>'),xml.replace('<a:rPr lang="zh-CN" dirty="0"/>','<a:rPr><a:hlinkClick r:id="rId99"/></a:rPr>'),xml.replace('</p:spTree>',body[0]+'</p:spTree>')]){
  opened.archive.entries.set(path,Buffer.from(changed));const state=inspectSlideNotes(opened,0)
  assert.equal(state.notesEditable,false);assert.ok(state.notesReason);assert.equal(state.notesText,getSlideNotes(opened.archive,opened.deck.slides[0]!.path))
  const before=new Map(opened.archive.entries);assert.throws(()=>prepareNotesEdits(opened,[{slideIndex:0,text:'覆盖'}]));assert.deepEqual(opened.archive.entries,before)
 }
})
test('创建前拒绝孤立master、未注册master及原生字面插入锚失效',async()=>{
 for(const part of ['[Content_Types].xml','ppt/_rels/presentation.xml.rels','ppt/presentation.xml']){
  const opened=await fixture(),xml=opened.archive.readText(part)!
  const changed=part==='[Content_Types].xml'?xml.replace('</Types>','</Types >'):part.endsWith('.rels')?xml.replace('</Relationships>','</Relationships >'):xml.replace('</p:sldMasterIdLst>','</p:sldMasterIdLst >').replace('<p:sldIdLst>','<p:sldIdLst >')
  opened.archive.entries.set(part,Buffer.from(changed));assert.equal(inspectSlideNotes(opened,0).notesEditable,false);assert.throws(()=>prepareNotesEdits(opened,[{slideIndex:0,text:'禁止'}]))
 }
 const opened=await fixture();setSlideNotes(opened,0,'已存在')
 const pres=opened.archive.readText('ppt/presentation.xml')!;opened.archive.entries.set('ppt/presentation.xml',Buffer.from(pres.replace(/<p:notesMasterIdLst>[\s\S]*?<\/p:notesMasterIdLst>/,'')))
 assert.equal(inspectSlideNotes(opened,1).notesEditable,false)
 const orphan=await fixture();orphan.archive.entries.set('ppt/notesMasters/notesMaster1.xml',Buffer.from('<p:notesMaster/>'))
 assert.equal(inspectSlideNotes(orphan,0).notesEditable,false)
})
test('缺少a或r命名空间与非法字符实体的来源只读',async()=>{
 const opened=await fixture();setSlideNotes(opened,0,'原文')
 const path=notesPathForSlide(opened.archive,opened.deck.slides[0]!.path)!,xml=opened.archive.readText(path)!
 for(const changed of [xml.replace(/ xmlns:a="[^"]+"/,''),xml.replace(/ xmlns:r="[^"]+"/,''),xml.replace('原文','&#0;')]){
  opened.archive.entries.set(path,Buffer.from(changed));assert.equal(inspectSlideNotes(opened,0).notesEditable,false)
  const before=new Map(opened.archive.entries);assert.throws(()=>prepareNotesEdits(opened,[{slideIndex:0,text:'禁止'}]));assert.deepEqual(opened.archive.entries,before)
 }
})
test('创建前拒绝将被原生复用的错误孤立CT或notes关系，不能先写入后报错',async()=>{
 for(const part of ['ppt/notesSlides/notesSlide1.xml','ppt/notesMasters/notesMaster1.xml','notes-rels']){
  const opened=await fixture()
  if(part==='notes-rels')opened.archive.entries.set('ppt/notesSlides/_rels/notesSlide1.xml.rels',Buffer.from('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="urn:foreign" Target="foreign"/></Relationships>'))
  else{const ct=opened.archive.readText('[Content_Types].xml')!;opened.archive.entries.set('[Content_Types].xml',Buffer.from(ct.replace('</Types>','<Override PartName="/'+part+'" ContentType="urn:foreign"/></Types>')))}
  assert.equal(inspectSlideNotes(opened,0).notesEditable,false)
  const before=new Map(opened.archive.entries);assert.throws(()=>prepareNotesEdits(opened,[{slideIndex:0,text:'禁止'}]));assert.deepEqual(opened.archive.entries,before)
 }
})
test('整批预检第二个新notes分配路径的孤立注册及缺少原生可复用theme',async()=>{
 for(const kind of ['rels','ct','theme']){
  const opened=await fixture()
  if(kind==='rels')opened.archive.entries.set('ppt/notesSlides/_rels/notesSlide2.xml.rels',Buffer.from('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>'))
  if(kind==='ct'){const xml=opened.archive.readText('[Content_Types].xml')!;opened.archive.entries.set('[Content_Types].xml',Buffer.from(xml.replace('</Types>','<Override PartName="/ppt/notesSlides/notesSlide2.xml" ContentType="urn:foreign"/></Types>')))}
  if(kind==='theme')for(const path of opened.archive.entries.keys())if(/^ppt\/theme\/theme\d+\.xml$/.test(path))opened.archive.entries.delete(path)
  const before=new Map(opened.archive.entries)
  assert.throws(()=>prepareNotesEdits(opened,[{slideIndex:0,text:'第一项不可先写'},{slideIndex:1,text:'第二项'}]));assert.deepEqual(opened.archive.entries,before)
 }
 const opened=await fixture(),prepared=prepareNotesEdits(opened,[{slideIndex:0,text:'第一项不可先写'},{slideIndex:1,text:'第二项'}])
 opened.archive.entries.set('ppt/notesSlides/_rels/notesSlide2.xml.rels',Buffer.from('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>'))
 const before=new Map(opened.archive.entries);assert.throws(()=>applyNotesEdits(opened,prepared));assert.deepEqual(opened.archive.entries,before)
})
test('原生二次实体解码与XML真实文本不一致时只读，数字换行与字面实体保持区分',async()=>{
 const opened=await fixture();setSlideNotes(opened,0,'原文')
 const path=notesPathForSlide(opened.archive,opened.deck.slides[0]!.path)!,xml=opened.archive.readText(path)!
 for(const [encoded,editable,text] of [['&#38;lt;',false,'<'],['&#38;quot;',false,'"'],['&#10;',true,'\n'],['&amp;#10;',true,'&#10;'],['&#38;#10;',true,'&#10;']] as const){
  opened.archive.entries.set(path,Buffer.from(xml.replace('原文',encoded)))
  const state=inspectSlideNotes(opened,0);assert.equal(state.notesEditable,editable,encoded);assert.equal(state.notesText,text,encoded)
  const before=new Map(opened.archive.entries)
  if(!editable){assert.match(state.notesReason!,/native_text_mismatch/);assert.throws(()=>prepareNotesEdits(opened,[{slideIndex:0,text:'禁止覆盖'}]));assert.deepEqual(opened.archive.entries,before)}
  else{applyNotesEdits(opened,prepareNotesEdits(opened,[{slideIndex:0,text:'写入 $& &#10; 😀'}]));assert.equal(getSlideNotes(opened.archive,opened.deck.slides[0]!.path),'写入 $& &#10; 😀')}
 }
})
test('超安全整数或临界rId在两项新建备注前整批拒绝，第二项异常不得先写第一项',async()=>{
 for(const part of ['presentation','second-slide'])for(const rid of ['rId9007199254740992','rId9007199254740991']){
  const opened=await fixture(),request=[{slideIndex:0,text:'第一项不可先写'},{slideIndex:1,text:'第二项'}],prepared=prepareNotesEdits(opened,request),path=part==='presentation'?'ppt/presentation.xml':opened.deck.slides[1]!.path,rels=relsPathFor(path),xml=opened.archive.readText(rels)!
  opened.archive.entries.set(rels,Buffer.from(xml.replace('Id="rId1"','Id="'+rid+'"')))
  if(part==='presentation')opened.archive.entries.set(path,Buffer.from(opened.archive.readText(path)!.replace('r:id="rId1"','r:id="'+rid+'"')))
  const before=new Map(opened.archive.entries)
  assert.throws(()=>prepareNotesEdits(opened,request),/relationship_id_capacity/)
  assert.throws(()=>applyNotesEdits(opened,prepared),/relationship_id_capacity/)
  assert.deepEqual(opened.archive.entries,before)
 }
})
