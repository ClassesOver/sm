// 源码或统一冻结包上的真实媒体闭环。授权和修订入口是显式夹具，writer/reader/下载字节均为实际实现。
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {dirname,resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright'
import {createMediaNativeFixture} from './pptx-media-native-fixture.mjs'

const frontend=resolve(dirname(fileURLToPath(import.meta.url)),'..'),source=process.env.PPTX_MEDIA_SOURCE_MODE==='1'
assert.ok(process.env.PPTX_MEDIA_DIRECTORY&&process.env.PPTX_MEDIA_FIXTURE&&process.env.PPTX_MEDIA_ENGINE)
assert.ok(source||process.env.PPTX_MEDIA_STATIC&&process.env.PPTX_MEDIA_MANIFEST)
const output=resolve(process.env.PPTX_MEDIA_DIRECTORY),directory=resolve(process.env.PPTX_MEDIA_FIXTURE);await mkdir(output,{recursive:true})
const evidence={mode:source?'source':'frozen',cases:[],errors:[]};let vite,browser,fixture,page,stage='setup'
try{
 let sourceOrigin
 if(source){const {createServer,loadConfigFromFile}=await import('vite');const loaded=await loadConfigFromFile({command:'serve',mode:'development'},resolve(frontend,'vite.config.ts'));vite=await createServer({...loaded.config,root:frontend,configFile:false,cacheDir:resolve(output,'vite-cache'),server:{host:'127.0.0.1',port:0,cors:true,hmr:false}});await vite.listen();sourceOrigin=`http://127.0.0.1:${vite.httpServer.address().port}`}
 fixture=await createMediaNativeFixture({frontend,directory,engineRoot:resolve(process.env.PPTX_MEDIA_ENGINE),sourceOrigin,staticRoot:process.env.PPTX_MEDIA_STATIC&&resolve(process.env.PPTX_MEDIA_STATIC),expectedManifest:process.env.PPTX_MEDIA_MANIFEST});await fixture.listen()
 browser=await chromium.launch({headless:true});page=await browser.newPage();page.setDefaultTimeout(90000);await fixture.setup(page)
 const waitMedia=async selector=>{await page.locator(selector).waitFor();await page.waitForFunction(selector=>{const el=document.querySelector(selector);return el&&el.currentTime>.25&&el.readyState>=2&&!el.paused},selector,{timeout:15000})}
 const sample=selector=>page.locator(selector).evaluate(el=>{const canvas=document.createElement('canvas');canvas.width=160;canvas.height=90;if(el instanceof HTMLVideoElement)canvas.getContext('2d').drawImage(el,0,0,160,90);return {currentTime:el.currentTime,readyState:el.readyState,paused:el.paused,videoWidth:el.videoWidth??0,frame:canvas.toDataURL()}})
 const compact=sample=>({...sample,frame:createHash('sha256').update(sample.frame).digest('hex')})
 const viewports=process.env.PPTX_MEDIA_VIEWPORTS?JSON.parse(process.env.PPTX_MEDIA_VIEWPORTS):[[1440,900],[320,640],[640,360],[390,320]]
 for(const [width,height] of viewports){
  stage=`${width}x${height}:source`;console.log(stage);await page.setViewportSize({width,height});await fixture.open(page);await page.locator('[data-media-play]').nth(1).waitFor()
  const before=await fixture.draft(page)
  await page.locator('[data-media-play]').first().click();await waitMedia('.slides-media-playback video');const first=compact(await sample('.slides-media-playback video'));await page.waitForTimeout(400);const second=compact(await sample('.slides-media-playback video'));assert.notEqual(first.frame,second.frame);assert.ok(second.currentTime>first.currentTime)
  await page.screenshot({path:resolve(output,`editor-${width}x${height}.png`)});await page.locator('[aria-label="关闭媒体播放"]').click();assert.equal(await page.locator('.slides-media-playback').count(),0)
  await page.locator('[data-media-play]').nth(1).click();await waitMedia('.slides-media-playback audio');const audio=compact(await sample('.slides-media-playback audio'));await page.locator('[aria-label="关闭媒体播放"]').click()
  stage=`${width}x${height}:show`;console.log(stage);await page.locator('[data-ribbon-tab="slideShow"]').click();await page.locator('[data-command="startShow"]').click();await page.locator('.slides-show video').waitFor()
  await page.keyboard.press('ArrowRight');await waitMedia('.slides-show video');const shown=compact(await sample('.slides-show video'))
  await page.keyboard.press('ArrowRight');await page.waitForFunction(()=>document.querySelector('.slides-show video')?.paused===true);const paused=compact(await sample('.slides-show video'))
  await page.keyboard.press('ArrowRight');await page.waitForFunction(()=>{const v=document.querySelector('.slides-show video');return v?.paused&&v.currentTime===0})
  await page.screenshot({path:resolve(output,`show-${width}x${height}.png`)})
  await page.keyboard.press('ArrowRight');await page.waitForFunction(()=>document.querySelector('[aria-label="放映页码"]')?.textContent==='2 / 3')
  await page.locator('.slides-show video').evaluate(el=>el.click());await page.waitForFunction(()=>document.querySelector('.slides-show')?.textContent.includes('浏览器无法播放'))
  const unsupported=await page.locator('.slides-show').textContent();assert.match(unsupported,/AVI|浏览器无法播放/)
  await page.locator('.slides-show [aria-label="退出放映"]').click();assert.deepEqual(await fixture.draft(page),before)
  evidence.cases.push({width,height,editorVideo:[first,second],editorAudio:audio,showVideo:shown,pausedVideo:paused,mediaCommands:['play','pause','stop'],unsupportedExplicit:true,playbackDidNotMutateDraft:true})
 }
 stage='insert-and-save';console.log(stage);await page.setViewportSize({width:1440,height:900});await page.locator('.slide-open[data-slide-index="0"]').click();await page.locator('[data-ribbon-tab="insert"]').click()
 const [chooser]=await Promise.all([page.waitForEvent('filechooser'),page.locator('[data-command="insertAudio"]').click()]);await chooser.setFiles(resolve(directory,'insert.wav'))
 await page.waitForFunction(()=>document.querySelectorAll('[data-media-play]').length===3,null,{timeout:90000});assert.equal((await fixture.draft(page))[0].mediaInsertions.length,1)
 await page.locator('[aria-label="撤销"]').click();await page.waitForFunction(()=>document.querySelectorAll('[data-media-play]').length===2)
 await page.locator('[aria-label="重做"]').click();await page.waitForFunction(()=>document.querySelectorAll('[data-media-play]').length===3)
 const videoBytes=[...await readFile(resolve(directory,'insert.webm'))]
 await page.locator('.slides-canvas').evaluate((host,bytes)=>{const data=new DataTransfer();data.items.add(new File([new Uint8Array(bytes)],'insert.webm',{type:'application/octet-stream'}));const rect=host.getBoundingClientRect();host.dispatchEvent(new DragEvent('drop',{dataTransfer:data,bubbles:true,cancelable:true,clientX:rect.left+rect.width*.75,clientY:rect.top+rect.height*.7}))},videoBytes)
 await page.waitForFunction(()=>document.querySelectorAll('[data-media-play]').length===4,null,{timeout:90000});const journal=await fixture.draft(page);assert.equal(journal[0].mediaInsertions.length,2)
 await page.locator('[data-media-play]').last().click();await waitMedia('.slides-media-playback video');evidence.insertedVideo=compact(await sample('.slides-media-playback video'));await page.locator('[aria-label="关闭媒体播放"]').click()
 await page.locator('.structure-pending li').filter({hasText:'insert.webm'}).getByRole('button',{name:'撤销此项修改'}).click();await page.waitForFunction(()=>document.querySelectorAll('[data-media-play]').length===3)
 await page.locator('[aria-label="撤销"]').click();await page.waitForFunction(()=>document.querySelectorAll('[data-media-play]').length===4)
 await page.reload();await page.locator('.slides-canvas canvas').first().waitFor();await page.waitForFunction(()=>document.querySelectorAll('[data-media-play]').length===4,null,{timeout:90000});assert.deepEqual(await fixture.draft(page),journal)
 await page.locator('[data-action="save"]').click();await page.getByRole('link',{name:'下载 PPTX',exact:true}).waitFor({timeout:120000})
 const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('link',{name:'下载 PPTX',exact:true}).click()]);const downloaded=resolve(directory,'downloaded.pptx');await download.saveAs(downloaded)
 evidence.saved=fixture.engine({mode:'verify',file:downloaded});evidence.native=await fixture.finish();evidence.draftRestoreAndUndoRedo=true;assert.equal(await page.locator('[data-action="save"]').isDisabled(),true)
 await writeFile(resolve(output,'evidence.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify({ok:true,cases:evidence.cases.length,sourceSha256:evidence.native.sourceSha256,savedSha256:evidence.saved.savedSha256,resources:evidence.native.resourceCount}))
}catch(error){evidence.errors.push(`${stage}: ${error.stack}`);if(page){await page.screenshot({path:resolve(output,'failure.png')}).catch(()=>{});await writeFile(resolve(output,'failure.html'),await page.content()).catch(()=>{})}await writeFile(resolve(output,'evidence.json'),JSON.stringify(evidence,null,2));throw error}
finally{await browser?.close();await fixture?.close();await vite?.close()}
