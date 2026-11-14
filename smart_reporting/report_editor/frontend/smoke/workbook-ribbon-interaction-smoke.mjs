// 真正挂载当前功能区与样式；view/chart是显式组件夹具，不执行文件保存或工作簿修改。
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { createServer } from 'node:http'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'esbuild'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const directory = process.env.WORKBOOK_RIBBON_INTERACTION_DIRECTORY
assert(directory, '显式指定 WORKBOOK_RIBBON_INTERACTION_DIRECTORY')
await mkdir(directory, { recursive: true })
const source = `
import { mountWorkbookRibbon } from './src/workbook-ribbon';
import './src/style.css'; import './src/office-theme.css'; import './src/workbook.css';
const state={editable:true,protected:false,chart:true},commands=[];
const ribbon=mountWorkbookRibbon(document.querySelector('#ribbon'),command=>commands.push(command),{
 editable:()=>state.editable,rotation:()=>0,
 chart:()=>state.chart?{isPie:false,canLabel:true,seriesCount:2,categoryCount:2}:null,
 protection:()=>({sheet:{protected:state.protected},workbook:{locked:false}})
});
window.ribbonProbe={commands,set:next=>{Object.assign(state,next);ribbon.refreshState()},dispose:()=>ribbon.dispose()};
`
const built = await build({ absWorkingDir: frontend, stdin: { contents: source, resolveDir: frontend, sourcefile: 'ribbon-interaction.ts', loader: 'ts' }, bundle: true, format: 'esm', outfile: join(directory, 'component.js'), loader: { '.svg': 'dataurl', '.png': 'dataurl', '.woff': 'dataurl', '.woff2': 'dataurl' }, metafile: true })
await writeFile(join(directory, 'metafile.json'), JSON.stringify(built.metafile, null, 2))
const sources = await Promise.all(['src/workbook-ribbon.ts', 'src/workbook.css', 'src/office-theme.css'].map(async file => ({ file, sha256: createHash('sha256').update(await readFile(join(frontend, file))).digest('hex') })))
const server = createServer(async (request, response) => {
  const file = request.url === '/component.js' ? 'component.js' : request.url === '/component.css' ? 'component.css' : null
  response.setHeader('content-type', file ? file.endsWith('.js') ? 'text/javascript' : 'text/css' : 'text/html')
  response.end(file ? await readFile(join(directory, file)) : '<!doctype html><html lang="zh-CN"><head><link rel="stylesheet" href="/component.css"></head><body class="editor-format-xlsx" style="margin:0"><div id="ribbon" class="workbook-ribbon-host"></div><script type="module" src="/component.js"></script></body></html>')
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const browser = await chromium.launch({ headless: true })
const errors = [], cases = [], failures = []
const page = await browser.newPage()
page.on('pageerror', error => errors.push(error.message))
const check = (condition, message) => { if (!condition) failures.push(message) }
try {
  for (const [width, height] of [[1440, 900], [320, 640], [640, 360], [390, 320]]) {
    await page.setViewportSize({ width, height })
    await page.goto(`http://127.0.0.1:${server.address().port}`)
    await page.waitForFunction(() => window.ribbonProbe)
    const row = { width, height, protections: [], menus: [], ordinary: [] }
    for (const protection of ['composing', 'legacy229', 'consumed']) for (const key of ['ArrowLeft', 'ArrowRight', 'Home', 'End']) {
      await page.getByRole('tab', { name: '图表设计', exact: true }).click()
      const result = await page.evaluate(({ protection, key }) => {
        const selected = document.querySelector('[role="tab"][aria-selected="true"]')
        selected.focus()
        const control = document.querySelector('[data-ribbon-menu="chart-layout"]')
        const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, isComposing: protection === 'composing', keyCode: protection === 'legacy229' ? 229 : 0 })
        if (protection === 'consumed') event.preventDefault()
        selected.dispatchEvent(event)
        return { sameTab: document.querySelector('[role="tab"][aria-selected="true"]') === selected, sameFocus: document.activeElement === selected, sameControl: document.querySelector('[data-ribbon-menu="chart-layout"]') === control, defaultPrevented: event.defaultPrevented }
      }, { protection, key })
      row.protections.push({ protection, key, ...result })
      check(result.sameTab && result.sameFocus && result.sameControl && result.defaultPrevented === (protection === 'consumed'), `${width}x${height} ${protection}/${key}: ${JSON.stringify(result)}`)
    }
    for (const [key, expected] of [['ArrowLeft', 'View'], ['ArrowRight', 'File'], ['Home', 'File'], ['End', 'Chart Design']]) {
      await page.getByRole('tab', { name: '图表设计', exact: true }).click()
      await page.keyboard.press(key)
      const selected = await page.locator('[role="tab"][aria-selected="true"]').getAttribute('data-ribbon-tab')
      row.ordinary.push({ key, expected, selected })
      check(selected === expected, `${width}x${height} ordinary ${key}: ${selected}`)
    }
    await page.getByRole('tab', { name: '图表设计', exact: true }).click()
    await page.keyboard.press('Tab')
    check(await page.getByRole('combobox', { name: '快速布局', exact: true }).evaluate(element => element === document.activeElement), `${width}x${height} Tab must enter quick layout`)
    for (const [name, value] of [['快速布局', 'chart-layout:2'], ['更改颜色', 'chart-colors:green']]) {
      const select = page.getByRole('combobox', { name, exact: true })
      await select.scrollIntoViewIfNeeded()
      const geometry = await select.evaluate(element => {
        const icon = element.parentElement.querySelector('svg'), r = element.getBoundingClientRect(), i = icon.getBoundingClientRect()
        return { iconWidth: i.width, iconHeight: i.height, height: r.height, hit: document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2) === element }
      })
      row.menus.push({ name, ...geometry })
      check(geometry.iconWidth === 18 && geometry.iconHeight === 18 && geometry.hit, `${width}x${height} ${name}: ${JSON.stringify(geometry)}`)
      await select.click(); await page.keyboard.press('Escape')
      await select.selectOption(value)
      check(await select.inputValue() === '', `${width}x${height} ${name} should reset after command`)
    }
    for (const [state, reason] of [[{ editable: false }, '不可编辑'], [{ editable: true, protected: true }, '保护'], [{ protected: false, chart: false }, '选择要操作的图表']]) {
      await page.evaluate(state => window.ribbonProbe.set(state), state)
      for (const name of ['快速布局', '更改颜色']) {
        const menu = page.getByRole('combobox', { name, exact: true })
        check(await menu.isDisabled(), `${width}x${height} ${name} should be disabled: ${JSON.stringify(state)}`)
        check((await menu.getAttribute('aria-description')).includes(reason), `${width}x${height} ${name} missing reason`)
      }
    }
    await page.evaluate(() => window.ribbonProbe.set({ editable: true, protected: false, chart: true }))
    row.commands = await page.evaluate(() => window.ribbonProbe.commands)
    check(JSON.stringify(row.commands) === JSON.stringify(['chart-layout:2', 'chart-colors:green']), `${width}x${height} unexpected commands: ${row.commands}`)
    await page.locator('.workbook-ribbon-body').evaluate(element => { element.scrollLeft = 0 })
    await page.screenshot({ path: join(directory, `ribbon-${width}x${height}.png`) })
    await page.evaluate(() => window.ribbonProbe.dispose())
    check(await page.locator('#ribbon').textContent() === '', `${width}x${height} dispose left controls`)
    cases.push(row)
  }
  check(errors.length === 0, `page errors: ${errors}`)
  const evidence = { ok: !failures.length, scope: 'Actual ribbon component and CSS; explicit chart/view providers, no workbook save or production authorization claim. Composition and legacy events are synthetic browser protocol checks.', browserVersion: browser.version(), sources, cases, errors, failures }
  await writeFile(join(directory, 'evidence.json'), JSON.stringify(evidence, null, 2))
  console.log(JSON.stringify({ ok: evidence.ok, cases: cases.length, failures }))
  if (!evidence.ok) process.exitCode = 1
} finally {
  await browser.close()
  await new Promise(resolve => server.close(resolve))
}
