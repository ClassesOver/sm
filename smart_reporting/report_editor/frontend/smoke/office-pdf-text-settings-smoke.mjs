// Frozen production assets and real grants/CSRF/PDF writer/publication; shared fixture repositories only.
import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
import {checkPdfTextSettingsLayout} from './office-pdf-text-settings-layout.mjs'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const directory=process.env.PDF_TEXT_SETTINGS_OUTPUT??'/tmp/office-pdf-text-settings-built-20261112',port=Number(process.env.PDF_TEXT_SETTINGS_PORT??4384),origin='http://127.0.0.1:'+port
const staticDirectory=process.env.PDF_SMOKE_STATIC_DIRECTORY??join(frontend,'../static')
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
await mkdir(directory,{recursive:true});const manifest=await readFile(join(staticDirectory,'.vite/manifest.json'));if(process.env.PDF_EXPECTED_MANIFEST_SHA256)assert.equal(sha(manifest),process.env.PDF_EXPECTED_MANIFEST_SHA256);await writeFile(join(directory,'build-manifest.json'),manifest)
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-static-text-server.py'),'--directory',directory,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo},stdio:'pipe'})
let serverLog='',browser,page,layout,stage='server';server.stdout.on('data',data=>{serverLog+=data;void writeFile(join(directory,'server-live.log'),serverLog)});server.stderr.on('data',data=>{serverLog+=data;void writeFile(join(directory,'server-live.log'),serverLog)})
const pageErrors=[],consoleErrors=[],httpErrors=[],assetErrors=[],checks=[],assets=new Map(),records=[]
try{
 for(let attempt=0;;attempt++){assert.equal(server.exitCode,null,serverLog);try{if((await fetch(origin+'/__smoke__/state',{signal:AbortSignal.timeout(1500)})).ok)break}catch{}assert(attempt<240,serverLog);await delay(250)}
 const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8'))
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})});page=await browser.newPage({viewport:{width:1500,height:1100}})
 page.on('pageerror',error=>pageErrors.push(error.message));page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text())})
 page.on('response',response=>{const path=new URL(response.url()).pathname;if(response.status()>=400)httpErrors.push({path,status:response.status()});if(response.status()!==200||!path.startsWith('/reports/v1/editor/assets/')||!(/\.(?:m?js|css)$/).test(path))return;checks.push((async()=>{const bytes=await response.body(),disk=await readFile(join(staticDirectory,path.slice('/reports/v1/editor/assets/'.length)));assert.equal(sha(bytes),sha(disk));assets.set(path,{sha256:sha(bytes),size:bytes.length})})().catch(error=>{assetErrors.push({path,error:String(error)})}))})
 const ready=()=>page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
 const operations=source=>page.evaluate(sourceSha=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).map(([,value])=>JSON.parse(value)).find(value=>value.identity?.sourceSha256===sourceSha)?.operations??[],source)
 const waitOperations=(source,count)=>page.waitForFunction(({sourceSha,count})=>(Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).map(([,value])=>JSON.parse(value)).find(value=>value.identity?.sourceSha256===sourceSha)?.operations??[]).length===count,{sourceSha:source,count})
 async function previewSave(name,sourceSha,parentRevision){
  const staged=await operations(sourceSha);assert.equal(staged.length,1)
  await page.locator('[data-pdf-ribbon-tab="edit"]').click()
  const previewing=page.waitForResponse(response=>response.url().endsWith('/api/preview')&&response.request().method()==='POST'&&response.request().postDataJSON().operations?.length===1)
  await page.getByRole('button',{name:'校验当前修改',exact:true}).click();const preview=await(await previewing).json()
  assert.deepEqual(preview.appliedOperationIndices,[0],JSON.stringify(preview));assert.deepEqual(preview.skippedOperations,[])
  await page.locator('.pdf-preview-review input[type="checkbox"]').waitFor({state:'visible'});await page.locator('.pdf-preview-review input[type="checkbox"]').check();await page.screenshot({path:join(directory,name+'-preview.png'),fullPage:true})
  stage=name+'-save';const saving=page.waitForResponse(response=>response.url().endsWith('/api/save')&&response.request().method()==='POST');await page.locator('[data-action="save"]').click();const saved=await saving,payload=await saved.json()
  assert.equal(saved.status(),200,JSON.stringify(payload));assert.equal(payload.revisionRegistered,true);assert.equal(payload.parentRevision,parentRevision);assert.equal(payload.revision,parentRevision+1);assert.deepEqual(saved.request().postDataJSON().operations,staged);assert.equal(saved.request().postDataJSON().confirmedPreviewDigest,preview.previewDigest)
  const link=page.locator('.native-delivery a').filter({hasText:'下载 PDF'});await link.waitFor();assert.equal(await link.getAttribute('href'),payload.artifacts.pdf.downloadUrl)
  const downloading=page.waitForEvent('download');await link.click();const download=await downloading;assert.equal(await download.failure(),null);const bytes=await readFile(await download.path());assert.equal(sha(bytes),payload.artifacts.pdf.sha256);assert.equal(bytes.length,payload.artifacts.pdf.size);await writeFile(join(directory,name+'.pdf'),bytes)
  records.push({name,staged,preview,payload});await page.goto(payload.editor.openUrl);await ready();const reopened=await page.evaluate(async()=>(await fetch(location.pathname+'/api/context')).json());assert.equal(reopened.context.revision,parentRevision+1);assert.equal(reopened.context.sourceFile.sha256,payload.artifacts.pdf.sha256);records.at(-1).reopened=reopened
  return payload
 }
 stage='layout';layout=await checkPdfTextSettingsLayout(page,{directory,reset:async()=>{await page.goto(origin+info.openPath);await ready()}});if(process.env.PDF_LAYOUT_BASELINE==='1'){await writeFile(join(directory,'baseline.json'),JSON.stringify({layout,manifestSha256:sha(manifest)},null,2));console.log(JSON.stringify({baseline:true,failures:layout.failures.length}));}else{assert.deepEqual(layout.failures,[]);
 await page.setViewportSize({width:1440,height:900});
 stage='selection-existing-replacement';await page.goto(origin+info.openPath);await ready()
 const edit=page.locator('[data-source-command-id="genoffice.pdf.home.edit.editText"]');await edit.waitFor();await page.waitForFunction(()=>!document.querySelector('[data-source-command-id="genoffice.pdf.home.edit.editText"]')?.disabled);await edit.click()
 const objects=page.getByLabel('待修改文字对象',{exact:true});await objects.waitFor();await objects.selectOption({label:'source page one'})
 const panel=page.locator('.pdf-text-editor'),textarea=panel.getByLabel('替换后的文字',{exact:true});await textarea.fill('AABBCC');await panel.getByLabel('替换文字字体',{exact:true}).selectOption('courier');await panel.getByLabel('替换文字字号',{exact:true}).fill('12');await panel.getByLabel('替换文字对齐',{exact:true}).selectOption('left')
 await textarea.focus();await textarea.press('Home');await textarea.press('ArrowRight');await textarea.press('ArrowRight');await textarea.press('Shift+ArrowRight');await textarea.press('Shift+ArrowRight')
 assert.deepEqual(await textarea.evaluate(node=>[node.selectionStart,node.selectionEnd]),[2,4])
 await panel.getByLabel('选区字号',{exact:true}).fill('5');await panel.locator('[data-pdf-selection-style-apply]').click();assert.match(await panel.locator('.pdf-text-selection-style [role=alert]').innerText(),/6–72/);assert.equal(await panel.getByLabel('选区字号',{exact:true}).inputValue(),'5');assert.deepEqual(await textarea.evaluate(node=>[node.selectionStart,node.selectionEnd]),[2,4]);assert.deepEqual(await operations(info.sourceSha256),[]);
 await panel.getByLabel('选区字体',{exact:true}).selectOption('times');await panel.getByLabel('选区字号',{exact:true}).fill('18');await panel.getByLabel('选区粗体',{exact:true}).selectOption('true');await panel.getByLabel('选区斜体',{exact:true}).selectOption('true');await panel.getByLabel('选区指定颜色',{exact:true}).check();await panel.getByLabel('选区颜色',{exact:true}).fill('#ff0000');await panel.locator('[data-pdf-selection-style-apply]').click()
 assert.deepEqual(await textarea.evaluate(node=>[node.selectionStart,node.selectionEnd,node===document.activeElement]),[2,4,true]);const current=panel.locator('[data-pdf-selection-style-current]');assert.equal(await current.getAttribute('data-font'),'times');assert.equal(await current.getAttribute('data-size'),'18');assert.equal(await current.getAttribute('data-bold'),'true');assert.equal(await current.getAttribute('data-color'),'#ff0000')
 await textarea.press('Home');await textarea.press('ArrowRight');for(let i=0;i<4;i++)await textarea.press('Shift+ArrowRight');assert.equal(await current.getAttribute('data-font'),'mixed');await panel.screenshot({path:join(directory,'mixed-selection.png')})
 await textarea.press('Home');await textarea.press('ArrowRight');await textarea.press('ArrowRight');await textarea.press('Shift+ArrowRight');await textarea.press('Shift+ArrowRight')
 await panel.getByLabel('替换文字字体',{exact:true}).selectOption('arial');assert.equal(await current.getAttribute('data-font'),'inherit');assert.equal(await current.getAttribute('data-size'),'18')
 await panel.getByLabel('替换文字字号',{exact:true}).fill('16');assert.equal(await current.getAttribute('data-size'),'inherit');assert.equal(await current.getAttribute('data-color'),'#ff0000')
 await panel.getByLabel('替换文字指定颜色',{exact:true}).check();await panel.getByLabel('替换文字颜色',{exact:true}).fill('#0000ff');assert.equal(await current.getAttribute('data-color'),'inherit');assert.equal(await current.getAttribute('data-bold'),'true')
 await panel.getByLabel('替换文字粗体',{exact:true}).check();assert.equal(await current.getAttribute('data-bold'),'inherit');assert.equal(await current.getAttribute('data-italic'),'true')
 await panel.getByLabel('替换文字斜体',{exact:true}).check();assert.equal(await current.getAttribute('data-italic'),'inherit');assert.match(await panel.locator('.pdf-text-selection-style').innerText(),/尚未配置选区样式/)
 await panel.screenshot({path:join(directory,'whole-fields-cleared.png')})
 await panel.getByLabel('替换文字字体',{exact:true}).selectOption('courier');await panel.getByLabel('替换文字字号',{exact:true}).fill('12');await panel.getByLabel('替换文字粗体',{exact:true}).uncheck();await panel.getByLabel('替换文字斜体',{exact:true}).uncheck();await panel.getByLabel('替换文字指定颜色',{exact:true}).uncheck()
 await panel.locator('[data-pdf-selection-style-apply]').click();assert.equal(await current.getAttribute('data-font'),'times');await panel.locator('[data-pdf-selection-style-clear]').click();assert.equal(await current.getAttribute('data-font'),'inherit');assert.deepEqual(await textarea.evaluate(node=>[node.selectionStart,node.selectionEnd,node.selectionDirection,node===document.activeElement]),[2,4,'forward',true]);await panel.screenshot({path:join(directory,'selection-cleared.png')})
 await panel.locator('[data-pdf-selection-style-apply]').click();assert.equal(await current.getAttribute('data-font'),'times');assert.deepEqual(await textarea.evaluate(node=>[node.selectionStart,node.selectionEnd,node===document.activeElement]),[2,4,true]);await panel.screenshot({path:join(directory,'selection-configuration.png')});await panel.getByRole('button',{name:'加入文字修改',exact:true}).click();await waitOperations(info.sourceSha256,1)
 const replaced=await operations(info.sourceSha256);assert.equal(replaced[0].kind,'replaceText');assert.equal(replaced[0].sourceSha256,info.sourceSha256);assert.equal(replaced[0].font,'courier');assert.equal(replaced[0].align,'left');assert.equal(replaced[0].newText,'AABBCC');assert.deepEqual(replaced[0].styleRuns,[{start:2,end:4,color:[1,0,0],font:'times',size:18,bold:true,italic:true}])
 await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click();await waitOperations(info.sourceSha256,0);await page.locator('[data-source-command-id="genoffice.pdf.home.edit.redo"]').click();await waitOperations(info.sourceSha256,1);assert.deepEqual(await operations(info.sourceSha256),replaced)
 await page.reload();await ready();await waitOperations(info.sourceSha256,1);assert.deepEqual(await operations(info.sourceSha256),replaced)
 const saved=await previewSave('selection',info.sourceSha256,4)
 await page.locator('.pdf-page .textLayer').filter({hasText:'AA'}).first().waitFor();await page.screenshot({path:join(directory,'reopened-final.png'),fullPage:true})
 stage='independent-pypdf';const python=String.raw`import sys,json,hashlib
from pathlib import Path
from pypdf import PdfReader
from pypdf.generic import ContentStream
root=Path(sys.argv[1]);source=PdfReader(root/'source.pdf');output=PdfReader(root/'selection.pdf')
assert len(source.pages)==len(output.pages)==3
for index in range(3):
 if index: assert source.pages[index].extract_text().strip() in output.pages[index].extract_text()
 assert list(source.pages[index].mediabox)==list(output.pages[index].mediabox)
 assert list(source.pages[index].cropbox)==list(output.pages[index].cropbox)
assert 'source page one' not in output.pages[0].extract_text()
found=[];output.pages[0].extract_text(visitor_text=lambda text,cm,tm,font,size:found.append((text,cm,tm,font,size)));rows=[]
for segment,family,size,expected_x in [('AA','LiberationMono',12,24),('BB','LiberationSerif-BoldItalic',18,38.4),('CC','LiberationMono',12,62.412)]:
 text,cm,tm,font,pt=next(value for value in found if value[0].strip()==segment)
 assert family in str(font['/BaseFont']) and abs(pt-size)<.002
 x=tm[4]*cm[0]+tm[5]*cm[2]+cm[4];y=tm[4]*cm[1]+tm[5]*cm[3]+cm[5]
 assert abs(x-expected_x)<.05 and abs(y-350)<.002,(segment,x,y,expected_x)
 descriptor=font['/DescendantFonts'][0].get_object()['/FontDescriptor'].get_object();assert len(descriptor['/FontFile2'].get_object().get_data())>100
 rows.append({'text':segment,'font':str(font['/BaseFont']),'size':pt,'baseline':[x,y]})
colors=[args for args,operator in ContentStream(output.pages[0].get_contents(),output).operations if operator==b'rg'];assert any(list(map(float,color))==[1,0,0] for color in colors)
assert not output.pages[0].get('/Annots') and not output.get_fields()
print(json.dumps({'ok':True,'rows':rows,'selectionColor':[1,0,0],'otherPagesPreserved':True,'sourceSha256':hashlib.sha256((root/'source.pdf').read_bytes()).hexdigest(),'outputSha256':hashlib.sha256((root/'selection.pdf').read_bytes()).hexdigest()}))`
 const verification=spawnSync(join(repo,'.venv/bin/python'),['-c',python,directory],{cwd:repo,encoding:'utf8'});assert.equal(verification.status,0,verification.stderr);const independent=JSON.parse(verification.stdout);assert.equal(independent.sourceSha256,info.sourceSha256);assert.equal(independent.outputSha256,saved.artifacts.pdf.sha256);await writeFile(join(directory,'independent.json'),JSON.stringify(independent,null,2))
 await Promise.all(checks);assert(assets.size>0);assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[]);assert.deepEqual(assetErrors,[]);assert.deepEqual(await readFile(join(staticDirectory,'.vite/manifest.json')),manifest)
 const state=await(await fetch(origin+'/__smoke__/state',{signal:AbortSignal.timeout(1500)})).json();assert.equal(state.sourceSha256,info.sourceSha256);assert.equal(state.savedRevisions,1)
 const summary={ok:true,directory,feature:'whole draft field inheritance reset and keyboard selection uniform mixed inherited state with clear/refocus',scope:'real production assets/PDF.js/grants/cookies/CSRF/packed engine/publication/download/reopen; fixture persistence only',browserVersion:browser.version(),manifestSha256:sha(manifest),sourceSha256:info.sourceSha256,records,independent,sourceUnchanged:true,layout,assets:Object.fromEntries(assets),pageErrors,consoleErrors,httpErrors,assetErrors,requests:state.requests};await writeFile(join(directory,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok:true,directory}))
}
}catch(error){await page?.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});if(page)await page.content().then(html=>writeFile(join(directory,'failure.html'),html)).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),pageErrors,consoleErrors,httpErrors,assetErrors},null,2));throw error}finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),serverLog);if(server.exitCode===null)await Promise.race([new Promise(resolve=>server.once('exit',resolve)),delay(5000)]);if(server.exitCode===null)server.kill('SIGKILL')}
