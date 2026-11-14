import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn } from 'node:child_process'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import { verifyPdfInputLifecycleInEditor } from './pdf-input-lifecycle-check.mjs'

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..'), repo = resolve(frontend, '../../..')
const output = resolve(process.env.PDF_INPUT_EVIDENCE_DIR ?? '/dev/shm/office-pdf-input-lifecycle-built-verification-20261113')
const staticRoot = resolve(process.env.PDF_INPUT_STATIC_ROOT ?? join(frontend, '../static'))
const port = Number(process.env.PDF_INPUT_PORT ?? 4394), origin = `http://127.0.0.1:${port}`
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
const manifest = await readFile(join(staticRoot, '.vite/manifest.json')), manifestSha256 = sha(manifest)
if (process.env.PDF_INPUT_EXPECTED_MANIFEST_SHA256) assert.equal(manifestSha256, process.env.PDF_INPUT_EXPECTED_MANIFEST_SHA256)
await mkdir(output, { recursive: true })
const server = spawn(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/pdf-static-text-server.py'), '--directory', output, '--port', String(port)], {
  cwd: repo, env: { ...process.env, PYTHONPATH: repo, PDF_SMOKE_STATIC_DIRECTORY: staticRoot }, stdio: 'pipe',
})
let serverLog = '', browser, page
server.stdout.on('data', bytes => { serverLog += bytes }); server.stderr.on('data', bytes => { serverLog += bytes })
const evidence = { manifestSha256, staticRoot, pageErrors: [], consoleErrors: [], httpErrors: [], assetErrors: [], assets: {}, checks: [] }
const assetReads = []
try {
  for (let attempt = 0; ; attempt++) {
    assert.equal(server.exitCode, null, serverLog)
    try { if ((await fetch(`${origin}/__smoke__/state`)).ok) break } catch {}
    assert.ok(attempt < 240, serverLog); await delay(250)
  }
  const info = JSON.parse(await readFile(join(output, 'server-info.json'), 'utf8'))
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  page = await browser.newPage({ viewport: { width: 1500, height: 1100 } })
  page.on('pageerror', error => evidence.pageErrors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') evidence.consoleErrors.push(message.text()) })
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400) evidence.httpErrors.push({ path, status: response.status() })
    if (!path.startsWith('/reports/v1/editor/assets/') || !/\.m?js$/.test(path)) return
    assetReads.push((async () => {
      const bytes = await response.body(), relative = path.slice('/reports/v1/editor/assets/'.length)
      assert.ok(!relative.includes('..'))
      const disk = await readFile(join(staticRoot, relative)); assert.equal(sha(bytes), sha(disk), path)
      evidence.assets[path] = sha(bytes)
    })().catch(error => evidence.assetErrors.push(String(error))))
  })
  await page.goto(origin + info.openPath)
  await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 60000 })
  evidence.checks = await verifyPdfInputLifecycleInEditor(page)
  const operations = await page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.startsWith('native-editor-draft:'))?.[1] ?? '{"operations":[]}').operations)
  assert.deepEqual(operations, [])
  const state = await (await fetch(`${origin}/__smoke__/state`)).json()
  assert.equal(state.sourceSha256, info.sourceSha256); assert.equal(state.savedRevisions, 0)
  evidence.sourceSha256 = info.sourceSha256; evidence.sourceUnchanged = true; evidence.savedRevisions = 0
  await page.screenshot({ path: join(output, 'frozen-editor.png'), fullPage: true })
  await Promise.all(assetReads)
  for (const field of ['pageErrors', 'consoleErrors', 'httpErrors', 'assetErrors']) assert.deepEqual(evidence[field], [], field)
  assert.equal(sha(await readFile(join(staticRoot, '.vite/manifest.json'))), manifestSha256)
  evidence.passed = true; console.log(JSON.stringify(evidence, null, 2))
} finally {
  await writeFile(join(output, 'result.json'), JSON.stringify(evidence, null, 2))
  await writeFile(join(output, 'server.log'), serverLog)
  await browser?.close(); server.kill('SIGTERM')
}
