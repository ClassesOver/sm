import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { openPdfObjectNativeHost, openPdfObjectFromNativeRibbon, inspectPdfNativeRibbon } from './pdf-object-native-host.mjs'

// 使用真实 PDF 引擎来源模型、产品宿主和原生浏览器事件；不执行保存或发布。
const frontend = fileURLToPath(new URL('../', import.meta.url))
const directory = resolve(process.env.PDF_OBJECT_INTERACTION_EVIDENCE ?? '/dev/shm/office-pdf-object-dialog-interaction-20261113')
const source = JSON.parse(await readFile(process.env.PDF_OBJECT_SOURCE_JSON ?? resolve(directory, 'source.json'), 'utf8'))
const port = Number(process.env.PDF_OBJECT_INTERACTION_PORT ?? 4441)
const base = `http://127.0.0.1:${port}/reports/v1/editor/assets/`
const staticRoot = process.env.PDF_OBJECT_INTERACTION_STATIC_ROOT ? resolve(process.env.PDF_OBJECT_INTERACTION_STATIC_ROOT) : null
const nativeHost = !!staticRoot || process.env.PDF_OBJECT_INTERACTION_NATIVE_HOST === '1'
const sourceRoot = process.env.PDF_OBJECT_INTERACTION_SOURCE_ROOT ? resolve(process.env.PDF_OBJECT_INTERACTION_SOURCE_ROOT) : (staticRoot ? null : frontend)
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
const manifestSha256 = staticRoot ? sha(await readFile(resolve(staticRoot, '.vite/manifest.json'))) : null
if (process.env.PDF_OBJECT_INTERACTION_MANIFEST_SHA256) assert.equal(manifestSha256, process.env.PDF_OBJECT_INTERACTION_MANIFEST_SHA256)
const viewports = process.env.PDF_OBJECT_INTERACTION_VIEWPORTS?.split(',').map(value => value.split('x').map(Number)) ?? [[1440, 900], [768, 1024], [390, 844], [640, 360]]
const modes = [
  { mode: 'note-edit', title: '编辑便签正文', opener: '编辑便签', invalid: ['', '   '] },
  { mode: 'drawing-move', title: '移动待保存绘图', opener: '移动所选绘图', invalid: ['', '9999'] },
  { mode: 'image-resize', title: '缩放待保存图像', opener: '缩放所选图像', invalid: ['', '-50', '9999'] },
].filter(item => !process.env.PDF_OBJECT_INTERACTION_MODES || process.env.PDF_OBJECT_INTERACTION_MODES.split(',').includes(item.mode))
await mkdir(directory, { recursive: true })
let viteLog = '', browser
const results = [], errors = [], requests = [], assetChecks = [], assetErrors = [], assets = new Map(), ribbonResults = []
const server = staticRoot
  ? spawn('./node_modules/.bin/vite', ['preview', '--outDir', staticRoot, '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: ['ignore', 'pipe', 'pipe'] })
  : spawn(process.execPath, ['--input-type=module', '-e', `import {createServer} from 'vite'; const server=await createServer({cacheDir:${JSON.stringify(resolve(directory, 'vite-cache'))},server:{host:'127.0.0.1',port:${port},strictPort:true}}); await server.listen()`], { cwd: frontend, stdio: ['ignore', 'pipe', 'pipe'] })
server.stdout.on('data', data => { viteLog += data })
server.stderr.on('data', data => { viteLog += data })
const operations = page => page.evaluate(() => window.pdfObjectInteractionHost?.draft.operations ?? JSON.parse(localStorage.getItem(window.pdfObjectInteractionDraftKey)).operations)
const fieldValues = dialog => dialog.locator('input,textarea,select').evaluateAll(nodes => nodes.map(node => node.value))
async function dispatchKey(cdp, key, keyCode = key === 'Escape' ? 27 : 13) {
  for (const type of ['keyDown', 'keyUp']) await cdp.send('Input.dispatchKeyEvent', { type, key, code: key, windowsVirtualKeyCode: keyCode, nativeVirtualKeyCode: keyCode })
}
async function observe(page) {
  await page.evaluate(() => {
    const dialog = document.querySelector('dialog[open]')
    const state = { dialog, cancels: 0, closes: 0, events: [] }
    window.pdfObjectInteractionEvents = state
    for (const type of ['compositionstart', 'compositionupdate', 'compositionend', 'keydown']) dialog.addEventListener(type, event => {
      queueMicrotask(() => state.events.push({ type, key: event.key, keyCode: event.keyCode, isComposing: event.isComposing, data: event.data, trusted: event.isTrusted, prevented: event.defaultPrevented }))
    })
    dialog.addEventListener('cancel', () => { state.cancels++ })
    dialog.addEventListener('close', () => { state.closes++ })
  })
}
const recorded = page => page.evaluate(() => {
  const { cancels, closes, events, dialog } = window.pdfObjectInteractionEvents
  return { cancels, closes, events, open: dialog.open, connected: dialog.isConnected }
})
const waitClosed = page => page.waitForFunction(() => window.pdfObjectInteractionEvents.closes === 1)
const released = page => page.evaluate(() => {
  const event = new KeyboardEvent('keydown', { key: 'Escape', isComposing: true, bubbles: true, cancelable: true })
  window.pdfObjectInteractionEvents.dialog.dispatchEvent(event)
  return !event.defaultPrevented
})
async function checkGeometry(dialog, viewport) {
  const geometry = await dialog.evaluate(node => {
    const r = node.getBoundingClientRect()
    return { x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, overflow: node.scrollWidth > node.clientWidth + 1 }
  })
  assert.ok(geometry.x >= 0 && geometry.y >= 0 && geometry.right <= viewport.width + 1 && geometry.bottom <= viewport.height + 1 && !geometry.overflow, JSON.stringify(geometry))
  return geometry
}
async function checkFocus(page, control) {
  assert.ok(await control.evaluate(node => {
    const r = node.getBoundingClientRect()
    return document.activeElement === node && r.y >= 0 && r.bottom <= innerHeight && node.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2))
  }), '焦点控件应可见且可命中')
}

