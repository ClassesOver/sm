import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const port=Number(process.env.DOCX_REVIEW_SMOKE_PORT??4196),origin=`http://127.0.0.1:${port}`,mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const staticRoot=process.env.DOCX_REVIEW_STATIC_ROOT,expectedManifestSha=process.env.DOCX_REVIEW_MANIFEST_SHA
assert(staticRoot&&expectedManifestSha,'DOCX_REVIEW_STATIC_ROOT and DOCX_REVIEW_MANIFEST_SHA are required')
const sha=bytes=>createHash('sha256').update(bytes).digest('hex'),evidenceRoot=process.env.DOCX_REVIEW_SMOKE_OUT??join(tmpdir(),`docx-review-view-${new Date().toISOString().replace(/[:.]/g,'-')}`)
await mkdir(evidenceRoot,{recursive:true})
const python=input=>{
 const result=spawnSync(join(repo,'.venv/bin/python'),['-c',String.raw`
import base64,json,sys
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree
from smart_reporting.reporting.delivery.docx_native import inspect_docx
payload=json.load(sys.stdin)
doc=Document();p=doc.add_paragraph();p.add_run('Body plain ')
for tag,author,text in [('ins','Body Alice','inserted body'),('del','Body Bob','deleted body')]:
 el=OxmlElement('w:'+tag);el.set(qn('w:id'),'1' if tag=='ins' else '2');el.set(qn('w:author'),author);el.set(qn('w:date'),'2026-11-13T00:00:00Z')
 r=OxmlElement('w:r');t=OxmlElement('w:'+('delText' if tag=='del' else 't'));t.text=text;r.append(t);el.append(r);p._p.append(el)
p.add_run(' body tail')
doc.add_paragraph('History probe target')
formatted=OxmlElement('w:r');props=OxmlElement('w:rPr');props.append(OxmlElement('w:b'));change=OxmlElement('w:rPrChange');change.set(qn('w:id'),'7');change.set(qn('w:author'),'Format Alice');change.set(qn('w:date'),'2026-11-13T00:00:00Z');old=OxmlElement('w:rPr');old.append(OxmlElement('w:i'));change.append(old);props.append(change);formatted.append(props);text=OxmlElement('w:t');text.text=' formatted body';formatted.append(text);p._p.append(formatted)
hp=doc.sections[0].header.paragraphs[0];hp.add_run('HF plain ')
el=OxmlElement('w:ins');el.set(qn('w:id'),'3');el.set(qn('w:author'),'HF Alice');el.set(qn('w:date'),'2026-11-13T00:00:00Z');r=OxmlElement('w:r');t=OxmlElement('w:t');t.text='inserted header';r.append(t);el.append(r);hp._p.append(el)
el=OxmlElement('w:del');el.set(qn('w:id'),'4');el.set(qn('w:author'),'HF Bob');el.set(qn('w:date'),'2026-11-13T00:00:00Z');r=OxmlElement('w:r');t=OxmlElement('w:delText');t.text='deleted header';r.append(t);el.append(r);hp._p.append(el)
fr=OxmlElement('w:r');ref=OxmlElement('w:footnoteReference');ref.set(qn('w:id'),'1');fr.append(ref);p._p.append(fr)
buf=BytesIO();doc.save(buf);source=buf.getvalue();out=BytesIO();ns='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
with ZipFile(BytesIO(source)) as zin,ZipFile(out,'w',ZIP_DEFLATED) as zout:
 for item in zin.infolist():
  data=zin.read(item.filename)
  if item.filename=='[Content_Types].xml':
   root=etree.fromstring(data);node=etree.SubElement(root,'{http://schemas.openxmlformats.org/package/2006/content-types}Override');node.set('PartName','/word/footnotes.xml');node.set('ContentType','application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml');data=etree.tostring(root)
  elif item.filename=='word/_rels/document.xml.rels':
   root=etree.fromstring(data);node=etree.SubElement(root,'{http://schemas.openxmlformats.org/package/2006/relationships}Relationship');node.set('Id','rIdFootnotes');node.set('Type','http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes');node.set('Target','footnotes.xml');data=etree.tostring(root)
  zout.writestr(item,data)
root=etree.Element('{%s}footnotes'%ns,nsmap={'w':ns})
for ident,kind in [('-1','separator'),('0','continuationSeparator')]:
 note=etree.SubElement(root,'{%s}footnote'%ns);note.set('{%s}id'%ns,ident);r=etree.SubElement(etree.SubElement(note,'{%s}p'%ns),'{%s}r'%ns);etree.SubElement(r,'{%s}%s'%(ns,kind))
note=etree.SubElement(root,'{%s}footnote'%ns);note.set('{%s}id'%ns,'1');para=etree.SubElement(note,'{%s}p'%ns)
for tag,author,text in [('ins','Note Alice','inserted note'),('del','Note Bob','deleted note')]:
 rev=etree.SubElement(para,'{%s}%s'%(ns,tag));rev.set('{%s}id'%ns,'5' if tag=='ins' else '6');rev.set('{%s}author'%ns,author);rev.set('{%s}date'%ns,'2026-11-13T00:00:00Z');run=etree.SubElement(rev,'{%s}r'%ns);etree.SubElement(run,'{%s}%s'%(ns,'delText' if tag=='del' else 't')).text=text
with ZipFile(out,'a',ZIP_DEFLATED) as zout:zout.writestr('word/footnotes.xml',etree.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True))
raw=out.getvalue();info=inspect_docx(raw);print(json.dumps({'bytes':base64.b64encode(raw).decode(),'model':info},ensure_ascii=False))
`],{cwd:repo,env:{...process.env,PYTHONPATH:repo},input:'{}',encoding:'utf8',maxBuffer:20*1024*1024})
 if(result.status!==0)throw new Error(result.stderr||`fixture python exit ${result.status}`)
 return JSON.parse(result.stdout.trim())
}
let server,browser,page,errors=[],responses=[]
smoke: try{
 const fixture=python(),bytes=Buffer.from(fixture.bytes,'base64'),sourceSha=sha(bytes),model=fixture.model
 await writeFile(join(evidenceRoot,'source.docx'),bytes);await writeFile(join(evidenceRoot,'model.json'),JSON.stringify(model,null,2))
 const manifest=await readFile(join(staticRoot,'.vite/manifest.json'));assert.equal(sha(manifest),expectedManifestSha,'freeze manifest SHA mismatch')
 server=spawn('./node_modules/.bin/vite',['preview','--outDir',staticRoot,'--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:frontend,stdio:'ignore'})
 let ready=false;for(let attempt=0;attempt<120;attempt++){try{if((await fetch(`${origin}/reports/v1/editor/assets/native.html`)).ok){ready=true;break}}catch{}await delay(250)}assert(ready,'Vite did not become ready')
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})})
 const context=await browser.newContext({viewport:{width:1500,height:1050}});page=await context.newPage();const assets=new Map(),assetChecks=[]
 page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text())})
 page.on('response',response=>{const path=new URL(response.url()).pathname;responses.push({status:response.status(),path});const prefix='/reports/v1/editor/assets/';if(path.startsWith(prefix)&&/\.(js|css)$/.test(path))assetChecks.push((async()=>{assert.equal(response.status(),200);const actual=await response.body(),expected=await readFile(join(staticRoot,path.slice(prefix.length)));assert.equal(sha(actual),sha(expected),`asset mismatch ${path}`);assets.set(path,sha(actual))})())})
 let readOnly=false
 await page.route('**/reports/v1/native/review-fixture/1/api/context',route=>route.fulfill({json:{context:{documentId:'review-fixture',format:'docx',revision:1,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'review.docx',size:bytes.length,sha256:sourceSha,mediaType:mime},origin:'report'},csrfToken:'review-csrf',capabilities:{docx_editor:true},editingEnabled:!readOnly}}))
 await page.route('**/reports/v1/native/review-fixture/1/api/file',route=>route.fulfill({body:bytes,contentType:mime}))
 await page.route('**/reports/v1/native/review-fixture/1/api/preview',route=>route.fulfill({json:{sourceSha256:sourceSha,draftSha256:sourceSha,model}}))
 await page.route(/^http:\/\/127\.0\.0\.1:\d+\/reports\/v1\/native\/review-fixture\/1$/,async route=>route.fulfill({response:await route.fetch({url:`${origin}/reports/v1/editor/assets/native.html`})}))
 const open=async()=>{await page.goto(`${origin}/reports/v1/native/review-fixture/1`);await page.locator('.docx-source-home').waitFor({timeout:60000});await page.getByRole('textbox',{name:'Word 文档编辑区'}).waitFor()}
 await open()
 const editor=page.getByRole('textbox',{name:'Word 文档编辑区'}),reviewTab=page.locator('[data-tab-id="review"]'),mode=page.locator('[data-action="revision-display"]'),authors=page.locator('[data-action="revision-filter-authors"]')
 await reviewTab.click();await expectAuthors(['Body Alice','Body Bob','Format Alice','HF Alice','HF Bob','Note Alice','Note Bob'])
 const getDoc=()=>editor.evaluate(el=>JSON.stringify(el.editor.getJSON())),getDraft=()=>page.evaluate(()=>Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).map(key=>localStorage.getItem(key)))
 assert.equal(await editor.evaluate(el=>!!el.editor),true,'editable DOM must expose its live Tiptap instance')
 const openPreview=async()=>{await page.locator('[data-tab-id="view"]').click();await page.locator('[data-action="pagination-preview"]').click();await page.locator('.pagination-preview').waitFor({timeout:60000});await page.waitForTimeout(300)}
 const closePreview=async()=>{await page.keyboard.press('Escape');await page.locator('.pagination-preview').waitFor({state:'detached',timeout:10000})}
 const checkStory=(text,shouldShow,view)=>page.locator('.docx-preview-root').evaluate((root,{text,shouldShow,view})=>{const visible=Array.from(root.querySelectorAll('*')).filter(node=>node.childElementCount===0&&node.textContent?.includes(text)).some(node=>{const style=getComputedStyle(node);return style.display!=='none'&&style.visibility!=='hidden'&&!!node.getClientRects().length});if(visible!==shouldShow)throw new Error(`${view}: ${text} visible=${visible}, expected=${shouldShow}`)}, {text,shouldShow,view})
 if(process.env.DOCX_REVIEW_STORY_FILTERS_ONLY==='1'){
  const docBefore=await getDoc(),draftBefore=await getDraft(),storyResults=[]
  await authors.selectOption([{label:'HF Bob'},{label:'Note Bob'}]);await openPreview()
  await checkStory('inserted header',true,'hide-story-deletions');await checkStory('deleted header',false,'hide-story-deletions')
  await checkStory('inserted note',true,'hide-story-deletions');await checkStory('deleted note',false,'hide-story-deletions')
  storyResults.push({hiddenAuthors:['HF Bob','Note Bob'],header:{inserted:true,deleted:false},footnote:{inserted:true,deleted:false}})
  await page.screenshot({path:join(evidenceRoot,'stories-hidden-deletions.png'),fullPage:true});await closePreview()
  await reviewTab.click();await authors.selectOption([{label:'HF Alice'},{label:'Note Alice'}]);await openPreview()
  await checkStory('inserted header',true,'hide-story-insertions-ink');await checkStory('deleted header',true,'hide-story-insertions-ink')
  await checkStory('inserted note',true,'hide-story-insertions-ink');await checkStory('deleted note',true,'hide-story-insertions-ink')
  const ink=await page.locator('.docx-preview-root').evaluate(root=>Object.fromEntries(['inserted header','inserted note'].map(text=>{const node=Array.from(root.querySelectorAll('*')).find(item=>item.childElementCount===0&&item.textContent?.includes(text));if(!node)return[text,null];const parent=node.parentElement;return[text,{revisionClass:node.closest('.doc-ins,.doc-del')?.className??null,color:getComputedStyle(node).color,parentColor:parent?getComputedStyle(parent).color:null,textDecorationLine:getComputedStyle(node).textDecorationLine,fontWeight:getComputedStyle(node).fontWeight,parentWeight:parent?getComputedStyle(parent).fontWeight:null}]})))
  for(const text of ['inserted header','inserted note']){const style=ink[text];assert(style,`${text} DOM missing`);assert.equal(style.revisionClass,null);assert.equal(style.color,style.parentColor);assert.equal(style.textDecorationLine,'none');assert.equal(style.fontWeight,style.parentWeight)}
  storyResults.push({hiddenAuthors:['HF Alice','Note Alice'],header:{inserted:true,deleted:true},footnote:{inserted:true,deleted:true},hiddenInsertionInk:ink})
  await page.screenshot({path:join(evidenceRoot,'stories-hidden-insertion-ink.png'),fullPage:true})
  const docAfter=await getDoc(),draftAfter=await getDraft();assert.equal(docAfter,docBefore);assert.deepEqual(draftAfter,draftBefore)
  await Promise.all(assetChecks);assert(assets.size>0);assert.deepEqual(errors.filter(message=>!/WebSocket connection to 'ws:|\[vite\]/.test(String(message))),[])
  await writeFile(join(evidenceRoot,'operations.json'),JSON.stringify({editorDocBefore:JSON.parse(docBefore),editorDocBeforeRaw:docBefore,editorDocAfter:JSON.parse(docAfter),editorDocAfterRaw:docAfter,draftBeforeRaw:draftBefore,draftAfterRaw:draftAfter},null,2))
  const summary={ok:true,storyFiltersOnly:true,evidenceRoot,staticRoot,manifestSha256:sha(manifest),sourceSha256:sourceSha,storyResults,bodyUnchanged:docAfter===docBefore,draftUnchanged:JSON.stringify(draftAfter)===JSON.stringify(draftBefore),assets:Object.fromEntries(assets),errors}
  await writeFile(join(evidenceRoot,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify(summary));await context.close();break smoke
 }
 await editor.locator('p').filter({hasText:'History probe target'}).click();await page.keyboard.press('End');await page.keyboard.type(' history probe')
 const docBefore=await getDoc(),draftBefore=await getDraft()
 assert(docBefore.includes('History probe target history probe'),'test edit must reach the live document before view snapshots')
 const modeResults=[]
 for(const view of ['all','simple','none','original']){
  if(await page.locator('.pagination-preview').count())await closePreview()
  await reviewTab.click();await mode.selectOption(view);await openPreview()
  const inserted=view!=='original',deleted=view==='all'||view==='original'
  await checkStory('inserted body',inserted,view);await checkStory('deleted body',deleted,view)
  await checkStory('inserted header',inserted,view);await checkStory('deleted header',deleted,view)
  await checkStory('inserted note',inserted,view);await checkStory('deleted note',deleted,view)
  modeResults.push({mode:view,body:{inserted,deleted},header:{inserted,deleted},footnote:{inserted,deleted}})
  if(view==='all'){
   const formatStyle=await page.locator('.docx-preview-root').evaluate(root=>{const node=Array.from(root.querySelectorAll('*')).find(node=>node.childElementCount===0&&node.textContent?.includes('formatted body'));return node?{weight:getComputedStyle(node).fontWeight,style:getComputedStyle(node).fontStyle}:null})
   assert(formatStyle);assert.equal(formatStyle.weight,'700')
  }
  if(view==='original'){
   const formatStyle=await page.locator('.docx-preview-root').evaluate(root=>{const node=Array.from(root.querySelectorAll('*')).find(node=>node.childElementCount===0&&node.textContent?.includes('formatted body'));return node?{weight:getComputedStyle(node).fontWeight,style:getComputedStyle(node).fontStyle}:null})
   assert(formatStyle);assert.equal(formatStyle.style,'italic');assert.notEqual(formatStyle.weight,'700')
  }
  await page.screenshot({path:join(evidenceRoot,`preview-${view}.png`),fullPage:true})
 }
 await closePreview();await reviewTab.click();await mode.selectOption('all');await authors.selectOption({label:'Body Alice'});await openPreview()
 const insertion=page.locator('.docx-preview-root .doc-ins').filter({hasText:'inserted body'}).first()
 assert.equal(await insertion.count(),1,'hidden author insertion text remains in preview DOM')
 const style=await insertion.evaluate(node=>({color:getComputedStyle(node).color,parentColor:getComputedStyle(node.parentElement).color,textDecorationLine:getComputedStyle(node).textDecorationLine,fontWeight:getComputedStyle(node).fontWeight,parentWeight:getComputedStyle(node.parentElement).fontWeight}))
 assert.equal(style.color,style.parentColor);assert.equal(style.textDecorationLine,'none');assert.equal(style.fontWeight,style.parentWeight)
 await checkStory('inserted body',true,'specific-people');await checkStory('deleted body',true,'specific-people')
 assert.equal(await getDoc(),docBefore,'view and author filters must preserve editor JSON')
 assert.deepEqual(await getDraft(),draftBefore,'view and author filters must preserve draft state')
 await page.screenshot({path:join(evidenceRoot,'preview-specific-people.png'),fullPage:true});await closePreview()
 const undone=await page.evaluate(()=>{const editor=document.querySelector('[role="textbox"]').editor;return editor.commands.undo()})
 assert.equal(undone,true,'the real user edit remains undoable after view changes');assert.notEqual(await getDoc(),docBefore)
 readOnly=true;await open();await page.locator('[data-tab-id="review"]').click();assert.equal(await mode.isEnabled(),true);await mode.selectOption('original');assert.equal(await mode.inputValue(),'original')
 await Promise.all(assetChecks);assert(assets.size>0,'no frozen JS/CSS assets were observed')
 assert.deepEqual(errors.filter(message=>!/WebSocket connection to 'ws:|\[vite\]/.test(String(message))),[])
 const summary={ok:true,evidenceRoot,staticRoot,manifestSha256:sha(manifest),sourceSha256:sourceSha,authors:['Body Alice','Body Bob','Format Alice','HF Alice','HF Bob','Note Alice','Note Bob'],modeResults,originalFormatting:{allBold:true,originalItalic:true},assets:Object.fromEntries(assets),specificPeopleStyle:style,draftUnchanged:true,historyUndoAfterView:true,readOnlyDisplayAvailable:true,errors}
 const docAfterViews=await getDoc(),draftAfterViews=await getDraft()
 await writeFile(join(evidenceRoot,'operations.json'),JSON.stringify({editorDocBefore:JSON.parse(docBefore),editorDocBeforeRaw:docBefore,editorDocAfterViews:JSON.parse(docAfterViews),editorDocAfterViewsRaw:docAfterViews,draftBeforeRaw:draftBefore,draftAfterViewsRaw:draftAfterViews},null,2));await writeFile(join(evidenceRoot,'summary.json'),JSON.stringify(summary,null,2))
 console.log(JSON.stringify(summary))
 await context.close()
 async function expectAuthors(expected){assert.deepEqual(await authors.locator('option').evaluateAll(nodes=>nodes.map(node=>node.value)),expected)}
}catch(error){
 await writeFile(join(evidenceRoot,'failure.json'),JSON.stringify({message:error instanceof Error?error.stack:String(error),errors,responses},null,2)).catch(()=>{})
 await page?.screenshot({path:join(evidenceRoot,'failure.png'),fullPage:true}).catch(()=>{})
 throw error
}finally{await browser?.close();server?.kill()}
