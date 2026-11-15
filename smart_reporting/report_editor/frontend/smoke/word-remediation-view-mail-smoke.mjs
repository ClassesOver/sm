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
const directory=process.env.WORD_REMEDIATION_EVIDENCE??'/tmp/word-remediation-view-mail-20261114',staticRoot=process.env.WORD_REMEDIATION_BUILD??'/tmp/word-remediation-batch1-build'
const port=Number(process.env.WORD_REMEDIATION_PORT??4307),origin='http://127.0.0.1:'+port,sha=bytes=>createHash('sha256').update(bytes).digest('hex')
assert(process.env.FONTCONFIG_FILE?.startsWith('/'),'Use an absolute FONTCONFIG_FILE for browser font evidence')
await mkdir(directory,{recursive:true})
const fixture=join(directory,'template.docx')
const generated=spawnSync(join(repo,'.venv/bin/python'),['-c',`from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import sys
d=Document();p=d.add_paragraph('Dear ');f=OxmlElement('w:fldSimple');f.set(qn('w:instr'),' MERGEFIELD Name ');r=OxmlElement('w:r');t=OxmlElement('w:t');t.text='«Name»';r.append(t);f.append(r);p._p.append(f)
d.add_paragraph('secondplain')
if sys.argv[2]=='1':
 protection=OxmlElement('w:documentProtection');protection.set(qn('w:edit'),'readOnly');protection.set(qn('w:enforcement'),'1');d.settings.element.append(protection)
d.sections[0].header.paragraphs[0].text='HEADER KEEP';d.sections[0].footer.paragraphs[0].text='FOOTER KEEP';d.save(sys.argv[1])`,fixture,process.env.WORD_REMEDIATION_PROTECTED_ONLY?'1':'0'],{encoding:'utf8'});assert.equal(generated.status,0,generated.stderr)
await writeFile(join(directory,'recipients.csv'),'Name,Address\nAda,First Street\nGrace,Second Street\n')
const server=spawn(join(repo,'.venv/bin/python'),[join(frontend,'smoke/word-review-presets-server.py'),'--directory',directory,'--static',staticRoot,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo,WORD_PRESETS_REOPEN_FILE:fixture},stdio:'pipe'})
let log='',browser,page,stage='server';server.stdout.on('data',data=>{log+=data});server.stderr.on('data',data=>{log+=data})
const errors=[],checks=[],assets=new Map(),exports=[]
try{
 for(let i=0;;i++){assert.equal(server.exitCode,null,log);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(i<180,log);await delay(250)}
 const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8'))
 browser=await chromium.launch({headless:true});const fontProbe=await probeCanvasTextRendering(browser);await writeFile(join(directory,'font-preflight.json'),JSON.stringify(fontProbe,null,2));assert(fontProbe.ok)
 page=await browser.newPage({viewport:{width:1450,height:1000}});page.on('pageerror',error=>errors.push(error.message))
 page.on('response',response=>{const path=new URL(response.url()).pathname;if(!path.startsWith('/reports/v1/editor/assets/')||!/\.(js|css)$/.test(path))return;const check=(async()=>{if(response.status()===304){assert(assets.has(path));return}assert.equal(response.status(),200);const bytes=await response.body(),disk=await readFile(join(staticRoot,path.slice('/reports/v1/editor/assets/'.length)));assert.equal(sha(bytes),sha(disk));assets.set(path,sha(bytes))})();check.catch(()=>{});checks.push(check)})
 const body=()=>page.getByRole('textbox',{name:'Word 文档编辑区',exact:true}), tab=label=>page.getByRole('tab',{name:label,exact:true})
 stage='open';await page.goto(origin+info.openPath);await body().waitFor({timeout:60000});await body().getByText('secondplain',{exact:true}).waitFor()
 const originalText=await body().textContent(),originalHtml=await body().innerHTML()
 if(process.env.WORD_REMEDIATION_PROTECTED_ONLY){
  stage='protected-read';assert.equal(await body().getAttribute('contenteditable'),'false');await tab('视图').click();await page.getByRole('button',{name:'阅读视图',exact:true}).click();assert.equal(await body().getAttribute('contenteditable'),'false');await page.keyboard.press('Escape');assert.equal(await body().getAttribute('contenteditable'),'false');await body().click();await page.keyboard.type('BLOCKED');assert.equal(await body().textContent(),originalText)
  await page.screenshot({path:join(directory,'protected-read.png'),fullPage:true});await Promise.all(checks);assert.equal(errors.length,0,errors.join('\n'));await writeFile(join(directory,'result.json'),JSON.stringify({ok:true,protectedReadExitRemainsReadonly:true,assets:Object.fromEntries(assets),manifestSha256:sha(await readFile(join(staticRoot,'.vite/manifest.json'))),sourceSha256:sha(await readFile(fixture)),errors,saveCount:0},null,2));console.log(JSON.stringify({ok:true,directory,protectedReadExitRemainsReadonly:true,assets:assets.size}))
 }else{
 stage='home-caret-bold';await tab('开始').click();await body().getByText('secondplain',{exact:true}).click();await page.keyboard.press('End');await page.locator('[data-action=bold]').click();assert.equal(await body().textContent(),originalText);assert.equal(await body().innerHTML(),originalHtml);await page.locator('[data-action=bold]').click()
 stage='web';await tab('视图').click();await page.getByRole('button',{name:'Web 版式',exact:true}).click();await page.locator('.docx-native.docx-view-web').waitFor();assert.equal(await body().evaluate(el=>getComputedStyle(el).boxShadow),'none');await page.getByRole('button',{name:'页面视图',exact:true}).click();assert.equal(await page.locator('.docx-view-web').count(),0)
 stage='dark';await page.getByRole('button',{name:'深色模式',exact:true}).click();assert.equal(await page.evaluate(()=>localStorage.getItem('aidocs.darkPage')),'1');assert.equal(await body().evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(30, 30, 30)');await page.getByRole('button',{name:'深色模式',exact:true}).click()
 stage='wheel';const before=Number(await page.locator('.docx-native').getAttribute('data-docx-zoom'));await body().dispatchEvent('wheel',{ctrlKey:true,deltaY:-120,deltaMode:0,bubbles:true,cancelable:true});assert.equal(Number(await page.locator('.docx-native').getAttribute('data-docx-zoom')),before+10)
 stage='read';await page.getByRole('button',{name:'阅读视图',exact:true}).click();assert.equal(await body().getAttribute('contenteditable'),'false');assert.equal(await page.locator('.docx-native').getAttribute('data-docx-zoom'),'100');await body().click();await page.keyboard.type('BLOCKED');assert.equal(await body().textContent(),originalText);await page.keyboard.press('Escape');assert.equal(await body().getAttribute('contenteditable'),'true');assert.equal(Number(await page.locator('.docx-native').getAttribute('data-docx-zoom')),before+10)
 stage='preferences';await tab('文件').click();await page.locator('[data-action=preferences-general]').click();let dialog=page.getByRole('dialog');await dialog.getByRole('combobox').selectOption('mm');assert.equal(await page.evaluate(()=>localStorage.getItem('aidocs.measurementUnit')),'mm');await dialog.getByRole('button',{name:'关闭',exact:true}).click();await page.locator('[data-action=preferences-autocorrect]').click();dialog=page.getByRole('dialog');const firstRule=dialog.getByRole('checkbox').first();const checked=await firstRule.isChecked();await firstRule.locator('..').click();assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('aidocs.autocorrect')).smartQuotes),!checked);await dialog.getByRole('button',{name:'关闭',exact:true}).click()
 stage='mail-source';await tab('邮件').click();await page.locator('[data-action=mail-merge]').first().click();dialog=page.getByRole('dialog');const chooseSource=page.waitForEvent('filechooser');await dialog.getByRole('button',{name:'选择收件人 CSV',exact:true}).click();await(await chooseSource).setFiles(join(directory,'recipients.csv'));await page.locator('.mailmerge-preview').getByText('Dear Ada',{exact:false}).waitFor()
 for(const [mode,name,filename] of [['perRecord','每条记录一个文件','per-record.zip'],['labels','标签','labels.docx'],['envelopes','信封','envelopes.zip']]){
  stage='export-'+mode;await dialog.getByRole('radio',{name,exact:true}).check();const responseWait=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/mail-merge/export'));const downloadWait=page.waitForEvent('download');await dialog.getByRole('button',{name:'导出合并文件',exact:true}).click();const response=await responseWait;assert.equal(response.status(),200,await response.text().catch(()=>''));const bytes=await response.body(),headers=response.headers();assert.equal(sha(bytes),headers['x-native-export-sha256']);assert.equal(headers['x-native-source-sha256'],sha(await readFile(fixture)));const download=await downloadWait;await download.saveAs(join(directory,filename));assert.equal(sha(await readFile(join(directory,filename))),sha(bytes));exports.push({mode,filename,sha256:sha(bytes),size:bytes.length,sourceSha256:headers['x-native-source-sha256']})
 }
 stage='readback';const independent=spawnSync(join(repo,'.venv/bin/python'),['-c',`import json,sys
from pathlib import Path
from zipfile import ZipFile
from io import BytesIO
from lxml import etree as E
root=Path(sys.argv[1]);ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'};out={}
for name in ('per-record.zip','envelopes.zip'):
 with ZipFile(root/name) as z:
  files=z.namelist();assert len(files)==2,files;texts=[]
  for f in files:
   with ZipFile(BytesIO(z.read(f))) as d:
    xml=E.fromstring(d.read('word/document.xml'));text=''.join(xml.itertext());assert 'secondplain' in text;assert 'MERGEFIELD' not in text;texts.append(text)
    if name=='envelopes.zip':assert xml.xpath('string(//w:pgSz/@w:w)',namespaces=ns)=='13680'
  assert any('Ada' in t for t in texts) and any('Grace' in t for t in texts);out[name]=files
with ZipFile(root/'labels.docx') as z:
 xml=E.fromstring(z.read('word/document.xml'));assert xml.xpath('//w:tbl',namespaces=ns);text=''.join(xml.itertext());assert 'Ada' in text and 'Grace' in text;out['labels.docx']='table and both recipients'
print(json.dumps(out))`,directory],{encoding:'utf8'});assert.equal(independent.status,0,independent.stderr);await writeFile(join(directory,'independent.json'),independent.stdout)
 const state=await(await fetch(origin+'/__smoke__/state')).json();assert.equal(state.revisions.length,0);assert.equal(state.requests.filter(r=>r.path.endsWith('/save')).length,0);await Promise.all(checks);assert.equal(errors.length,0,errors.join('\n'));await page.screenshot({path:join(directory,'final-desktop.png'),fullPage:true});await writeFile(join(directory,'result.json'),JSON.stringify({ok:true,exports,assets:Object.fromEntries(assets),manifestSha256:sha(await readFile(join(staticRoot,'.vite/manifest.json'))),errors,sourceSha256:sha(await readFile(fixture)),saveCount:0},null,2));console.log(JSON.stringify({ok:true,directory,exports:exports.length,assets:assets.size}))
}
}catch(error){await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,log},null,2));if(page){await page.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(join(directory,'failure.html'),await page.content()).catch(()=>{})}throw error}
finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),log)}
