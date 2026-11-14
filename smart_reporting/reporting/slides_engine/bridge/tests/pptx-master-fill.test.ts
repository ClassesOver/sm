import assert from 'node:assert/strict'
import { test } from 'node:test'
import { mkdtemp,readFile,writeFile,mkdir } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { join } from 'node:path'
import { addElement,createBlankPptx,elementSpid,listMasterParts,openPptx,parseMasterPart,patchSlideXml,savePptx } from '@genoffice/pptx-engine'
import { runTxn } from '../../packages/pptx-ops/src/index.ts'
import { inspectMasterTextParts } from '../pptx-master-text.ts'
import { validateMasterElementEdits } from '../pptx-master-elements.ts'
const evidence='/dev/shm/office-next-pptx-master-fill-20261113'
const build=mkdtemp('/dev/shm/pptx-master-fill-engine-').then(dir=>{const result=spawnSync('node_modules/.bin/esbuild',['bridge/edit-pptx.ts','--bundle','--platform=node','--format=esm','--loader:.md=text',`--outfile=${join(dir,'edit.mjs')}`,'--log-level=error','--banner:js=import { createRequire } from "node:module"; const require = createRequire(import.meta.url);'],{encoding:'utf8'});assert.equal(result.status,0,result.stderr);return join(dir,'edit.mjs')})
async function bridge(input:Uint8Array,patch:object){const dir=await mkdtemp('/dev/shm/pptx-master-fill-call-'),source=join(dir,'source.pptx'),output=join(dir,'output.pptx'),request=join(dir,'request.json');await writeFile(source,input);await writeFile(request,JSON.stringify({action:'edit',input:source,output,...patch}));const result=spawnSync(process.execPath,[await build,request],{encoding:'utf8'});return{result,output}}
async function fixture(){const opened=await openPptx(await createBlankPptx());for(const part of listMasterParts(opened.archive)){const slide=parseMasterPart(opened.archive,part.partPath)!;addElement(slide,{kind:'rect',offset:{x:500000,y:500000,cx:2000000,cy:1000000},fillColor:'#AABBCC'});let xml=patchSlideXml(slide);if(part.kind==='layout')xml=xml.replace(/<p:txBody>[\s\S]*?<\/p:txBody>/g,'');opened.archive.entries.set(part.partPath,Buffer.from(xml))}return openPptx(await savePptx(opened))}
test('独立fillEditable允许无文字shape；实色和none与源part setFill相等且仅改目标part',async()=>{
 const opened=await fixture(),bytes=await savePptx(opened),parts=inspectMasterTextParts(opened),master=parts.find(p=>p.kind==='master')!,layout=parts.find(p=>p.kind==='layout')!,m=master.elements.at(-1)!,l=layout.elements.at(-1)!
 assert.equal(m.fillEditable,true);assert.equal(l.editable,false);assert.equal(l.fillEditable,true);assert.equal(l.fillValue,'#AABBCC')
 const edits=[{kind:'setFill',partPath:master.partPath,spid:m.spid,fill:'#1A73E8'},{kind:'setFill',partPath:layout.partPath,spid:l.spid,fill:'none'}];const result=await bridge(bytes,{masterElementEdits:edits});assert.equal(result.result.status,0,result.result.stderr)
 const actual=await openPptx(await readFile(result.output)),expected=await openPptx(bytes);assert(runTxn(expected,{ops:edits.map(edit=>({op:'setFill',target:{part:edit.partPath,el:`e_${edit.spid}`},fill:edit.fill}))}).applied)
 const targets=new Set(edits.map(edit=>edit.partPath));for(const[path,original]of opened.archive.entries){if(!targets.has(path))assert.deepEqual(actual.archive.readBytes(path),original,path);else{const a=parseMasterPart(actual.archive,path)!,e=parseMasterPart(expected.archive,path)!;assert.deepEqual(a.elements.map(el=>'fill'in el?el.fill:null),e.elements.map(el=>'fill'in el?el.fill:null));assert.deepEqual(a.elements.map(el=>el.transform),e.elements.map(el=>el.transform))}}
 await mkdir(evidence,{recursive:true});await writeFile(join(evidence,'source.pptx'),bytes);await writeFile(join(evidence,'output.pptx'),await readFile(result.output));await writeFile(join(evidence,'engine-edits.json'),JSON.stringify(edits,null,2))
})
test('复杂填充不伪称none，填充独立能力/身份/颜色/冲突校验',async()=>{
 const opened=await fixture(),part=listMasterParts(opened.archive)[0]!,slide=parseMasterPart(opened.archive,part.partPath)!,spid=elementSpid(slide.elements.at(-1)!)!,fill={kind:'setFill',partPath:part.partPath,spid,fill:'#123456'}
 assert(runTxn(opened,{ops:[{op:'setFill',target:{part:part.partPath,el:`e_${spid}`},fill:{stops:[{pos:0,color:'#000000'},{pos:1,color:'#FFFFFF'}],angle:0}}]}).applied);const inspected=inspectMasterTextParts(opened).find(p=>p.partPath===part.partPath)!.elements.find(el=>el.spid===spid)!;assert.equal(inspected.fillEditable,true);assert.equal(inspected.fillValue,null)
 assert.deepEqual(validateMasterElementEdits(opened,[fill]),[fill]);for(const edits of [[{...fill,partPath:'ppt/slideMasters/slideMaster999.xml'}],[{...fill,spid:999999}],[{...fill,fill:'#12345678'}],[{...fill,fill:'#123456\n'}],[{...fill,fill:'none\n'}],[{...fill,xml:'<a:noFill/>'}],[fill,fill],[fill,{kind:'delete',partPath:part.partPath,spid}]])assert.throws(()=>validateMasterElementEdits(opened,edits))
})
test('缺少可写spPr的畸形源只禁填充，不借此收紧文字能力',async()=>{
 const opened=await fixture(),part=listMasterParts(opened.archive).find(p=>p.kind==='master')!,slide=parseMasterPart(opened.archive,part.partPath)!,el=slide.elements.at(-1)!,spid=elementSpid(el)!,source=opened.archive.readText(part.partPath)!
 opened.archive.entries.set(part.partPath,Buffer.from(source.replace(el.anchor.originalXml,el.anchor.originalXml.replace(/<p:spPr\b[^>]*\/>|<p:spPr\b[^>]*>[\s\S]*?<\/p:spPr>/,''))))
 const target=inspectMasterTextParts(opened).find(p=>p.partPath===part.partPath)!.elements.find(item=>item.spid===spid)!;assert.equal(target.editable,true);assert.equal(target.fillEditable,false);assert.throws(()=>validateMasterElementEdits(opened,[{kind:'setFill',partPath:part.partPath,spid,fill:'#123456'}]))
})
