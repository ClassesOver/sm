import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { cp, mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const directory = process.env.WORD_AI_LIFECYCLE_DIRECTORY ?? '/tmp/native-ai-lifecycle-browser-20261113'
const port = Number(process.env.WORD_AI_LIFECYCLE_PORT ?? 4297), origin = 'http://127.0.0.1:' + port
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
await mkdir(directory, { recursive: true })
const staticRoot = join(directory, 'static')
await cp(join(frontend, '../static'), staticRoot, { recursive: true, errorOnExist: true, force: false })
const manifest = await readFile(join(staticRoot, '.vite/manifest.json'))
const server = spawn(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/word-ai-review-server.py'), '--directory', directory, '--port', String(port)], {
  cwd: repo, env: { ...process.env, PYTHONPATH: repo, WORD_AI_REVIEW_STATIC_ROOT: staticRoot, WORD_AI_REVIEW_HOLD_START: '1' }, stdio: 'pipe',
})
let log = '', browser, page
server.stdout.on('data', data => { log += data }); server.stderr.on('data', data => { log += data })
const assets = new Map(), checks = [], errors = [], results = []
const state = async () => (await fetch(origin + '/__smoke__/state')).json()
async function until(predicate) {
  for (let index = 0; index < 240; index++) {
    assert.equal(server.exitCode, null, log)
    const value = await state()
    if (predicate(value)) return value
    await delay(100)
  }
  throw new Error('lifecycle_state_timeout')
}
try {
  for (let index = 0; ; index++) {
    assert.equal(server.exitCode, null, log)
    try { if ((await fetch(origin + '/__smoke__/state')).ok) break } catch {}
    assert(index < 240, log); await delay(250)
  }
  const info = JSON.parse(await readFile(join(directory, 'server-info.json'), 'utf8'))
  const comment = info.model.commentThreads.targets.find(target => target.parentId === null)
  browser = await chromium.launch({ headless: true })
  for (const [index, action] of ['cancel', 'instruction', 'close'].entries()) {
    const context = await browser.newContext({ viewport: { width: 1450, height: 1000 } })
    page = await context.newPage()
    page.on('pageerror', error => errors.push(error.message))
    page.on('response', response => {
      const path = new URL(response.url()).pathname
      if (path.startsWith('/reports/v1/editor/assets/') && /\.(js|css)$/.test(path)) checks.push((async () => {
        assert.equal(response.status(), 200)
        const actual = await response.body(), expected = await readFile(join(staticRoot, path.slice('/reports/v1/editor/assets/'.length)))
        assert.equal(sha(actual), sha(expected)); assets.set(path, sha(actual))
      })())
    })
    await page.goto(origin + info.openPaths[['reply', 'resolve', 'revision'][index]])
    await page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 60000 })
    await page.getByRole('tab', { name: '审阅', exact: true }).click()
    await page.locator('[data-action=comment-text-list]').click()
    await page.getByLabel('选择已有批注', { exact: true }).selectOption(comment.targetId)
    await page.locator('[data-comment-ai=reply]').click()
    const panel = page.getByRole('region', { name: 'AI 编辑选区', exact: true })
    await panel.getByLabel('AI 修改要求', { exact: true }).fill('请回复当前批注：已核实收入42。')
    const before = await page.evaluate(() => JSON.stringify({ ...localStorage }))
    const requestPromise = page.waitForRequest(request => request.url().endsWith('/api/ai/start'))
    await panel.locator('[data-ai=start]').click()
    const start = await requestPromise, requestId = start.postDataJSON().clientRequestId
    assert.equal(typeof requestId, 'string')
    await until(value => value.heldStarts === index + 1)
    if (action === 'cancel') await panel.locator('[data-ai=cancel]').click()
    else if (action === 'instruction') await panel.getByLabel('AI 修改要求', { exact: true }).fill('换一个要求')
    else await page.locator('.office-task-dock').getByRole('button', { name: '关闭助手', exact: true }).click()
    await until(value => value.jobs.some(job => job.clientRequestId === requestId && job.status === 'cancelled'))
    await fetch(origin + '/__smoke__/release-start', { method: 'POST' })
    const finished = await until(value => value.requests.some(request => request.path.endsWith('/api/ai/start') && request.body?.clientRequestId === requestId))
    const job = finished.jobs.find(job => job.clientRequestId === requestId)
    assert.equal(job.status, 'cancelled'); assert.equal(job.accepted, false); assert.equal(job.proposal, undefined)
    assert.deepEqual(job.events.map(event => event.kind), ['terminal'])
    assert.deepEqual(finished.plannerCalls, []); assert.equal(finished.sourceSha256, info.sourceSha256)
    assert.equal(await page.evaluate(() => JSON.stringify({ ...localStorage })), before)
    const url = `/reports/v1/native/word-ai-review-smoke/1/api/ai/${job.editId}/events`
    const replay = await page.evaluate(async url => (await fetch(url + '?after=999')).text(), url)
    const consumed = await page.evaluate(async url => (await fetch(url + '?after=1')).text(), url)
    assert(replay.includes('"kind":"reset"') && replay.includes('"status":"cancelled"')); assert.equal(consumed, '')
    assert(!finished.requests.some(request => request.method === 'POST' && /\/(accept|save|export)$/.test(request.path)))
    await page.screenshot({ path: join(directory, action + '.png'), fullPage: true })
    results.push({ action, requestId, job, replay, consumed, sourceSha256: finished.sourceSha256 })
    await context.close(); page = undefined
  }
  await Promise.all(checks); assert(assets.size > 0); assert.deepEqual(errors, [])
  assert.deepEqual(await readFile(join(staticRoot, '.vite/manifest.json')), manifest)
  await writeFile(join(directory, 'summary.json'), JSON.stringify({ ok: true, results, assets: Object.fromEntries(assets),
    manifestSha256: sha(manifest), browserVersion: browser.version(), errors,
    evidence: '真实浏览器／FastAPI／授权／工作区；启动回执前取消，模型未调用；内存修订仓储，非生产端到端。' }, null, 2))
  console.log(JSON.stringify({ ok: true, cases: results.length, assets: assets.size, directory }))
} catch (error) {
  if (page) { await writeFile(join(directory, 'failure.html'), await page.content()).catch(() => {}); await page.screenshot({ path: join(directory, 'failure.png'), fullPage: true }).catch(() => {}) }
  throw error
} finally {
  await browser?.close(); server.kill(); await writeFile(join(directory, 'server.log'), log)
}
