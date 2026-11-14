import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { chromium } from 'playwright'
import { createSlidesPanelsNativeFixture } from './slides-panels-native-fixture.mjs'

// 真实 slides-main 属性窗格与浏览器交互；固定来源/渲染树，不保存或导出业务文件。
const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const phase = process.env.SLIDES_PANELS_PHASE ?? 'green'
const staticRoot = process.env.SLIDES_PANELS_STATIC ? resolve(process.env.SLIDES_PANELS_STATIC) : undefined
const output = resolve(process.env.SLIDES_PANELS_DIRECTORY ?? '/dev/shm/office-pptx-panels-review-20261113', phase)
await mkdir(output, { recursive: true })
const base = '/reports/v1/editor/assets/', fixturePath = `${base}__slides-panels.html`
const sourceFiles = ['src/slides-geometry-pane.ts', 'src/slides-shape-format-pane.tsx', 'src/slides-chart-format-pane.tsx', 'src/slides-main.ts', 'src/slides-geometry-pane.css', 'src/slides-shape-format-pane.css']
const hashes = async () => Object.fromEntries(await Promise.all(sourceFiles.map(async name => [name, createHash('sha256').update(await readFile(resolve(frontend, name))).digest('hex')])))
const sourceSha256 = staticRoot ? undefined : await hashes()
const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>
<script type="module">
import '${base}src/style.css';import '${base}src/native.css';
import {createEditorShell} from '${base}src/shell.ts';
import {createSlidesEditorView} from '${base}src/slides-main.ts';
import {NativeDraft} from '${base}src/native-draft.ts';
const source={revision:1,sha256:'a'.repeat(64),size:{cx:9144000,cy:5143500},slides:[{slideIndex:0,headerFooter:{footer:null,slideNum:false,date:null},elements:['a','b'].map((id,index)=>({id,name:'对象 '+id,type:'text',text:'属性窗格 '+id,editable:true,deletable:true,arrangeEditable:true,brushSource:{supported:true,shape:{fill:'#123456',stroke:{color:'#345678',widthPt:2.25}}},geometry:{x:80,y:80+index*100,width:index?200:192,height:80}}))}]};
const tree={slides:[{slideIndex:0,widthPx:source.size.cx/9525,heightPx:540,background:{kind:'solid',color:'#ffffff'},nodes:[]}]};
const draft=new NativeDraft({documentId:'panels-interaction',revision:1,sourceSha256:source.sha256,scope:{database:'fixture',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem(){},removeItem(){}});
const shell=createEditorShell(document.body.appendChild(document.createElement('main')),'full','pptx');document.querySelector('.report-app').dataset.nativeEditor='true';
const requests=[];const view=createSlidesEditorView(shell.editor,{native:true,draft,save:shell.save,download:shell.exportPptx,request:async(path)=>{requests.push(path);if(path==='deck')return source;if(path==='render-tree')return tree;throw Error('夹具禁止保存或未知请求：'+path)}});
await view.ready;window.panelsApp={draft,view,shell,requests};
</script></body></html>`
const nativeFixture = staticRoot ? await createSlidesPanelsNativeFixture({ frontend, staticRoot, expectedManifest: process.env.SLIDES_PANELS_EXPECTED_MANIFEST_SHA256,
  sourcePath: resolve(process.env.SLIDES_PANELS_SOURCE ?? '/dev/shm/office-parallel-ui-verification-20261113/pptx-clipboard-built/source.pptx') }) : undefined
const server = nativeFixture?.server ?? await createServer({ root: frontend, configFile: resolve(frontend, 'vite.config.ts'), cacheDir: resolve(output, 'vite-cache'), optimizeDeps: { entries: [], noDiscovery: true, include: ['lucide', 'react', 'react/jsx-dev-runtime', 'react/jsx-runtime', 'react-dom', 'react-dom/client', 'react-dom/server', 'react-konva', 'konva'] }, server: { host: '127.0.0.1', port: 0 },
  plugins: [{ name: 'slides-panels-interaction-fixture', configureServer(vite) { vite.middlewares.use((request, response, next) => {
    if (request.url?.split('?')[0] !== fixturePath) return next()
    response.setHeader('Content-Type', 'text/html; charset=utf-8'); response.end(html)
  }) } }],
})
let browser, page
const evidence = { phase, sourceSha256, scope: nativeFixture ? 'frozen native PPTX host; fixture authorization/context, reused real PPTX + Python/Node inspect/render; no save/download' : 'actual slides-main source host and geometry/shape panes in Chromium; explicit source/render-tree fixture, no backend save/export', cases: [], failures: [], errors: [] }

try {
  await server.listen(); browser = await chromium.launch({ headless: true })
  page = await browser.newPage({ viewport: { width: 1440, height: 900 } }); page.on('pageerror', error => evidence.errors.push(error.message))
  if (nativeFixture) await nativeFixture.setup(page)
  else await page.route('**/api/preview.pdf*', route => route.fulfill({ status: 204, body: '' }))
  const open = async () => {
    if (nativeFixture) await nativeFixture.open(page)
    else { await page.goto(`http://127.0.0.1:${server.httpServer.address().port}${fixturePath}`); await page.waitForFunction(() => window.panelsApp) }
    await page.evaluate(() => document.fonts.ready)
  }
  const draft = () => nativeFixture ? nativeFixture.draft(page) : page.evaluate(() => structuredClone(window.panelsApp.draft.operations))
  const width = () => page.locator('[data-geometry="width"]')
  const check = (value, label) => { if (!value) evidence.failures.push(label) }
  for (const [w, h] of phase === 'red' ? [[1440, 900]] : [[1440, 900], [320, 640], [640, 360], [390, 320]]) {
    await page.setViewportSize({ width: w, height: h })
    for (const mode of ['partial', 'invalid']) {
      await open()
      const color = page.locator('[data-chart-format-well="shape-fill"]'); await color.scrollIntoViewIfNeeded(); await color.press('ArrowDown')
      const before = await width().inputValue(), start = Date.now()
      await page.locator('[role="gridcell"][data-pos="0-5"]').click()
      await width().fill(mode === 'partial' ? '7.' : 'invalid')
      if (mode === 'invalid') await width().press('Enter')
      const enteredInMs = Date.now() - start
      // 先证实输入发生在200ms提交前，避免把调度不稳定当产品RED。
      assert.ok(enteredInMs < 180, `fixture typing too slow: ${enteredInMs}ms`)
      await page.waitForTimeout(350)
      const result = await width().evaluate(node => ({ value: node.value, focused: document.activeElement === node, invalid: node.getAttribute('aria-invalid'), message: node.ownerDocument.getElementById(node.getAttribute('aria-describedby'))?.textContent }))
      const operations = await draft(), changes = operations[0] ?? {}
      const row = { width: w, height: h, mode, before, enteredInMs, afterShapeCommit: result, operations }
      check(changes.shapeStyles?.[0]?.fill === '#E97132', `${w}x${h} ${mode} shape commit did not run`)
      check(result.value === (mode === 'partial' ? '7.' : 'invalid') && result.focused, `${w}x${h} ${mode} geometry draft/focus was replaced by unrelated shape commit`)
      check(!changes.edits?.length, `${w}x${h} ${mode} geometry was committed before confirmation`)
      if (mode === 'invalid') check(result.invalid === 'true' && result.message.includes('完整'), `${w}x${h} invalid geometry error silently cleared`)
      await width().scrollIntoViewIfNeeded()
      const geometry = await width().evaluate(node => { const r = node.getBoundingClientRect(), style = getComputedStyle(node); return { x: r.x, right: r.right, y: r.y, bottom: r.bottom, hit: node === document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2), ring: style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) >= 2 } })
      row.geometry = geometry; check(geometry.hit && geometry.x >= 0 && geometry.right <= w + 1 && geometry.y >= 0 && geometry.bottom <= h + 1, `${w}x${h} ${mode} field unreachable`)
      await page.screenshot({ path: resolve(output, `geometry-${mode}-${w}x${h}.png`) })
      if (phase !== 'red') {
        if (mode === 'invalid') {
          const status = page.locator('#' + await width().getAttribute('aria-describedby')); await status.focus(); await status.scrollIntoViewIfNeeded()
          row.errorStatus = await status.evaluate(node => { const r = node.getBoundingClientRect(); return { text: node.textContent, focused: node === document.activeElement, x: r.x, y: r.y, right: r.right, bottom: r.bottom, hit: node.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)) } })
          check(row.errorStatus.focused && row.errorStatus.hit && row.errorStatus.x >= 0 && row.errorStatus.right <= w + 1 && row.errorStatus.y >= 0 && row.errorStatus.bottom <= h + 1, `${w}x${h} error reason unreachable`)
          await page.screenshot({ path: resolve(output, `geometry-status-${w}x${h}.png`) })
        }
        await width().fill('7.62'); await width().press('Enter')
        const after = (await draft())[0]; check(Math.abs(after.edits?.[0]?.geometry?.width - 288) < .001, `${w}x${h} ${mode} corrected dimension not committed`)
        await page.locator('#object-select').focus(); await page.locator('#object-select').selectOption(nativeFixture?.otherTarget ?? 'b')
        row.switched = await width().inputValue(); check(row.switched === (nativeFixture?.otherWidth ?? '5.29'), `${w}x${h} ${mode} draft leaked into other object`)
        check(await page.locator('#object-select').evaluate(node => document.activeElement === node), `${w}x${h} ${mode} selection focus lost`)
      }
      row.requests = nativeFixture ? [...nativeFixture.requests] : await page.evaluate(() => window.panelsApp.requests)
      check(row.requests.every(path => ['deck', 'render-tree', 'context', 'file', 'preview', 'preview.pdf'].includes(path)), `${w}x${h} unexpected write request`)
      evidence.cases.push(row)
    }
  }
  if (nativeFixture) evidence.native = await nativeFixture.finish()
  check(evidence.errors.length === 0, `page errors ${evidence.errors}`); evidence.ok = !evidence.failures.length
  await writeFile(resolve(output, 'evidence.json'), JSON.stringify(evidence, null, 2)); console.log(JSON.stringify({ ok: evidence.ok, cases: evidence.cases.length, failures: evidence.failures })); if (!evidence.ok) process.exitCode = 1
} finally { await browser?.close(); await server.close() }
