import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { join, resolve } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const directory = resolve(process.env.OFFICE_REFERENCE_OUTPUT ?? '/tmp/office-docx-reference-20261112')
const port = Number(process.env.OFFICE_REFERENCE_PORT ?? 4293)
const base = `http://127.0.0.1:${port}/reports/v1/editor/assets/`
const modes = process.env.OFFICE_REFERENCE_CASES?.split(',') ?? ['link', 'link-error', 'link-readonly', 'bookmarks-empty', 'bookmarks-long', 'bookmarks-readonly', 'cross-reference-long', 'cross-reference-readonly', 'cross-reference-empty', 'cross-reference-error']
const viewports=(process.env.OFFICE_REFERENCE_VIEWPORTS??'1440x900,768x1024,390x844,320x640,640x360,390x320').split(',').map(value=>value.split('x').map(Number))
const html = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><script type="module" src="./smoke/office-docx-reference-fixture.mjs"></script></body></html>'
const server = spawn('./node_modules/.bin/vite', ['--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'pipe' })
let log = '', browser
server.stdout.on('data', data => { log += data }); server.stderr.on('data', data => { log += data })
const evidence = { kind: 'product-component-fixture', failures: [], pageErrors: [], cases: [], bookmarkKeyboard: [], crossReferenceKeyboard: [], accessibility: [] }
try {
  await mkdir(directory, { recursive: true })
  for (let attempt = 0; ; attempt++) {
    if (server.exitCode !== null) throw new Error(log)
    try { if ((await fetch(base)).ok) break } catch {}
    if (attempt > 120) throw new Error(log)
    await delay(250)
  }
  browser = await chromium.launch({ headless: true })
  for (const mode of modes) {
    const context = await browser.newContext()
    const page = await context.newPage()
    page.on('pageerror', error => evidence.pageErrors.push({ mode, message: error.message }))
    await page.route('**/office-docx-reference-fixture.html?*', route => route.fulfill({ contentType: 'text/html', body: html }))
    for (const [width, height] of viewports) {
      await page.setViewportSize({ width, height })
      await page.goto(`${base}office-docx-reference-fixture.html?mode=${mode}`)
      await page.waitForSelector('html[data-fixture-ready=true]')
      const before = await page.evaluate(() => window.officeReferenceEditor.getJSON())
      await page.getByRole('button', { name: '打开设置', exact: true }).click()
      const isLink = mode.startsWith('link')
      const surface = page.locator(isLink ? '[role=dialog]:visible' : '.docx-comment-panel:visible')
      await surface.waitFor()
      if (mode === 'link-error') {
        await surface.getByLabel('Link URL', { exact: true }).fill('javascript:alert(1)')
        await surface.locator('[data-command=applyLink]').click()
        await surface.getByRole('alert').waitFor()
      }
      if (mode === 'link-readonly') await page.evaluate(() => window.officeReferenceReadonly())
      if(mode==='cross-reference-error'){
        await surface.locator('[data-cross-reference-insert]:enabled').first().click()
        assert.equal(await surface.getByRole('status').textContent(),'请把光标放在普通正文或标题段落中')
      }
      await page.evaluate(() => document.fonts.ready)
      const check = (condition, message) => { if (!condition) evidence.failures.push(`${mode} ${width}×${height}: ${message}`) }
      const measurement = await surface.evaluate(element => {
        const card = element.querySelector('.modal-card') ?? element, rect = card.getBoundingClientRect()
        const visible = node => node.getClientRects().length && getComputedStyle(node).visibility !== 'hidden'
        const fields = [...card.querySelectorAll('input,select,textarea')].filter(visible)
        const buttons = [...card.querySelectorAll('button')].filter(visible)
        const list = card.querySelector('ul'), input = fields[0], label = input?.closest('label')
        const labelText = label && [...label.childNodes].find(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim())
        const range = document.createRange(); if (labelText) range.selectNodeContents(labelText)
        return { rect: { x: rect.x, right: rect.right, y: rect.y, bottom: rect.bottom, width: rect.width },
          overflow: card.scrollWidth > card.clientWidth + 1,
          fields: fields.map(node => ({ width: node.getBoundingClientRect().width, height: node.getBoundingClientRect().height, font: getComputedStyle(node).fontFamily, disabled: node.disabled })),
          buttons: buttons.map(node => ({ height: node.getBoundingClientRect().height, font: getComputedStyle(node).fontFamily })),
          desktopLabel: !labelText || range.getBoundingClientRect().right < input.getBoundingClientRect().left,
          list: list ? { height: list.getBoundingClientRect().height, top: list.getBoundingClientRect().top, overflow: getComputedStyle(list).overflowY, count: list.children.length } : null,
          headingTop: card.querySelector('h2')?.getBoundingClientRect().top,
          fieldsTop:card.querySelector('.docx-reference-fields')?.getBoundingClientRect().top,
        }
      })
      check(!measurement.overflow && measurement.rect.x >= -1 && measurement.rect.right <= width + 1, '设置界面横向溢出')
      if (isLink) check(measurement.rect.y >= 0 && measurement.rect.bottom <= height + 1, '弹窗未约束在视口内')
      check(measurement.fields.every(field => field.height >= 32 && field.font.includes('Noto Sans')), '字段尺寸或字体未沿用 PC 主题')
      check(measurement.buttons.every(button => button.height >= 28 && button.font.includes('Noto Sans')), '操作按钮尺寸或字体未沿用 PC 主题')
      if (width >= 1000) check(measurement.desktopLabel, 'PC 字段未采用左标签右输入布局')
      if (measurement.list && measurement.list.count) check(measurement.list.height <= 250 && /auto|scroll/.test(measurement.list.overflow), '长列表缺少内部滚动')
      if (!isLink && width >= 1000 && measurement.list?.count) check(measurement.list.top <= (mode.startsWith('cross-reference')?measurement.fieldsTop:measurement.headingTop) + 8, 'PC 列表未与字段区并列，面板高度被纵向堆叠占用')
      if (mode.endsWith('readonly')) check(await surface.locator(isLink ? '[data-command=applyLink]' : mode.startsWith('bookmarks') ? '[data-bookmark-add]' : '[data-cross-reference-insert]').first().isDisabled(), '只读状态仍允许写入')
      await page.screenshot({ path: join(directory, `${mode}-${width}x${height}.png`) })
      if (isLink) {
        const controls = surface.locator('button:enabled,input:enabled')
        await controls.last().focus()
        await page.keyboard.press('Tab')
        check(await surface.evaluate(node => node.contains(document.activeElement)), 'Tab 离开模态窗口')
        check(await surface.evaluate(() => parseFloat(getComputedStyle(document.activeElement).outlineWidth) >= 2), '模态窗口缺少可见的键盘焦点环')
        await page.keyboard.press('Escape')
        check(!await surface.isVisible(), 'Escape 未关闭超链接弹窗')
        if (await surface.isVisible()) await surface.locator('[data-command=cancelLink]').click()
      } else {
        if(process.env.OFFICE_CROSS_REFERENCE_KEYBOARD==='1'&&mode.startsWith('cross-reference')){
          const chrome=await surface.evaluate(node=>{
            const header=node.querySelector('header'),body=node.querySelector('.docx-cross-reference-body');if(!header||!body)return null
            const top=header.getBoundingClientRect().top;body.scrollTop=body.scrollHeight
            const fixed=header.getBoundingClientRect().top===top;body.scrollTop=0
            return {fixed,bodyHeight:body.clientHeight,bodyScrollHeight:body.scrollHeight}
          })
          check(!!chrome&&chrome.fixed&&chrome.bodyHeight>=64,'交叉引用缺少固定标题关闭区或可用滚动主体')
          const close=surface.locator('[data-cross-reference-close]'),first=surface.locator('[data-cross-reference-insert]:enabled').first(),hasFirst=await first.count()>0
          check(await (hasFirst?first:close).evaluate(node=>document.activeElement===node),'交叉引用打开后未聚焦首个可用项或关闭')
          if(mode==='cross-reference-long'){
            await page.evaluate(()=>{window.officeReferenceFocusedNode=document.activeElement;window.officeReferenceEditor.commands.setTextSelection(2)})
            check(await page.evaluate(()=>window.officeReferenceFocusedNode.isConnected&&document.activeElement===window.officeReferenceFocusedNode),'普通光标事务丢失交叉引用焦点')
            await page.evaluate(()=>window.officeReferenceSetEditable(false))
            check(await close.evaluate(node=>document.activeElement===node),'锁定后焦点留在禁用引用项')
            check(await surface.locator('[data-cross-reference-insert]:enabled').count()===0,'锁定后仍可插入')
            await page.evaluate(()=>window.officeReferenceSetEditable(true))
            check(await first.isEnabled(),'解除锁定后引用项未恢复')
          }
          if(mode==='cross-reference-error'||mode.endsWith('readonly')||mode.endsWith('empty')){
            await close.focus();await page.keyboard.press('Tab')
            const status=surface.getByRole('status',{name:'交叉引用状态'})
            check(await status.evaluate(node=>document.activeElement===node),'Tab未进入交叉引用状态说明')
            check(await status.evaluate(node=>{const r=node.getBoundingClientRect(),body=node.closest('.docx-cross-reference-body')?.getBoundingClientRect();return body&&r.top>=Math.max(0,body.top)-1&&r.bottom<=Math.min(innerHeight,body.bottom)+1&&parseFloat(getComputedStyle(node).outlineWidth)>=2}),'状态阅读区被主体裁切或无焦点环')
            if(mode.endsWith('empty'))check(await status.textContent()==='当前文档没有可插入的已保存书签','空引用列表缺少说明')
            if(mode.endsWith('readonly')){
              await page.keyboard.press('Tab')
              const list=surface.getByRole('list',{name:'已保存书签'})
              check(await list.evaluate(node=>document.activeElement===node),'Tab未进入只读书签列表')
              await page.keyboard.press('End')
              await page.waitForFunction(()=>{const node=document.querySelector('[data-cross-reference-list]');return node&&node.scrollTop>0&&node.scrollTop+node.clientHeight>=node.scrollHeight-2},null,{timeout:2000}).catch(()=>{})
              check(await list.evaluate(node=>node.scrollTop>0&&node.scrollTop+node.clientHeight>=node.scrollHeight-2),'键盘无法滚到只读列表末尾')
              check(await list.locator('li button').last().evaluate(node=>{const r=node.getBoundingClientRect(),body=node.closest('.docx-cross-reference-body').getBoundingClientRect(),list=node.closest('ul').getBoundingClientRect();return r.top>=Math.max(body.top,list.top)-1&&r.bottom<=Math.min(body.bottom,list.bottom)+1}),'End后末项名称仍被主体或列表裁切')
              await page.screenshot({path:join(directory,`${mode}-keyboard-end-${width}x${height}.png`)})
              await page.keyboard.press('Home')
              await page.waitForFunction(()=>document.querySelector('[data-cross-reference-list]')?.scrollTop<=1,null,{timeout:2000}).catch(()=>{})
              check(await list.evaluate(node=>node.scrollTop<=1),'键盘无法回到只读列表开头')
            }
          }
          evidence.crossReferenceKeyboard.push({mode,width,height,checked:true,chrome})
        }
        if (process.env.OFFICE_BOOKMARK_KEYBOARD === '1' && mode.startsWith('bookmarks')) {
          const input=surface.locator('[data-bookmark-name]'),close=surface.locator('[data-bookmark-close]')
          check(await (mode.endsWith('readonly')?close:input).evaluate(node=>document.activeElement===node),'打开后焦点未进入可用字段或关闭按钮')
          if(mode==='bookmarks-long'){
            await input.focus()
            for(let step=0;step<4;step++)await page.keyboard.press('Tab')
            const first=surface.locator('[data-bookmark-delete]').first()
            check(await first.evaluate(node=>document.activeElement===node),'Tab未到达首项删除按钮')
            await page.evaluate(()=>{window.officeBookmarkFocusedNode=document.activeElement;window.officeReferenceEditor.commands.setTextSelection({from:2,to:4})})
            check(await page.evaluate(()=>window.officeBookmarkFocusedNode.isConnected&&document.activeElement===window.officeBookmarkFocusedNode),'普通选区事务丢失键盘焦点')
            const deletedId=await first.getAttribute('data-bookmark-delete'),expected=await surface.locator('[data-bookmark-delete]').nth(2).getAttribute('data-bookmark-delete')
            await page.keyboard.press('Space')
            check(await surface.locator(`[data-bookmark-delete="${deletedId}"]`).count()===0,'键盘删除未生效')
            check(await surface.locator(`[data-bookmark-delete="${expected}"]`).evaluate(node=>document.activeElement===node),'删除后未跳过只读项并聚焦下一可删除书签')
            await page.evaluate(()=>window.officeReferenceEditor.commands.undo())
            check(await surface.locator(`[data-bookmark-delete="${deletedId}"]`).count()===1,'撤销未恢复书签')
            check(JSON.stringify(before)===JSON.stringify(await page.evaluate(()=>window.officeReferenceEditor.getJSON())),'删除再撤销没有恢复原始正文与书签意图')
          }
          evidence.bookmarkKeyboard.push({mode,width,height,checked:true})
        }
        if(process.env.OFFICE_REFERENCE_AXE==='1'){
          const {default:AxeBuilder}=await import('@axe-core/playwright')
          const result=await new AxeBuilder({page}).include('.docx-comment-panel:not([hidden])').analyze()
          evidence.accessibility.push({mode,width,height,violations:result.violations})
          check(!result.violations.length,`无障碍违规：${result.violations.map(item=>item.id).join(',')}`)
        }
        if (measurement.list?.count) {
          const button = surface.locator('li button').last()
          await button.scrollIntoViewIfNeeded()
          check(await button.isVisible(), '列表末项不可访问')
          check(await button.evaluate(node => {
            const bounds = node.getBoundingClientRect(), panel = node.closest('.docx-comment-panel').getBoundingClientRect(), list = node.closest('ul').getBoundingClientRect()
            return bounds.top >= Math.max(panel.top, list.top) - 1 && bounds.bottom <= Math.min(panel.bottom, list.bottom) + 1
          }), '列表末项被面板或列表裁切')
        }
        await surface.locator(mode.startsWith('bookmarks') ? '[data-bookmark-close]' : '[data-cross-reference-close]').click()
        check(!await surface.isVisible(), '面板关闭后仍可见')
        if(process.env.OFFICE_BOOKMARK_KEYBOARD==='1'&&mode.startsWith('bookmarks'))check(await page.getByRole('button',{name:'打开设置',exact:true}).evaluate(node=>document.activeElement===node),'关闭后焦点未回入口')
        if(process.env.OFFICE_CROSS_REFERENCE_KEYBOARD==='1'&&mode.startsWith('cross-reference'))check(await page.getByRole('button',{name:'打开设置',exact:true}).evaluate(node=>document.activeElement===node),'交叉引用关闭后焦点未回入口')
      }
      check(JSON.stringify(before) === JSON.stringify(await page.evaluate(() => window.officeReferenceEditor.getJSON())), '检查设置改变了正文')
      evidence.cases.push({ mode, width, height, measurement })
    }
    await context.close()
  }
} finally {
  await browser?.close(); server.kill('SIGTERM')
  await writeFile(join(directory, 'evidence.json'), JSON.stringify(evidence, null, 2))
}
assert.deepEqual(evidence.pageErrors, [])
assert.deepEqual(evidence.failures, [])
console.log(JSON.stringify({ directory, cases: evidence.cases.length, failures: evidence.failures }))
