import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// 独立组件烟测：真实 slides-main、Konva 画布和浏览器键盘；数据边界使用固定来源。
// 不构建或写入共享 static，也不声明业务后端或 PPTX 导出验收通过。
const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const output = resolve(process.env.PPTX_CLIPBOARD_EVIDENCE_DIR ?? '/dev/shm/office-pptx-clipboard-verification-20261113')
await mkdir(output, { recursive: true })
const base = '/reports/v1/editor/assets/'
const fixturePath = `${base}__clipboard-focus.html`
const html = `<!doctype html><html><head><meta charset="UTF-8"></head><body><button id="outside">编辑器外部按钮</button>
<script type="module">
import '${base}src/style.css';
import '${base}src/native.css';
import { createEditorShell } from '${base}src/shell.ts';
import { createSlidesEditorView } from '${base}src/slides-main.ts';
import { NativeDraft } from '${base}src/native-draft.ts';
const source = { revision: 1, sha256: 'a'.repeat(64), size: { cx: 9144000, cy: 5143500 }, slides: [{ slideIndex: 0, notesText: '', notesEditable: true, elements: [
  { id: 'a', name: '测试矩形', type: 'shape', text: '', editable: true, deletable: true, clipboardEditable: true, brushSource: { supported: true, text: { bold: true }, align: 'left' }, geometry: { x: 80, y: 80, width: 160, height: 80 } }
] }] };
const tree = { slides: [{ slideIndex: 0, widthPx: 960, heightPx: 540, background: { kind: 'solid', color: '#ffffff' }, nodes: [
  { id: 'a', sourceId: 'a', type: 'shape', box: { x: 80, y: 80, w: 160, h: 80, rotationDeg: 0 }, presetGeometry: 'rect', fill: { kind: 'solid', color: '#2864b4' } }
] }] };
const draft = new NativeDraft({ documentId: 'clipboard-focus', revision: 1, sourceSha256: source.sha256, scope: { database: 'fixture', companyId: 'c', userId: 'u', threadId: 't' } }, { getItem: () => null, setItem() {}, removeItem() {} });
const shell = createEditorShell(document.body.appendChild(document.createElement('main')), 'full', 'pptx');
document.querySelector('.report-app').dataset.nativeEditor = 'true';
const view = createSlidesEditorView(shell.editor, { native: true, draft, save: shell.save, download: shell.exportPptx, request: async path => path === 'deck' ? source : tree });
await view.ready;
window.clipboardApp = { draft, view, shell };
</script></body></html>`
const server = await createServer({
  root: frontend, configFile: resolve(frontend, 'vite.config.ts'),
  cacheDir: resolve(output, 'vite-cache'),
  optimizeDeps: { entries: [] },
  server: { host: '127.0.0.1', port: Number(process.env.PPTX_CLIPBOARD_PORT ?? 4293), strictPort: true },
  plugins: [{ name: 'pptx-clipboard-focus-fixture', configureServer(vite) {
    vite.middlewares.use((request, response, next) => {
      if (request.url?.split('?')[0] !== fixturePath) return next()
      response.setHeader('Content-Type', 'text/html; charset=utf-8'); response.end(html)
    })
  } }],
})
let browser, page
const evidence = { errors: [], steps: [] }
try {
  await server.listen()
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
  page.on('pageerror', error => evidence.errors.push(error.message))
  await page.route('**/api/preview.pdf*', route => route.fulfill({ contentType: 'text/html', body: '' }))
  await page.goto(`http://127.0.0.1:${server.config.server.port}${fixturePath}`)
  await page.waitForFunction(() => window.clipboardApp)
  const canvas = page.locator('.slides-canvas canvas').first()
  await canvas.waitFor()
  const operations = () => page.evaluate(() => structuredClone(window.clipboardApp.draft.operations))
  const clickObject = async (origin = 'body') => {
    if (origin === 'outside') await page.locator('#outside').click()
    else if (origin === 'input') await page.locator('#object-text').focus()
    else await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.blur())
    const bounds = await canvas.boundingBox()
    await canvas.click({ position: { x: bounds.width * 160 / 960, y: bounds.height * 120 / 540 } })
    return page.evaluate(() => ({ tag: document.activeElement?.tagName, className: document.activeElement?.className }))
  }
  evidence.steps.push({ name: 'click-object-from-body', focus: await clickObject() })
  await page.keyboard.press('Control+c'); await page.keyboard.press('Control+v')
  evidence.steps.push({ name: 'canvas-copy-paste', operations: await operations() })
  assert.deepEqual((await operations())[0]?.clipboardPastes, [{ sourceSlideIndex: 0, elementIds: ['a'], slideIndex: 0, dx: 20, dy: 20 }], '点击画布对象后 Ctrl+C/V 应粘贴来源对象')
  await page.locator('[data-source-action="onUndo"]').click()
  assert.deepEqual(await operations(), [])
  const protectionFailures = []
  const resetDraft = async () => {
    while (await page.evaluate(() => window.clipboardApp.draft.canUndo)) await page.locator('[data-source-action="onUndo"]').click()
    await clickObject()
  }
  for (const marker of [{ isComposing: true }, { keyCode: 229 }]) for (const key of ['c', 'x', 'v']) {
    await resetDraft()
    await page.locator('[data-command="copy"]').click(); await clickObject()
    const before = await operations()
    const prevented = await page.evaluate(({ marker, key }) => {
      const event = new KeyboardEvent('keydown', { key, ctrlKey: true, ...marker, bubbles: true, cancelable: true })
      document.activeElement.dispatchEvent(event)
      return event.defaultPrevented
    }, { marker, key })
    if (prevented || JSON.stringify(await operations()) !== JSON.stringify(before)) protectionFailures.push({ marker, key, prevented, operations: await operations() })
  }
  for (const key of ['c', 'x', 'v']) {
    await resetDraft()
    await page.locator('[data-command="copy"]').click(); await clickObject()
    const before = await operations()
    await page.evaluate(key => {
      const host = document.querySelector('.slides-canvas')
      host.dataset.keyConsumed = 'false'
      window.clipboardConsumer = event => { if (event.key.toLowerCase() === key) { host.dataset.keyConsumed = 'true'; event.preventDefault() } }
      host.addEventListener('keydown', window.clipboardConsumer)
    }, key)
    await page.keyboard.press(`Control+${key}`)
    const consumed = await page.evaluate(() => {
      const host = document.querySelector('.slides-canvas')
      host.removeEventListener('keydown', window.clipboardConsumer)
      return host.dataset.keyConsumed === 'true'
    })
    if (!consumed || JSON.stringify(await operations()) !== JSON.stringify(before)) protectionFailures.push({ targetConsumer: key, consumed, operations: await operations() })
  }
  await resetDraft()
  await page.locator('[data-command="formatBrush"]').click()
  await page.locator('#object-text').focus(); await page.keyboard.press('Escape')
  if (await page.locator('[data-command="formatBrush"]').getAttribute('aria-pressed') !== 'true') protectionFailures.push({ inputEscapeCancelledBrush: true })
  evidence.steps.push({ name: 'keyboard-protection-boundaries', failures: protectionFailures })
  assert.deepEqual(protectionFailures, [], '组合输入、目标消费事件和输入框 Escape 应保留目标事件所有权')
  await page.locator('[data-command="formatBrush"]').focus(); await page.keyboard.press('Escape')
  for (const modifier of ['Control', 'Meta']) for (const origin of ['body', 'outside', 'input']) {
    const focus = await clickObject(origin)
    assert.equal(focus.className, 'slides-canvas', `${origin} 点击对象后应将焦点交给画布`)
    await page.keyboard.press(`${modifier}+c`); await page.keyboard.press(`${modifier}+v`)
    assert.deepEqual((await operations())[0]?.clipboardPastes, [{ sourceSlideIndex: 0, elementIds: ['a'], slideIndex: 0, dx: 20, dy: 20 }])
    await page.locator('[data-source-action="onUndo"]').click()
    await clickObject(origin); await page.keyboard.press(`${modifier}+x`)
    assert.deepEqual((await operations())[0]?.deletions, [{ slideIndex: 0, elementId: 'a' }])
    await page.keyboard.press(`${modifier}+v`)
    assert.deepEqual((await operations())[0]?.clipboardPastes, [{ sourceSlideIndex: 0, elementIds: ['a'], slideIndex: 0, dx: 20, dy: 20 }])
    await page.locator('[data-source-action="onUndo"]').click()
    await page.locator('[data-source-action="onUndo"]').click()
    assert.deepEqual(await operations(), [])
    evidence.steps.push({ name: 'pointer-clipboard-lifecycle', modifier, origin, focus, passed: true })
  }
  await clickObject()
  await page.keyboard.press('Control+c')
  const bounds = await canvas.boundingBox()
  await canvas.click({ position: { x: bounds.width * .65, y: bounds.height * .65 } })
  await page.keyboard.press('Control+v')
  assert.deepEqual((await operations())[0]?.clipboardPastes, [{ sourceSlideIndex: 0, elementIds: ['a'], slideIndex: 0, dx: 20, dy: 20 }], '画布空白取消选择后仍应允许粘贴')
  await page.locator('[data-source-action="onUndo"]').click()
  evidence.steps.push({ name: 'blank-canvas-paste', passed: true })
  await clickObject()
  for (const selector of ['#object-text', '[data-notes-text]']) {
    const input = page.locator(selector)
    await input.focus()
    assert.equal(await input.evaluate(element => element === document.activeElement), true, `${selector} 应实际取得焦点`)
    const before = await operations()
    await page.keyboard.press('Control+c'); await page.keyboard.press('Control+x'); await page.keyboard.press('Control+v')
    const after = await operations()
    for (const field of ['clipboardPastes', 'deletions']) assert.deepEqual(after[0]?.[field] ?? [], before[0]?.[field] ?? [], `${selector} 的文字剪贴板不应改动对象 ${field}`)
    const composing = await input.evaluate(element => {
      element.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }))
      const event = new KeyboardEvent('keydown', { key: 'x', ctrlKey: true, isComposing: true, bubbles: true, cancelable: true })
      element.dispatchEvent(event)
      element.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true }))
      return event.defaultPrevented
    })
    assert.equal(composing, false, `${selector} 的组合输入快捷键不应被画布取消`)
    assert.deepEqual(await operations(), after)
    evidence.steps.push({ name: 'text-input-clipboard-boundary', selector, passed: true })
  }
  evidence.steps.push({ name: 'cut-input-and-composition-boundaries', passed: true })
  await page.locator('#outside').click()
  const beforeLocked = await operations()
  await page.evaluate(() => window.clipboardApp.draft.beginSave())
  await clickObject()
  await page.keyboard.press('Control+x'); await page.keyboard.press('Control+v')
  assert.deepEqual(await operations(), beforeLocked, '只读/保存锁定时点击画布和快捷键不应改动草稿')
  await page.evaluate(() => window.clipboardApp.draft.saveFailed())
  evidence.steps.push({ name: 'saving-lock-preserves-draft', passed: true })
  await clickObject()
  await page.screenshot({ path: resolve(output, 'clipboard-focus-active.png'), fullPage: true })
  await page.evaluate(() => window.clipboardApp.view.dispose())
  const disposed = await page.evaluate(() => {
    const event = new KeyboardEvent('keydown', { key: 'v', ctrlKey: true, bubbles: true, cancelable: true })
    document.activeElement.dispatchEvent(event)
    return event.defaultPrevented
  })
  assert.equal(disposed, false, '卸载编辑器后应移除对象剪贴板监听')
  assert.deepEqual(evidence.errors, [])
  evidence.passed = true
  console.log(JSON.stringify(evidence, null, 2))
} finally {
  if (page) await page.screenshot({ path: resolve(output, 'clipboard-focus.png'), fullPage: true })
  await writeFile(resolve(output, 'clipboard-focus.json'), JSON.stringify(evidence, null, 2))
  await browser?.close()
  await server.close()
}
