import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const output = process.env.DOCX_HOME_NUMBERING_DIRECTORY, staticRoot = process.env.PDF_SMOKE_STATIC_DIRECTORY
const port = Number(process.env.DOCX_HOME_NUMBERING_PORT ?? 4482), origin = `http://127.0.0.1:${port}`
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
await mkdir(output, { recursive: false })
const manifestSha256 = sha(await readFile(join(staticRoot, '.vite/manifest.json')))
const bridge = join(process.env.AGENT_REPORTING_DOC_ENGINE_DIR, 'dist/edit-docx.mjs'), bridgeSha256 = sha(await readFile(bridge))
const fixture = spawnSync(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/docx-home-numbering-verify.py'), output, '--fixture'], { encoding: 'utf8' })
assert.equal(fixture.status, 0, fixture.stderr)
const server = spawn(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/docx-multilevel-server.py'), '--directory', output, '--port', String(port), '--source', join(output, 'source.docx')], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, stdio: 'pipe' })
let serverLog = '', browser, page, stage = 'server'
server.stdout.on('data', data => { serverLog += data }); server.stderr.on('data', data => { serverLog += data })
const errors = [], consoleErrors = [], httpErrors = [], assetErrors = [], checks = [], assets = new Map()
try {
  for (let i = 0; ; i++) {
    assert.equal(server.exitCode, null, serverLog)
    try { if ((await fetch(origin + '/__smoke__/state', { signal: AbortSignal.timeout(1000) })).ok) break } catch {}
    assert(i < 180, serverLog); await delay(250)
  }
  const info = JSON.parse(await readFile(join(output, 'server-info.json'), 'utf8'))
  browser = await chromium.launch({ headless: true }); page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true })
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400) httpErrors.push({ path, status: response.status() })
    if (response.status() >= 300) return
    if (path.startsWith('/reports/v1/editor/assets/') && /\.(js|css)$/.test(path)) checks.push((async () => {
      const bytes = await response.body(), disk = await readFile(join(staticRoot, path.slice('/reports/v1/editor/assets/'.length)))
      assert.equal(sha(bytes), sha(disk)); assets.set(path, sha(bytes))
    })().catch(error => assetErrors.push(String(error))))
  })
  const ready = () => page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 120000 })
  const editor = page.getByRole('textbox', { name: 'Word 文档编辑区', exact: true })
  const snapshot = () => editor.evaluate(node => node.editor.getJSON())
  const select = index => editor.evaluate((node, index) => {
    let pos = 0; node.editor.state.doc.forEach((child, offset, i) => { if (i === index) pos = offset + 1 })
    node.editor.commands.setTextSelection(pos); node.editor.commands.focus()
  }, index)
  const operations = () => page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')).flatMap(([, value]) => JSON.parse(value).operations ?? []))
  const trigger = page.locator('[data-action=list-numbering-set-value]'), dialog = page.locator('.list-value-dialog')
  const open = async () => { await trigger.click(); await dialog.waitFor() }
  const confirm = async () => { await dialog.locator('.modal-actions .primary').click(); await dialog.waitFor({ state: 'detached' }) }
  stage = 'open'; const htmlResponse = await page.goto(origin + info.openPath)
  assert.equal(sha(await htmlResponse.body()), sha(await readFile(join(staticRoot, 'native.html'))))
  await ready(); await editor.waitFor()
  const baseline = await snapshot()
  stage = 'home-list'; await editor.evaluate(node => {
    let end = 0; node.editor.state.doc.forEach((child, offset, index) => { if (index === 1) end = offset + child.nodeSize - 1 })
    node.editor.commands.setTextSelection({ from: 1, to: end })
  })
  await page.locator('[data-action=numbering]').click()
  const home = await snapshot()
  assert.equal(home.content[0].type, 'docListItem'); assert.equal(home.content[1].type, 'docListItem')
  assert.equal(home.content[0].attrs.numId, home.content[1].attrs.numId)
  assert(home.content[0].attrs.nativeNumberingBinding.sourceNumId)
  const originalNumId = home.content[0].attrs.nativeNumberingBinding.sourceNumId
  assert.deepEqual(home.content[0].attrs.nativeNumberingBinding.startOverrides, { 0: 1 })
  stage = 'history'; await editor.focus(); await page.keyboard.press('Control+z'); assert.deepEqual(await snapshot(), baseline)
  await page.keyboard.press('Control+Shift+z'); assert.deepEqual(await snapshot(), home)
  await select(1)
  stage = 'cancel'; await open(); assert.equal(await dialog.locator('input[type=number]').inputValue(), '2')
  await dialog.locator('.modal-actions button:not(.primary)').click(); assert.deepEqual(await snapshot(), home)
  stage = 'restart'; await open(); await dialog.locator('input[type=number]').fill('9')
  await page.screenshot({ path: join(output, 'home-value-desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 }); await page.screenshot({ path: join(output, 'home-value-mobile.png'), fullPage: true })
  const dialogFit = await dialog.evaluate(node => { const r = node.getBoundingClientRect(); return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: innerWidth, height: innerHeight, scrollWidth: node.scrollWidth, clientWidth: node.clientWidth } })
  assert(dialogFit.left >= -1 && dialogFit.right <= dialogFit.width + 1 && dialogFit.top >= -1 && dialogFit.bottom <= dialogFit.height + 1)
  await confirm(); await page.setViewportSize({ width: 1440, height: 1000 })
  const changed = await snapshot()
  assert.notEqual(changed.content[0].attrs.numId, changed.content[1].attrs.numId)
  assert.equal(changed.content[1].attrs.nativeNumberingBinding.sourceNumId, originalNumId)
  assert.deepEqual(changed.content[1].attrs.nativeNumberingBinding.startOverrides, { 0: 9 })
  await page.waitForFunction(() => Object.entries(localStorage).some(([key, value]) => key.startsWith('native-editor-draft:') && (JSON.parse(value).operations ?? []).filter(op => op.kind === 'setParagraphNumberingValue').length === 2))
  const staged = await operations(); await writeFile(join(output, 'staged-operations.json'), JSON.stringify(staged, null, 2))
  stage = 'reload'; await page.reload(); await ready(); await editor.waitFor(); assert.deepEqual(await snapshot(), changed)
  stage = 'save'; const [response] = await Promise.all([page.waitForResponse(r => r.url().endsWith('/api/save') && r.request().method() === 'POST'), page.locator('[data-action=save]').click()])
  const saved = await response.json(); assert.equal(response.status(), 200, JSON.stringify(saved)); assert.equal(saved.revisionRegistered, true)
  await writeFile(join(output, 'save-response.json'), JSON.stringify(saved, null, 2))
  assert.equal(saved.revision, info.context.revision + 1); assert.equal(saved.parentRevision, info.context.revision)
  const saveRequest = response.request().postDataJSON(); assert.equal(saveRequest.expectedSha256, info.sourceSha256); assert.deepEqual(saveRequest.operations, staged)
  const link = page.getByRole('link', { name: '下载 Word', exact: true }); await link.waitFor()
  const downloading = page.waitForEvent('download'); await link.click(); const download = await downloading
  assert.equal(await download.failure(), null); const bytes = await readFile(await download.path()); assert.equal(sha(bytes), saved.artifacts.word.sha256)
  await writeFile(join(output, 'downloaded.docx'), bytes)
  stage = 'reopen'; await page.goto(saved.editor.openUrl); await ready(); await editor.waitFor()
  const reopened = await snapshot(); assert.notEqual(reopened.content[0].attrs.numId, reopened.content[1].attrs.numId)
  assert.equal(reopened.content[0].attrs.ilvl, 0); assert.equal(reopened.content[1].attrs.ilvl, 0)
  await page.screenshot({ path: join(output, 'reopened.png'), fullPage: true })
  const file = await page.request.get(page.url() + '/api/file'); assert.equal(file.status(), 200); assert.equal(sha(await file.body()), sha(bytes))
  const state = await (await fetch(origin + '/__smoke__/state')).json(); assert.equal(state.savedRevisions, 1); assert.equal(state.sourceSha256, info.sourceSha256)
  const verification = spawnSync(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/docx-home-numbering-verify.py'), output], { encoding: 'utf8' })
  assert.equal(verification.status, 0, verification.stderr || verification.stdout)
  await Promise.all(checks)
  await writeFile(join(output, 'loaded-assets.json'), JSON.stringify({ assets: Object.fromEntries(assets), assetErrors }, null, 2))
  assert.deepEqual(errors, []); assert.deepEqual(consoleErrors, []); assert.deepEqual(httpErrors, []); assert.deepEqual(assetErrors, [])
  assert.equal(sha(await readFile(join(staticRoot, '.vite/manifest.json'))), manifestSha256); assert.equal(sha(await readFile(bridge)), bridgeSha256)
  const evidence = { ok: true, manifestSha256, bridgeSha256, sourceSha256: info.sourceSha256, assets: Object.fromEntries(assets), dialogFit, staged, saveRequest, saved, originalNumId, independent: JSON.parse(verification.stdout), errors, consoleErrors, httpErrors, assetErrors, requests: state.requests }
  await writeFile(join(output, 'evidence.json'), JSON.stringify(evidence, null, 2)); console.log(JSON.stringify({ ok: true, output, resources: assets.size, manifestSha256 }))
} catch (error) {
  await page?.screenshot({ path: join(output, 'failure.png'), fullPage: true }).catch(() => {})
  await writeFile(join(output, 'failure.json'), JSON.stringify({ stage, error: String(error), errors, consoleErrors, httpErrors, assetErrors }, null, 2)); throw error
} finally {
  await browser?.close(); server.kill(); await writeFile(join(output, 'server.log'), serverLog)
  if (server.exitCode === null) await Promise.race([new Promise(resolve => server.once('exit', resolve)), delay(5000)])
  if (server.exitCode === null) server.kill('SIGKILL')
}
