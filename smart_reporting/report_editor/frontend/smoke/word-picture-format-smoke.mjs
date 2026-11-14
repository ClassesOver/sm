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
const directory=process.env.WORD_PICTURE_FORMAT_EVIDENCE??'/tmp/word-picture-format-20261114',staticRoot=process.env.WORD_PICTURE_FORMAT_BUILD??'/tmp/word-genoffice-integrated-build'
const port=Number(process.env.WORD_PICTURE_FORMAT_PORT??4308),origin='http://127.0.0.1:'+port,sha=bytes=>createHash('sha256').update(bytes).digest('hex'),python=join(repo,'.venv/bin/python')
await mkdir(directory,{recursive:true})
const fixture=spawnSync(python,['-c',`from docx import Document
from docx.shared import Inches
from PIL import Image,ImageDraw
from pathlib import Path
from zipfile import ZipFile
from lxml import etree as E
import sys,json
root=Path(sys.argv[1]); im=Image.new('RGB',(240,160),'#f0d080');d=ImageDraw.Draw(im);d.rectangle((12,12,75,55),fill='#2040d0');d.polygon([(120,25),(220,80),(130,145)],fill='#d03030');im.save(root/'picture.png')
doc=Document();doc.add_paragraph('PICTURE FORMAT KEEP BEFORE');doc.add_picture(str(root/'picture.png'),width=Inches(2.5));doc.add_paragraph('PICTURE FORMAT KEEP AFTER');doc.sections[0].header.paragraphs[0].text='HEADER KEEP';doc.sections[0].footer.paragraphs[0].text='FOOTER KEEP';doc.save(root/'picture-source.docx')
with ZipFile(root/'picture-source.docx') as z:
 xml=E.fromstring(z.read('word/document.xml')); ns={'pic':'http://schemas.openxmlformats.org/drawingml/2006/picture','a':'http://schemas.openxmlformats.org/drawingml/2006/main'};assert len(xml.xpath('//pic:spPr/a:xfrm',namespaces=ns))==1
print(json.dumps({'fixture':'python-docx add_picture','sourceTransform':'genuine python-docx pic:spPr/a:xfrm, no XML injection','naturalPixels':[240,160]}))`,directory],{encoding:'utf8'});assert.equal(fixture.status,0,fixture.stderr);await writeFile(join(directory,'fixture.json'),fixture.stdout)
const server=spawn(python,[join(frontend,'smoke/word-review-presets-server.py'),'--directory',directory,'--static',staticRoot,'--port',String(port)],{cwd:repo,env:{...process.env,PYTHONPATH:repo,WORD_PRESETS_REOPEN_FILE:join(directory,'picture-source.docx')},stdio:'pipe'})
let log='',browser,page,stage='server';server.stdout.on('data',data=>{log+=data});server.stderr.on('data',data=>{log+=data})
const errors=[],checks=[],assets=new Map()
try{
 for(let i=0;;i++){assert.equal(server.exitCode,null,log);try{if((await fetch(origin+'/__smoke__/state')).ok)break}catch{}assert(i<180,log);await delay(250)}
 const info=JSON.parse(await readFile(join(directory,'server-info.json'),'utf8'))
 browser=await chromium.launch({headless:true});const fontProbe=await probeCanvasTextRendering(browser);await writeFile(join(directory,'font-preflight.json'),JSON.stringify(fontProbe,null,2));assert(fontProbe.ok)
 page=await browser.newPage({viewport:{width:1450,height:1000}});page.on('pageerror',error=>errors.push(error.message))
 page.on('response',response=>{const path=new URL(response.url()).pathname;if(!path.startsWith('/reports/v1/editor/assets/')||!/\.(js|css)$/.test(path))return;const check=(async()=>{if(response.status()===304){assert(assets.has(path));return}assert.equal(response.status(),200);const bytes=await response.body(),disk=await readFile(join(staticRoot,path.slice('/reports/v1/editor/assets/'.length)));assert.equal(sha(bytes),sha(disk));assets.set(path,sha(bytes))})();check.catch(()=>{});checks.push(check)})
 const body=()=>page.getByRole('textbox',{name:'Word 文档编辑区',exact:true}),picture=()=>body().locator('[data-doc-protected=image] img').first()
 stage='open';await page.goto(origin+info.openPath);await body().waitFor({timeout:60000});await body().getByText('PICTURE FORMAT KEEP BEFORE',{exact:true}).waitFor();await picture().click();await page.getByRole('tab',{name:'图片格式',exact:true}).click()
 stage='rotate-flip';const rotate=page.locator('[data-action=picture-format-rotateRight]');assert(await rotate.isEnabled());await rotate.click();const flip=page.locator('[data-action=picture-format-flipH]');assert(await flip.isEnabled());await flip.click()
 const preview=await picture().evaluate(img=>({style:img.getAttribute('style'),src:img.getAttribute('src')}));assert.match(preview.style,/rotate\(90deg\)/);assert.match(preview.style,/scaleX\(-1\)/);await writeFile(join(directory,'preview.json'),JSON.stringify(preview,null,2));await page.screenshot({path:join(directory,'rotated-preview.png'),fullPage:true})
 stage='save';const response=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/save'));await page.locator('[data-action=save]').click();const saveResponse=await response,receipt=await saveResponse.json();await writeFile(join(directory,'rotated-flipped-saved.json'),JSON.stringify(receipt,null,2));assert.equal(saveResponse.status(),200,JSON.stringify(receipt));assert.equal(receipt.revisionRegistered,true,JSON.stringify(receipt));assert.equal(receipt.revision,2)
 const downloaded=await page.request.get(receipt.artifacts.word.downloadUrl);assert.equal(downloaded.status(),200);const bytes=await downloaded.body();assert.equal(sha(bytes),receipt.artifacts.word.sha256);await writeFile(join(directory,'rotated-flipped-r2.docx'),bytes)
 stage='reopen';await page.goto(receipt.editor.openUrl);await body().waitFor({timeout:60000});await picture().waitFor();const reopened=await picture().evaluate(img=>({style:img.getAttribute('style'),src:img.getAttribute('src')}));assert.match(reopened.style,/rotate\(90deg\)/);assert.match(reopened.style,/scaleX\(-1\)/);assert.equal(reopened.src,preview.src);await page.screenshot({path:join(directory,'reopened.png'),fullPage:true})
 stage='independent-ooxml';const independent=spawnSync(python,['-c',`import json,sys,hashlib
from zipfile import ZipFile
from docx import Document
from lxml import etree as E
root=sys.argv[1];ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main','pic':'http://schemas.openxmlformats.org/drawingml/2006/picture'}
with ZipFile(root+'/picture-source.docx') as before,ZipFile(root+'/rotated-flipped-r2.docx') as after:
 assert set(before.namelist())==set(after.namelist());changed=[n for n in before.namelist() if before.read(n)!=after.read(n)];assert changed==['word/document.xml'],changed
 x=E.fromstring(after.read('word/document.xml'));xf=x.xpath('//pic:spPr/a:xfrm',namespaces=ns)[0];assert xf.get('rot')=='5400000' and xf.get('flipH')=='1';assert len(x.xpath('//w:drawing',namespaces=ns))==1
 old=E.fromstring(before.read('word/document.xml'));oldp=old.xpath('//w:body/w:p',namespaces=ns);newp=x.xpath('//w:body/w:p',namespaces=ns)
 assert E.tostring(oldp[0])==E.tostring(newp[0]);assert E.tostring(oldp[2])==E.tostring(newp[2]);media={n:hashlib.sha256(after.read(n)).hexdigest() for n in after.namelist() if n.startswith('word/media/')}
 doc=Document(root+'/rotated-flipped-r2.docx');assert len(doc.inline_shapes)==1;assert doc.sections[0].header.paragraphs[0].text=='HEADER KEEP';assert doc.sections[0].footer.paragraphs[0].text=='FOOTER KEEP'
 print(json.dumps({'rotation':90,'flipH':True,'editableDrawing':True,'changedParts':changed,'media':media,'otherPartsByteIdentical':True,'neighborParagraphsUnchanged':True,'headerFooterKept':True}))`,directory],{encoding:'utf8'});assert.equal(independent.status,0,independent.stderr);await writeFile(join(directory,'independent.json'),independent.stdout)
 const state=await(await fetch(origin+'/__smoke__/state')).json(),saveRequest=state.requests.find(r=>r.method==='POST'&&r.path.endsWith('/save'));assert(saveRequest);assert(saveRequest.body.operations.some(op=>op.kind==='formatImage'&&op.rotDeg===90&&op.flipH===true));await writeFile(join(directory,'save-request.json'),JSON.stringify(saveRequest,null,2))
 await Promise.all(checks);assert.equal(errors.length,0,errors.join('\n'));const result={ok:true,revision:receipt.revision,sha256:sha(bytes),validation:receipt.validation,assets:Object.fromEntries(assets),errors,manifestSha256:sha(await readFile(join(staticRoot,'.vite/manifest.json'))),independent:JSON.parse(independent.stdout)};await writeFile(join(directory,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({ok:true,directory,revision:receipt.revision,assets:assets.size}))
}catch(error){await writeFile(join(directory,'failure.json'),JSON.stringify({stage,error:String(error),stack:error.stack,log},null,2));if(page)await page.screenshot({path:join(directory,'failure.png'),fullPage:true}).catch(()=>{});throw error}
finally{await browser?.close();server.kill();await writeFile(join(directory,'server.log'),log)}
