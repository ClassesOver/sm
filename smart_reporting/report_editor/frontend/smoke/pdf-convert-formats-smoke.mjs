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
const directory = process.env.PDF_CONVERT_FORMATS_SMOKE_DIRECTORY ?? '/tmp/pdf-convert-formats-browser-20261111'
const port = Number(process.env.PDF_CONVERT_FORMATS_SMOKE_PORT ?? 4313), origin = `http://127.0.0.1:${port}`
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
await mkdir(directory, { recursive: true })
const manifest = await readFile(join(frontend, '../static/.vite/manifest.json'))
await writeFile(join(directory, 'build-manifest.json'), manifest)
const server = spawn(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/pdf-convert-formats-server.py'), '--directory', directory, '--port', String(port)], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, stdio: 'pipe' })
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
  stage='open-real-grant';await page.goto(origin+info.openPath);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
  await page.locator('[data-pdf-ribbon-tab="home"]').click()
  for(const format of ['docx','xlsx']){
    stage='convert-'+format;await command('home.convert.'+(format==='docx'?'toWord':'toExcel')).click()
    const dialog=page.getByRole('dialog',{name:'转换 PDF 为'+(format==='docx'?'Word':'Excel'),exact:true});await dialog.waitFor({state:'visible'})
    const pending=page.waitForResponse(response=>response.url().endsWith('/api/convert-office')&&response.request().method()==='POST');await dialog.locator('[data-pdf-convert-office-apply]').click()
    const response=await pending,result=await response.json();assert.equal(response.status(),200,JSON.stringify(result));assert.equal(result.source.sha256,info.sourceSha256);assert.equal(result.conversion.format,format);assert.equal(result.validation.ok,false);assert(result.conversion.pageResults.some(page=>page.status==='scanned'));assert(result.conversion.pageResults.every(page=>page.status!=='ocr'))
    assert.equal(response.request().postDataJSON().format,format);assert.equal(response.request().postDataJSON().expectedSha256,info.sourceSha256)
    const identity=result.artifacts[format==='docx'?'word':'xlsx'];assert(identity?.downloadUrl);const download=await page.request.get(identity.downloadUrl);assert.equal(download.status(),200);const bytes=await download.body();assert.equal(sha(bytes),identity.sha256);assert.equal(bytes.length,identity.size);await writeFile(join(directory,'converted.'+format),bytes)
    await dialog.getByRole('link',{name:'下载转换后的 '+format.toUpperCase(),exact:true}).waitFor({state:'visible'});await dialog.screenshot({path:join(directory,'converted-'+format+'.png')});await dialog.getByRole('button',{name:'关闭',exact:true}).click();results[format]=result
  }
  for(const format of ['markdown','html']){
    stage='export-'+format;await command('home.convert.'+(format==='html'?'toHtml':'toMarkdown')).click()
    const label=format==='html'?'HTML':'Markdown',dialog=page.getByRole('dialog',{name:'导出 '+label,exact:true});await dialog.waitFor({state:'visible'})
    const pending=page.waitForResponse(response=>response.url().endsWith('/api/convert-office')&&response.request().method()==='POST');await dialog.locator('[data-pdf-export-text-apply]').click()
    const response=await pending,result=await response.json();assert.equal(response.status(),200,JSON.stringify(result));assert.equal(response.request().postDataJSON().format,'docx');assert.equal(result.source.sha256,info.sourceSha256)
    const link=dialog.getByRole('link',{name:'下载 '+label,exact:true});await link.waitFor({state:'visible',timeout:90000});assert.match(await link.getAttribute('href'),/^blob:/)
    const downloading=page.waitForEvent('download');await link.click();const target=join(directory,format==='html'?'exported.html':'exported.md');await(await downloading).saveAs(target);const text=await readFile(target,'utf8')
    for(const value of ['source page one','source page two','source page three'])assert(text.includes(value),value)
    assert(text.includes('data:image/png;base64,'),'scanned image must be self-contained');assert(!text.includes('__genoffice_media__'));assert(!text.includes('genoffice-docx-media://'));assert(!/src=["'](?:file:|blob:|https?:)/i.test(text));assert((await dialog.textContent()).includes('验收未通过'))
    await dialog.getByRole('link',{name:'下载已生成的 Word',exact:true}).waitFor({state:'visible'});await dialog.screenshot({path:join(directory,'exported-'+format+'.png')});results[format]={sourceSha256:result.source.sha256,size:Buffer.byteLength(text),sha256:sha(Buffer.from(text)),selfContained:true,manualReview:true};await dialog.getByRole('button',{name:'关闭',exact:true}).click()
  }
  stage='independent-office-read';const verification=spawnSync(join(repo,'.venv/bin/python'),['-c',String.raw`
import sys,json
from pathlib import Path
from docx import Document
from openpyxl import load_workbook
from zipfile import ZipFile
from PIL import Image
from io import BytesIO
import re,base64
p=Path(sys.argv[1]);doc=Document(p/"converted.docx");texts=[x.text for x in doc.paragraphs];book=load_workbook(p/"converted.xlsx");cells=[str(value) for sheet in book for row in sheet.values for value in row if value is not None]
for expected in ["source page one","source page two","source page three"]:
 assert any(expected in text for text in texts),texts
 assert any(expected in text for text in cells),cells
for format in ["docx","xlsx"]:
 with ZipFile(p/("converted."+format)) as archive:
  assert any("/media/" in path and not path.endswith("/") for path in archive.namelist())
for name in ["exported.html","exported.md"]:
 text=(p/name).read_text();images=re.findall(r"data:image/png;base64,([A-Za-z0-9+/=]+)",text);assert images,name
 for encoded in images:
  image=Image.open(BytesIO(base64.b64decode(encoded)));image.load();assert image.width>0 and image.height>0
print(json.dumps({"paragraphs":texts,"sheets":book.sheetnames,"cells":cells,"scanImagesDecoded":True}))
`,directory],{cwd:repo,encoding:'utf8'});assert.equal(verification.status,0,verification.stdout+verification.stderr);await writeFile(join(directory,'independent-office.json'),verification.stdout)
  await Promise.all(checks);assert(assets.size>0);assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[]);assert.deepEqual(httpErrors,[]);assert.deepEqual(await readFile(join(frontend,'../static/.vite/manifest.json')),manifest)
  const state=await(await fetch(origin+'/__smoke__/state',{signal:AbortSignal.timeout(5000)})).json();assert.equal(state.sourceSha256,info.sourceSha256);assert.equal(state.savedRevisions,0)
  const summary={ok:true,directory,features:['editable DOCX','editable XLSX','Markdown from actual Word renderer','standalone HTML from actual Word renderer'],scope:'frozen production assets/real grant-cookie-CSRF/packed engine/actual signed downloads/browser Blob; in-memory repositories',sourceUnchanged:true,manifestSha256:sha(manifest),browserVersion:browser.version(),results,assets:Object.fromEntries(assets),pageErrors,consoleErrors,httpErrors,requests:state.requests}
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
