import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import { inspectAssistantWindow } from './office-assistant-window-layout.mjs'

const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = resolve(frontend, '../../..')
const output = process.env.OFFICE_ASSISTANT_WINDOW_OUTPUT ?? '/tmp/office-assistant-window-20261112'
const port = Number(process.env.OFFICE_ASSISTANT_WINDOW_PORT ?? 4321)
const formats = (process.env.OFFICE_ASSISTANT_WINDOW_FORMATS ?? 'xlsx,pptx,docx,pdf').split(',')
const viewports = process.env.OFFICE_ASSISTANT_WINDOW_VIEWPORTS ?? '1440x900,320x640,640x360,390x320,1440x360'
const sha = data => createHash('sha256').update(data).digest('hex')
const manifest = await readFile(join(frontend, '../static/.vite/manifest.json'))
assert.equal(sha(manifest), process.env.OFFICE_ASSISTANT_EXPECTED_MANIFEST)
await mkdir(output, { recursive: false })
let browser, page, server, stage = 'start', serverLog = ''
const evidence = { ok: false, apiRoutesAreReal: true, revisionLookupIsFixture: true, model: 'ScriptedModel through actual Agno; not a real provider',
  manifestSha256: sha(manifest), formats: [], errors: [], consoleErrors: [], httpErrors: [], runtimeJavaScript: [] }
const chunks = new Map(), identities = []
try {
  browser = await chromium.launch({ headless: true })
  for (const format of formats) {
    stage = `${format}-server`
    const directory = join(output, format); await mkdir(directory)
    const script = format === 'docx' ? 'word-ai-read-server.py' : format === 'pdf' ? 'pdf-ai-read-server.py' : 'office-ai-read-server.py'
    serverLog = ''
    server = spawn(join(repo, '.venv/bin/python'), [join(frontend, 'smoke', script), format === 'pdf' ? '--directory' : '--output-dir', directory, '--port', String(port)], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, stdio: 'pipe' })
    server.stdout.on('data', data => { serverLog += data }); server.stderr.on('data', data => { serverLog += data })
    const origin = `http://127.0.0.1:${port}`
    for (let attempt = 0; ; attempt++) {
      assert.equal(server.exitCode, null, serverLog)
      try { if ((await fetch(origin + '/__smoke__/state')).ok) break } catch {}
      assert.ok(attempt < 240, serverLog); await delay(250)
    }
    const info = JSON.parse(await readFile(join(directory, 'server-info.json'))), document = info.documents?.[format] ?? info
    page = await browser.newPage({ viewport: { width: 1550, height: 1100 } })
    page.on('pageerror', error => evidence.errors.push({ format, message: error.message }))
    page.on('console', message => { if (message.type() === 'error') evidence.consoleErrors.push({ format, message: message.text() }) })
    page.on('response', response => {
      const path = new URL(response.url()).pathname
      if (response.status() >= 400) evidence.httpErrors.push({ format, path, status: response.status() })
      if (response.ok() && path.startsWith('/reports/v1/editor/assets/') && path.endsWith('.js')) identities.push(response.body().then(async data => {
        assert.equal(sha(data), sha(await readFile(join(frontend, '../static', path.slice('/reports/v1/editor/assets/'.length)))))
        chunks.set(path, { path, size: data.length, sha256: sha(data) })
      }))
    })
    stage = `${format}-open`; await page.goto(origin + document.openPath)
    await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 60000 })
    const draft = () => page.evaluate(() => Object.fromEntries(Object.keys(localStorage).filter(key => key.startsWith('native-editor-draft:')).map(key => [key, localStorage.getItem(key)])))
    const before = await draft()
    if (format === 'docx') await page.locator('[data-action="word-read-ai"]').click()
    else if (format === 'pdf') {
      await page.locator('[data-pdf-ribbon-tab="home"]').click()
      await page.locator('[data-source-command-id="genoffice.pdf.home.ai.openAssistant"]').click()
    } else await page.locator('[data-action="office-read-ai"]').click()
    const dock = page.locator(format === 'pdf' ? '.pdf-ai-dock' : '.office-task-dock')
    await dock.waitFor({ state: 'visible' })
    const prefix = format === 'pdf' ? 'pdf' : format === 'docx' ? 'word' : 'office'
    stage = `${format}-real-read`
    if (format === 'pdf') await page.locator('[data-source-command-id="genoffice.pdf.home.ai.summarize"]').click()
    else await dock.locator(`[data-${prefix}-ai="summarize"]`).click()
    await page.waitForFunction(() => [...document.querySelectorAll('.native-ai [role="status"]')].some(node => node.textContent === '阅读完成，文档与草稿未修改。'), null, { timeout: 60000 })
    const state = await (await fetch(origin + '/__smoke__/state')).json(), job = state.jobs.at(-1)
    assert.equal(job.status, 'completed'); assert.ok(job.result.answer); assert.deepEqual(job.result.issues, [])
    assert.equal(job.result.sourceSha256, document.sourceSha256)
    assert.deepEqual(await draft(), before)
    stage = `${format}-layout`
    const layout = await inspectAssistantWindow(page, { output, format, viewports, draft })
    assert.ok(state.requests.every(request => request.method !== 'POST' || /\/ai\/(office-read|read|word-read)\//.test(request.path)), '不得提交编辑或发布请求')
    await page.screenshot({ path: join(output, `${format}-completed.png`) })
    const finalState = await (await fetch(origin + '/__smoke__/state')).json()
    assert.equal(finalState.jobs.length, state.jobs.length, '窗口操作不得启动新的AI任务')
    evidence.formats.push({ format, sourceSha256: document.sourceSha256, layout, job, requests: finalState.requests, finalState, draftUnchanged: true })
    await page.close(); page = undefined
    const stopped = new Promise(done => server.once('exit', done)); server.kill(); await stopped
    await writeFile(join(directory, 'server.log'), serverLog); server = undefined
    await writeFile(join(output, 'checkpoint.json'), JSON.stringify(evidence, null, 2))
  }
  stage = 'final-audit'
  await Promise.all(identities); evidence.runtimeJavaScript = [...chunks.values()]
  assert.deepEqual(await readFile(join(frontend, '../static/.vite/manifest.json')), manifest)
  assert.deepEqual(evidence.errors, []); assert.deepEqual(evidence.consoleErrors, []); assert.deepEqual(evidence.httpErrors, [])
  const failures = evidence.formats.flatMap(item => item.layout.failures)
  evidence.ok = failures.length === 0
  await writeFile(join(output, 'evidence.json'), JSON.stringify(evidence, null, 2))
  assert.deepEqual(failures, [])
  console.log(JSON.stringify({ ok: true, output, formats, layoutCases: evidence.formats.reduce((count, item) => count + item.layout.cases.length, 0), javascriptCount: chunks.size }))
} catch (error) {
  await page?.screenshot({ path: join(output, 'failure.png') }).catch(() => {})
  await writeFile(join(output, 'failure.json'), JSON.stringify({ stage, error: error.message, stack: error.stack, evidence }, null, 2))
  throw error
} finally {
  await browser?.close()
  if (server) {
    if (server.exitCode === null && server.signalCode === null) { const stopped = new Promise(done => server.once('exit', done)); server.kill(); await stopped }
    await writeFile(join(output, 'last-server.log'), serverLog)
  }
}
