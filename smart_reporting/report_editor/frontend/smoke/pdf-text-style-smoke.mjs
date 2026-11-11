// Frozen production assets and real grants/CSRF/PDF writer/publication; shared fixture repositories only.
import assert from 'node:assert/strict'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url))
const directory=process.env.PDF_TEXT_STYLE_SMOKE_DIRECTORY??'/tmp/pdf-text-style-browser-20261111-root01',port=Number(process.env.PDF_TEXT_STYLE_SMOKE_PORT??4306),origin='http://127.0.0.1:'+port
const sha=bytes=>createHash('sha256').update(bytes).digest('hex')
await mkdir(directory,{recursive:true});const manifest=await readFile(join(frontend,'../static/.vite/manifest.json'));await writeFile(join(directory,'build-manifest.json'),manifest)
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/pdf-static-text-server.py'),'--directory',directory,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo},stdio:'pipe'})
let serverLog='',browser,page,stage='server';server.stdout.on('data',data=>{serverLog+=data;void writeFile(join(directory,'server-live.log'),serverLog)});server.stderr.on('data',data=>{serverLog+=data;void writeFile(join(directory,'server-live.log'),serverLog)})
const pageErrors=[],consoleErrors=[],httpErrors=[],assetErrors=[],checks=[],assets=new Map(),records=[]
try{
 for(let attempt=0;;attempt++){assert.equal(server.exitCode,null,serverLog);try{if((await fetch(origin+'/__smoke__/state',{signal:AbortSignal.timeout(1500)})).ok)break}catch{}assert(attempt<240,serverLog);await delay(250)}
 const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8'))
 browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})});page=await browser.newPage({viewport:{width:1500,height:1100}})
 page.on('pageerror',error=>pageErrors.push(error.message));page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text())})
 page.on('response',response=>{const path=new URL(response.url()).pathname;if(response.status()>=400)httpErrors.push({path,status:response.status()});if(response.status()!==200||!path.startsWith('/reports/v1/editor/assets/')||!(/\.m?js$/).test(path))return;checks.push((async()=>{const bytes=await response.body(),disk=await readFile(join(frontend,'../static',path.slice('/reports/v1/editor/assets/'.length)));assert.equal(sha(bytes),sha(disk));assets.set(path,sha(bytes))})().catch(error=>{assetErrors.push({path,error:String(error)})}))})
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
  const download=await page.request.get(payload.artifacts.pdf.downloadUrl);assert.equal(download.status(),200);const bytes=await download.body();assert.equal(sha(bytes),payload.artifacts.pdf.sha256);assert.equal(bytes.length,payload.artifacts.pdf.size);await writeFile(join(directory,name+'.pdf'),bytes)
  records.push({name,staged,preview,payload});await page.goto(payload.editor.openUrl);await ready();const reopened=await page.evaluate(async()=>(await fetch(location.pathname+'/api/context')).json());assert.equal(reopened.context.revision,parentRevision+1);assert.equal(reopened.context.sourceFile.sha256,payload.artifacts.pdf.sha256);records.at(-1).reopened=reopened
  return payload
 }
 stage='styled-insert';await page.goto(origin+info.openPath);await ready();const command=page.locator('[data-source-command-id="genoffice.pdf.home.edit.insertText"]');await command.waitFor();assert.equal(await command.isDisabled(),false);await command.click()
 const dialog=page.getByRole('dialog',{name:'插入文字',exact:true});await dialog.waitFor({state:'visible'})
 await dialog.getByLabel('插入文字内容',{exact:true}).fill('First insert\n\nNext insert');await dialog.getByLabel('插入文字字号',{exact:true}).fill('18');await dialog.getByLabel('插入文字字体',{exact:true}).selectOption('courier');await dialog.getByLabel('插入文字粗体',{exact:true}).check();await dialog.getByLabel('插入文字斜体',{exact:true}).check();await dialog.getByLabel('插入文字对齐',{exact:true}).selectOption('center');await dialog.getByLabel('插入文字行距',{exact:true}).fill('18');await dialog.getByLabel('插入文字颜色',{exact:true}).fill('#336699');await dialog.screenshot({path:join(directory,'insert-configuration.png')});await dialog.locator('[data-pdf-static-text-confirm]').click()
 const holder=page.locator('.pdf-page-content').first();await holder.locator('canvas').waitFor();const bounds=await holder.boundingBox();assert(bounds);await holder.click({position:{x:bounds.width*.5,y:bounds.height*.5}});await waitOperations(info.sourceSha256,1)
 const inserted=await operations(info.sourceSha256);assert.equal(inserted[0].align,'center');assert.equal(inserted[0].font,'courier');assert.equal(inserted[0].bold,true);assert.equal(inserted[0].italic,true);assert.equal(inserted[0].text,'First insert\n\nNext insert');assert(Math.abs(inserted[0].origin[0]-150)<1);assert(Math.abs(inserted[0].origin[1]-200)<1)
 await page.locator('[data-source-command-id="genoffice.pdf.home.edit.undo"]').click();await waitOperations(info.sourceSha256,0);await page.locator('[data-source-command-id="genoffice.pdf.home.edit.redo"]').click();await waitOperations(info.sourceSha256,1);assert.deepEqual(await operations(info.sourceSha256),inserted)
 const first=await previewSave('insert',info.sourceSha256,4)
 stage='styled-existing-replacement';const edit=page.locator('[data-source-command-id="genoffice.pdf.home.edit.editText"]');await edit.waitFor();await page.waitForFunction(()=>!document.querySelector('[data-source-command-id="genoffice.pdf.home.edit.editText"]')?.disabled);await edit.click()
 const objects=page.getByLabel('待修改文字对象',{exact:true});await objects.waitFor();await objects.selectOption({label:'First insert'})
 const panel=page.locator('.pdf-text-editor');await panel.getByLabel('替换后的文字',{exact:true}).fill('Changed\n\nAgain');await panel.getByLabel('替换文字字体',{exact:true}).selectOption('times');await panel.getByLabel('替换文字字号',{exact:true}).fill('14');await panel.getByLabel('替换文字粗体',{exact:true}).check();await panel.getByLabel('替换文字斜体',{exact:true}).check();await panel.getByLabel('替换文字对齐',{exact:true}).selectOption('right');await panel.getByLabel('替换文字行距',{exact:true}).fill('18');await panel.getByLabel('替换文字指定颜色',{exact:true}).check();await panel.getByLabel('替换文字颜色',{exact:true}).fill('#993366');await panel.screenshot({path:join(directory,'replacement-configuration.png')});await panel.getByRole('button',{name:'加入文字修改',exact:true}).click();await waitOperations(first.artifacts.pdf.sha256,1)
 const replaced=await operations(first.artifacts.pdf.sha256);assert.equal(replaced[0].kind,'replaceText');assert.equal(replaced[0].sourceSha256,first.artifacts.pdf.sha256);assert.equal(replaced[0].font,'times');assert.equal(replaced[0].align,'right');assert.equal(replaced[0].newText,'Changed\n\nAgain')
 const second=await previewSave('replacement',first.artifacts.pdf.sha256,5)
 await page.locator('.pdf-page .textLayer').filter({hasText:'Changed'}).first().waitFor();await page.screenshot({path:join(directory,'reopened-final.png'),fullPage:true})
 stage='independent-pypdf';const python=String.raw`import sys,json,hashlib
from pathlib import Path
from pypdf import PdfReader
from pypdf.generic import ContentStream
root=Path(sys.argv[1]);source=PdfReader(root/'source.pdf');insert=PdfReader(root/'insert.pdf');output=PdfReader(root/'replacement.pdf')
assert len(source.pages)==len(insert.pages)==len(output.pages)==3
for index in range(3):
 assert source.pages[index].extract_text().strip() in output.pages[index].extract_text()
 assert list(source.pages[index].mediabox)==list(output.pages[index].mediabox)
 assert list(source.pages[index].cropbox)==list(output.pages[index].cropbox)
assert 'First insert' in insert.pages[0].extract_text() and 'First insert' not in output.pages[0].extract_text()
assert 'Next insert' in output.pages[0].extract_text() and 'Changed' in output.pages[0].extract_text() and 'Again' in output.pages[0].extract_text()
rows=[]
for reader,line,family,size,color in [(insert,'First insert','LiberationMono-BoldItalic',18,[.2,.4,.6]),(insert,'Next insert','LiberationMono-BoldItalic',18,[.2,.4,.6]),(output,'Changed','LiberationSerif-BoldItalic',14,[.6,.2,.4]),(output,'Again','LiberationSerif-BoldItalic',14,[.6,.2,.4])]:
 found=[];reader.pages[0].extract_text(visitor_text=lambda text,cm,tm,font,pt:found.append((text,cm,tm,font,pt)))
 text,cm,tm,font,pt=next(value for value in found if line in value[0]);x=tm[4]*cm[0]+tm[5]*cm[2]+cm[4];y=tm[4]*cm[1]+tm[5]*cm[3]+cm[5]
 assert family in str(font['/BaseFont']) and abs(pt-size)<.002
 expected={'First insert':[85.2,200],'Next insert':[90.6,164],'Changed':[33.106,200],'Again':[50.214,164]}[line]
 assert abs(x-expected[0])<1 and abs(y-expected[1])<1,(line,x,y,expected)
 descriptor=font['/DescendantFonts'][0].get_object()['/FontDescriptor'].get_object();assert len(descriptor['/FontFile2'].get_object().get_data())>100
 colors=[args for args,operator in ContentStream(reader.pages[0].get_contents(),reader).operations if operator==b'rg'];assert any(all(abs(float(value)-expected)<.002 for value,expected in zip(actual,color)) for actual in colors)
 rows.append({'text':line,'font':family,'size':pt,'baseline':[x,y],'color':color})
 assert not reader.pages[0].get('/Annots') and not reader.get_fields()
print(json.dumps({'ok':True,'rows':rows,'sourceBodyPreserved':True,'sourceSha256':hashlib.sha256((root/'source.pdf').read_bytes()).hexdigest(),'insertSha256':hashlib.sha256((root/'insert.pdf').read_bytes()).hexdigest(),'replacementSha256':hashlib.sha256((root/'replacement.pdf').read_bytes()).hexdigest()}))`
 const verification=spawnSync(join(repo,'.venv/bin/python'),['-c',python,directory],{cwd:repo,encoding:'utf8'});assert.equal(verification.status,0,verification.stderr);const independent=JSON.parse(verification.stdout);assert.equal(independent.sourceSha256,info.sourceSha256);assert.equal(independent.insertSha256,first.artifacts.pdf.sha256);assert.equal(independent.replacementSha256,second.artifacts.pdf.sha256);await writeFile(join(directory,'independent.json'),JSON.stringify(independent,null,2))
 await Promise.all(checks);assert(assets.size>0);assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[]);assert.deepEqual(assetErrors,[]);assert.deepEqual(await readFile(join(frontend,'../static/.vite/manifest.json')),manifest)
 const state=await(await fetch(origin+'/__smoke__/state',{signal:AbortSignal.timeout(1500)})).json();assert.equal(state.sourceSha256,info.sourceSha256);assert.equal(state.savedRevisions,2)
 const summary={ok:true,directory,feature:'styled multiline static insert and source-bound existing object replacement',scope:'real production assets/PDF.js/grants/cookies/CSRF/packed engine/publication/download/reopen; fixture persistence only',browserVersion:browser.version(),manifestSha256:sha(manifest),sourceSha256:info.sourceSha256,records,independent,sourceUnchanged:true,assets:Object.fromEntries(assets),pageErrors,consoleErrors,httpErrors,assetErrors,requests:state.requests};await writeFile(join(directory,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok:true,directory}))
}catch(error){await page?.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});if(page)await page.content().then(html=>writeFile(join(directory,'failure.html'),html)).catch(()=>{});await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),pageErrors,consoleErrors,httpErrors,assetErrors},null,2));throw error}finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),serverLog);if(server.exitCode===null)await Promise.race([new Promise(resolve=>server.once('exit',resolve)),delay(5000)]);if(server.exitCode===null)server.kill('SIGKILL')}
