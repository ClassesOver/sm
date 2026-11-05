import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

// 授权和保存故障使用浏览器路由；解析、写回和独立回读均处理真实 DOCX。
const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.DOCX_RECOVERY_SMOKE_PORT ?? 4197), base = `http://127.0.0.1:${port}`
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
const media = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const python = payload => {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import base64,json,sys
from io import BytesIO
from docx import Document
from docx.oxml.ns import qn
from smart_reporting.reporting.delivery.docx_native import inspect_docx,patch_docx
p=json.load(sys.stdin)
if p['mode']=='create':
    d=Document(); d.add_paragraph('页面设置恢复正文'); b=BytesIO(); d.save(b); content=b.getvalue()
elif p['mode']=='patch': content=patch_docx(base64.b64decode(p['bytes']),p['operations'])
else: content=base64.b64decode(p['bytes'])
d=Document(BytesIO(content)); s=d.sections[-1]
print(json.dumps({'bytes':base64.b64encode(content).decode(),'model':inspect_docx(content),
 'paragraphs':[a.text for a in d.paragraphs], 'settings':{'pageWidth':s.page_width.twips,'pageHeight':s.page_height.twips,
 'marginLeft':s.left_margin.twips,'marginRight':s.right_margin.twips,'marginTop':s.top_margin.twips,'marginBottom':s.bottom_margin.twips,
 'headerDist':s.header_distance.twips,'footerDist':s.footer_distance.twips,
 'columns':int(s._sectPr.find(qn('w:cols')).get(qn('w:num'),'1'))}},ensure_ascii=False))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(payload), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw Error(result.stderr)
  return JSON.parse(result.stdout)
}
const initial = python({ mode: 'create' }), source = Buffer.from(initial.bytes, 'base64'), sourceSha = sha(source)
let saved, savedModel, receipt, browser
const attempts = [], errors = [], failures = []
const server = spawn('./node_modules/.bin/vite', ['--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
try {
  let ready = false
  for (let n = 0; n < 120; n++) {
    try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) { ready = true; break } } catch {}
    await delay(250)
  }
  assert.ok(ready)
  browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('response', response => { if (response.status() >= 400) failures.push({ status: response.status(), url: response.url() }) })
  await page.route('**/reports/v1/native/fixture-docx-recovery/*/api/context', route => {
    const revision = route.request().url().includes('/1/api/') ? 1 : 2, bytes = revision === 1 ? source : saved
    return route.fulfill({ json: { context: { documentId: 'fixture-docx-recovery', revision, parentRevision: revision === 1 ? null : 1,
      format: 'docx', scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' },
      sourceFile: { path: `revision-${revision}.docx`, size: bytes.length, sha256: sha(bytes), mediaType: media }, origin: 'report' },
      editingEnabled: true, csrfToken: 'fixture-csrf', capabilities: { docx_editor: true } } })
  })
  await page.route('**/reports/v1/native/fixture-docx-recovery/*/api/file', route => route.fulfill({
    body: route.request().url().includes('/1/api/') ? source : saved, contentType: media,
  }))
  await page.route('**/reports/v1/native/fixture-docx-recovery/*/api/preview', route => {
    const model = route.request().url().includes('/1/api/') ? initial.model : savedModel
    assert.deepEqual(route.request().postDataJSON(), { expectedSha256: model.sourceSha256, operations: [] })
    return route.fulfill({ json: { sourceSha256: model.sourceSha256, draftSha256: model.sourceSha256, model } })
  })
  await page.route('**/reports/v1/native/fixture-docx-recovery/1/api/save', async route => {
    assert.equal(route.request().headers()['x-csrf-token'], 'fixture-csrf')
    const payload = route.request().postDataJSON(); attempts.push(payload)
    if (attempts.length <= 2) return route.fulfill({ status: 503, json: { detail: { message: '故障注入：保存暂不可用' } } })
    const result = python({ mode: 'patch', bytes: initial.bytes, operations: payload.operations })
    saved = Buffer.from(result.bytes, 'base64'); savedModel = result.model
    receipt = { documentId: 'fixture-docx-recovery', revision: 2, parentRevision: 1, revisionRegistered: true,
      artifacts: { word: { downloadUrl: '/fixture-docx-recovery.docx', size: saved.length, sha256: sha(saved) } },
      editor: { openUrl: '/reports/v1/native/fixture-docx-recovery/2' }, validation: { ok: false, issues: [{ code: 'fixture_review', message: '验收待复核，保留下载' }] } }
    return route.fulfill({ json: receipt })
  })
  await page.route('**/fixture-docx-recovery.docx', route => route.fulfill({ body: saved, contentType: media }))
  await page.route(/\/reports\/v1\/native\/fixture-docx-recovery\/[12]$/, async route => route.fulfill({
    response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }),
  }))
  const open = async revision => {
    await page.goto(`${base}/reports/v1/native/fixture-docx-recovery/${revision}`)
    await page.locator('.docx-source-home').waitFor({ timeout: 60000 })
    await page.locator('[data-tab-id="layout"]').click()
  }
  const select = action => page.locator(`[data-source-action="${action}"]`)
  const save = async () => { await page.locator('[data-action="save"]').click() }
  const failed = () => page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent.includes('故障注入'))
  await open(1)
  await select('layout-orientation').selectOption('landscape')
  await select('layout-paper-size').selectOption('a4')
  await select('layout-margins').selectOption('720')
  await select('layout-columns').selectOption('2')
  await select('layout-header-distance').fill('900')
  await select('layout-footer-distance').fill('1000')
  await save(); await failed()
  await open(1)
  assert.equal(await select('layout-orientation').inputValue(), 'landscape')
  assert.equal(await select('layout-paper-size').inputValue(), 'a4')
  assert.equal(await select('layout-margins').inputValue(), '720')
  assert.equal(await select('layout-columns').inputValue(), '2')
  assert.equal(await select('layout-header-distance').inputValue(), '900')
  assert.equal(await select('layout-footer-distance').inputValue(), '1000')
  await save(); await failed()
  assert.deepEqual(attempts[1], attempts[0])
  await page.getByRole('textbox', { name: 'Word 文档编辑区' }).evaluate(node => node.editor.commands.insertContentAt(2, '刷新后正文修改'))
  await save()
  await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 30000 })
  assert.notEqual(attempts[2].requestId, attempts[0].requestId)
  assert.deepEqual(attempts[2].operations.find(op => op.kind === 'setSectionLayout'), attempts[0].operations.find(op => op.kind === 'setSectionLayout'))
  assert.ok(await select('layout-orientation').isDisabled())
  assert.ok(await page.locator('.native-delivery').getByText('验收待复核，保留下载').isVisible())
  const downloaded = Buffer.from(await page.evaluate(async () => Array.from(new Uint8Array(await (await fetch('/fixture-docx-recovery.docx')).arrayBuffer()))))
  assert.equal(sha(downloaded), receipt.artifacts.word.sha256)
  assert.equal(downloaded.length, receipt.artifacts.word.size)
  const readback = python({ mode: 'inspect', bytes: downloaded.toString('base64') })
  assert.deepEqual(readback.settings, { pageWidth: 16838, pageHeight: 11906, marginLeft: 720, marginRight: 720, marginTop: 720, marginBottom: 720, columns: 2, headerDist: 900, footerDist: 1000 })
  assert.ok(readback.paragraphs[0].includes('刷新后正文修改'))
  assert.equal(sha(source), sourceSha)
  await open(2)
  assert.equal(await select('layout-orientation').inputValue(), 'landscape')
  assert.equal(await select('layout-columns').inputValue(), '2')
  await page.screenshot({ path: '/tmp/docx-section-recovery-revision-2.png', fullPage: true })
  assert.equal(failures.length, 2)
  assert.ok(failures.every(item => item.status === 503 && item.url.endsWith('/api/save')))
  assert.equal(errors.length, 2)
  assert.ok(errors.every(item => item.includes('503')))
  console.log(JSON.stringify({ ok: true, revision: 2, attempts: attempts.length, sha256: sha(downloaded), settings: readback.settings }))
} finally { await browser?.close(); server.kill('SIGTERM') }
