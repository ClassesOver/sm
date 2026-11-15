import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
import {probeCanvasTextRendering} from './canvas-font-preflight.mjs'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const directory=process.env.WORD_PRESETS_EVIDENCE??'/tmp/word-review-presets-20261114',staticRoot=process.env.WORD_PRESETS_BUILD??'/tmp/word-genoffice-build-final'
const port=Number(process.env.WORD_PRESETS_PORT??4298),origin='http://127.0.0.1:'+port,sha=bytes=>createHash('sha256').update(bytes).digest('hex')
await mkdir(directory,{recursive:true})
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/word-review-presets-server.py'),'--directory',directory,'--static',staticRoot,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo},stdio:'pipe'})
let log='',browser,page,stage='server';server.stdout.on('data',data=>{log+=data});server.stderr.on('data',data=>{log+=data})
const errors=[],checks=[],assets=new Map()
try{
 for(let i=0;;i++){assert.equal(server.exitCode,null,log);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(i<180,log);await delay(250)}
 const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8'))
 browser=await chromium.launch({headless:true});const fontProbe=await probeCanvasTextRendering(browser);await writeFile(join(directory,'font-preflight.json'),JSON.stringify(fontProbe,null,2));assert(fontProbe.ok,'System font preflight failed; explicitly select the documented test Fontconfig.');page=await browser.newPage({viewport:{width:1450,height:1000}})
 page.on('pageerror',error=>errors.push(error.message))
 page.on('response',response=>{const path=new URL(response.url()).pathname;if(path.startsWith('/reports/v1/editor/assets/')&&/\.(js|css)$/.test(path))checks.push((async()=>{assert.equal(response.status(),200);const bytes=await response.body(),disk=await readFile(join(staticRoot,path.slice('/reports/v1/editor/assets/'.length)));assert.equal(sha(bytes),sha(disk));assets.set(path,sha(bytes))})())})
 const state=async()=>await(await fetch(origin+'/__smoke__/state')).json()
 stage='open';await page.goto(origin+info.openPath);await page.getByRole('textbox',{name:'Word 文档编辑区',exact:true}).waitFor({timeout:60000})
 if(process.env.WORD_PRESETS_REOPEN_FILE){
  stage='reimport-reviewed-build';await page.getByRole('textbox',{name:'Word 文档编辑区',exact:true}).getByText('Translated paragraph 1',{exact:true}).waitFor()
  await page.getByRole('tab',{name:'审阅',exact:true}).click();await page.locator('[data-action=review-compare]').click();await page.locator('input[type=file]').setInputFiles(process.env.WORD_PRESETS_COMPARE_FILE??process.env.WORD_PRESETS_REOPEN_FILE);await page.locator('[data-compare-results]').getByText('当前：Translated paragraph 1',{exact:true}).waitFor();await page.setViewportSize({width:390,height:844});await page.screenshot({path:join(directory,'reviewed-compare-narrow.png'),fullPage:true});await page.getByRole('button',{name:'关闭文档比较',exact:true}).click()
  const actual=await state();assert.equal(actual.calls.length,0);assert.equal(actual.revisions.length,0);assert.equal(actual.requests.filter(item=>item.method==='POST'&&item.path.endsWith('/save')).length,0);await Promise.all(checks);assert.equal(errors.length,0)
  await writeFile(join(directory,'result.json'),JSON.stringify({ok:true,mode:'actual-download-reimport',saveCount:0,modelCalls:0,sourceSha256:sha(await readFile(process.env.WORD_PRESETS_REOPEN_FILE)),manifestSha256:sha(await readFile(join(staticRoot,'.vite/manifest.json'))),assets:Object.fromEntries(assets),errors},null,2));console.log(JSON.stringify({ok:true,directory,assetCount:assets.size,saveCount:0}))
 }else{
 await page.getByRole('tab',{name:'审阅',exact:true}).click()
 stage='cancel-whole';page.once('dialog',dialog=>dialog.dismiss());await page.locator('[data-action=review-editor]').click();assert.equal((await state()).calls.length,0)
 stage='translate';await page.locator('[data-action=review-translate]').click();assert.equal(await page.locator('[data-language]').count(),22)
 page.once('dialog',dialog=>dialog.accept());await page.locator('[data-language=en]').click()
 const panel=page.locator('.native-ai:not(.native-word-assistant)');await panel.waitFor({state:'visible'});assert.match(await panel.locator('textarea').inputValue(),/英文/);assert.equal((await state()).calls.length,0)
 stage='generate';await panel.locator('[data-ai=start]').click();await panel.locator('[data-ai=accept]:enabled').waitFor({timeout:60000})
 assert.equal((await state()).revisions.length,0);await writeFile(join(directory,'before-adoption-dom.json'),JSON.stringify(await page.getByRole('textbox',{name:'Word 文档编辑区',exact:true}).evaluate(el=>({html:el.outerHTML,text:el.textContent,parents:[el,...Array.from(el.parentElement.children)].map(n=>({tag:n.tagName,cls:n.className,style:n.getAttribute('style')}))})),null,2));assert.match(await page.getByRole('textbox',{name:'Word 文档编辑区',exact:true}).textContent(),/本季度/)
 stage='accept';await panel.locator('[data-ai=accept]').click();await page.getByRole('textbox',{name:'Word 文档编辑区',exact:true}).getByText('Translated paragraph 1',{exact:true}).waitFor()
 const saveResponse=page.waitForResponse(response=>response.request().method()==='POST'&&response.url().endsWith('/save'))
 stage='save';await page.locator('[data-action=save]').click();const saved=await(await saveResponse).json();await writeFile(join(directory,'saved.json'),JSON.stringify(saved,null,2));assert.equal(saved.revision,2);assert.equal(saved.revisionRegistered,true)
 const download=await page.request.get(saved.artifacts.word.downloadUrl);assert.equal(download.status(),200);const bytes=await download.body();assert.equal(sha(bytes),saved.artifacts.word.sha256);await writeFile(join(directory,'downloaded.docx'),bytes)
 stage='independent-readback';const independent=spawnSync(join(repo,'.venv/bin/python'),['-c',`import json,sys\nfrom docx import Document\nfrom zipfile import ZipFile\na,b=sys.argv[1:]\nd=Document(b)\nassert [p.text for p in d.paragraphs]==['Translated paragraph 1','Translated paragraph 2']\nassert d.sections[0].header.paragraphs[0].text=='HEADER KEEP'\nassert d.sections[0].footer.paragraphs[0].text=='FOOTER KEEP'\nwith ZipFile(a) as x,ZipFile(b) as y:\n changed=[n for n in x.namelist() if not n.endswith('/') and x.read(n)!=y.read(n)]\n assert set(changed)<=set(['word/document.xml','docProps/core.xml']),changed\n print(json.dumps({'paragraphs':[p.text for p in d.paragraphs],'changedParts':changed}))`,join(directory,'source.docx'),join(directory,'downloaded.docx')],{encoding:'utf8'});assert.equal(independent.status,0,independent.stderr);await writeFile(join(directory,'independent.json'),independent.stdout)
 stage='reopen';await page.goto(saved.editor.openUrl);await page.getByRole('textbox',{name:'Word 文档编辑区',exact:true}).getByText('Translated paragraph 1',{exact:true}).waitFor({timeout:60000})
 stage='compare';await page.getByRole('tab',{name:'审阅',exact:true}).click();await page.locator('[data-action=review-compare]').click();await page.locator('input[type=file]').setInputFiles(join(directory,'source.docx'));await page.locator('[data-compare-results]').getByText('当前：Translated paragraph 1',{exact:true}).waitFor();await page.screenshot({path:join(directory,'compare-desktop.png'),fullPage:true})
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:join(directory,'compare-narrow.png'),fullPage:true});await page.getByRole('button',{name:'关闭文档比较',exact:true}).click()
 const final=await state();assert.equal(final.calls.length,1);assert.equal(final.requests.filter(item=>item.method==='POST'&&item.path.endsWith('/save')).length,1);assert.equal(errors.length,0,errors.join('\n'));await Promise.all(checks)
 await writeFile(join(directory,'result.json'),JSON.stringify({ok:true,manifestSha256:sha(await readFile(join(staticRoot,'.vite/manifest.json'))),downloadSha256:sha(bytes),assets:Object.fromEntries(assets),errors,validation:saved.validation,provider:'ScriptedModel via actual Agno, not real provider',repository:'scoped in-memory, actual native HTTP authorization and publication',saveCount:1},null,2))
 console.log(JSON.stringify({ok:true,directory,assetCount:assets.size,saveCount:1}))
 }
}catch(error){await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,log},null,2));if(page)await writeFile(join(directory,'failure-dom.json'),JSON.stringify(await page.locator('.ProseMirror').first().evaluate(el=>{const chain=[];for(let n=el;n;n=n.parentElement){const c=getComputedStyle(n),r=n.getBoundingClientRect();chain.push({tag:n.tagName,cls:n.className,hidden:n.hidden,style:n.getAttribute('style'),display:c.display,visibility:c.visibility,opacity:c.opacity,color:c.color,width:r.width,height:r.height,children:[...n.children].slice(0,3).map(child=>({tag:child.tagName,cls:child.className,style:child.getAttribute('style'),visibility:getComputedStyle(child).visibility,display:getComputedStyle(child).display}))})}return chain}),null,2)).catch(()=>{});if(page)await page.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});throw error}
finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),log)}