try {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (server.exitCode !== null) throw Error(viteLog)
    try { if ((await fetch(base)).ok) break } catch {}
    await delay(100)
  }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  for (const [width, height] of viewports) for (const item of modes) {
    const viewport = { width, height }, key = `${item.mode}-${width}x${height}`
    const page = await browser.newPage({ viewport })
    page.on('pageerror', error => errors.push({ key, error: error.message }))
    page.on('console', entry => { if (entry.type() === 'error') errors.push({ key, console: entry.text() }) })
    if (staticRoot) page.on('response', response => {
      const url = new URL(response.url()), prefix = '/reports/v1/editor/assets/'
      if (!url.pathname.startsWith(prefix) || !/\.(?:m?js|css)$/.test(url.pathname)) return
      assetChecks.push((async () => {
        const path = decodeURIComponent(url.pathname.slice(prefix.length))
        assert.ok(!path.split('/').includes('..'))
        assert.equal(response.status(), 200)
        const bytes = await response.body(), actual = sha(bytes)
        assert.equal(actual, sha(await readFile(resolve(staticRoot, path))), path)
        assets.set(path, { path, size: bytes.length, sha256: actual })
      })().catch(error => assetErrors.push(String(error))))
    })
    page.on('dialog', dialog => dialog.type() === 'beforeunload' ? dialog.accept() : dialog.dismiss())
    if (nativeHost) {
      await openPdfObjectNativeHost(page, { source, mode: item.mode, base, requests })
      if (item === modes[0]) {
        ribbonResults.push({ key, ...await inspectPdfNativeRibbon(page) })
        await page.screenshot({ path: resolve(directory, `ribbon-${width}x${height}.png`) })
      }
      await openPdfObjectFromNativeRibbon(page, item.mode)
    } else {
      await page.route('**/pdf-object-fixture.html?*', route => route.fulfill({ contentType: 'text/html', body: '<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><script>window.officePdfFixtureContent=' + JSON.stringify(source) + '</script><script type="module" src="./smoke/pdf-object-dialog-interaction-fixture.mjs"></script></body></html>' }))
      await page.goto(`${base}pdf-object-fixture.html?mode=${item.mode}`)
      await page.waitForSelector('html[data-object-interaction-ready="true"]', { timeout: 60000 })
    }
    const dialog = page.getByRole('dialog', { name: item.title, exact: true })
    const close = dialog.getByRole('button', { name: '关闭' + item.title, exact: true })
    // 自动准备入口只做夹具引导，此后全部使用 Playwright 真实点击产品入口。
    await close.click(); await dialog.waitFor({ state: 'detached' })
    const opener = item.mode === 'note-edit' ? page.locator('.pdf-pending-note').getByRole('button', { name: item.opener, exact: true }) : page.getByRole('button', { name: item.opener, exact: true })
    const initial = await operations(page)
    await opener.click(); await dialog.waitFor()
    const field = dialog.locator('input,textarea').first()
    const originalValues = await fieldValues(dialog)
    await checkFocus(page, field)
    const geometry = await checkGeometry(dialog, viewport)
    const controls = dialog.locator('button,input,textarea,select')
    const count = await controls.count()
    // DOM 顺序：标题关闭、首字段、其余字段、取消、应用。
    for (let step = 1; step <= count; step++) {
      await page.keyboard.press('Tab')
      await checkFocus(page, controls.nth((1 + step) % count))
    }
    for (let step = 1; step <= count; step++) {
      await page.keyboard.press('Shift+Tab')
      await checkFocus(page, controls.nth((1 - step + count) % count))
    }
    await page.screenshot({ path: resolve(directory, `${key}-controls.png`) })
    const invalid = []
    for (const value of item.invalid) {
      await field.fill(value)
      await dialog.getByRole('button', { name: /^应用/ }).click()
      assert.equal(await dialog.count(), 1)
      assert.deepEqual(await operations(page), initial)
      const issue = await field.evaluate(node => node.validationMessage) || await dialog.locator('[role="alert"]').textContent()
      assert.ok(issue, '无效值必须有可读原因')
      invalid.push({ value, issue })
    }
    await page.screenshot({ path: resolve(directory, `${key}-invalid.png`) })
    await field.fill(item.mode === 'note-edit' ? '尚未提交的正文' : '12')
    await dialog.getByRole('button', { name: '取消', exact: true }).click()
    await dialog.waitFor({ state: 'detached' })
    assert.deepEqual(await operations(page), initial)
    await checkFocus(page, opener)
    await opener.click(); await dialog.waitFor()
    assert.deepEqual(await fieldValues(dialog), originalValues)
    await observe(page)
    const cdp = await page.context().newCDPSession(page)
    let composition = null
    if (item.mode === 'note-edit') {
      await field.fill('未提交的输入法正文')
      await cdp.send('Input.imeSetComposition', { text: '组合输入', selectionStart: 4, selectionEnd: 4 })
      const beforeEscape = await field.inputValue()
      await dispatchKey(cdp, 'Escape')
      composition = await recorded(page)
      assert.equal(composition.open, true)
      assert.equal(composition.cancels, 0)
      assert.ok(composition.events.some(event => event.type === 'compositionstart' && event.trusted))
      assert.ok(composition.events.some(event => event.key === 'Escape' && event.trusted && event.isComposing && event.prevented))
      assert.equal(await field.inputValue(), beforeEscape)
      await checkFocus(page, field)
      await page.screenshot({ path: resolve(directory, `${key}-ime-escape.png`) })
      await cdp.send('Input.imeSetComposition', { text: '', selectionStart: 0, selectionEnd: 0 })
      // Chromium 的 CDP 清空组合输入会给结束事件 trusted=false；原样保留，不冒充物理输入法。
      assert.ok((await recorded(page)).events.some(event => event.type === 'compositionend'), JSON.stringify(await recorded(page)))
    } else {
      // 真实229对照：既有浏览器行为未触发关闭/提交，不额外拦截。
      await dispatchKey(cdp, item.mode === 'drawing-move' ? 'Escape' : 'Enter', 229)
      assert.equal((await recorded(page)).open, true)
      assert.deepEqual(await operations(page), initial)
    }
    await page.keyboard.press('Escape')
    await dialog.waitFor({ state: 'detached' })
    await waitClosed(page)
    const normalEscape = await recorded(page)
    assert.equal(normalEscape.cancels, 1)
    assert.equal(normalEscape.closes, 1)
    assert.ok(await released(page))
    assert.deepEqual(await operations(page), initial)
    await checkFocus(page, opener)
    await opener.click(); await dialog.waitFor(); await observe(page)
    await close.click(); await dialog.waitFor({ state: 'detached' })
    await waitClosed(page)
    assert.ok(await released(page))
    assert.deepEqual(await operations(page), initial)
    await checkFocus(page, opener)
    await opener.click(); await dialog.waitFor()
    // 同一任务中替换窗口，使旧窗口 close 事件晚于新窗口 showModal。
    const replacing = await opener.evaluate(async node => {
      const old = document.querySelector('dialog[open]')
      window.pdfObjectReplacementOld = old
      old.close(); node.click()
      await Promise.resolve()
      const next = [...document.querySelectorAll('dialog[open]')].find(dialog => dialog !== old)
      return !!next && next.contains(document.activeElement)
    })
    assert.ok(replacing)
    await page.waitForFunction(() => !window.pdfObjectReplacementOld.isConnected)
    assert.ok(await dialog.evaluate(node => node.contains(document.activeElement)))
    await observe(page)
    // 文本域 Enter 是换行；数字字段 Enter 使用原生表单提交，空值保持窗口。
    await field.fill(item.mode === 'note-edit' ? '正文' : '')
    await page.keyboard.press('Enter')
    assert.equal(await dialog.count(), 1)
    if (item.mode === 'note-edit') assert.ok((await field.inputValue()).includes('\n'))
    assert.deepEqual(await operations(page), initial)
    let appliedOperations = null
    if (process.env.PDF_OBJECT_INTERACTION_APPLY === '1') {
      const expected = structuredClone(initial)
      if (item.mode === 'note-edit') {
        await field.fill(' 应用后的正文 ')
        expected[0].text = '应用后的正文'
        await dialog.getByRole('button', { name: '应用便签修改', exact: true }).click()
      } else {
        await field.fill(item.mode === 'drawing-move' ? '12' : '50')
        expected[0].rect = item.mode === 'drawing-move' ? [84, 500, 192, 560] : [72, 500, 126, 530]
        await page.keyboard.press('Enter')
      }
      await dialog.waitFor({ state: 'detached' })
      await waitClosed(page)
      appliedOperations = await operations(page)
      assert.deepEqual(appliedOperations, expected)
      assert.ok(await released(page))
      if (item.mode !== 'note-edit') await page.locator('.pdf-pending-drawings-panel [data-pdf-pending-drawing] button').click()
      await opener.click(); await dialog.waitFor(); await observe(page)
    }
    // abort 关闭旧窗口时，焦点保持在已打开的新窗口中。
    await page.evaluate(() => {
      const next = document.body.appendChild(document.createElement('dialog'))
      next.dataset.disposeFocusSentinel = ''
      const input = next.appendChild(document.createElement('input'))
      next.showModal(); input.focus()
      if (window.pdfObjectInteractionHost) window.pdfObjectInteractionHost.view.dispose()
      else window.dispatchEvent(new PageTransitionEvent('pagehide'))
    })
    await dialog.waitFor({ state: 'detached' })
    // 原生 close 为异步事件；DOM移除不能代替生命周期回执。
    await waitClosed(page)
    const disposal = await recorded(page)
    const listenerReleasedAfterDispose = await released(page)
    const abortKeepsNewFocus = await page.locator('[data-dispose-focus-sentinel] input').evaluate(node => document.activeElement === node)
    results.push({ key, viewport, geometry, tabSteps: count * 2, invalid, cancelReopensOriginalValues: true, normalEscape, composition, titleCloseReleasedListener: true, replacementKeepsNewFocus: true, enterKeepsInvalidOrMultilineDraft: true, appliedOperations, disposal: { ...disposal, listenerReleasedAfterDispose, abortKeepsNewFocus } })
    assert.equal(disposal.open, false, '宿主销毁必须关闭便签或绘图窗口')
    assert.equal(disposal.closes, 1)
    assert.ok(listenerReleasedAfterDispose, '宿主销毁后必须释放组合输入监听')
    assert.ok(abortKeepsNewFocus, '旧窗口的 abort 关闭不得抢走新窗口焦点')
    await page.close()
  }
  assert.deepEqual(errors, [])
  await Promise.all(assetChecks)
  assert.deepEqual(assetErrors, [])
  assert.ok(requests.every(request => ['context', 'file', 'preview'].includes(request.operation)), '零保存/发布/导出请求')
  if (staticRoot) {
    assert.equal(sha(await readFile(resolve(staticRoot, '.vite/manifest.json'))), manifestSha256)
    const manifest = JSON.parse(await readFile(resolve(staticRoot, '.vite/manifest.json'), 'utf8'))
    const pdf = Object.values(manifest).find(entry => entry.name === 'pdf-main' && entry.isDynamicEntry)
    assert.ok(pdf && assets.has(pdf.file), '必须加载冻结构建的实际PDF模块')
    assert.ok([...assets.keys()].some(path => path.endsWith('.css')))
  }
  const hashes = {}
  const sourceFiles = ['src/pdf-main.ts', 'src/pdf-object-dialog.ts', 'src/focus-trap.ts', 'src/pdf-ribbon.ts']
  if (!nativeHost) sourceFiles.push('smoke/office-pdf-host-fixture.mjs')
  if (sourceRoot) for (const file of sourceFiles) hashes[file] = sha(await readFile(resolve(sourceRoot, file)))
  await writeFile(resolve(directory, 'interaction-results.json'), JSON.stringify({ scope: 'Chromium trusted CDP composition; physical OS IME not tested; no save/publication', nativeHost, build: { staticRoot, manifestSha256, sourceRoot }, lifecycle: nativeHost ? 'native pagehide → session.dispose → view.dispose' : 'component view.dispose', hashes, results, ribbonResults, requests, assets: [...assets.values()], assetErrors, errors }, null, 2))
  console.log(JSON.stringify({ cases: results.length, errors, disposal: results.map(({ key, disposal }) => ({ key, ...disposal })), hashes }, null, 2))
} catch (error) {
  await writeFile(resolve(directory, 'interaction-failure.json'), JSON.stringify({ error: String(error), stack: error.stack, nativeHost, build: { staticRoot, manifestSha256 }, results, ribbonResults, requests, assets: [...assets.values()], assetErrors, errors }, null, 2))
  throw error
} finally {
  await browser?.close()
  server.kill('SIGTERM')
  await writeFile(resolve(directory, 'interaction-vite.log'), viteLog)
}
