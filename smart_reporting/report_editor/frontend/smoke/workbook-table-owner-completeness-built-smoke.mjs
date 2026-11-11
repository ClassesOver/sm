import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = process.cwd(), repo = resolve('../../..'), base = 'http://127.0.0.1:4239'
const evidence = process.env.TABLE_OWNER_EVIDENCE_DIR || '/tmp/workbook-table-owner-completeness-built'
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
await mkdir(evidence, { recursive: true })
const manifestSha256 = sha(await readFile('../static/.vite/manifest.json'))
if (process.env.WORKBOOK_EXPECTED_MANIFEST_SHA256) assert.equal(manifestSha256, process.env.WORKBOOK_EXPECTED_MANIFEST_SHA256)
function fixture(missing) {
 const result = spawnSync(join(repo, '.venv/bin/python'), ['-c', '\nimport sys,base64,re\nfrom io import BytesIO\nfrom zipfile import ZipFile,ZIP_DEFLATED\nfrom openpyxl import Workbook\nfrom openpyxl.worksheet.table import Table\nb=Workbook();s=b.active;s.title="Source";other=b.create_sheet("Other")\ns.append(["Amount",None,"Count"]);s.append([10,None,2]);s.append([20,None,4])\ns.add_table(Table(displayName="First",ref="A1:A3"));s.add_table(Table(displayName="Second",ref="C1:C3"))\nother["A1"]="=SUM(Second[Count])";other["B1"]=17\nraw=BytesIO();b.save(raw);out=BytesIO()\nwith ZipFile(BytesIO(raw.getvalue())) as source, ZipFile(out,"w",ZIP_DEFLATED) as target:\n for item in source.infolist():\n  data=source.read(item.filename)\n  if item.filename=="xl/worksheets/sheet1.xml":\n   if sys.argv[1]=="all":data=re.sub(rb"<tableParts\\b[\\s\\S]*?</tableParts>",b"",data)\n   else:data=data.replace(b\'count="2"\',b\'count="1"\').replace(b\'<tablePart xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rId2"/>\',b"")\n  target.writestr(item.filename,data)\nprint(base64.b64encode(out.getvalue()).decode())\n', missing], { cwd: repo, encoding: 'utf8' })
 assert.equal(result.status, 0, result.stderr)
 return Buffer.from(result.stdout.trim(), 'base64')
}
const server = spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', '4239', '--strictPort'], { cwd: frontend, stdio: 'ignore' })
let browser, page
const receipt = { ok: false, preview: true, manifestSha256, cases: [] }
try {
 for (let i = 0; i < 120; i++) {
  try { if ((await fetch(base + '/reports/v1/editor/assets/native.html')).ok) break } catch {}
  await delay(250)
 }
 browser = await chromium.launch({ headless: true })
 receipt.browserVersion = browser.version()
 for (const missing of ['all', 'second']) {
  const bytes = fixture(missing), id = 'owner-' + missing, media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
  const context = { documentId: id, format: 'xlsx', revision: 1, parentRevision: null, scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' }, sourceFile: { path: id + '.xlsx', size: bytes.length, sha256: sha(bytes), mediaType: media }, origin: 'upload' }
  await writeFile(join(evidence, id + '.xlsx'), bytes)
  page = await browser.newPage({ viewport: { width: 1500, height: 1100 } })
  const pageErrors = [], mutationRequests = [], runtimeJavaScript = new Map(), tasks = []
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('request', request => { if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) mutationRequests.push({ method: request.method(), url: request.url() }) })
  page.on('response', response => {
   const path = new URL(response.url()).pathname
   if (path.startsWith('/reports/v1/editor/assets/') && path.endsWith('.js')) tasks.push((async () => {
    assert.equal(response.status(), 200)
    const body = await response.body(), actualSha256 = sha(body)
    assert.equal(actualSha256, sha(await readFile('../static/' + path.slice('/reports/v1/editor/assets/'.length))))
    runtimeJavaScript.set(path, { path, size: body.length, sha256: actualSha256 })
   })())
  })
  await page.route('**/reports/v1/native/' + id + '/1/api/context', route => route.fulfill({ json: { context, csrfToken: 'csrf', capabilities: { xlsx_editor: true }, editingEnabled: true } }))
  await page.route('**/reports/v1/native/' + id + '/1/api/file', route => route.fulfill({ body: bytes, contentType: media }))
  await page.addInitScript(id => history.replaceState(null, '', '/reports/v1/native/' + id + '/1'), id)
  await page.goto(base + '/reports/v1/editor/assets/native.html')
  await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 60000 })
  const tab = name => page.locator('[data-u-comp="slide-tab-item"]').filter({ hasText: name })
  await tab('Source').waitFor()
  await tab('Other').waitFor()
  const beforeDraft = await page.evaluate(() => Object.fromEntries(Object.entries(localStorage)))
  const beforeSaveLabel = await page.locator('.save-state-label').textContent()
  await tab('Source').click({ button: 'right' })
  await page.getByText('删除', { exact: true }).last().click()
  await page.getByRole('button', { name: '确定', exact: true }).click()
  const reason = '表格来源无法完整核对：表格所属关系未完整登记在工作表中'
  await page.getByText(reason, { exact: false }).waitFor()
  await tab('Source').waitFor()
  await tab('Other').waitFor()
  assert.deepEqual(await page.evaluate(() => Object.fromEntries(Object.entries(localStorage))), beforeDraft)
  assert.equal(await page.locator('.save-state-label').textContent(), beforeSaveLabel)
  await Promise.all(tasks)
  assert([...runtimeJavaScript.keys()].some(path => /workbook-main-/.test(path)))
  assert.deepEqual(mutationRequests, [])
  assert.deepEqual(pageErrors, [])
  await page.screenshot({ path: join(evidence, id + '-refused.png'), fullPage: true })
  receipt.cases.push({ missing, sourceSha256: sha(bytes), reason, sourceAndOtherRemain: true, draftUnchanged: true, saveLabelUnchanged: true, mutationRequests, pageErrors, runtimeJavaScript: [...runtimeJavaScript.values()] })
  await page.close()
  page = undefined
 }
 receipt.ok = true
 await writeFile(join(evidence, 'evidence.json'), JSON.stringify(receipt, null, 2) + '\n')
 console.log(JSON.stringify(receipt))
} catch (error) {
 receipt.error = String(error)
 await writeFile(join(evidence, 'failure.json'), JSON.stringify(receipt, null, 2) + '\n')
 if (page) await page.screenshot({ path: join(evidence, 'failure.png'), fullPage: true }).catch(() => {})
 throw error
} finally {
 await browser?.close()
 server.kill()
}
