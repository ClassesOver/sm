import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, writeFile, readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const base = `http://127.0.0.1:${process.env.PPTX_SMOKE_PORT ?? 4197}`, sha = bytes => createHash('sha256').update(bytes).digest('hex')
const mime = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
const python = input => {
  const result = spawnSync(join(repo, '.venv/bin/python'), ['-c', `
import base64,json,sys
from io import BytesIO
from zipfile import ZipFile
from lxml import etree
from pptx import Presentation
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches
from smart_reporting.report_editor.native_office import inspect_office,patch_office
from smart_reporting.report_editor.slides_render import render_pptx_tree
p=json.load(sys.stdin)
if p['mode']=='create':
 from smart_reporting.reporting.tests.test_pptx_transition_preservation import source_bytes,MC,P14
 d=Presentation(BytesIO(source_bytes()))
 transition=d.slides[1]._element.find(qn('p:transition'));d.slides[1]._element.remove(transition)
 wrapper=etree.SubElement(d.slides[1]._element,'{'+MC+'}AlternateContent',nsmap={'mc':MC,'p14':P14})
 etree.SubElement(wrapper,'{'+MC+'}Choice',Requires='p14').append(transition)
 b=BytesIO();d.save(b);print(base64.b64encode(b.getvalue()).decode())
else:
 b=base64.b64decode(p['bytes'])
 if p.get('operations'):b=patch_office('pptx',b,p['operations'])
 if p['mode']=='inspect':print(json.dumps(inspect_office('pptx',b)))
 elif p['mode']=='render':print(json.dumps(render_pptx_tree(b)))
 elif p['mode']=='patch':print(base64.b64encode(b).decode())
 elif p['mode']=='verify':
  from smart_reporting.reporting.tests.test_pptx_transition_preservation import metadata
  source=base64.b64decode(p['source']);before=Presentation(BytesIO(source));after=Presentation(BytesIO(b))
  old=before.slides[0]._element.find(qn('p:transition'));new=after.slides[0]._element.find(qn('p:transition'))
  assert new.find(qn('p:wipe')) is not None
  assert metadata(old)==metadata(new)
  assert new.get('spd')=='fast' and new.get('advClick')=='0' and new.get('advTm')=='1234'
  assert etree.tostring(before.slides[0].shapes[0]._element,method='c14n')==etree.tostring(after.slides[0].shapes[0]._element,method='c14n')
  for i in [1,2]:assert etree.tostring(before.slides[i]._element,method='c14n')==etree.tostring(after.slides[i]._element,method='c14n')
  with ZipFile(BytesIO(source)) as a,ZipFile(BytesIO(b)) as z:
   names={n for n in a.namelist() if not n.endswith('/')};assert names=={n for n in z.namelist() if not n.endswith('/')}
   for n in names-{'ppt/slides/slide1.xml','ppt/presentation.xml','docProps/core.xml'}:assert a.read(n)==z.read(n),n
   assert a.read('ppt/media/fixture.wav')==z.read('ppt/media/fixture.wav')
  print(json.dumps({'effect':'wipe','attributes':dict(new.attrib),'soundAndExtensionsPreserved':True,'audioAndRelationshipsPreserved':True,'untouchedSlidesPreserved':True}))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr)
  return result.stdout.trim()
}
const source = Buffer.from(python({ mode: 'create' }), 'base64'), sourceModel = JSON.parse(python({ mode: 'inspect', bytes: source.toString('base64') }))
let saved, savedModel, payload, browser
const server = spawn('./node_modules/.bin/vite', ['--host', '127.0.0.1', '--port', new URL(base).port, '--strictPort'], { cwd: frontend, stdio: 'ignore' })
try {
  for (let i = 0; i < 120; i++) { try { if ((await fetch(base + '/reports/v1/editor/assets/native.html')).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ?? '/usr/bin/chromium' })
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, acceptDownloads: true }), errors = []
  page.on('pageerror', error => errors.push(error.message))
  const rev = route => route.request().url().includes('/1/api/') ? 1 : 2
  const active = route => rev(route) === 1 ? source : saved
  await page.route('**/favicon.ico', route => route.fulfill({ status: 200, body: '' }))
  await page.route('**/reports/v1/native/transition-fixture/*/api/context', route => route.fulfill({ json: {
    context: { documentId: 'transition-fixture', revision: rev(route), parentRevision: rev(route) === 1 ? null : 1, format: 'pptx', sourceFile: { path: 'source.pptx', size: active(route).length, sha256: sha(active(route)), mediaType: mime }, scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, origin: 'upload' },
    csrfToken: 'fixture', capabilities: { pptx_editor: true }, editingEnabled: true,
  } }))
  await page.route('**/reports/v1/native/transition-fixture/*/api/file', route => route.fulfill({ body: active(route), contentType: mime }))
  await page.route('**/reports/v1/native/transition-fixture/*/api/preview', route => {
    const operations = route.request().postDataJSON().operations
    const bytes = operations.length ? Buffer.from(python({ mode: 'patch', bytes: active(route).toString('base64'), operations }), 'base64') : active(route)
    const model = operations.length ? JSON.parse(python({ mode: 'inspect', bytes: bytes.toString('base64') })) : rev(route) === 1 ? sourceModel : savedModel
    return route.fulfill({ json: { sourceSha256: sha(active(route)), draftSha256: sha(bytes), model } })
  })
  await page.route('**/reports/v1/native/transition-fixture/*/api/render-tree', route => {
    const request = route.request().postDataJSON(); assert.equal(request.expectedSha256, sha(active(route)))
    const tree = JSON.parse(python({ mode: 'render', bytes: active(route).toString('base64'), operations: request.operations }))
    return route.fulfill({ json: tree })
  })
  await page.route('**/reports/v1/native/transition-fixture/*/api/preview.pdf*', route => route.fulfill({ body: '%PDF-1.4\n%%EOF', contentType: 'application/pdf' }))
  await page.route('**/reports/v1/native/transition-fixture/1/api/save', route => {
    payload = route.request().postDataJSON(); assert.equal(payload.expectedSha256, sha(source))
    saved = Buffer.from(python({ mode: 'patch', bytes: source.toString('base64'), operations: payload.operations }), 'base64')
    savedModel = JSON.parse(python({ mode: 'inspect', bytes: saved.toString('base64') }))
    return route.fulfill({ json: { documentId: 'transition-fixture', revision: 2, parentRevision: 1, revisionRegistered: true, artifacts: { pptx: { downloadUrl: '/transition-download.pptx', size: saved.length, sha256: sha(saved) } }, editor: { openUrl: '/reports/v1/native/transition-fixture/2' }, validation: { ok: false, issues: [{ code: 'fixture_review', message: '保留下载' }] } } })
  })
  await page.route('**/transition-download.pptx', route => route.fulfill({ body: saved, contentType: mime, headers: { 'Content-Disposition': 'attachment; filename="slides.pptx"' } }))
  await page.route(/\/reports\/v1\/native\/transition-fixture\/[12]$/, async route => route.fulfill({ response: await route.fetch({ url: base + '/reports/v1/editor/assets/native.html' }) }))
  const open = async revision => { await page.goto(base + `/reports/v1/native/transition-fixture/${revision}`); try { await page.locator('.slides-canvas canvas').first().waitFor({ timeout: 60000 }) } catch { throw new Error(JSON.stringify({ errors, body: await page.locator('body').innerText() })) } }
  const all = page.locator('[data-command="applyTransitionAll"]'), effect = page.locator('[data-command="transition"]')
  const undo = page.locator('[data-source-action="onUndo"]'), redo = page.locator('[data-source-action="onRedo"]'), slides = page.locator('.slide-open')
  await open(1); await page.locator('[data-ribbon-tab="transitions"]').click()
  assert.equal(sourceModel.slides[0].transitionEditSafe, true)
  assert.equal(await effect.isEnabled(), true); assert.equal(await all.isDisabled(), true)
  await effect.selectOption('wipe'); await undo.click(); assert.equal(await effect.inputValue(), 'fade')
  await redo.click(); assert.equal(await effect.inputValue(), 'wipe')
  await page.reload(); await page.locator('.slides-canvas canvas').first().waitFor({ timeout: 60000 })
  await page.locator('[data-ribbon-tab="transitions"]').click(); assert.equal(await effect.inputValue(), 'wipe')
  await slides.nth(1).click(); assert.equal(await effect.isDisabled(), true)
  await effect.evaluate(el => { el.value = 'zoom'; el.dispatchEvent(new Event('change', { bubbles: true })) })
  await slides.first().click(); assert.equal(await effect.inputValue(), 'wipe')
  await page.locator('[data-action="save"]').click()
  await page.getByRole('link', { name: '下载 PPTX', exact: true }).waitFor({ timeout: 60000 })
  assert.deepEqual(payload.operations[0].transitions, [{ slideIndex: 0, kind: 'wipe' }])
  assert.equal(await all.isDisabled(), true)
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: '下载 PPTX', exact: true }).click()])
  const downloaded = await readFile(await download.path()); assert.equal(sha(downloaded), sha(saved))
  const readback = JSON.parse(python({ mode: 'verify', bytes: downloaded.toString('base64'), source: source.toString('base64') }))
  await open(2); await page.locator('[data-ribbon-tab="transitions"]').click()
  assert.equal(await effect.inputValue(), 'wipe'); assert.equal(await all.isDisabled(), true); assert.equal(await effect.isEnabled(), true)
  assert.deepEqual(errors, [])
  const evidence = { ok: true, browserVersion: browser.version(), sourceSha256: sha(source), downloadedSha256: sha(saved), operations: payload.operations, readback, desktopVerified: false, provenance: 'browser auth/revision routes are substitutes; actual packed engine and independent python-pptx/XML/ZIP readback' }
  if (process.env.PPTX_SMOKE_EVIDENCE_DIR) { const output = process.env.PPTX_SMOKE_EVIDENCE_DIR; await mkdir(output, { recursive: true }); await writeFile(join(output, 'source.pptx'), source); await writeFile(join(output, 'downloaded.pptx'), saved); await writeFile(join(output, 'evidence.json'), JSON.stringify(evidence, null, 2)) }
  console.log(JSON.stringify(evidence))
} finally { if (browser) await browser.close(); server.kill() }
