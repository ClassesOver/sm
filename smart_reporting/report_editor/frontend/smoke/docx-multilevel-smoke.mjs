import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { cp, mkdir, readFile, symlink, writeFile } from 'node:fs/promises'
import { createServer } from 'vite'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const output = process.env.DOCX_MULTILEVEL_OUTPUT ?? '/tmp/office-word-multilevel-20261113/browser-built'
const sourceMode = process.env.DOCX_LIST_LIBRARY_SOURCE === '1'
const staticRoot = sourceMode ? join(output, 'static') : process.env.PDF_SMOKE_STATIC_DIRECTORY
const libraryMode = process.env.DOCX_LIST_LIBRARY_SMOKE === '1'
const resumeRoot = process.env.DOCX_MULTILEVEL_RESUME_DIRECTORY
const engineRoot = process.env.AGENT_REPORTING_DOC_ENGINE_DIR
assert(staticRoot, '必须指定冻结静态资源')
const port = Number(process.env.DOCX_MULTILEVEL_PORT ?? 4402), origin = `http://127.0.0.1:${port}`
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
await mkdir(output, { recursive: false })
let vite
if (sourceMode) {
  await cp('/tmp/office-four-format-source-entry-20261113/static', staticRoot, { recursive: true, force: false, errorOnExist: true })
  await mkdir(join(staticRoot, 'src'), { recursive: true }); await symlink(join(frontend, 'src/assets'), join(staticRoot, 'src/assets'), 'dir')
  vite = await createServer({ root: frontend, configFile: join(frontend, 'vite.config.ts'), server: { host: '127.0.0.1', port: port + 1, strictPort: true, cors: true } })
  await vite.listen()
  const html = (await readFile(join(frontend, 'native.html'), 'utf8')).replace('/src/unified-main.ts', `http://127.0.0.1:${port + 1}/reports/v1/editor/assets/src/unified-main.ts`)
  await writeFile(join(staticRoot, 'native.html'), html)
}
const sourceFiles = ['docx-list-gallery.tsx', 'docx-ribbon.ts', 'docx-home-source.tsx', 'docx-custom-list.ts', 'docx-list-gallery.css']
const sourceHashes = Object.fromEntries(await Promise.all(sourceFiles.map(async file => [file, sha(await readFile(join(frontend, 'src', file)))])))
const manifestSha256 = sourceMode ? null : sha(await readFile(join(staticRoot, '.vite/manifest.json')))
const engineSha256 = engineRoot ? sha(await readFile(join(engineRoot, 'dist/edit-docx.mjs'))) : null
const nativeSource = join(repo, 'smart_reporting/reporting/delivery/docx_native.py')
const nativeSourceSha256 = sha(await readFile(nativeSource))
const resumeInfo = resumeRoot ? JSON.parse(await readFile(join(resumeRoot, 'server-info.json'), 'utf8')) : undefined
const resumeOperations = resumeRoot ? JSON.parse(await readFile(join(resumeRoot, 'staged-operations.json'), 'utf8')) : undefined
if (resumeRoot) {
  assert(engineRoot, '续验必须指定冻结 doc bridge')
  assert.equal(sha(await readFile(join(resumeRoot, 'source.docx'))), resumeInfo.sourceSha256)
}
const server = spawn(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/docx-multilevel-server.py'), '--directory', output, '--port', String(port), ...(resumeRoot ? ['--source', join(resumeRoot, 'source.docx')] : [])], { cwd: repo, env: { ...process.env, PYTHONPATH: repo, PDF_SMOKE_STATIC_DIRECTORY: staticRoot }, stdio: 'pipe' })
let log = '', browser, page, stage = 'server'
server.stdout.on('data', data => { log += data }); server.stderr.on('data', data => { log += data })
const errors = [], consoleErrors = [], httpErrors = [], assetErrors = [], assets = new Map(), checks = []
try {
  for (let i = 0; ; i++) {
    assert.equal(server.exitCode, null, log)
    try { if ((await fetch(origin + '/__smoke__/state', { signal: AbortSignal.timeout(1000) })).ok) break } catch {}
    assert(i < 240, log); await delay(250)
  }
  const info = JSON.parse(await readFile(join(output, 'server-info.json'), 'utf8'))
  browser = await chromium.launch({ headless: true }); page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true })
  let restoredEnvelope
  if (resumeRoot) {
    assert.equal(info.sourceSha256, resumeInfo.sourceSha256)
    assert.deepEqual(info.context, resumeInfo.context)
    const identity = { documentId: info.context.documentId, revision: info.context.revision, sourceSha256: info.sourceSha256, scope: info.context.scope }
    const key = `native-editor-draft:v1:${JSON.stringify([identity.scope.database, identity.scope.companyId, identity.scope.userId, identity.scope.threadId, identity.documentId, identity.revision, identity.sourceSha256])}`
    restoredEnvelope = { version: 1, identity, operations: resumeOperations }
    await writeFile(join(output, 'restored-draft-envelope.json'), JSON.stringify({ key, value: restoredEnvelope }, null, 2))
    await page.addInitScript(({ key, value }) => {
      if (sessionStorage.getItem('docx-multilevel-restored')) return
      localStorage.setItem(key, JSON.stringify(value)); sessionStorage.setItem('docx-multilevel-restored', '1')
    }, { key, value: restoredEnvelope })
  }
  const cdp = await page.context().newCDPSession(page); await cdp.send('Network.enable'); await cdp.send('Network.setCacheDisabled', { cacheDisabled: true })
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400) httpErrors.push({ path, status: response.status() })
    if (sourceMode && response.url().startsWith(`http://127.0.0.1:${port + 1}/`) && /\.(?:js|ts|tsx|css)(?:[?]|$)/.test(response.url())) checks.push((async () => { assets.set(response.url(), sha(await response.body())) })().catch(error => assetErrors.push(String(error))))
    if (!sourceMode && path.startsWith('/reports/v1/editor/assets/') && /\.(js|css)$/.test(path)) checks.push((async () => {
      const bytes = await response.body(), disk = await readFile(join(staticRoot, path.slice('/reports/v1/editor/assets/'.length)))
      assert.equal(sha(bytes), sha(disk)); assets.set(path, sha(bytes))
    })().catch(error => assetErrors.push(String(error))))
  })
  const ready = () => page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 120000 })
  const editor = page.getByRole('textbox', { name: 'Word 文档编辑区', exact: true })
  const snapshot = () => editor.evaluate(node => node.editor.getJSON())
  const operations = () => page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')).flatMap(([, value]) => JSON.parse(value).operations ?? []))
  const waitOperations = count => page.waitForFunction(count => Object.entries(localStorage).some(([key, value]) => key.startsWith('native-editor-draft:') && (JSON.parse(value).operations ?? []).filter(op => op.kind === 'setParagraphCustomList').length === count), count)
  const trigger = () => page.locator('[data-source-action="list-multilevel-gallery"]')
  stage = 'open'; await page.goto(origin + info.openPath); await ready(); await editor.waitFor()
  let custom, staged, dialogFit
  if (resumeRoot) {
    stage = 'restored-draft'; staged = await operations(); assert.deepEqual(staged, resumeOperations)
    custom = await snapshot()
    assert.deepEqual(custom.content.slice(0, 2).map(node => node.type), ['docListItem', 'docListItem'])
    assert.equal(custom.content[0].attrs.numId, custom.content[1].attrs.numId)
    assert.equal(custom.content[0].attrs.nativeListDefinition.levels.length, 9)
    assert.equal(custom.content[0].attrs.nativeListDefinition.levels[0].lvlText, '第%1章')
    assert.equal(custom.content[0].attrs.nativeListDefinition.levels[0].start, 4)
    await writeFile(join(output, 'staged-operations.json'), JSON.stringify(staged, null, 2))
  } else if (libraryMode) {
    const baseline = await snapshot()
    const select = async (first, last = first) => {
      await editor.evaluate((node, { first, last }) => {
        const range = document.createRange(), children = node.children
        range.setStart(children[first], 0); range.setEnd(children[last], children[last].childNodes.length)
        const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range); node.focus()
      }, { first, last })
      await page.waitForFunction(({ first, last }) => {
        const e = document.querySelector('[role=textbox][aria-label="Word 文档编辑区"]').editor
        return e.state.selection.$from.index(0) === first && e.state.selection.$to.index(0) === last
      }, { first, last })
    }
    const gallery = kind => page.locator(`[data-source-action="list-${kind}-gallery"]`)
    const pick = async (dialog, index, value) => { await dialog.locator('.gs-dd-btn').nth(index).click(); await dialog.locator(`.gs-dd-item[data-value="${value}"]`).click() }
    stage = 'ordinary-library'; await select(0, 1); await gallery('bullets').click()
    assert.equal(await page.locator('[data-docx-list-preset]').count(), 6)
    await page.locator('[data-docx-list-preset="3"]').click(); await waitOperations(2)
    assert.deepEqual((await snapshot()).content.slice(0, 2).map(n => n.attrs.kind), ['bullet', 'bullet'])
    await editor.focus(); await page.keyboard.press('Control+z'); assert.deepEqual(await snapshot(), baseline)
    await page.keyboard.press('Control+Shift+z'); await waitOperations(2)
    await gallery('bullets').click(); assert((await page.locator('[data-docx-list-recent]').count()) >= 1)
    assert((await page.locator('[data-docx-list-document]').count()) >= 1)
    await page.locator('[data-docx-list-clear]').click(); assert.deepEqual(await snapshot(), baseline)
    stage = 'symbol-dialog'; await select(0); await gallery('bullets').click(); await page.locator('[data-docx-list-define]').click()
    const bullet = page.locator('.list-bullet-dialog'); await bullet.waitFor()
    assert.equal(await bullet.getByRole('tab', { name: '图片', exact: true }).isDisabled(), true)
    await page.setViewportSize({ width: 390, height: 844 }); await page.screenshot({ path: join(output, 'symbol-mobile.png'), fullPage: true })
    assert.equal(await bullet.evaluate(n => {const r=n.getBoundingClientRect();return r.left>=0 && r.right<=innerWidth && n.scrollWidth<=n.clientWidth+1}), true)
    await page.setViewportSize({ width: 1440, height: 1000 }); await bullet.getByRole('option', { name: '★', exact: true }).click()
    await pick(bullet, 0, 'Arial'); await bullet.locator('.modal-actions .primary').click(); await waitOperations(1)
    assert.equal((await snapshot()).content[0].attrs.nativeListDefinition.levels[0].lvlText, '★')
    stage = 'number-library'; await select(1); await gallery('numbering').click(); assert.equal(await page.locator('[data-docx-list-preset]').count(), 8)
    await page.locator('[data-docx-list-preset="2"]').click(); await waitOperations(2)
    assert.equal((await snapshot()).content[1].attrs.nativeListDefinition.levels[0].numFmt, 'upperRoman')
    stage = 'number-dialog'; await gallery('numbering').click(); await page.locator('[data-docx-list-define]').click()
    const number = page.locator('.list-number-dialog'); await number.waitFor()
    await page.setViewportSize({ width: 390, height: 844 }); await page.screenshot({ path: join(output, 'number-mobile.png'), fullPage: true })
    dialogFit = await number.evaluate(n => { const r=n.getBoundingClientRect();return { left:r.left,right:r.right,width:innerWidth,scrollWidth:n.scrollWidth,clientWidth:n.clientWidth } })
    assert(dialogFit.left>=0 && dialogFit.right<=dialogFit.width && dialogFit.scrollWidth<=dialogFit.clientWidth+1)
    await page.setViewportSize({ width: 1440, height: 1000 }); await pick(number, 0, 'upperRoman')
    await number.getByRole('textbox', { name: '编号格式', exact: true }).fill('第%1项')
    await number.locator('input[type=number]').first().fill('7'); await pick(number, 1, 'Arial')
    await number.locator('.list-dialog-font input[type=number]').fill('14')
    await number.locator('input[type=color]').evaluate(n => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(n, '#123abc'); n.dispatchEvent(new Event('input',{bubbles:true})); n.dispatchEvent(new Event('change',{bubbles:true})) })
    for (const checkbox of await number.locator('input[type=checkbox]').all()) await checkbox.check()
    await pick(number, 2, 'right'); await page.screenshot({ path: join(output, 'number-desktop.png'), fullPage: true })
    await number.locator('.modal-actions .primary').click(); await waitOperations(2)
    custom = await snapshot(); staged = await operations()
    assert.equal(custom.content[1].attrs.nativeListDefinition.levels[0].start, 7)
    await writeFile(join(output, 'staged-operations.json'), JSON.stringify(staged, null, 2))
  } else {
  const baseline = await snapshot()
  // 只设置浏览器原生选区，修改全部由真实功能区事件完成。
  await editor.evaluate(node => {
    const paragraphs = node.querySelectorAll(':scope > p'), range = document.createRange()
    range.setStart(paragraphs[0], 0); range.setEnd(paragraphs[1], paragraphs[1].childNodes.length)
    const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range); node.focus()
  })
  stage = 'preset'; await trigger().click(); assert.equal(await page.locator('[data-docx-list-preset]').count(), 8)
  await page.locator('[data-docx-list-preset="1"]').click(); await waitOperations(2)
  const selected = await snapshot(); assert.deepEqual(selected.content.slice(0, 2).map(node => node.type), ['docListItem', 'docListItem'])
  assert.equal(selected.content[0].attrs.numId, selected.content[1].attrs.numId)
  assert.equal(selected.content[0].attrs.nativeListDefinition.levels.length, 9)
  await editor.focus(); await page.keyboard.press('Control+z')
  assert.deepEqual(await snapshot(), baseline)
  await page.keyboard.press('Control+Shift+z'); await waitOperations(2)
  stage = 'custom-dialog'; await trigger().click(); await page.locator('[data-docx-list-define]').click()
  const dialog = page.locator('.list-define-modal')
  await dialog.waitFor(); await page.screenshot({ path: join(output, 'define-desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 }); await page.screenshot({ path: join(output, 'define-mobile.png'), fullPage: true })
  dialogFit = await dialog.evaluate(node => { const r = node.getBoundingClientRect(); return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, viewportWidth: innerWidth, viewportHeight: innerHeight } })
  assert(dialogFit.left >= 0 && dialogFit.right <= dialogFit.viewportWidth && dialogFit.top >= 0 && dialogFit.bottom <= dialogFit.viewportHeight)
  assert.equal(await dialog.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true, '多级列表字段不得横向裁切')
  await page.setViewportSize({ width: 1440, height: 1000 })
  await dialog.getByRole('textbox', { name: '编号格式', exact: true }).fill('第%1章')
  // 源对话框起始数字为 number input，输入后直接点确定，覆盖未失焦提交。
  await dialog.locator('input[type=number]').first().fill('4')
  await dialog.locator('.modal-actions .primary').click(); await waitOperations(2)
  custom = await snapshot(); staged = await operations()
  await writeFile(join(output, 'staged-operations.json'), JSON.stringify(staged, null, 2))
  assert.equal(custom.content[0].attrs.nativeListDefinition.levels[0].lvlText, '第%1章')
  assert.equal(custom.content[0].attrs.nativeListDefinition.levels[0].start, 4)
  }
  stage = 'reload'; await page.reload(); await ready(); await editor.waitFor(); assert.deepEqual(await snapshot(), custom)
  stage = 'save'
  const [response] = await Promise.all([page.waitForResponse(r => r.url().endsWith('/api/save') && r.request().method() === 'POST'), page.locator('[data-action="save"]').click()])
  const saved = await response.json()
  assert.equal(response.status(), 200, JSON.stringify(saved)); assert.equal(saved.revisionRegistered, true)
  assert.equal(saved.revision, info.context.revision + 1)
  assert.equal(saved.parentRevision, info.context.revision)
  const saveRequest = response.request().postDataJSON()
  assert.equal(saveRequest.expectedSha256, info.sourceSha256); assert.deepEqual(saveRequest.operations, staged)
  const link = page.getByRole('link', { name: '下载 Word', exact: true }); await link.waitFor()
  const downloading = page.waitForEvent('download'); await link.click(); const download = await downloading
  assert.equal(await download.failure(), null); const bytes = await readFile(await download.path())
  assert.equal(sha(bytes), saved.artifacts.word.sha256); await writeFile(join(output, 'downloaded.docx'), bytes)
  stage = 'reopen'; await page.goto(saved.editor.openUrl); await ready(); await editor.waitFor()
  const reopened = await snapshot(); assert.deepEqual(reopened.content.slice(0, 2).map(node => node.type), ['docListItem', 'docListItem'])
  if (libraryMode) assert.notEqual(reopened.content[0].attrs.numId, reopened.content[1].attrs.numId)
  else assert.equal(reopened.content[0].attrs.numId, reopened.content[1].attrs.numId)
  await page.screenshot({ path: join(output, 'reopened.png'), fullPage: true })
  const reopenedFile = await page.request.get(page.url() + '/api/file')
  assert.equal(reopenedFile.status(), 200); assert.equal(sha(await reopenedFile.body()), saved.artifacts.word.sha256)
  const state = await (await fetch(origin + '/__smoke__/state')).json()
  assert.equal(state.sourceSha256, info.sourceSha256); assert.equal(state.savedRevisions, 1)
  await Promise.all(checks); assert.deepEqual(errors, []); assert.deepEqual(consoleErrors, []); assert.deepEqual(httpErrors, []); assert.deepEqual(assetErrors, [])
  const verification = spawnSync(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/docx-multilevel-verify.py'), output, ...(libraryMode ? ['--libraries'] : [])], { encoding: 'utf8' })
  assert.equal(verification.status, 0, verification.stderr || verification.stdout)
  if (!sourceMode) assert.equal(sha(await readFile(join(staticRoot, '.vite/manifest.json'))), manifestSha256)
  for (const [file, identity] of Object.entries(sourceHashes)) assert.equal(sha(await readFile(join(frontend, 'src', file))), identity)
  assert.equal(sha(await readFile(nativeSource)), nativeSourceSha256)
  if (engineRoot) assert.equal(sha(await readFile(join(engineRoot, 'dist/edit-docx.mjs'))), engineSha256)
  const evidence = { ok: true, mode: sourceMode ? 'source-vite' : 'frozen-static', sourceHashes, libraryMode, resumedFrom: resumeRoot ?? null, restoredEnvelope, sourceSha256: info.sourceSha256, manifestSha256, engineSha256, nativeSourceSha256, assets: Object.fromEntries(assets), staged, saveRequest, saved, dialogFit, independent: JSON.parse(verification.stdout), errors, consoleErrors, httpErrors, assetErrors, requests: state.requests }
  await writeFile(join(output, 'evidence.json'), JSON.stringify(evidence, null, 2)); console.log(JSON.stringify({ ok: true, output, assets: assets.size, manifestSha256 }))
} catch (error) {
  await page?.screenshot({ path: join(output, 'failure.png'), fullPage: true }).catch(() => {})
  await writeFile(join(output, 'failure.json'), JSON.stringify({ stage, error: String(error), errors, consoleErrors, httpErrors }, null, 2)); throw error
} finally {
  await browser?.close(); server.kill(); await vite?.close(); await writeFile(join(output, 'server.log'), log)
  if (server.exitCode === null) await Promise.race([new Promise(resolve => server.once('exit', resolve)), delay(5000)])
  if (server.exitCode === null) server.kill('SIGKILL')
}
