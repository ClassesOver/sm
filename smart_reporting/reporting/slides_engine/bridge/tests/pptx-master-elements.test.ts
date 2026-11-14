import assert from 'node:assert/strict'
import { test } from 'node:test'
import { mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { join } from 'node:path'
import { addElement, createBlankPptx, elementSpid, listMasterParts, openPptx, parseMasterPart, patchSlideXml, savePptx } from '@genoffice/pptx-engine'
import { runTxn } from '../../packages/pptx-ops/src/index.ts'

const evidence='/dev/shm/office-next-pptx-master-structure-20261113'
const build=mkdtemp('/dev/shm/pptx-master-elements-').then(dir=>{
  const result=spawnSync('node_modules/.bin/esbuild',['bridge/edit-pptx.ts','--bundle','--platform=node','--format=esm','--loader:.md=text',`--outfile=${join(dir,'edit.mjs')}`,'--log-level=error','--banner:js=import { createRequire } from "node:module"; const require = createRequire(import.meta.url);'],{encoding:'utf8'})
  assert.equal(result.status,0,result.stderr);return join(dir,'edit.mjs')
})
async function bridge(input:Uint8Array,patch?:object){
 const dir=await mkdtemp('/dev/shm/pptx-master-elements-call-'),source=join(dir,'source.pptx'),output=join(dir,'output.pptx'),request=join(dir,'request.json')
 await writeFile(source,input);await writeFile(request,JSON.stringify({action:patch?'edit':'inspect',input:source,output,...patch}))
 const result=spawnSync(process.execPath,[await build,request],{encoding:'utf8'})
 return{result,output,model:result.status===0?JSON.parse(result.stdout):undefined}
}
async function fixture(){
 const opened=await openPptx(await createBlankPptx())
 const parts=listMasterParts(opened.archive)
 for(const part of parts){const slide=parseMasterPart(opened.archive,part.partPath)!;addElement(slide,{kind:'textbox',offset:{x:500000,y:500000,cx:5000000,cy:1000000},paragraphs:[{runs:[{text:`${part.kind}旧品牌`,bold:true}]}]});opened.archive.entries.set(part.partPath,Buffer.from(patchSlideXml(slide)))}
 return openPptx(await savePptx(opened))
}
test('实际母版文字框增删与源part事务等价，只触及目标master/layout并刷新继承',async()=>{
 const opened=await fixture(),bytes=await savePptx(opened),parts=listMasterParts(opened.archive),master=parts.find(p=>p.kind==='master')!,layout=parts.find(p=>p.kind==='layout')!
 const spid=elementSpid(parseMasterPart(opened.archive,layout.partPath)!.elements.at(-1)!)!
 const inspected=await bridge(bytes);assert.equal(inspected.result.status,0,inspected.result.stderr);assert.equal(inspected.model.masterTextParts.find((p:any)=>p.partPath===master.partPath).structureEditable,true)
 const edits=[{kind:'addTextBox',partPath:master.partPath,clientId:'new-brand',text:'新增品牌 <&>😀\n第二行',box:{x:48,y:500,width:480,height:96}},{kind:'delete',partPath:layout.partPath,spid}]
 const result=await bridge(bytes,{masterElementEdits:edits});assert.equal(result.result.status,0,result.result.stderr)
 const actual=await openPptx(await readFile(result.output)),expected=await openPptx(bytes)
 assert.equal(runTxn(expected,{ops:[{op:'addElement',target:{part:master.partPath},kind:'textbox',offset:{x:48*9525,y:500*9525,cx:480*9525,cy:96*9525},paragraphs:[{runs:[{text:'新增品牌 <&>😀'}]},{runs:[{text:'第二行'}]}],bodyPr:{wrap:'none',autoFit:'resize'}},{op:'deleteElement',target:{part:layout.partPath,el:`e_${spid}`}}]}).applied,true)
 for(const part of parts){const a=parseMasterPart(actual.archive,part.partPath)!,e=parseMasterPart(expected.archive,part.partPath)!;assert.deepEqual(a.elements.map(el=>({type:el.type,transform:el.transform,text:'text'in el?el.text:null})),e.elements.map(el=>({type:el.type,transform:el.transform,text:'text'in el?el.text:null})))}
 const targets=new Set([master.partPath,layout.partPath]);for(const [path,original]of opened.archive.entries)if(!targets.has(path))assert.deepEqual(actual.archive.readBytes(path),original,path)
 assert(actual.deck.slides[0]!.decorations?.some(el=>'text'in el&&el.text?.paragraphs.some(p=>p.runs.some(r=>r.text.includes('新增品牌')))))
 await mkdir(evidence,{recursive:true});await writeFile(join(evidence,'source.pptx'),bytes);await writeFile(join(evidence,'output.pptx'),await readFile(result.output));await writeFile(join(evidence,'engine-edits.json'),JSON.stringify(edits,null,2))
})
test('既有母版几何经源setTransform事务回写位置尺寸与旋转',async()=>{
 const opened=await fixture(),bytes=await savePptx(opened),part=listMasterParts(opened.archive).find(p=>p.kind==='master')!,slide=parseMasterPart(opened.archive,part.partPath)!,spid=elementSpid(slide.elements.at(-1)!)!,box={x:96,y:120,width:400,height:88,rotationDeg:12.5}
 const inspected=await bridge(bytes),metadata=inspected.model.masterTextParts.find((item:any)=>item.partPath===part.partPath).elements.find((item:any)=>item.spid===spid)
 assert.equal(metadata.transformEditable,true)
 const result=await bridge(bytes,{masterElementEdits:[{kind:'setTransform',partPath:part.partPath,spid,box}]});assert.equal(result.result.status,0,result.result.stderr)
 const actual=await openPptx(await readFile(result.output)),expected=await openPptx(bytes)
 assert.equal(runTxn(expected,{ops:[{op:'setTransform',target:{part:part.partPath,el:`e_${spid}`},box:{x:96*9525,y:120*9525,cx:400*9525,cy:88*9525},rotDeg:12.5}]}).applied,true)
 const got=parseMasterPart(actual.archive,part.partPath)!.elements.find(el=>elementSpid(el)===spid)!,want=parseMasterPart(expected.archive,part.partPath)!.elements.find(el=>elementSpid(el)===spid)!
 assert.deepEqual(got.transform,want.transform)
})
test('既有母版轮廓经源setStroke事务写入实色并支持清除',async()=>{
 const opened=await fixture(),bytes=await savePptx(opened),part=listMasterParts(opened.archive).find(p=>p.kind==='master')!,slide=parseMasterPart(opened.archive,part.partPath)!,spid=elementSpid(slide.elements.at(-1)!)!
 const inspected=await bridge(bytes),metadata=inspected.model.masterTextParts.find((item:any)=>item.partPath===part.partPath).elements.find((item:any)=>item.spid===spid)
 assert.equal(metadata.strokeEditable,true);assert.equal(metadata.strokeValue,'none')
 for(const stroke of [{color:'#12AB34',widthPt:1},null]){
  const result=await bridge(bytes,{masterElementEdits:[{kind:'setStroke',partPath:part.partPath,spid,stroke}]});assert.equal(result.result.status,0,result.result.stderr)
  const actual=await openPptx(await readFile(result.output)),expected=await openPptx(bytes)
  assert.equal(runTxn(expected,{ops:[{op:'setStroke',target:{part:part.partPath,el:`e_${spid}`},stroke:stroke?{color:stroke.color,widthEmu:12700}:null}]}).applied,true)
  assert.deepEqual(parseMasterPart(actual.archive,part.partPath)!.elements.find(el=>elementSpid(el)===spid)!.stroke,parseMasterPart(expected.archive,part.partPath)!.elements.find(el=>elementSpid(el)===spid)!.stroke)
 }
})
test('未登记part、伪造SPID、重复新框身份和任意XML不能产生输出',async()=>{
 const opened=await fixture(),bytes=await savePptx(opened),part=listMasterParts(opened.archive)[0]!,add={kind:'addTextBox',partPath:part.partPath,clientId:'one',text:'甲',box:{x:0,y:0,width:100,height:100}}
 for(const edits of [[{...add,partPath:'ppt/slideMasters/slideMaster999.xml'}],[{kind:'delete',partPath:part.partPath,spid:999999}],[{kind:'setTransform',partPath:part.partPath,spid:999999,box:{x:0,y:0,width:100,height:100,rotationDeg:0}}],[{kind:'setStroke',partPath:part.partPath,spid:999999,stroke:null}],[add,add],[{...add,xml:'<p:sp/>'}]]){const output=await bridge(bytes,{masterElementEdits:edits});assert.notEqual(output.result.status,0);await assert.rejects(readFile(output.output))}
})
test('普通页面文字和母版文字事务与结构事务共存，已改字对象仍可按原SPID删除',async()=>{
 const source=await fixture(),slide=source.deck.slides[0]!
 addElement(slide,{kind:'textbox',offset:{x:10,y:10,cx:2000000,cy:500000},paragraphs:[{runs:[{text:'普通页面原文'}]}]});source.archive.entries.set('ppt/slides/slide1.xml',Buffer.from(patchSlideXml(slide)))
 const bytes=await savePptx(source),opened=await openPptx(bytes),part=listMasterParts(opened.archive)[0]!,spid=elementSpid(parseMasterPart(opened.archive,part.partPath)!.elements.at(-1)!)!,inspected=await bridge(bytes),element=inspected.model.slides[0].elements.at(-1)
 const result=await bridge(bytes,{edits:[{slideIndex:0,elementId:element.id,text:'普通页面改后'}],masterTextEdits:[{partPath:part.partPath,spid,text:'删除前改字'}],masterElementEdits:[{kind:'delete',partPath:part.partPath,spid}]});assert.equal(result.result.status,0,result.result.stderr)
 const actual=await openPptx(await readFile(result.output));assert(!parseMasterPart(actual.archive,part.partPath)!.elements.some(el=>elementSpid(el)===spid));assert(actual.deck.slides[0]!.elements.some(el=>'text'in el&&el.text?.paragraphs.some(p=>p.runs.some(r=>r.text==='普通页面改后'))))
})
