// Frozen production assets, real grant/cookie/CSRF, PDF engine, publication and download.
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const directory = process.env.PDF_DELIVERY_BATCH_SMOKE_DIRECTORY ?? '/tmp/pdf-delivery-batch-browser-20261111-final01'
const port = Number(process.env.PDF_DELIVERY_BATCH_SMOKE_PORT ?? 4303), origin = `http://127.0.0.1:${port}`
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
await mkdir(directory, { recursive: true })
const manifest = await readFile(join(frontend, '../static/.vite/manifest.json'))
await writeFile(join(directory, 'build-manifest.json'), manifest)
const server = spawn(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/pdf-delivery-batch-server.py'), '--directory', directory, '--port', String(port)], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, stdio: 'pipe' })
let serverLog = '', browser, page, stage = 'server'
server.stdout.on('data', data => { serverLog += data; void writeFile(join(directory,'server-live.log'),serverLog) }); server.stderr.on('data', data => { serverLog += data; void writeFile(join(directory,'server-live.log'),serverLog) })
const pageErrors = [], consoleErrors = [], httpErrors = [], checks = [], assets = new Map()
try {
  for (let attempt = 0; ; attempt++) {
    assert.equal(server.exitCode, null, serverLog)
    try { if ((await fetch(`${origin}/__smoke__/state`,{signal:AbortSignal.timeout(1500)})).ok) break } catch {}
    assert(attempt < 240, serverLog); await delay(250)
  }
  const info = JSON.parse(await readFile(join(directory, 'server-info.json'), 'utf8'))
  browser = await chromium.launch({ headless: true })
  page = await browser.newPage({ viewport: { width: 1500, height: 1100 } })
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400) httpErrors.push({ path, status: response.status() })
    if (!path.startsWith('/reports/v1/editor/assets/') || !/\.m?js$/.test(path)) return
    checks.push((async () => {
      const bytes = await response.body(), disk = await readFile(join(frontend, '../static', path.slice('/reports/v1/editor/assets/'.length)))
      assert.equal(sha(bytes), sha(disk)); assets.set(path, sha(bytes))
    })())
  })
  const results={},command=id=>page.locator('[data-source-command-id="genoffice.pdf.'+id+'"]')
  async function tab(id){await page.locator('[data-pdf-ribbon-tab="'+id+'"]').click()}
  async function open(url){await page.goto(url);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})}
  const verifyScript=String.raw`
import sys,json,hashlib
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
from pypdf import PdfReader
root=Path(sys.argv[1]);mode=sys.argv[2]
if mode in ('png','jpeg'):
 from PIL import Image
 receipt=json.loads((root/('export-'+mode+'-receipt.json')).read_text());raw=(root/('export-'+mode+'.zip')).read_bytes()
 assert len(raw)==receipt['size'] and hashlib.sha256(raw).hexdigest()==receipt['sha256']
 with ZipFile(BytesIO(raw)) as archive:
  manifest=json.loads(archive.read('manifest.json'));assert manifest['sourceSha256']==receipt['sourceSha256'];assert manifest['format']==mode;assert manifest['pages']==[3,1] and manifest['dpi']==72
  assert len(manifest['images'])==2;assert archive.namelist()==[entry['name'] for entry in manifest['images']]+['manifest.json']
  for entry in manifest['images']:
   data=archive.read(entry['name']);assert len(data)==entry['size'];assert hashlib.sha256(data).hexdigest()==entry['sha256']
   image=Image.open(BytesIO(data));image.load();assert image.format==('PNG' if mode=='png' else 'JPEG');assert image.size==(300,400)==(entry['width'],entry['height']);assert min(low for low,high in image.convert('RGB').getextrema())<255
 result={'manifest':manifest,'decodedImages':True,'identityHeadersVerified':True}
elif mode=='protection':
 source=PdfReader(root/'source.pdf');output=PdfReader(root/'protected.pdf');assert output.is_encrypted;assert output.trailer['/Encrypt']['/R']==6;assert output.decrypt('Batch-Open-4303!')
 assert len(output.pages)==len(source.pages)==3;assert [p.extract_text() for p in output.pages]==[p.extract_text() for p in source.pages];assert not(int(output.trailer['/Encrypt']['/P'])&16)
 result={'aes256':True,'passwordDecryptVerified':True,'copyingDisabled':True,'bodyPreserved':True}
elif mode=='pptx':
 from pptx import Presentation
 presentation=Presentation(root/'converted.pptx');assert len(presentation.slides)==3
 texts=['\n'.join(shape.text for shape in slide.shapes if shape.has_text_frame) for slide in presentation.slides]
 for text,expected in zip(texts,['source page one','source page two','source page three']):assert expected in text
 assert sum(bool(shape.text.strip()) for slide in presentation.slides for shape in slide.shapes if shape.has_text_frame)>=3
 result={'slideTexts':texts,'editableTextVerified':True,'slides':3}
else:
 source=PdfReader(root/'source.pdf');output=PdfReader(root/('external-'+mode+'.pdf'));texts=[p.extract_text().strip() for p in output.pages]
 expected=['source page one','external page one','external page two','source page two','source page three'] if mode=='insert' else ['external page one','external page two','external page one','external page two','source page two','source page three']
 assert texts==expected;assert [p.extract_text().strip() for p in source.pages]==['source page one','source page two','source page three'];assert all(tuple(p.mediabox)==(0,0,300,400) for p in output.pages)
 result={'pageTexts':texts,'newRevisionVerified':True,'sourcePreserved':True}
print(json.dumps(result))
`
  async function verify(mode){const output=spawnSync(join(repo,'.venv/bin/python'),['-c',verifyScript,directory,mode],{cwd:repo,encoding:'utf8'});assert.equal(output.status,0,output.stdout+output.stderr);const value=JSON.parse(output.stdout);await writeFile(join(directory,'verify-'+mode+'.json'),JSON.stringify(value,null,2));return value}
  async function artifact(identity,filename){assert(identity?.downloadUrl);const response=await page.request.get(identity.downloadUrl);assert.equal(response.status(),200);const bytes=await response.body();assert.equal(sha(bytes),identity.sha256);assert.equal(bytes.length,identity.size);await writeFile(join(directory,filename),bytes)}
  async function jsonResponse(path,submit){const pending=page.waitForResponse(response=>response.url().endsWith('/api/'+path)&&response.request().method()==='POST');await submit();const response=await pending,result=await response.json();assert.equal(response.status(),200,JSON.stringify(result));return {response,result}}
  stage='open-real-grant';await open(origin+info.openPath)
  for(const format of ['png','jpeg']){
    stage='export-'+format;await tab('home');await command('home.convert.'+(format==='png'?'exportImagesPng':'exportImagesJpg')).click()
    const dialog=page.getByRole('dialog',{name:'导出 PDF 页面图片',exact:true});await dialog.waitFor({state:'visible'});assert.equal(await dialog.getByLabel('导出图片格式',{exact:true}).inputValue(),format)
    await dialog.getByLabel('导出图片页码',{exact:true}).fill('3,1');await dialog.getByLabel('导出图片 DPI',{exact:true}).fill('72')
    const pending=page.waitForResponse(response=>response.url().endsWith('/api/export-images')&&response.request().method()==='POST');await dialog.locator('[data-pdf-image-export-apply]').click();const response=await pending;assert.equal(response.status(),200)
    const bytes=await response.body(),headers=response.headers();assert.equal(headers['x-native-source-sha256'],info.sourceSha256);assert.equal(headers['x-native-export-sha256'],sha(bytes));assert.equal(Number(headers['x-native-export-size']),bytes.length);assert.deepEqual(response.request().postDataJSON(),{expectedSha256:info.sourceSha256,pages:[3,1],format,dpi:72})
    const link=dialog.getByRole('link',{name:'下载图片 ZIP',exact:true});await link.waitFor({state:'visible'});const downloading=page.waitForEvent('download');await link.click();await(await downloading).saveAs(join(directory,'export-'+format+'.zip'));assert.equal(sha(await readFile(join(directory,'export-'+format+'.zip'))),sha(bytes))
    await writeFile(join(directory,'export-'+format+'-receipt.json'),JSON.stringify({sourceSha256:info.sourceSha256,sha256:sha(bytes),size:bytes.length,format}));results[format]=await verify(format);await dialog.screenshot({path:join(directory,'export-'+format+'.png')});await dialog.getByRole('button',{name:'关闭',exact:true}).click()
  }
  stage='protect';await tab('annotate');await command('annotate.protection.protect').click();const protection=page.getByRole('dialog',{name:'保护 PDF',exact:true});await protection.waitFor({state:'visible'})
  const password='Batch-Open-4303!',ownerPassword='Batch-Owner-4303!';await protection.getByLabel('打开密码',{exact:true}).fill(password);await protection.getByLabel('确认打开密码',{exact:true}).fill(password);await protection.getByLabel('所有者密码（可选）',{exact:true}).fill(ownerPassword);await protection.locator('[data-permission="copying"]').uncheck()
  const {result:protectedResult}=await jsonResponse('protect-pdf',()=>protection.locator('[data-pdf-protection-apply]').click());assert.equal(protectedResult.revisionRegistered,false);assert.equal(protectedResult.validation.ok,false)
  const protectedLink=protection.getByRole('link',{name:'下载保护 PDF',exact:true});await protectedLink.waitFor({state:'visible'});assert.equal(await protectedLink.getAttribute('href'),protectedResult.artifacts.pdf.downloadUrl);await artifact(protectedResult.artifacts.pdf,'protected.pdf')
  for(const label of ['打开密码','确认打开密码','所有者密码（可选）'])assert.equal(await protection.getByLabel(label,{exact:true}).inputValue(),'')
  const stored=await page.evaluate(()=>JSON.stringify(Object.fromEntries(Object.entries(localStorage))));assert(!stored.includes(password));assert(!stored.includes(ownerPassword));assert(!JSON.stringify(protectedResult).includes(password));results.protection=await verify('protection');results.protectionResponse=protectedResult;await protection.screenshot({path:join(directory,'protected.png')});await protection.getByRole('button',{name:'关闭',exact:true}).click()
  stage='convert-pptx';await tab('home');await command('home.convert.toPowerPoint').click();const conversion=page.getByRole('dialog',{name:'转换 PDF 为演示文稿',exact:true});await conversion.waitFor({state:'visible'})
  const {result:converted}=await jsonResponse('convert-office',()=>conversion.locator('[data-pdf-convert-office-apply]').click());assert.equal(converted.source.sha256,info.sourceSha256);assert.equal(converted.source.documentId,info.context.documentId);assert.equal(converted.conversion.format,'pptx');assert.equal(converted.conversion.scannedDocument,false);assert.equal(converted.revisionRegistered,true);assert.equal(converted.validation.ok,false)
  const convertedLink=conversion.getByRole('link',{name:'下载转换后的 PPTX',exact:true});await convertedLink.waitFor({state:'visible'});assert.equal(await convertedLink.getAttribute('href'),converted.artifacts.pptx.downloadUrl);await artifact(converted.artifacts.pptx,'converted.pptx');results.conversion=await verify('pptx');results.conversionResponse=converted;await conversion.screenshot({path:join(directory,'converted.png')});await conversion.getByRole('button',{name:'关闭',exact:true}).click()
  let currentSha=info.sourceSha256,currentRevision=4
  for(const action of ['insert','replace']){
    stage='external-'+action;await tab('page');await command('page.'+(action==='insert'?'insertPdf':'replace')).click();const dialog=page.getByRole('dialog',{name:'外部 PDF 页面',exact:true});await dialog.waitFor({state:'visible'});await dialog.getByLabel('外部 PDF 文件',{exact:true}).setInputFiles(info.externalPath)
    if(action==='insert')await dialog.getByLabel('插入父 PDF 页后',{exact:true}).fill('1');else await dialog.getByLabel('替换父 PDF 页码',{exact:true}).fill('1')
    const {response,result}=await jsonResponse('external-pages',()=>dialog.locator('[data-pdf-external-pages-apply]').click());assert.equal(result.revisionRegistered,true);assert.equal(result.parentRevision,currentRevision);assert.equal(result.revision,currentRevision+1);assert.equal(response.request().postDataJSON().expectedSha256,currentSha)
    const link=dialog.getByRole('link',{name:'下载新修订 PDF',exact:true});await link.waitFor({state:'visible'});assert.equal(await link.getAttribute('href'),result.artifacts.pdf.downloadUrl);await artifact(result.artifacts.pdf,'external-'+action+'.pdf');results[action]=await verify(action);results[action+'Response']=result;currentSha=result.artifacts.pdf.sha256;currentRevision=result.revision
    await open(result.editor.openUrl);const reopened=await page.evaluate(async()=>(await fetch(location.pathname+'/api/context')).json());assert.equal(reopened.context.revision,currentRevision);assert.equal(reopened.context.sourceFile.sha256,currentSha);await page.screenshot({path:join(directory,'external-'+action+'-reopened.png'),fullPage:true})
  }
  await Promise.all(checks);assert(assets.size>0);assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[]);assert.deepEqual(await readFile(join(frontend,'../static/.vite/manifest.json')),manifest)
  const state=await(await fetch(origin+'/__smoke__/state',{signal:AbortSignal.timeout(5000)})).json();assert.equal(state.sourceSha256,info.sourceSha256);assert.equal(state.savedRevisions,2)
  const summary={ok:true,directory,features:['PNG/JPEG ZIP','AES-256 download','editable PPTX derived download','external PDF insert/replace revisions'],scope:'real browser/frozen assets/real HTTP grant-cookie-CSRF/packed engine/publication/download; in-memory scope repositories; no HTTP substitutes',browserVersion:browser.version(),manifestSha256:sha(manifest),sourceSha256:info.sourceSha256,sourceUnchanged:true,results,assets:Object.fromEntries(assets),pageErrors,consoleErrors,httpErrors,requests:state.requests}
  await writeFile(join(directory,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify({ok:true,directory}))
} catch (error) {
  await page?.screenshot({ path: join(directory, 'failure.png'), fullPage: true }).catch(() => {})
  if (page) await page.content().then(html => writeFile(join(directory, 'failure.html'), html)).catch(() => {})
  await writeFile(join(directory, 'failure.json'), JSON.stringify({ stage, error: String(error), pageErrors, consoleErrors, httpErrors }, null, 2))
  throw error
} finally {
  await browser?.close(); server.kill()
  await writeFile(join(directory, 'server.log'), serverLog)
  if (server.exitCode === null) await Promise.race([new Promise(resolve => server.once('exit', resolve)), delay(5000)])
  if (server.exitCode === null) server.kill('SIGKILL')
}
