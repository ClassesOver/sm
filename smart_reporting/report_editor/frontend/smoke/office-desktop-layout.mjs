import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'

// 在真实文件 smoke 中复用，验证外壳几何；不替换引擎或注入界面样式。
export async function auditOfficeDesktopLayout(page, format) {
  const directory = process.env.OFFICE_VISUAL_DIR
  if (!directory) return
  await mkdir(directory, { recursive: true })
  const original = page.viewportSize()
  const measurements = []
  const failures = []
  const missingIcons = new Set()
  const tabChecks = []
  let wheelCheck, keyboardCheck
  try {
    for (const [width, height] of [[1440, 900], [1280, 720], [768, 1024], [390, 844]]) {
      await page.setViewportSize({ width, height })
      await page.evaluate(() => document.fonts.ready)
      await page.waitForTimeout(350)
      const result = await page.evaluate(() => {
        const box = selector => {
          const element = document.querySelector(selector)
          if (!element) return null
          const rect = element.getBoundingClientRect()
          const style = getComputedStyle(element)
          return { x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height,
            padding: style.padding, radius: style.borderRadius, shadow: style.boxShadow,
            scrollWidth: element.scrollWidth, clientWidth: element.clientWidth }
        }
        return { root: box('#app'), workspace: box('.report-workspace'), surface: box('.editor-surface'),
          editor: box('#report-editor'), header: box('.app-bar'),
          aiEntry: box('.office-ai-group .office-ai-entry'),
          ai: (() => {
            const group = document.querySelector('.office-ai-group'), entry = group?.querySelector('.office-ai-entry')
            return { first: group?.parentElement?.firstElementChild === group, label: entry?.textContent?.trim(), icons: entry?.querySelectorAll('svg').length, branded: /genspark/i.test(document.querySelector('[role=tabpanel]:not([hidden])')?.textContent || '') }
          })(),
          canvas: box('.editor-scroll, .workbook-grid, .pdf-layout, .slides-stage'),
          status: box('.docx-view-status, .pdf-view-status, .slides-statusbar'),
          slidePaper: box('.slides-canvas .konvajs-content'),
          colorButtons: [...document.querySelectorAll('.workbook-ribbon-color')].map(element => element.getBoundingClientRect().width),
          fontSize: box('.slides-native-ribbon [role=tabpanel]:not([hidden]) input[data-command=fontSize]'),
          colorOverflow: [...document.querySelectorAll('.workbook-ribbon-color input')].some(input => {
            const outer = input.parentElement.getBoundingClientRect(), inner = input.getBoundingClientRect()
            return inner.width > 0 && inner.height > 0 && (inner.top < outer.top || inner.bottom > outer.bottom || inner.left < outer.left || inner.right > outer.right)
          }),
          wrappedWordCommands: [...document.querySelectorAll('.docx-source-home .docx-source-command')].filter(button => {
            const lines = new Set()
            const walker = document.createTreeWalker(button, NodeFilter.SHOW_TEXT)
            while (walker.nextNode()) {
              const range = document.createRange(); range.selectNodeContents(walker.currentNode)
              for (const rect of range.getClientRects()) if (rect.width) lines.add(Math.round(rect.top))
            }
            return lines.size > 1
          }).map(button => button.textContent),
          bodyWidth: document.documentElement.scrollWidth, bodyHeight: document.documentElement.scrollHeight,
          primary: getComputedStyle(document.documentElement).getPropertyValue('--color-primary').trim(),
          overlappingGroups: [...document.querySelectorAll('.workbook-ribbon-group, .pdf-ribbon-group, .slides-native-ribbon-group')].filter(group => {
            const title = group.querySelector(':scope > h3')
            if (!title || !group.getBoundingClientRect().height) return false
            const top = title.getBoundingClientRect().top
            return [...group.children].some(child => child !== title && child.getBoundingClientRect().height > 0 && child.getBoundingClientRect().bottom > top + 1)
          }).map(group => group.getAttribute('aria-label') || group.querySelector('h3')?.textContent) }
      })
      measurements.push({ width, height, ...result })
      await page.screenshot({ path: join(directory, `${format}-${width}x${height}.png`) })
      const check = (condition, message) => { if (!condition) failures.push(`${format} ${width}×${height}: ${message}`) }
      check(result.ai.first && result.ai.label === 'AI 助手' && result.ai.icons === 1 && !result.ai.branded, 'AI 助手名称、图标或首位顺序不一致')
      check(result.aiEntry?.width === 72 && result.aiEntry?.x >= 0 && result.aiEntry?.right <= width, 'AI 入口尺寸不一致或位于窗口外')
      check(result.primary === '#0b4f8a', '智能报告主题主色变化')
      for (const name of ['root', 'workspace', 'surface']) {
        const rect = result[name]
        check(rect && Math.abs(rect.x) <= 1 && Math.abs(rect.right - width) <= 1, `${name} 未贴齐窗口左右边界`)
        check(rect && Math.abs(rect.bottom - height) <= 1, `${name} 未填满窗口高度`)
      }
      check(result.surface?.radius === '0px' && result.surface?.shadow === 'none', '工作区仍有外围卡片装饰')
      check(result.bodyWidth <= width + 1 && result.bodyHeight <= height + 1, '存在页面级溢出')
      check(result.canvas?.height > 100 && result.canvas?.bottom <= height + 1, '编辑画布高度不足或被裁切')
      if (result.slidePaper) check(result.slidePaper.y >= result.canvas.y, '幻灯片顶部被居中布局裁切')
      if (result.status?.height) check(result.status.bottom <= height + 1, '状态栏位于窗口之外')
      check(result.overlappingGroups.length === 0, '功能区控件覆盖分组标题：' + result.overlappingGroups.join('、'))
      check(!result.colorOverflow, '颜色输入框超出控件边界')
      check(result.colorButtons.every(value => value <= 80), '颜色控件被拉伸为整列宽度')
      if (result.fontSize) check(result.fontSize.width <= 80, '字号输入框过宽')
      check(result.wrappedWordCommands.length === 0, '短命令文字发生换行：' + result.wrappedWordCommands.join('、'))
      const assistant = page.locator('.native-ai-panel:has(.office-assistant-header)'), entry = page.locator('.office-ai-group .office-ai-entry')
      if (process.env.OFFICE_RIBBON_ONLY !== '1' && await assistant.count() && await entry.isEnabled()) {
        await entry.click()
        await assistant.waitFor({state:'visible'})
        const detail = await assistant.evaluate(panel => {
          const rect = panel.getBoundingClientRect(), input = panel.querySelector('textarea'), close = panel.querySelector('.office-assistant-close')
          const inputRect = input.getBoundingClientRect(), closeRect = close.getBoundingClientRect(), actionsRect = panel.querySelector('.office-assistant-actions').getBoundingClientRect()
          const canvas = document.querySelector('.editor-scroll, .workbook-grid, .pdf-layout, .slides-stage').getBoundingClientRect()
          return {height:rect.height,width:rect.width,bottom:rect.bottom,x:rect.x,canvasHeight:canvas.height,padding:getComputedStyle(panel).paddingLeft,
            overflow:panel.scrollWidth>panel.clientWidth+1, focused:document.activeElement===input,
            inputFits:inputRect.left>=rect.left && inputRect.right<=rect.right, actionsVisible:actionsRect.bottom<=rect.bottom && actionsRect.top>=rect.top,
            closeVisible:closeRect.top>=rect.top && closeRect.bottom<=rect.bottom && closeRect.right<=rect.right,
            pageOverflow:document.documentElement.scrollWidth>innerWidth+1 || document.documentElement.scrollHeight>innerHeight+1}
        })
        measurements.at(-1).assistant = detail
        check(detail.padding === (width<=768 ? '8px' : '12px'), '助手面板横向留白不一致')
        check(detail.focused && detail.inputFits && detail.closeVisible && detail.actionsVisible && !detail.overflow, '助手输入、关闭按钮或横向布局异常')
        check(!detail.pageOverflow && detail.canvasHeight>100 && detail.bottom<=height+1, '助手挤出文档画布或窗口')
        await page.screenshot({path:join(directory, format+'-assistant-'+width+'x'+height+'.png')})
        await assistant.locator('textarea').press('Escape')
        check(await assistant.isHidden(), 'Esc 未关闭助手')
        check(await entry.evaluate(button => document.activeElement===button), '关闭后焦点未返回入口')
      }

    }
    await page.setViewportSize({ width:1280, height:720 })
    const scrollSelector = format === 'docx' ? '.docx-ribbon .ribbon-body' : format === 'xlsx' ? '.workbook-ribbon-body' : format === 'pdf' ? '.pdf-ribbon [role=tabpanel]:not([hidden])' : '.slides-native-ribbon [role=tabpanel]:not([hidden])'
    const wheelResult = await page.locator(scrollSelector).evaluate(panel => {
      if (panel.scrollWidth <= panel.clientWidth + 1) return { overflow: false }
      panel.scrollLeft = 0
      const move = new WheelEvent('wheel', { deltaY: 160, bubbles: true, cancelable: true })
      panel.dispatchEvent(move)
      const moved = panel.scrollLeft > 0 && move.defaultPrevented
      panel.scrollLeft = panel.scrollWidth
      const edge = new WheelEvent('wheel', { deltaY: 160, bubbles: true, cancelable: true })
      panel.dispatchEvent(edge)
      panel.scrollLeft = 0
      return { overflow: true, moved, edgeReleased: !edge.defaultPrevented }
    })
    wheelCheck = wheelResult
    if (wheelResult.overflow && (!wheelResult.moved || !wheelResult.edgeReleased)) failures.push(format + ' 功能区横滚或边缘释放失败')
    const tabs = page.locator(format === 'docx' ? '.docx-ribbon .ribbon-tab' : format === 'xlsx' ? '.workbook-ribbon-tabs button' : format === 'pdf' ? '.pdf-ribbon-tabs [role=tab]' : '.slides-native-ribbon-tabs [role=tab]')
    for (let index=0; index<await tabs.count(); index++) {
      const tab=tabs.nth(index)
      if (!await tab.isVisible() || !await tab.isEnabled()) continue
      await tab.click()
      await page.waitForTimeout(80)
      const title=(await tab.textContent())?.trim()
      const missing = await page.locator('[role=tabpanel]:not([hidden]) button').evaluateAll(buttons => buttons.filter(button => button.getBoundingClientRect().height && button.textContent.trim() && !button.querySelector('svg')).map(button => ({ command: button.dataset.ribbonCommand || button.dataset.command || button.dataset.action || button.dataset.sourceCommandId, label: button.textContent.trim() })))
      for (const item of missing) missingIcons.add(JSON.stringify(item))
      const layouts = []
      for (const width of [1280,768,390]) {
        await page.setViewportSize({width,height:width===390?844:900})
        const layout = await page.locator('[role=tabpanel]:not([hidden])').evaluate(panel => {
          const groups=[...panel.querySelectorAll('.ribbon-group, .workbook-ribbon-group, .pdf-ribbon-group, .slides-native-ribbon-group')]
          const overlaps=groups.filter(group=>{
            const title=group.querySelector(':scope > h3, :scope > .ribbon-group-label')
            if(!title || !title.getBoundingClientRect().height)return false
            return [...group.querySelectorAll('button,input,select,textarea')].some(control=>{
              const rect=control.getBoundingClientRect(), heading=title.getBoundingClientRect()
              return rect.height && rect.width && rect.top<heading.bottom && rect.bottom>heading.top && rect.left<heading.right && rect.right>heading.left
            })
          }).map(group=>group.getAttribute('aria-label')||group.querySelector('h3,.ribbon-group-label')?.textContent)
          const unnamed=[...panel.querySelectorAll('button,input,select,textarea')].filter(control=>control.getBoundingClientRect().height && !control.getAttribute('aria-label') && !control.getAttribute('title') && !control.textContent?.trim() && !control.closest('label')).map(control=>control.dataset.command||control.dataset.action||control.tagName)
          return {overlaps,unnamed,pageOverflow:document.documentElement.scrollWidth>innerWidth+1}
        })
        layouts.push({width,...layout})
        if(layout.overlaps.length)failures.push(format+' '+title+' '+width+' 控件覆盖组名：'+layout.overlaps.join('、'))
        if(layout.pageOverflow)failures.push(format+' '+title+' '+width+' 页面横向溢出')
      }
      await page.setViewportSize({width:1280,height:720})
      tabChecks.push({title, missingIcons:missing, layouts})
      const dimensions=await page.locator('.editor-scroll, .workbook-grid, .pdf-layout, .slides-stage').first().boundingBox()
      if (!dimensions || dimensions.height<100) failures.push(format + ' 功能标签「' + title + '」挤占画布高度')
      await page.screenshot({path:join(directory, format + '-tab-' + index + '.png')})
    }
    await tabs.filter({hasText:/^(开始|Home)$/}).first().click()
    const home = tabs.filter({hasText:/^(开始|Home)$/}).first()
    await home.focus()
    await page.keyboard.press('Tab')
    await page.keyboard.press('Shift+Tab')
    const focus = await home.evaluate(element => {
      const style = getComputedStyle(element)
      return { visible: element.matches(':focus-visible'), width: parseFloat(style.outlineWidth), offset: parseFloat(style.outlineOffset) }
    })
    keyboardCheck = focus
    if (!focus.visible || focus.width < 2 || focus.offset >= 0) failures.push(format + ' 标签键盘焦点不清晰或会被滚动容器裁切')
    await page.screenshot({path:join(directory, format + '-keyboard-focus.png')})
    if (format==='docx') {
      const trigger=page.locator('.docx-source-home [data-action="line-spacing"]')
      await trigger.click()
      const menu=page.locator('[data-source-action="line-spacing-options-menu"]')
      const reachable=await menu.evaluate(element=>{
        const rect=element.getBoundingClientRect()
        return rect.top>=0 && rect.bottom<=innerHeight && rect.left>=0 && rect.right<=innerWidth
          && element.contains(document.elementFromPoint(rect.left+rect.width/2,rect.bottom-8))
      })
      if (!reachable) failures.push('Word 行距菜单被裁切或遮挡')
      await page.screenshot({path:join(directory,'docx-line-spacing-menu.png')})
      await trigger.click()
    }
    await writeFile(join(directory, format+'-layout.json'), JSON.stringify({ measurements, failures, tabChecks, wheelCheck, keyboardCheck, missingIcons: [...missingIcons].map(value => JSON.parse(value)) }, null, 2))
    assert.deepEqual(failures, [])
    console.log(JSON.stringify({ visualLayout: format, viewports: measurements.length, failures }))
  } finally {
    if (original) {
      await page.setViewportSize(original)
      await page.waitForTimeout(350)
    }
  }
}
