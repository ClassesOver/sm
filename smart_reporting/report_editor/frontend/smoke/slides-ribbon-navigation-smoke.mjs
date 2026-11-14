// 实际产品 Ribbon 和样式；上下文夹具不执行保存、导出或业务编辑。
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { createServer } from 'node:http'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'esbuild'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const phase = process.env.SLIDES_RIBBON_PHASE ?? 'green'
const directory = join(process.env.SLIDES_RIBBON_DIRECTORY ?? '/dev/shm/office-slides-ribbon-navigation-20261113', phase)
await mkdir(directory, { recursive: true })
const source = `import {createSlidesNativeRibbon} from './src/slides-native-ribbon';
import './src/style.css';import './src/native.css';import './src/slides.css';
const actions=[],ribbon=createSlidesNativeRibbon(document.querySelector('#ribbon'),{onAction:(...args)=>actions.push(args)});
window.ribbonProbe={ribbon,actions};`
const built = await build({ absWorkingDir: frontend, stdin: { contents: source, resolveDir: frontend, sourcefile: 'slides-ribbon-navigation.ts', loader: 'ts' }, bundle: true, format: 'esm', outfile: join(directory, 'component.js'), loader: { '.svg': 'dataurl', '.png': 'dataurl', '.woff': 'dataurl', '.woff2': 'dataurl' }, metafile: true })
await writeFile(join(directory, 'metafile.json'), JSON.stringify(built.metafile, null, 2))
const sources = await Promise.all(['src/slides-native-ribbon.ts', 'src/office-ribbon-scroll.ts', 'src/office-theme.css', 'src/slides.css'].map(async file => ({ file, sha256: createHash('sha256').update(await readFile(join(frontend, file))).digest('hex') })))
const server = createServer(async (request, response) => {
  const file = request.url === '/component.js' ? 'component.js' : request.url === '/component.css' ? 'component.css' : null
  response.setHeader('content-type', file ? file.endsWith('.js') ? 'text/javascript' : 'text/css' : 'text/html')
  response.end(file ? await readFile(join(directory, file)) : '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/component.css"></head><body class="editor-format-pptx" style="margin:0"><main id="ribbon"></main><button id="outside">外部焦点</button><script type="module" src="/component.js"></script></body></html>')
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const browser = await chromium.launch({ headless: true }), page = await browser.newPage()
const evidence = { phase, scope: 'Actual createSlidesNativeRibbon + product CSS, fixture context changes; no backend/save/export. IME/229/consumed events are synthetic; ordinary keys use Chromium keyboard.', browserVersion: browser.version(), sources, cases: [], errors: [], failures: [] }
page.on('pageerror', error => evidence.errors.push(error.message))
const check = (value, label) => { if (!value) evidence.failures.push(label) }
const tab = id => page.locator(`[data-ribbon-tab="${id}"]`)
const state = () => page.evaluate(() => {
  const selected = document.querySelector('[role=tab][aria-selected=true]'), focused = document.activeElement
  return { selected: selected?.dataset.ribbonTab, focus: focused?.dataset.ribbonTab ?? focused?.id, roving: [...document.querySelectorAll('[role=tab]')].filter(tab => tab.tabIndex === 0).map(tab => tab.dataset.ribbonTab), panels: [...document.querySelectorAll('[role=tabpanel]')].filter(panel => !panel.hidden).map(panel => panel.id), controls: selected?.getAttribute('aria-controls') }
})
const coherent = (s, id) => s.selected === id && s.focus === id && JSON.stringify(s.roving) === JSON.stringify([id]) && JSON.stringify(s.panels) === JSON.stringify([s.controls])
try {
  for (const [width, height] of phase === 'red' ? [[1440, 900]] : [[1440, 900], [320, 640], [640, 360], [390, 320]]) {
    await page.setViewportSize({ width, height }); await page.goto(`http://127.0.0.1:${server.address().port}`); await page.waitForFunction(() => window.ribbonProbe)
    const row = { width, height, protections: [], ordinary: [], contexts: [] }
    for (const protection of ['composing', 'legacy229', 'consumed']) for (const key of ['ArrowLeft', 'ArrowRight', 'Home', 'End']) {
      const initial = key === 'Home' ? 'view' : 'home'; await tab(initial).click(); await tab(initial).focus()
      const result = await tab(initial).evaluate((node, { key, protection }) => {
        const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, isComposing: protection === 'composing', keyCode: protection === 'legacy229' ? 229 : 0 })
        if (protection === 'consumed') event.preventDefault()
        node.dispatchEvent(event); return { prevented: event.defaultPrevented, focus: document.activeElement === node }
      }, { key, protection })
      const after = await state(); row.protections.push({ protection, key, ...result, after })
      check(coherent(after, initial) && result.prevented === (protection === 'consumed'), `${width}x${height} ${protection} ${key}`)
    }
    await tab('insert').evaluate(node => { node.disabled = true }); await tab('draw').evaluate(node => { node.hidden = true })
    for (const [from, key, expected] of [['home', 'ArrowRight', 'design'], ['design', 'ArrowLeft', 'home'], ['file', 'ArrowLeft', 'view'], ['view', 'ArrowRight', 'file'], ['home', 'Home', 'file'], ['home', 'End', 'view']]) {
      await tab(from).click(); await tab(from).focus(); await page.keyboard.press(key)
      const after = await state(); row.ordinary.push({ from, key, expected, after }); check(coherent(after, expected), `${width}x${height} ordinary ${from} ${key}`)
    }
    await tab('insert').evaluate(node => { node.disabled = false }); await tab('draw').evaluate(node => { node.hidden = false })
    for (const [context, id] of [['table', 'tableDesign'], ['chart', 'chartDesign'], ['picture', 'pictureFormat'], ['shape', 'shapeFormat'], ['model3d', 'model3dFormat']]) {
      for (const position of ['tab', 'panel', 'outside']) {
        await page.evaluate(context => window.ribbonProbe.ribbon.setContext(context), context)
        await tab('home').click(); await tab('home').focus(); await page.keyboard.press('End'); check(coherent(await state(), id), `${width}x${height} enter ${context}`)
        if (position === 'panel') await page.locator(`[data-ribbon-panel="${id}"]`).evaluate(panel => { const button = document.createElement('button'); button.id = 'panel-fixture'; button.textContent = '焦点夹具'; panel.append(button); button.focus() })
        if (position === 'outside') await page.locator('#outside').focus()
        await page.evaluate(() => window.ribbonProbe.ribbon.setContext(null))
        const after = await state(), hidden = await tab(id).isHidden(), panelHidden = await page.locator(`[data-ribbon-panel="${id}"]`).isHidden()
        row.contexts.push({ context, position, hidden, panelHidden, after }); check(after.selected === 'home' && after.focus === (position === 'outside' ? 'outside' : 'home') && hidden && panelHidden, `${width}x${height} remove ${context} ${position}`)
        await page.locator('#panel-fixture').evaluateAll(nodes => nodes.forEach(node => node.remove()))
      }
    }
    await page.evaluate(() => window.ribbonProbe.ribbon.setContext('table')); await tab('tableDesign').click(); await tab('tableDesign').focus()
    await page.evaluate(() => window.ribbonProbe.ribbon.setContext('table')); check(coherent(await state(), 'tableDesign'), `${width}x${height} unchanged context`)
    await page.evaluate(() => window.ribbonProbe.ribbon.setContext('picture')); check(coherent(await state(), 'home'), `${width}x${height} replacement context`)
    await page.keyboard.press('End'); check(coherent(await state(), 'pictureFormat'), `${width}x${height} replacement reachable`)
    await tab('view').click(); await tab('view').focus(); await page.evaluate(() => window.ribbonProbe.ribbon.setContext('shape')); check(coherent(await state(), 'view'), `${width}x${height} ordinary context preserve`)
    await page.keyboard.press('End')
    const geometry = await tab('shapeFormat').evaluate(node => { const r = node.getBoundingClientRect(), owner = node.closest('[role=tablist]').getBoundingClientRect(); return { x: r.x, right: r.right, y: r.y, bottom: r.bottom, ownerX: owner.x, ownerRight: owner.right, hit: node.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)) } })
    row.geometry = geometry; check(geometry.hit && geometry.x >= 0 && geometry.right <= width + 1 && geometry.bottom <= height, `${width}x${height} focused contextual tab visibility`)
    await page.keyboard.press('Tab'); const panelFocus = await page.evaluate(() => document.activeElement?.closest('[role=tabpanel]')?.dataset.ribbonPanel); row.tabPanelFocus = panelFocus; check(panelFocus === 'shapeFormat', `${width}x${height} Tab enters active panel`)
    await page.keyboard.press('Shift+Tab'); check(coherent(await state(), 'shapeFormat'), `${width}x${height} Shift+Tab returns single active tab`)
    check(await page.evaluate(() => window.ribbonProbe.actions.length) === 0, `${width}x${height} navigation must not edit`)
    await page.screenshot({ path: join(directory, `ribbon-${width}x${height}.png`) }); evidence.cases.push(row)
  }
  check(evidence.errors.length === 0, `page errors ${evidence.errors}`)
  evidence.ok = !evidence.failures.length
  await writeFile(join(directory, 'evidence.json'), JSON.stringify(evidence, null, 2))
  console.log(JSON.stringify({ ok: evidence.ok, cases: evidence.cases.length, failures: evidence.failures })); if (!evidence.ok) process.exitCode = 1
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)) }
