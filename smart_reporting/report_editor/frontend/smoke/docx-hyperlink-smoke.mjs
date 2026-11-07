import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import { verifyBrowserTextInput } from './browser-input-preflight.mjs'

// Authorization/revision storage are route substitutes; DOCX parsing/patching/readback are real.
const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.DOCX_LINK_SMOKE_PORT ?? 4196)
const baseUrl = `http://127.0.0.1:${port}`
const mediaType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const temporary = await mkdtemp(join(tmpdir(), 'docx-links-'))
const hash = bytes => createHash('sha256').update(bytes).digest('hex')
const targetText = '经营收入100万元'
const paragraphText = `前缀 ${targetText} 后缀😀同段链接`
const firstUrl = 'https://example.test/report?a=1&b=2'
const secondUrl = 'mailto:reports@example.test'
const python = payload => {
  const result = spawnSync(join(repo, '.venv/bin/python'), ['-c', `
import base64,json,sys
from io import BytesIO
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from smart_reporting.reporting.delivery.docx_native import inspect_docx,patch_docx
p=json.load(sys.stdin)
if p['mode']=='create':
 d=Document(); para=d.add_paragraph(); para.add_run('前缀 ')
 r=para.add_run('经营收入100万元'); r.bold=True; r.italic=True
 para.add_run(' 后缀😀')
 h=OxmlElement('w:hyperlink'); h.set(qn('r:id'),d.part.relate_to('https://example.test/same',RT.HYPERLINK,is_external=True));h.set(qn('w:tooltip'),'Same paragraph tooltip')
 r=OxmlElement('w:r');t=OxmlElement('w:t');t.text='同段链接';r.append(t);h.append(r);para._p.append(h)
 para=d.add_paragraph(); h=OxmlElement('w:hyperlink'); h.set(qn('r:id'),d.part.relate_to('https://example.test/keep',RT.HYPERLINK,is_external=True)); h.set(qn('w:tooltip'),'Untouched tooltip')
 r=OxmlElement('w:r');t=OxmlElement('w:t');t.text='保留链接';r.append(t);h.append(r);para._p.append(h);para.add_run(' 保留文字')
 s=BytesIO();d.save(s);print(base64.b64encode(s.getvalue()).decode())
elif p['mode']=='patch':
 print(base64.b64encode(patch_docx(base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 b=base64.b64decode(p['bytes']);d=Document(BytesIO(b)); paras=[]
 for para in d.paragraphs:
  links=[]; runs=[]
  for child in para._p:
   if child.tag==qn('w:hyperlink'):
    rel=d.part.rels[child.get(qn('r:id'))]
    links.append({'text':''.join(x.text or '' for x in child.iter(qn('w:t'))),'href':rel.target_ref,'external':rel.is_external,'tooltip':child.get(qn('w:tooltip')),'styleIds':[x.get(qn('w:val')) for x in child.iter(qn('w:rStyle'))]})
   for run in ([child] if child.tag==qn('w:r') else child.findall(qn('w:r')) if child.tag==qn('w:hyperlink') else []):
    runs.append({'text':''.join(x.text or '' for x in run.iter(qn('w:t'))),'bold':run.find('./'+qn('w:rPr')+'/'+qn('w:b')) is not None,'italic':run.find('./'+qn('w:rPr')+'/'+qn('w:i')) is not None})
  paras.append({'text':para.text,'links':links,'runs':runs})
 print(json.dumps({'model':inspect_docx(b),'paragraphs':paras},ensure_ascii=False))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(payload), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr || `Python exit ${result.status}`)
  return result.stdout.trim()
}
const inspect = bytes => JSON.parse(python({ mode: 'inspect', bytes: bytes.toString('base64') }))
let browser, server
try {
  const source = Buffer.from(python({ mode: 'create' }), 'base64')
  const sourceSha = hash(source)
  const revisions = new Map([[1, source]])
  const inspections = new Map([[1, inspect(source)]])
  const saves = []
  server = spawn('./node_modules/.bin/vite', ['--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
  let ready = false
  for (let attempt = 0; attempt < 120; attempt++) {
    try { if ((await fetch(`${baseUrl}/reports/v1/editor/assets/native.html`)).ok) { ready = true; break } } catch {}
    await delay(250)
  }
  assert.ok(ready, 'Vite unavailable')
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  const baseline = await verifyBrowserTextInput(browser)
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, acceptDownloads: true })
  const errors = [], failedResponses = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('response', response => { if (response.status() >= 400) failedResponses.push([response.status(), response.url()]) })
  const revisionOf = request => Number(new URL(request.url()).pathname.split('/')[5])
  await page.route('**/reports/v1/native/fixture-links/*/api/context', route => {
    const revision = revisionOf(route.request()), bytes = revisions.get(revision)
    return route.fulfill({ json: { context: {
      documentId: 'fixture-links', format: 'docx', revision, parentRevision: revision === 1 ? null : revision - 1,
      scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' },
      sourceFile: { path: `revision-${revision}.docx`, size: bytes.length, sha256: hash(bytes), mediaType }, origin: 'upload',
    }, csrfToken: 'fixture-csrf', capabilities: { docx_editor: true }, editingEnabled: true } })
  })
  await page.route('**/reports/v1/native/fixture-links/*/api/file', route => route.fulfill({ body: revisions.get(revisionOf(route.request())), contentType: mediaType }))
  await page.route('**/reports/v1/native/fixture-links/*/api/preview', route => {
    const revision = revisionOf(route.request()), payload = route.request().postDataJSON()
    assert.equal(payload.expectedSha256, hash(revisions.get(revision)))
    assert.deepEqual(payload.operations, [])
    const model = inspections.get(revision).model
    return route.fulfill({ json: { model, sourceSha256: model.sourceSha256, draftSha256: model.sourceSha256 } })
  })
  await page.route('**/reports/v1/native/fixture-links/*/api/save', async route => {
    const revision = revisionOf(route.request()), payload = route.request().postDataJSON()
    assert.equal(payload.expectedSha256, hash(revisions.get(revision)))
    const bytes = Buffer.from(python({ mode: 'patch', bytes: revisions.get(revision).toString('base64'), operations: payload.operations }), 'base64')
    revisions.set(revision + 1, bytes); inspections.set(revision + 1, inspect(bytes)); saves.push(payload)
    await route.fulfill({ json: { documentId: 'fixture-links', revision: revision + 1, parentRevision: revision, revisionRegistered: true,
      artifacts: { word: { downloadUrl: `/fixture-links-download-${revision + 1}.docx`, size: bytes.length, sha256: hash(bytes) } },
      editor: { openUrl: `/reports/v1/native/fixture-links/${revision + 1}` },
      validation: { ok: false, issues: [{ code: 'fixture_review', message: '链接验收待复核，保留 Word 下载' }] } } })
  })
  await page.route(/\/fixture-links-download-\d+\.docx$/, route => {
    const revision = Number(/download-(\d+)/.exec(route.request().url())[1])
    return route.fulfill({ body: revisions.get(revision), contentType: mediaType, headers: { 'Content-Disposition': `attachment; filename="revision-${revision}.docx"` } })
  })
  await page.route(/\/reports\/v1\/native\/fixture-links\/\d+$/, async route => {
    const response = await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }); await route.fulfill({ response })
  })
  const editor = page.getByRole('textbox', { name: 'Word 文档编辑区' })
  const paragraph = () => editor.locator('p').filter({ hasText: paragraphText })
  const open = async revision => {
    await page.goto(`${baseUrl}/reports/v1/native/fixture-links/${revision}`)
    try { await paragraph().waitFor({ timeout: 30000 }) }
    catch { throw new Error(JSON.stringify({ phase: 'open', revision, body: (await page.locator('body').innerText()).slice(-2400), errors, failedResponses })) }
    await page.locator('.docx-source-home').waitFor()
  }
  const selectTarget = async () => {
    await paragraph().click(); await page.keyboard.press('Home')
    for (let i = 0; i < '前缀 '.length; i++) await page.keyboard.press('ArrowRight')
    for (let i = 0; i < targetText.length; i++) await page.keyboard.press('Shift+ArrowRight')
    assert.equal(await page.evaluate(() => getSelection()?.toString()), targetText)
  }
  const targetLink = () => paragraph().locator('a').filter({ hasText: targetText })
  const linkCount = () => targetLink().count()
  const dialog = page.getByRole('dialog', { name: 'Link', exact: true })
  const invoke = async action => {
    await page.locator('[data-tab-id="insert"]').click()
    await page.locator(`.docx-source-insert [data-action="${action}"]`).click()
  }
  const expectedRuns = [{ text: '前缀 ', bold: false, italic: false }, { text: targetText, bold: true, italic: true }, { text: ' 后缀😀', bold: false, italic: false }, { text: '同段链接', bold: false, italic: false }]
  const saveAndReopen = async (revision, expectedHref) => {
    await page.locator('[data-action="save"]').click()
    await page.getByText(`已保存修订 ${revision}`, { exact: true }).waitFor({ timeout: 60000 })
    await page.getByText('链接验收待复核，保留 Word 下载', { exact: true }).waitFor()
    const event = page.waitForEvent('download')
    await page.getByRole('link', { name: '下载 Word', exact: true }).click()
    const download = await event, path = join(temporary, `download-${revision}.docx`)
    await download.saveAs(path); const bytes = await readFile(path)
    assert.equal(hash(bytes), hash(revisions.get(revision)))
    const actual = inspect(bytes), first = actual.paragraphs[0]
    assert.equal(first.text, paragraphText)
    assert.deepEqual(first.runs, expectedRuns)
    const sameLink = { text: '同段链接', href: 'https://example.test/same', external: true, tooltip: 'Same paragraph tooltip' }
    assert.deepEqual(first.links.map(({ styleIds, ...link }) => link), [...(expectedHref ? [{ text: targetText, href: expectedHref, external: true, tooltip: null }] : []), sameLink])
    assert.deepEqual(first.links.find(link => link.href === sameLink.href).styleIds, [], 'Untargeted unstyled link must not acquire Hyperlink style')
    assert.deepEqual(actual.paragraphs[1], inspections.get(1).paragraphs[1])
    assert.equal(hash(revisions.get(1)), sourceSha)
    await open(revision)
    assert.equal(await linkCount(), expectedHref ? 1 : 0)
    if (expectedHref) assert.equal(await targetLink().getAttribute('href'), expectedHref)
  }
  await open(1)
  await selectTarget(); await invoke('insert-link')
  await dialog.getByLabel('Link URL', { exact: true }).fill('javascript:alert(1)')
  await dialog.locator('[data-command="applyLink"]').click()
  assert.ok(await dialog.isVisible(), 'Invalid URL must not close dialog or modify document')
  assert.equal(await linkCount(), 0)
  await dialog.getByLabel('Link URL', { exact: true }).fill(firstUrl)
  await dialog.locator('[data-command="applyLink"]').click()
  assert.equal(await linkCount(), 1)
  await paragraph().click(); await page.keyboard.press('ControlOrMeta+z'); assert.equal(await linkCount(), 0)
  await page.keyboard.press('ControlOrMeta+Shift+z'); assert.equal(await linkCount(), 1)
  await open(1); assert.equal(await linkCount(), 1, 'Draft must survive a real refresh')
  await saveAndReopen(2, firstUrl)
  await selectTarget(); await invoke('edit-link')
  assert.equal(await dialog.getByLabel('Link URL', { exact: true }).inputValue(), firstUrl)
  await dialog.getByLabel('Link URL', { exact: true }).fill(secondUrl)
  await dialog.locator('[data-command="applyLink"]').click()
  await saveAndReopen(3, secondUrl)
  await selectTarget(); await invoke('remove-link')
  assert.equal(await linkCount(), 0)
  await saveAndReopen(4, null)
  assert.equal(saves.length, 3)
  assert.ok(saves.every(save => save.operations.some(op => op.kind === 'setParagraphLink')))
  assert.deepEqual(errors, []); assert.deepEqual(failedResponses, [])
  const receipt = { ok: true, browserVersion: baseline.browserVersion, revisions: [2, 3, 4],
    sourceSha256: sourceSha, finalSha256: hash(revisions.get(4)), unchangedOtherLinkTooltip: true,
    mixedStylesPreserved: true, nativeSelection: true, draftRefresh: true, undoRedo: true,
    failedValidationRetainsDownload: true, operationKinds: saves.map(save => save.operations.map(op => op.kind)),
    files: Object.fromEntries([...revisions].map(([revision, bytes]) => [revision, { sha256: hash(bytes), size: bytes.length }])),
    independentReadbacks: Object.fromEntries([...inspections].map(([revision, value]) => [revision, value.paragraphs])),
  }
  if (process.env.DOCX_LINK_SMOKE_EVIDENCE_DIR) {
    const evidenceDir = resolve(process.env.DOCX_LINK_SMOKE_EVIDENCE_DIR)
    await mkdir(evidenceDir, { recursive: true })
    for (const [revision, bytes] of revisions) await writeFile(join(evidenceDir, `revision-${revision}.docx`), bytes)
    await writeFile(join(evidenceDir, 'evidence.json'), JSON.stringify(receipt, null, 2) + '\n')
  }
  console.log(JSON.stringify(receipt))
} finally {
  await browser?.close()
  if (server && server.exitCode === null) { const exited = new Promise(resolve => server.once('exit', resolve)); server.kill('SIGTERM'); await exited }
  await rm(temporary, { recursive: true, force: true })
}
