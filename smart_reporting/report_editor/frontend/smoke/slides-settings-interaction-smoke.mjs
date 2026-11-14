import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// 真实 slides-main 对话框和浏览器交互；固定来源/渲染树，不保存或导出业务文件。
const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const phase = process.env.SLIDES_SETTINGS_PHASE ?? 'green'
const output = resolve(process.env.SLIDES_SETTINGS_DIRECTORY ?? '/dev/shm/office-slides-settings-interaction-20261113', phase)
await mkdir(output, { recursive: true })
const base = '/reports/v1/editor/assets/', fixturePath = `${base}__slides-settings.html`
const sourceFiles = ['src/focus-trap.ts', 'src/slides-size-dialog.ts', 'src/slides-settings-dialog.ts', 'src/slides-main.ts', 'src/slides.css']
const hashes = async () => Object.fromEntries(await Promise.all(sourceFiles.map(async name => [name, createHash('sha256').update(await readFile(resolve(frontend, name))).digest('hex')])))
const sourceSha256 = await hashes()
const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>
<script type="module">
import '${base}src/style.css';import '${base}src/native.css';
import {createEditorShell} from '${base}src/shell.ts';
import {createSlidesEditorView} from '${base}src/slides-main.ts';
import {NativeDraft} from '${base}src/native-draft.ts';
const source={revision:1,sha256:'a'.repeat(64),size:{cx:9144123,cy:6858000},slides:[{slideIndex:0,headerFooter:{footer:null,slideNum:false,date:null},elements:[{id:'a',name:'正文',type:'text',text:'设置交互来源',editable:true,deletable:true,geometry:{x:80,y:80,width:300,height:80}}]}]};
const tree={slides:[{slideIndex:0,widthPx:source.size.cx/9525,heightPx:720,background:{kind:'solid',color:'#ffffff'},nodes:[]}]};
const draft=new NativeDraft({documentId:'settings-interaction',revision:1,sourceSha256:source.sha256,scope:{database:'fixture',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem(){},removeItem(){}});
const shell=createEditorShell(document.body.appendChild(document.createElement('main')),'full','pptx');document.querySelector('.report-app').dataset.nativeEditor='true';
const requests=[];const view=createSlidesEditorView(shell.editor,{native:true,draft,save:shell.save,download:shell.exportPptx,request:async(path)=>{requests.push(path);if(path==='deck')return source;if(path==='render-tree')return tree;throw Error('夹具禁止保存或未知请求：'+path)}});
await view.ready;window.settingsApp={draft,view,shell,requests};
</script></body></html>`
const server = await createServer({ root: frontend, configFile: resolve(frontend, 'vite.config.ts'), cacheDir: resolve(output, 'vite-cache'), optimizeDeps: { entries: [], noDiscovery: true, include: ['lucide', 'react', 'react/jsx-dev-runtime', 'react/jsx-runtime', 'react-dom', 'react-dom/client', 'react-dom/server', 'react-konva', 'konva'] }, server: { host: '127.0.0.1', port: 0 },
  plugins: [{ name: 'slides-settings-interaction-fixture', configureServer(vite) { vite.middlewares.use((request, response, next) => {
    if (request.url?.split('?')[0] !== fixturePath) return next()
    response.setHeader('Content-Type', 'text/html; charset=utf-8'); response.end(html)
  }) } }],
})
let browser, page
const evidence = { phase, sourceSha256, scope: 'actual product source dialogs and Chromium; fixture deck/render-tree; no backend save/export', cases: [], failures: [], errors: [] }
const specs = [
  { command: 'customSlideSize', tab: 'design', title: '自定义幻灯片尺寸', field: '[aria-label="幻灯片宽度"]', edited: '42', first: '[aria-label="关闭自定义幻灯片尺寸"]', last: '[data-command="applyCustomSlideSize"]' },
  { command: 'insertTable', tab: 'insert', title: '插入表格', field: '[name="cols"]', edited: '7', first: '[data-settings-close]', last: '[value="ok"]' },
  { command: 'addSection', tab: 'home', title: '新增节', field: '[name="name"]', edited: '未提交的节', first: '[data-settings-close]', last: '[value="ok"]' },
  { command: 'headerFooter', tab: 'insert', title: '页眉和页脚', field: '[name="footer"]', edited: '未提交页脚', first: '[data-settings-close]', last: '[value="ok"]' },
]
try {
  await server.listen(); browser = await chromium.launch({ headless: true })
  page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  page.on('pageerror', error => evidence.errors.push(error.message))
  await page.route('**/api/preview.pdf*', route => route.fulfill({ status: 204, body: '' }))
  const openPage = async () => { await page.goto(`http://127.0.0.1:${server.httpServer.address().port}${fixturePath}`); await page.waitForFunction(() => window.settingsApp) }
  const draft = () => page.evaluate(() => structuredClone(window.settingsApp.draft.operations))
  const check = (condition, label) => { if (!condition) evidence.failures.push(label) }
  await openPage()
  const viewports = phase === 'red' ? [[1440, 900]] : [[1440, 900], [320, 640], [640, 360], [390, 320]]
  for (const [width, height] of viewports) for (const spec of specs) {
    await page.setViewportSize({ width, height }); await page.locator(`[data-ribbon-tab="${spec.tab}"]`).click()
    const opener = page.locator(`[data-command="${spec.command}"]`); await opener.click()
    const dialog = page.getByRole('dialog', { name: spec.title, exact: true }); await dialog.waitFor()
    const initial = await dialog.locator(spec.field).inputValue(), before = await draft()
    const record = { command: spec.command, width, height, protections: [], controls: [] }
    const first = dialog.locator(spec.first), last = dialog.locator(spec.last)
    for (const protection of ['composition', 'legacy229', 'consumed']) for (const reverse of [false, true]) {
      const boundary = reverse ? first : last; await boundary.focus()
      const state = await boundary.evaluate((node, { protection, reverse }) => {
        const event = new KeyboardEvent('keydown', { key: 'Tab', shiftKey: reverse, bubbles: true, cancelable: true, isComposing: protection === 'composition', keyCode: protection === 'legacy229' ? 229 : 0 })
        if (protection === 'consumed') event.preventDefault()
        node.dispatchEvent(event)
        return { protection, reverse, focused: document.activeElement === node, prevented: event.defaultPrevented }
      }, { protection, reverse })
      record.protections.push(state); check(state.focused && state.prevented === (protection === 'consumed'), `${spec.command} ${width}x${height} ${protection} reverse=${reverse}`)
    }
    await last.focus(); await page.keyboard.press('Tab'); assert.equal(await first.evaluate(node => document.activeElement === node), true)
    await page.keyboard.press('Shift+Tab'); assert.equal(await last.evaluate(node => document.activeElement === node), true)
    for (const control of await dialog.locator('button:visible,input:visible,select:visible,[tabindex="0"]:visible').all()) {
      await control.focus(); await control.scrollIntoViewIfNeeded()
      const state = await control.evaluate(node => { const r = node.getBoundingClientRect(); return { label: node.getAttribute('aria-label') || node.getAttribute('name') || node.textContent, hit: node.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)), focused: document.activeElement === node, x: r.x, y: r.y, right: r.right, bottom: r.bottom } })
      record.controls.push(state); check(state.hit && state.focused && state.x >= 0 && state.y >= 0 && state.right <= width + 1 && state.bottom <= height + 1, `${spec.command} ${width}x${height} control ${state.label}`)
    }
    await dialog.locator(spec.field).fill(spec.edited)
    const protectedEscape = await dialog.locator(spec.field).evaluate(node => {
      const records = []
      for (const mode of ['composition', 'legacy229', 'consumed']) { const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true, isComposing: mode === 'composition', keyCode: mode === 'legacy229' ? 229 : 0 }); if (mode === 'consumed') event.preventDefault(); node.dispatchEvent(event); records.push({ mode, connected: node.isConnected, focused: document.activeElement === node, prevented: event.defaultPrevented }) }
      return records
    })
    assert.ok(protectedEscape.every(row => row.connected && row.focused && row.prevented === (row.mode === 'consumed'))); record.protectedEscape = protectedEscape
    await page.keyboard.press('Escape'); await dialog.waitFor({ state: 'detached' }); assert.equal(await opener.evaluate(node => document.activeElement === node), true); assert.deepEqual(await draft(), before)
    await opener.click(); assert.equal(await dialog.locator(spec.field).inputValue(), initial)
    const cancel = dialog.getByRole('button', { name: '取消', exact: true }); await cancel.click(); await dialog.waitFor({ state: 'detached' }); assert.deepEqual(await draft(), before)
    await opener.click(); await first.click(); await dialog.waitFor({ state: 'detached' }); assert.deepEqual(await draft(), before)
    record.cancelDiscarded = true; record.normalTabLoop = true; record.openerRestored = true
    if (phase !== 'red') {
      await opener.click()
      if (spec.command === 'customSlideSize') {
        const w = dialog.getByLabel('幻灯片宽度', { exact: true }), h = dialog.getByLabel('幻灯片高度', { exact: true }), unit = dialog.getByLabel('尺寸单位', { exact: true })
        await w.fill(''); await last.click(); assert.equal(await dialog.getByRole('alert').isVisible(), true); assert.deepEqual(await draft(), before)
        await unit.selectOption('in'); assert.equal(await unit.inputValue(), 'cm'); assert.equal(await w.inputValue(), '')
        await w.fill('25,4'); await unit.selectOption('mm'); assert.equal(await w.inputValue(), '254'); assert.equal(await h.inputValue(), '190.5'); assert.equal(await dialog.getByRole('alert').isVisible(), false)
        await w.fill('300'); await unit.selectOption('cm'); assert.equal(await w.inputValue(), '30'); assert.equal(await h.inputValue(), '19.05')
        await last.focus(); await page.keyboard.press('Tab'); assert.equal(await first.evaluate(node => document.activeElement === node), true)
        record.units = { invalidChangeRolledBack: true, commaCmToMm: '254', mmToCm: '30', untouchedHeightEmu: 6858000 }
      } else if (spec.command !== 'headerFooter') {
        await dialog.locator(spec.field).fill(spec.command === 'insertTable' ? '0' : ''); await last.click(); assert.equal(await dialog.getByRole('alert').isVisible(), true); assert.deepEqual(await draft(), before)
        await dialog.getByRole('alert').focus(); await page.keyboard.press('Tab'); assert.equal(await dialog.getByRole('button', { name: '取消', exact: true }).evaluate(node => document.activeElement === node), true)
        await dialog.locator(spec.field).fill(spec.command === 'insertTable' ? '3' : '新节')
        record.validationFocus = 'visible error participates in Tab order; edited input retained'
      }
      await page.screenshot({ path: resolve(output, `${spec.command}-${width}x${height}.png`) })
      await last.click(); await dialog.waitFor({ state: 'detached' }); assert.equal(await opener.evaluate(node => document.activeElement === node), true)
      const after = await draft(); assert.equal(after.length, before.length + 1); record.confirmedDraft = after
      if (spec.command === 'customSlideSize') {
        assert.equal(after[0].kind, 'editSlides'); assert.deepEqual(after[0].slideSize, { cx: 10800000, cy: 6858000 })
      }
      assert.equal(await page.evaluate(() => window.settingsApp.requests.some(path => path === 'save')), false)
      await openPage()
    }
    evidence.cases.push(record)
  }
  assert.deepEqual(await hashes(), sourceSha256, '受测源码在本次浏览器运行期间变化')
  assert.deepEqual(evidence.errors, []); assert.deepEqual(evidence.failures, [], '组合态与控件命中验收失败'); evidence.ok = true
} catch (error) {
  evidence.error = String(error); await page?.screenshot({ path: resolve(output, 'failure.png'), fullPage: true }).catch(() => {}); throw error
} finally {
  await writeFile(resolve(output, 'result.json'), JSON.stringify(evidence, null, 2)); await browser?.close(); await server.close()
}
