import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { join, resolve } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const output = resolve(process.env.OFFICE_NAVIGATION_OUTPUT ?? '/tmp/office-docx-navigation-20261112')
const port = Number(process.env.OFFICE_NAVIGATION_PORT ?? 4298), base = `http://127.0.0.1:${port}/reports/v1/editor/assets/`
const modes = process.env.OFFICE_NAVIGATION_CASES?.split(',') ?? ['headings','empty','search','no-results','pages','pages-unsupported','page-number','page-number-error']
const viewports = process.env.OFFICE_NAVIGATION_VIEWPORTS?.split(',').map(value => value.split('x').map(Number)) ?? [[1440,900],[768,1024],[390,844],[320,640],[640,360],[390,320]]
const html = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><script type="module" src="./smoke/office-docx-navigation-fixture.mjs"></script></body></html>'
const server = spawn('./node_modules/.bin/vite',['--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:frontend,stdio:'pipe'})
let browser, log = ''
server.stdout.on('data',data => {log += data}); server.stderr.on('data',data => {log += data})
const evidence = { kind:'product-component-explicit-pagination-fixture', cases:[], failures:[], pageErrors:[] }
try {
  await mkdir(output,{recursive:true})
  for(let attempt=0;;attempt++) {
    if(server.exitCode !== null) throw Error(log)
    try { if((await fetch(base)).ok) break } catch {}
    if(attempt>120) throw Error(log)
    await delay(250)
  }
  browser = await chromium.launch({headless:true})
  for(const mode of modes) {
    const page = await browser.newPage()
    page.on('pageerror',error => evidence.pageErrors.push({mode,message:error.message}))
    await page.route('**/office-docx-navigation-fixture.html?*',route => route.fulfill({contentType:'text/html',body:html}))
    for(const [width,height] of viewports) {
      await page.setViewportSize({width,height}); await page.goto(`${base}office-docx-navigation-fixture.html?mode=${mode}`)
      await page.waitForSelector('html[data-fixture-ready=true]')
      const before = await page.evaluate(() => JSON.stringify(window.officeNavigationEditor.getJSON()))
      const opener = page.getByRole('button',{name:'打开设置',exact:true}); await opener.click()
      const modal = mode.startsWith('page-number')
      const surface = page.locator(modal ? '[role=dialog]' : '[data-docx-navigation]')
      await surface.waitFor({state:'visible'})
      const check = (condition,message) => { if(!condition) evidence.failures.push(`${mode} ${width}×${height}: ${message}`) }
      check(await surface.evaluate(node => node.contains(document.activeElement)), '打开后未将焦点移入设置界面')
      if(mode === 'search' || mode === 'no-results') await surface.locator('[data-navigation-query]').fill(mode === 'search' ? '经营数据' : '不存在的匹配文字')
      if(mode.startsWith('pages')) {
        await surface.locator('[data-navigation-tab=pages]').click()
        await page.waitForFunction(() => !document.querySelector('[data-navigation-pages] [role=status]')?.textContent.includes('正在测量'))
      }
      if(mode === 'page-number-error') {
        await surface.getByLabel('起始页码',{exact:true}).fill('9007199254740992')
        await surface.locator('form').evaluate(node => node.requestSubmit())
        check(await surface.getByRole('alert').count() > 0 && !!await surface.getByRole('alert').textContent(), '无效起始页码缺少可见原因')
      }
      await page.evaluate(() => document.fonts.ready)
      const measurement = await surface.evaluate(node => {
        const card = node.querySelector('.modal-card') ?? node, rect = card.getBoundingClientRect()
        const controls = [...card.querySelectorAll('input,select,button')].filter(el => {const b=el.getBoundingClientRect();return b.width>0&&b.height>0&&getComputedStyle(el).visibility!=='hidden'})
        const list = card.querySelector('.docx-navigation-results:not([hidden]),.docx-navigation-tree:not([hidden]),.docx-navigation-pages:not([hidden])')
        const active = card.querySelector('.docx-navigation-heading.on'), input = card.querySelector('input'), select = card.querySelector('select')
        let desktopLabel = true
        if(select) {const range=document.createRange();range.selectNodeContents(select.closest('label').firstChild);desktopLabel=range.getBoundingClientRect().right<select.getBoundingClientRect().left}
        return {x:rect.x,right:rect.right,y:rect.y,bottom:rect.bottom,width:rect.width,font:getComputedStyle(card).fontFamily,overflow:card.scrollWidth>card.clientWidth+1,
          controls:controls.map(el => {const b=el.getBoundingClientRect();return {text:el.textContent,label:el.getAttribute('aria-label'),x:b.x,right:b.right,width:b.width,height:b.height,font:getComputedStyle(el).fontFamily}}),
          activeColor:active?getComputedStyle(active).color:null, inputWidth:input?.getBoundingClientRect().width, desktopLabel,
          list:list?{count:list.querySelectorAll('button').length,height:list.getBoundingClientRect().height,overflow:getComputedStyle(list).overflowY}:null,
          status:[...card.querySelectorAll('[role=status]')].map(el=>el.textContent)}
      })
      check(measurement.x >= -1 && measurement.right <= width+1 && !measurement.overflow,'界面横向溢出')
      check(measurement.y >= -1 && measurement.bottom <= height+1,'界面超出视口高度')
      check(measurement.font.includes('Noto Sans'),'面板字体未沿用Office主题')
      check(measurement.controls.every(control => control.height >= 28 && control.font.includes('Noto Sans')),'控件尺寸或字体未沿用PC主题')
      check(measurement.controls.every(control => control.x >= measurement.x-1 && control.right <= measurement.right+1),'控件被横向裁切')
      if(!modal) check(measurement.width >= 220 && measurement.width <= 320,'导航宽度不足以阅读或挤占桌面画布')
      if(measurement.activeColor) check(measurement.activeColor === 'rgb(11, 79, 138)','当前标题未沿用主题色')
      if(!modal && measurement.inputWidth > 0) check(measurement.inputWidth >= 120,'搜索输入框过窄')
      if(modal && width >= 1000) check(measurement.desktopLabel,'PC页码设置未使用左标签右字段')
      await page.screenshot({path:join(output,`${mode}-${width}x${height}.png`)})
      if(modal) {
        await surface.locator('button,input,select').last().focus(); await page.keyboard.press('Tab')
        check(await surface.evaluate(node=>node.contains(document.activeElement)),'Tab离开模态窗口')
        check(await surface.evaluate(()=>parseFloat(getComputedStyle(document.activeElement).outlineWidth)>=2),'缺少键盘焦点环')
      } else {
        const last = surface.locator('.docx-navigation-tree:not([hidden]) [data-navigation-heading],.docx-navigation-results:not([hidden]) [data-navigation-search-result],.docx-navigation-pages:not([hidden]) [data-navigation-page]').last()
        if(await last.count()) {
          await last.scrollIntoViewIfNeeded()
          check(await last.evaluate(node=>{const r=node.getBoundingClientRect();return node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}),'长列表末项无法滚动访问')
          await last.focus()
        } else await surface.locator('[data-navigation-action=close]').focus()
      }
      await page.keyboard.press('Escape')
      check(!await surface.isVisible(),'Escape未关闭设置界面')
      check(await opener.evaluate(node=>document.activeElement===node),'关闭未恢复入口焦点')
      check(await page.evaluate(()=>JSON.stringify(window.officeNavigationEditor.getJSON())) === before,'导航检查修改正文')
      check(await page.evaluate(()=>window.officeNavigationCommits.length) === 0,'布局检查写入页码设置')
      evidence.cases.push({mode,width,height,measurement})
    }
    await page.close()
  }
} finally {
  await browser?.close(); server.kill('SIGTERM')
  await writeFile(join(output,'evidence.json'),JSON.stringify(evidence,null,2))
}
assert.deepEqual(evidence.pageErrors,[]); assert.deepEqual(evidence.failures,[])
console.log(JSON.stringify({output,cases:evidence.cases.length,failures:evidence.failures}))
