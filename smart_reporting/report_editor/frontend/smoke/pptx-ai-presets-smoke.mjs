import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { cp, mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const output=process.env.PPTX_AI_PRESETS_DIRECTORY??'/tmp/office-word-pptx-source-gaps-20261113/ai-presets/browser-built'
const build=process.env.PPTX_AI_PRESETS_BUILD??join(frontend,'../static'),source=process.env.PPTX_AI_PRESETS_SOURCE==='1'
const port=Number(process.env.PPTX_AI_PRESETS_PORT??4353),origin='http://127.0.0.1:'+port,sha=bytes=>createHash('sha256').update(bytes).digest('hex')
await mkdir(output,{recursive:true})
const staticRoot=join(output,'static');await cp(build,staticRoot,{recursive:true,errorOnExist:true,force:false})
const manifest=await readFile(join(staticRoot,'.vite/manifest.json')),sources={}
let vite
if(source){
 const {createServer}=await import('vite')
 vite=await createServer({root:frontend,configFile:join(frontend,'vite.config.ts'),server:{host:'127.0.0.1',port:port+1,strictPort:true,cors:true}});await vite.listen()
 const html=(await readFile(join(frontend,'native.html'),'utf8')).replace('/src/unified-main.ts','http://127.0.0.1:'+(port+1)+'/reports/v1/editor/assets/src/unified-main.ts')
 await writeFile(join(staticRoot,'native.html'),html)
 for(const file of ['slides-ai-presets.ts','slides-main.ts','slides-native-ribbon.ts','slides-native-ribbon-locales.ts','slides-native-ai.ts'])sources[file]=sha(await readFile(join(frontend,'src',file)))
}
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pptx-ai-objects-server.py'),'--directory',output,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo,PPTX_AI_OBJECTS_STATIC_ROOT:staticRoot,PPTX_AI_PRESETS_SMOKE:'1'},stdio:'pipe'})
let log='',browser,page,stage='server'
server.stdout.on('data',data=>{log+=data});server.stderr.on('data',data=>{log+=data})
const errors=[],consoleErrors=[],httpErrors=[],checks=[],assets=new Map()
try{
 for(let attempt=0;;attempt++){assert.equal(server.exitCode,null,log);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(attempt<240,log);await delay(250)}
 const info=JSON.parse(await readFile(join(output,'server-info.json'),'utf8'))
 browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1600,height:1100}})
 page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text())})
 page.on('response',response=>{
  const url=new URL(response.url()),path=url.pathname
  if(response.status()>=400)httpErrors.push({path,status:response.status()})
  if(!source&&url.origin===origin&&path.startsWith('/reports/v1/editor/assets/')&&path.endsWith('.js'))checks.push((async()=>{const bytes=await response.body();assert.equal(sha(bytes),sha(await readFile(join(staticRoot,path.slice('/reports/v1/editor/assets/'.length)))));assets.set(path,sha(bytes))})())
 })
 await page.goto(origin+info.openPaths.presets)
 await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:120000})
 await page.locator('.slides-canvas canvas').first().waitFor({timeout:60000})
 const target=info.model.slides[0].elements.find(element=>element.type==='text')
 assert(target);await page.getByLabel('可编辑对象',{exact:true}).selectOption(target.id)
 await page.locator('#object-text').fill('人工草稿：收入42，费用17。')
 const drafts=()=>page.evaluate(()=>Object.keys(localStorage).filter(key=>key.startsWith('native-editor-draft:')).map(key=>JSON.parse(localStorage.getItem(key))))
 const before=await drafts();assert.equal(before.length,1)
 await page.locator('[data-ribbon-tab=review]').click()
 const language=page.locator('[data-command=translate]'),panel=page.getByRole('region',{name:'PPTX AI 助手',exact:true})
 const labels=await language.locator('option').evaluateAll(options=>options.map(option=>[option.value,option.textContent]))
 assert.equal(labels.length,22);assert.deepEqual(labels[1],['en','英语']);assert.deepEqual(labels.at(-1),['vi','越南文'])
 assert.equal(await language.locator('xpath=..').locator('svg').count(),1)
 const state=async()=>await(await fetch(origin+'/__smoke__/state')).json()
 const candidate=async()=>{await panel.locator('[type=submit]').click();await page.waitForFunction(()=>document.querySelector('.slides-native-ai .native-ai-preview')?.hidden===false,null,{timeout:60000});return(await state()).jobs.at(-1)}
 stage='translate-open';await language.selectOption('en');await page.getByRole('complementary',{name:'PPTX AI 助手侧栏',exact:true}).waitFor({state:'visible'})
 assert.equal(await panel.getByLabel('AI 授权范围',{exact:true}).inputValue(),'slide');assert.match(await panel.locator('textarea').inputValue(),/英语/)
 assert.match(await panel.locator('.native-ai-context').textContent(),/人工草稿/);assert.equal((await state()).jobs.length,0)
 stage='translate-candidate';const translated=await candidate();assert.equal(translated.status,'succeeded',JSON.stringify(translated))
 assert.deepEqual(await drafts(),before)
 const translationPreview=await panel.locator('.native-ai-preview').innerText();assert.match(translationPreview,/人工草稿.*Draft revenue 42, expenses 17\./)
 const start=(await state()).requests.filter(request=>request.path.endsWith('/slides-ai/start')).at(-1)
 assert.equal(start.body.scope,'selection');assert(start.body.selection.length>=2);assert(start.body.selection.every(item=>item.slideIndex===0));assert.deepEqual(start.body.operations,before[0].operations)
 await page.screenshot({path:join(output,'translation-candidate.png'),fullPage:true})
 stage='language-switch';await language.selectOption('ja');assert.equal(await panel.locator('.native-ai-preview').isVisible(),false);assert.match(await panel.locator('textarea').inputValue(),/日语/)
 assert.deepEqual(await drafts(),before)
 stage='translate-accept';await language.selectOption('en');const adopted=await candidate();await panel.locator('.native-ai-accept').click()
 await page.waitForFunction(()=>document.querySelector('.slides-native-ai .native-ai-status')?.textContent?.startsWith('候选已加入草稿'),null,{timeout:60000})
 const after=await drafts();assert.notDeepEqual(after,before)
 await page.locator('[data-source-action=onUndo]').click();assert.deepEqual((await drafts())[0].operations,before[0].operations)
 await page.locator('[data-source-action=onRedo]').click();assert.deepEqual((await drafts())[0].operations,after[0].operations)
 stage='spelling-deck';await page.locator('[data-command=spelling]').click();assert.equal(await panel.getByLabel('AI 授权范围',{exact:true}).inputValue(),'deck')
 const spelling=await candidate();assert.equal(spelling.status,'succeeded',JSON.stringify(spelling));assert.deepEqual(await drafts(),after)
 assert.match(await panel.locator('.native-ai-preview').innerText(),/第二页错别自.*第二页错别字/)
 const spellStart=(await state()).requests.filter(request=>request.path.endsWith('/slides-ai/start')).at(-1);assert.equal(spellStart.body.scope,'deck');assert.deepEqual(spellStart.body.selection,[])
 await page.screenshot({path:join(output,'spelling-candidate.png'),fullPage:true})
 stage='discard';await panel.locator('.native-ai-discard').click();assert.equal(await panel.locator('.native-ai-preview').isVisible(),false);assert.deepEqual(await drafts(),after)
 stage='stale-page';await page.locator('#object-text').fill('再次人工草稿：收入42，费用17。');const beforeStale=await drafts()
 await language.selectOption('en');await candidate();await page.locator('.slide-open[data-slide-index="1"]').click();await panel.locator('.native-ai-accept').click();await panel.locator('.native-ai-status').filter({hasText:'草稿已变化'}).waitFor();assert.deepEqual(await drafts(),beforeStale)
 stage='cancel';await page.locator('[data-command=spelling]').click();await candidate();await panel.getByRole('button',{name:'关闭助手',exact:true}).click();await panel.waitFor({state:'hidden'});assert.deepEqual(await drafts(),beforeStale)
 const final=await state(),readback=final.jobs.find(job=>job.editId===adopted.editId).independentReadback
 assert.deepEqual(readback.texts,[['Draft revenue 42, expenses 17.'],['第二页错别自：收入42。']]);assert.equal(readback.tables[0][1][1],'42');assert.deepEqual(readback.charts[0].series[0].values,[42,17])
 assert(final.requests.some(request=>request.path.endsWith('/cancel-request')));assert(!final.requests.some(request=>/\/(save|export)$/.test(request.path)))
 for(const job of [translated,adopted,spelling])assert.deepEqual(job.events.filter(event=>event.kind==='toolCompleted').map(event=>event.toolName),job.editId===spelling.editId?['get_presentation_context','read_slide','read_slide','propose_operations']:['get_presentation_context','read_slide','propose_operations'])
 await Promise.all(checks);assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[])
 assert.deepEqual(await readFile(join(staticRoot,'.vite/manifest.json')),manifest)
 await writeFile(join(output,'summary.json'),JSON.stringify({ok:true,layer:source?'real native HTTP + source Vite, not frozen production bundle':'real native HTTP + frozen production bundle',provider:'ScriptedModel through actual Agno; not real provider',manifestSha256:sha(manifest),sourceModuleHashes:sources,assets:Object.fromEntries(assets),labels,start:start.body,spellStart:spellStart.body,translationPreview,readback,acceptedId:adopted.editId,errors,consoleErrors,httpErrors},null,2))
 console.log(JSON.stringify({ok:true,output,source,assets:assets.size}))
}catch(error){if(page){await page.screenshot({path:join(output,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(output,'failure.html'),await page.content()).catch(()=>{})}console.error(JSON.stringify({stage,output}));throw error}
finally{await browser?.close();server.kill();await vite?.close();await writeFile(join(output,'server.log'),log)}
