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
const directory=process.env.WORD_FAMILIES_EVIDENCE??'/tmp/word-families-20261114',staticRoot=process.env.WORD_FAMILIES_BUILD??'/tmp/word-genoffice-families-build'
const port=Number(process.env.WORD_FAMILIES_PORT??4298),origin='http://127.0.0.1:'+port,sha=bytes=>createHash('sha256').update(bytes).digest('hex')
await mkdir(directory,{recursive:true})
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/word-review-presets-server.py'),'--directory',directory,'--static',staticRoot,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo},stdio:'pipe'})
let log='',browser,page,stage='server';server.stdout.on('data',data=>{log+=data});server.stderr.on('data',data=>{log+=data})
const errors=[],checks=[],assets=new Map(),saves=[]
try{
 for(let i=0;;i++){assert.equal(server.exitCode,null,log);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(i<180,log);await delay(250)}
 const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8'))
 browser=await chromium.launch({headless:true});const fontProbe=await probeCanvasTextRendering(browser);await writeFile(join(directory,'font-preflight.json'),JSON.stringify(fontProbe,null,2));assert(fontProbe.ok)
 page=await browser.newPage({viewport:{width:1450,height:1000}});page.on('pageerror',error=>errors.push(error.message))
 page.on('response',response=>{
  const path=new URL(response.url()).pathname
  if(!path.startsWith('/reports/v1/editor/assets/')||!/\.(js|css)$/.test(path))return
  const check=(async()=>{if(response.status()===304){assert(assets.has(path),'cached resource needs an earlier verified response');return}assert.equal(response.status(),200);const bytes=await response.body(),disk=await readFile(join(staticRoot,path.slice('/reports/v1/editor/assets/'.length)));assert.equal(sha(bytes),sha(disk));assets.set(path,sha(bytes))})()
  check.catch(()=>{});checks.push(check)
 })
 const body=()=>page.getByRole('textbox',{name:'Word 文档编辑区',exact:true})
 async function save(name){const response=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/save'));await page.locator('[data-action=save]').click();const receipt=await(await response).json();await writeFile(join(directory,name+'-saved.json'),JSON.stringify(receipt,null,2));assert.equal(receipt.revisionRegistered,true,JSON.stringify(receipt));const download=await page.request.get(receipt.artifacts.word.downloadUrl);assert.equal(download.status(),200);const bytes=await download.body();assert.equal(sha(bytes),receipt.artifacts.word.sha256);await writeFile(join(directory,name+'.docx'),bytes);saves.push({name,revision:receipt.revision,sha256:sha(bytes),validation:receipt.validation});await page.goto(receipt.editor.openUrl);await body().waitFor({timeout:60000});return receipt}
 stage='open';await page.goto(origin+info.openPath);await body().waitFor({timeout:60000});await body().getByText('现金流稳定。',{exact:true}).waitFor()
 if(!process.env.WORD_FAMILIES_RESUME_DIRECTORY){
 stage='insert-textbox';await page.getByRole('tab',{name:'插入',exact:true}).click();await page.locator('[data-action=insert-text-box]').click();await page.getByRole('textbox',{name:'对象文字',exact:true}).fill('BoxAdded');await page.getByRole('dialog',{name:'文本框',exact:true}).getByRole('button',{name:'插入',exact:true}).click();await page.getByRole('dialog',{name:'文本框',exact:true}).waitFor({state:'hidden'})
 stage='theme';await page.getByRole('tab',{name:'设计',exact:true}).click();await page.getByRole('combobox',{name:'主题',exact:true}).selectOption('ribbonThemeFacet')
 stage='ink';await page.getByRole('tab',{name:'绘图',exact:true}).click();await page.locator('[data-action=ink-pen]').click();const rect=await body().locator('p[data-idx="0"]').boundingBox();assert(rect);await page.mouse.move(rect.x+10,rect.y+10);await page.mouse.down();await page.mouse.move(rect.x+100,rect.y+20,{steps:12});await page.mouse.up();await page.locator('[data-action=ink-select]').click();assert(await page.locator('.ink-svg path').count()>0)
 stage='save-content';await save('content-r2')
 stage='export';await page.getByRole('tab',{name:'开始',exact:true}).click();for(const [action,file]of[['convert-html','export.html'],['convert-markdown','export.md']]){const wait=page.waitForEvent('download');await page.locator('[data-action='+action+']').click();const download=await wait;await download.saveAs(join(directory,file));assert((await readFile(join(directory,file))).length>0)}
 stage='protect';await page.getByRole('tab',{name:'审阅',exact:true}).click();await page.locator('[data-action=review-protect]').click();const dialog=page.getByRole('dialog',{name:'保护文档',exact:true});await dialog.getByLabel('保护密码（可选）',{exact:true}).fill('probe-password');await dialog.getByLabel('确认密码',{exact:true}).fill('probe-password');await dialog.getByRole('button',{name:'启用保护',exact:true}).click();assert(!(await page.evaluate(()=>JSON.stringify(localStorage))).includes('probe-password'));await save('protected-r3')
 }else{for(const name of ['content-r2','protected-r3']){const receipt=JSON.parse(await readFile(join(directory,name+'-saved.json'),'utf8'));saves.push({name,revision:receipt.revision,sha256:receipt.artifacts.word.sha256,validation:receipt.validation,resumed:true})}}
 stage='protected-state';await page.getByRole('tab',{name:'设计',exact:true}).click();assert(await page.getByRole('combobox',{name:'主题',exact:true}).isDisabled());await page.getByRole('tab',{name:'审阅',exact:true}).click();await page.locator('[data-action=review-protect]').click();await page.getByLabel('当前保护密码',{exact:true}).fill('probe-password');await page.getByRole('button',{name:'解除保护',exact:true}).click();await save('unprotected-r4')
 stage='independent';const independent=spawnSync(join(repo,'.venv/bin/python'),['-c',`import json,sys\nfrom docx import Document\nfrom zipfile import ZipFile\nfrom lxml import etree as E\nroot=sys.argv[1]\nns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main'}\nwith ZipFile(root+'/content-r2.docx') as z:\n xml=E.fromstring(z.read('word/document.xml'));assert 'BoxAdded' in ''.join(xml.itertext());assert b'aidocs-ink' in z.read('word/document.xml');theme=E.fromstring(z.read('word/theme/theme1.xml'));assert theme.xpath('string(//a:clrScheme/a:accent1/a:srgbClr/@val)',namespaces=ns)=='90C226'\n d=Document(root+'/content-r2.docx');assert d.sections[0].header.paragraphs[0].text=='HEADER KEEP';assert d.sections[0].footer.paragraphs[0].text=='FOOTER KEEP'\nwith ZipFile(root+'/protected-r3.docx') as z:\n p=E.fromstring(z.read('word/settings.xml')).find('w:documentProtection',ns);assert p is not None and p.get('{'+ns['w']+'}hash')\nwith ZipFile(root+'/unprotected-r4.docx') as z:assert E.fromstring(z.read('word/settings.xml')).find('w:documentProtection',ns) is None\nprint(json.dumps({'textbox':True,'theme':'Facet','ink':True,'protected':True,'unprotected':True}))`,directory],{encoding:'utf8'});assert.equal(independent.status,0,independent.stderr);await writeFile(join(directory,'independent.json'),independent.stdout)
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:join(directory,'final-narrow.png'),fullPage:true});await Promise.all(checks);assert.equal(errors.length,0,errors.join('\n'));await writeFile(join(directory,'result.json'),JSON.stringify({ok:true,saves,assets:Object.fromEntries(assets),errors,manifestSha256:sha(await readFile(join(staticRoot,'.vite/manifest.json')))},null,2));console.log(JSON.stringify({ok:true,directory,saves:saves.length,assets:assets.size}))
}catch(error){await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,log},null,2));if(page)await page.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});throw error}
finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),log)}
