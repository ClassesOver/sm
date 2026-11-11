import {afterEach, expect, it} from 'vitest'
import {execFileSync} from 'node:child_process'
import {mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs'
import {tmpdir} from 'node:os'
import {fileURLToPath} from 'node:url'
import {join} from 'node:path'
import {addSlideComment, createBlankPptx, getSlideComments, insertBlankSlide, openPptx, savePptx} from '../src/index'
import {relsPathFor,resolveTarget} from '../src/zip'
import {inspectClassicComments,validateClassicCommentEdits} from '../../../bridge/pptx-comments.ts'

const directories:string[]=[]
afterEach(()=>directories.splice(0).forEach(path=>rmSync(path,{recursive:true,force:true})))
const engineRoot=fileURLToPath(new URL('../../../',import.meta.url))
async function fixture(){
 const opened=await openPptx(await createBlankPptx());insertBlankSlide(opened,0)
 const first=addSlideComment(opened,0,{author:'Alice',text:'中文😀 <&> A'})!
 const second=addSlideComment(opened,0,{author:'Bob',text:'B'})!
 addSlideComment(opened,1,{author:'Alice',text:'第二页'})
 const directory=mkdtempSync(join(tmpdir(),'pptx-comments-bridge-'));directories.push(directory)
 const input=join(directory,'source.pptx');writeFileSync(input,await savePptx(opened))
 return {opened,first,second,directory,input}
}
function bridge(input:string,request:Record<string,unknown>={action:'inspect'}){
 const path=join(input.slice(0,input.lastIndexOf('/')),'request.json')
 writeFileSync(path,JSON.stringify({...request,input}))
 return JSON.parse(execFileSync(process.execPath,[join(engineRoot,'node_modules/tsx/dist/cli.mjs'),join(engineRoot,'bridge/edit-pptx.ts'),path],{encoding:'utf8',timeout:30000}))
}
it('projects real classic comments with author and exact source tuples per original slide',async()=>{
 const f=await fixture(),result=bridge(f.input)
 expect(result.slides[0].comments).toEqual({items:[{...f.first},{...f.second}],readOnlyReason:null})
 expect(result.slides[1].comments.items).toMatchObject([{author:'Alice',text:'第二页'}])
})
it('adds and deletes through the real bridge after reorder while preserving unrelated XML and the other author with equal idx',async()=>{
 const f=await fixture(),output=join(f.directory,'edited.pptx'),a=f.opened.archive
 a.entries.set('custom/preserved.xml',Buffer.from('<custom untouched="yes">中文😀 &amp; $&</custom>'))
 const originalSlide=a.readText(f.opened.deck.slides[0]!.path)
 const originalAuthors=a.readText('ppt/commentAuthors.xml')!
 a.entries.set('ppt/commentAuthors.xml',Buffer.from(originalAuthors.replace('name="Bob"','extra="keep" name="Bob"')))
 writeFileSync(f.input,await savePptx(f.opened))
 bridge(f.input,{action:'edit',output,order:[1,0],commentAuthor:'用户',commentEdits:[{slideIndex:0,kind:'delete',authorId:f.first.authorId,idx:f.first.idx},{slideIndex:0,kind:'add',clientId:'new-root',text:'  用户新增😀 <&> $&\n末行  '}]})
 const reopened=await openPptx(readFileSync(output)),first=getSlideComments(reopened.archive,reopened.deck.slides[0]!.path),second=getSlideComments(reopened.archive,reopened.deck.slides[1]!.path)
 expect(first.map(cm=>cm.text)).toEqual(['第二页'])
 expect(second).toMatchObject([{author:'Bob',idx:1,text:'B'},{author:'用户',text:'  用户新增😀 <&> $&\n末行  '}])
 expect(reopened.archive.readText('custom/preserved.xml')).toBe('<custom untouched="yes">中文😀 &amp; $&</custom>')
 expect(reopened.archive.readText(f.opened.deck.slides[0]!.path)).toBe(originalSlide)
 expect(reopened.archive.readText('ppt/commentAuthors.xml')).toContain('extra="keep" name="Bob"')
 expect(inspectClassicComments(reopened).every(cm=>cm.readOnlyReason===null)).toBe(true)
})
it('deletes the final saved source comment and cleans only its owned part relationship and type',async()=>{
 const f=await fixture(),output=join(f.directory,'deleted.pptx'),slide=f.opened.deck.slides[1]!,rel=[...f.opened.archive.readRels(slide.path).values()].find(r=>r.type.endsWith('/comments'))!,part=resolveTarget(slide.path,rel.target)
 bridge(f.input,{action:'edit',output,commentEdits:[{slideIndex:1,kind:'delete',authorId:0,idx:2}]})
 const reopened=await openPptx(readFileSync(output))
 expect(reopened.archive.has(part)).toBe(false)
 expect(reopened.archive.readText(relsPathFor(slide.path))).not.toContain(rel.id+'" Type="'+rel.type)
 expect(reopened.archive.readText('[Content_Types].xml')).not.toContain('PartName="/'+part+'"')
 expect(getSlideComments(reopened.archive,reopened.deck.slides[0]!.path)).toHaveLength(2)
})
it('validates the entire journal against original unique tuples and never mutates while checking',async()=>{
 const f=await fixture(),a=f.opened.archive,before=[...a.entries].map(([path,bytes])=>[path,Buffer.from(bytes).toString('base64')])
 const add={slideIndex:0,kind:'add',clientId:'add-1',text:'安全文本'}
 const del={slideIndex:0,kind:'delete',authorId:0,idx:1}
 const invalid:any[]=[[add,{...del,idx:999}],[del,del],[add,add],[{...add,slideIndex:2}],[{...add,author:'冒认'}],[{...add,clientId:'非ASCII'}],[{...add,text:' \n '}],[{...add,text:'x'.repeat(10001)}],[{...add,text:'\u0000'}],[{...add,text:'\ud800'}],[{...del,idx:true}],[{...del,authorId:Number.MAX_SAFE_INTEGER+1}]]
 for(const ops of invalid)expect(()=>validateClassicCommentEdits(f.opened,ops,'用户')).toThrow()
 expect(()=>validateClassicCommentEdits(f.opened,[add],'Alice')).toThrow()
 expect(()=>validateClassicCommentEdits(f.opened,[add],'用户',[0])).toThrow()
 expect(()=>validateClassicCommentEdits(f.opened,Array.from({length:501},(_,i)=>({...add,clientId:String(i)})),'用户')).toThrow()
 expect(validateClassicCommentEdits(f.opened,[{...add,text:'\t中文😀\r\n'}],'用户')).toHaveLength(1)
 expect([...a.entries].map(([path,bytes])=>[path,Buffer.from(bytes).toString('base64')])).toEqual(before)
})
it('retains readable classic items while making modern mixed sources readonly',async()=>{
 const f=await fixture(),slide=f.opened.deck.slides[0]!,path=relsPathFor(slide.path),a=f.opened.archive
 a.entries.set(path,Buffer.from(a.readText(path)!.replace('</Relationships>','<Relationship Id="rIdModern" Type="http://schemas.microsoft.com/office/2018/10/relationships/comments" Target="../comments/modern.xml"/></Relationships>')))
 const projection=inspectClassicComments(f.opened)[0]!
 expect(projection.items).toMatchObject([{author:'Alice',text:'中文😀 <&> A'},{author:'Bob',text:'B'}])
 expect(projection.readOnlyReason).toMatch(/现代|未知/)
 expect(()=>validateClassicCommentEdits(f.opened,[{slideIndex:0,kind:'delete',authorId:0,idx:1}],undefined)).toThrow()
})
it.each(['namespace','duplicate tuple','missing author','broken XML','external','duplicate relation','missing part'])('marks %s classic source readonly without throwing inspection',async scenario=>{
 const f=await fixture(),a=f.opened.archive,slide=f.opened.deck.slides[0]!,rp=relsPathFor(slide.path),rel=[...a.readRels(slide.path).values()].find(r=>r.type.endsWith('/comments'))!,part=resolveTarget(slide.path,rel.target),xml=a.readText(part)!
 if(scenario==='namespace')a.entries.set(part,Buffer.from(xml.replace('<p:cm authorId','<p:cm xmlns:p="urn:foreign" authorId')))
 if(scenario==='duplicate tuple')a.entries.set(part,Buffer.from(xml.replace('</p:cmLst>',xml.match(/<p:cm\b[^>]*>[\s\S]*?<\/p:cm>/)![0]+'</p:cmLst>')))
 if(scenario==='missing author')a.entries.set(part,Buffer.from(xml.replace('authorId="0"','authorId="999"')))
 if(scenario==='broken XML')a.entries.set(part,Buffer.from(xml.slice(0,-5)))
 if(scenario==='external')a.entries.set(rp,Buffer.from(a.readText(rp)!.replace('Target="'+rel.target+'"','Target="https://example.test/comments.xml" TargetMode="External"')))
 if(scenario==='duplicate relation')a.entries.set(rp,Buffer.from(a.readText(rp)!.replace('</Relationships>','<Relationship Id="rIdExtra" Type="'+rel.type+'" Target="'+rel.target+'"/></Relationships>')))
 if(scenario==='missing part')a.entries.delete(part)
 expect(inspectClassicComments(f.opened)[0]!.readOnlyReason).toEqual(expect.any(String))
})
it('creates the first classic comment on a blank real source without inventing a saved identity',async()=>{
 const directory=mkdtempSync(join(tmpdir(),'pptx-comments-first-'));directories.push(directory)
 const input=join(directory,'blank.pptx'),output=join(directory,'first.pptx');writeFileSync(input,await createBlankPptx())
 expect(bridge(input).slides[0].comments).toEqual({items:[],readOnlyReason:null})
 bridge(input,{action:'edit',output,commentAuthor:'用户',commentEdits:[{slideIndex:0,kind:'add',clientId:'new-1',text:'第一条中文😀 <&>'}]})
 expect(bridge(output).slides[0].comments).toMatchObject({items:[{author:'用户',text:'第一条中文😀 <&>'}],readOnlyReason:null})
})
it('refuses shared classic parts and preserves opaque root extensions by making only comments readonly',async()=>{
 const f=await fixture(),a=f.opened.archive,slide=f.opened.deck.slides[0]!,rel=[...a.readRels(slide.path).values()].find(r=>r.type.endsWith('/comments'))!,part=resolveTarget(slide.path,rel.target),xml=a.readText(part)!
 a.entries.set(part,Buffer.from(xml.replace('</p:cmLst>','<opaque:metadata xmlns:opaque="urn:preserve" value="keep"/></p:cmLst>')))
 const projection=inspectClassicComments(f.opened)[0]!
 expect(projection.items).toHaveLength(2);expect(projection.readOnlyReason).toContain('未知扩展')
 expect(()=>validateClassicCommentEdits(f.opened,[{slideIndex:0,kind:'delete',authorId:0,idx:1}],undefined)).toThrow()
 expect(a.readText(part)).toContain('<opaque:metadata xmlns:opaque="urn:preserve" value="keep"/>')
 a.entries.set(part,Buffer.from(xml))
 const second=f.opened.deck.slides[1]!,secondRel=[...a.readRels(second.path).values()].find(r=>r.type.endsWith('/comments'))!,rp=relsPathFor(second.path)
 a.entries.set(rp,Buffer.from(a.readText(rp)!.replace('Target="'+secondRel.target+'"','Target="'+rel.target+'"')))
 expect(inspectClassicComments(f.opened).every(cm=>cm.readOnlyReason!==null)).toBe(true)
})
it.each(['empty relationships','rebound relation namespace','spaced nested namespace'])('does not advertise safe comment writes for %s',async scenario=>{
 const f=await fixture(),opened=scenario==='empty relationships'?await openPptx(await createBlankPptx()):f.opened,a=opened.archive,slide=opened.deck.slides[0]!,rp=relsPathFor(slide.path)
 if(scenario==='empty relationships')a.entries.set(rp,Buffer.from('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'))
 if(scenario==='rebound relation namespace')a.entries.set(rp,Buffer.from(a.readText(rp)!.replace('<Relationship Id=','<Relationship xmlns="urn:foreign" Id=')))
 if(scenario==='spaced nested namespace'){const rel=[...a.readRels(slide.path).values()].find(r=>r.type.endsWith('/comments'))!,part=resolveTarget(slide.path,rel.target);a.entries.set(part,Buffer.from(a.readText(part)!.replace('<p:cm authorId','<p:cm xmlns:p = "urn:foreign" authorId')))}
 expect(inspectClassicComments(opened)[0]!.readOnlyReason).toEqual(expect.any(String))
})
