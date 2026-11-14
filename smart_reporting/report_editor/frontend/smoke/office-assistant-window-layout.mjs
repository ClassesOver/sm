import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

// 只检查现有助手窗口；不提交任务、不改回答、来源文件或编辑草稿。
export async function inspectAssistantWindow(page, { output, format, viewports, draft }) {
  const evidence = { format, cases: [], failures: [] }, before = await draft()
  const dock = page.locator(format === 'pdf' ? '.pdf-ai-dock' : '.office-task-dock')
  const input = dock.locator('textarea:visible').first()
  const toggle = () => dock.locator('.office-assistant-float-toggle')
  const inspect = async (mode, width, height) => {
    const check = (ok, message) => { if (!ok) evidence.failures.push(`${format} ${mode} ${width}x${height}: ${message}`) }
    await page.evaluate(() => document.fonts.ready)
    const geometry = await dock.evaluate(node => {
      const r = node.getBoundingClientRect(), s = getComputedStyle(node)
      const header = node.querySelector(':scope > header'), nav = node.querySelector(':scope > nav')
      return { x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height,
        font: s.fontFamily, radius: parseFloat(s.borderRadius), overflow: node.scrollWidth > node.clientWidth + 1,
        header: { height: header.getBoundingClientRect().height, font: getComputedStyle(header).fontFamily },
        nav: { radius: parseFloat(getComputedStyle(nav).borderRadius), overflow: nav.scrollWidth > nav.clientWidth + 1 },
        controls: [...node.querySelectorAll('button,select,textarea,summary,[role="separator"],.office-assistant-drag-handle')].filter(control => control.getClientRects().length).map(control => {
        const b = control.getBoundingClientRect(); return { tag: control.tagName, height: b.height, width: b.width, font: getComputedStyle(control).fontFamily, radius: parseFloat(getComputedStyle(control).borderRadius) }
        }) }
    })
    check(geometry.width > 0 && geometry.height > 0 && geometry.x >= -1 && geometry.right <= width + 1 && !geometry.overflow && !geometry.nav.overflow, '窗口或模式栏横向溢出')
    check(geometry.font.includes('Noto Sans') && geometry.header.font.includes('Noto Sans') && geometry.controls.every(control => control.font.includes('Noto Sans')), '字体未继承Office主题')
    check(geometry.radius <= 6 && geometry.nav.radius <= 6, '窗口或模式标签仍为大圆角')
    check(geometry.header.height >= 40 && geometry.header.height <= 48, '标题栏高度不符合PC窗口')
    if (mode === 'floating') check(geometry.y >= 0 && geometry.bottom <= height + 1, '浮动窗口超出视口')
    const states = []
    for (const control of await dock.locator('button:visible:enabled,select:visible:enabled,textarea:visible:enabled,summary:visible,[role="separator"]:visible,.office-assistant-drag-handle:visible,.office-assistant-body:visible').all()) {
      await control.focus(); await page.keyboard.press('Tab'); await page.keyboard.press('Shift+Tab')
      await control.evaluate(node => node.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' }))
      const state = await control.evaluate(node => {
        const r = node.getBoundingClientRect(), s = getComputedStyle(node), hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)
        const composer = node.closest('.office-assistant-composer'), composerShadow = composer ? getComputedStyle(composer).boxShadow : ''
        return { label: node.getAttribute('aria-label') || node.textContent.trim(), focused: node === document.activeElement,
          hit: node.contains(hit), ring: s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 2 || Boolean(composer?.matches(':focus-within') && composerShadow.includes('0px 0px 0px 3px')),
          rect: { x: r.x, y: r.y, width: r.width, height: r.height }, hitElement: hit?.className?.baseVal ?? hit?.className ?? null }
      })
      check(state.focused && state.hit && state.ring, `${state.label}不可聚焦、命中或无焦点环`)
      if (await control.evaluate(node => node.classList.contains('office-assistant-body'))) {
        const body = await control.evaluate(node => ({ height: node.clientHeight, scrollHeight: node.scrollHeight, tabindex: node.tabIndex, role: node.getAttribute('role') }))
        check(body.height >= 48 && body.tabindex === 0 && body.role === 'region', '结果区没有可用高度或不可键盘阅读')
        if (body.scrollHeight > body.height + 1) {
          await page.keyboard.press('End')
          await page.waitForFunction(node => node.scrollTop + node.clientHeight >= node.scrollHeight - 2, await control.elementHandle(), { timeout: 3000 }).catch(() => check(false, '结果区End未到末尾'))
          state.afterEnd = await control.evaluate(node => ({ top: node.scrollTop, height: node.clientHeight, scrollHeight: node.scrollHeight, focused: node === document.activeElement }))
          await page.keyboard.press('Home')
          await page.waitForFunction(node => node.scrollTop <= 1, await control.elementHandle(), { timeout: 3000 }).catch(() => check(false, '结果区Home未回到开头'))
          state.afterHome = await control.evaluate(node => ({ top: node.scrollTop, height: node.clientHeight, scrollHeight: node.scrollHeight, focused: node === document.activeElement }))
          state.resultScrolledByKeyboard = state.afterEnd.top + state.afterEnd.height >= state.afterEnd.scrollHeight - 2 && state.afterHome.top <= 1 && state.afterEnd.focused && state.afterHome.focused
        }
      }
      states.push(state)
    }
    evidence.cases.push({ mode, width, height, geometry, states })
    await writeFile(resolve(output, `${format}-window-layout.json`), JSON.stringify(evidence, null, 2))
    await page.screenshot({ path: resolve(output, `${format}-${mode}-${width}x${height}-content.png`) })
    await toggle().scrollIntoViewIfNeeded()
    await page.screenshot({ path: resolve(output, `${format}-${mode}-${width}x${height}.png`) })
    assert.deepEqual(await draft(), before)
  }
  const savedInput = await input.inputValue()
  await input.fill('保留的待提交问题：请结合当前文档解释收入与成本，窗口操作不得自动发送。')
  const pending = await input.inputValue()
  for (const viewport of viewports.split(',')) {
    const [width, height] = viewport.split('x').map(Number)
    await page.setViewportSize({ width, height })
    await inspect('docked', width, height)
    if (width > 900 && format !== 'pdf') {
      const divider = dock.locator('[role="separator"]'), previous = Number(await divider.getAttribute('aria-valuenow'))
      await divider.focus(); await page.keyboard.press('ArrowLeft'); assert.equal(Number(await divider.getAttribute('aria-valuenow')), previous + 20)
      await page.keyboard.press('ArrowRight'); assert.equal(Number(await divider.getAttribute('aria-valuenow')), previous)
    }
    await toggle().click(); await dock.locator('.office-assistant-drag-handle').waitFor({ state: 'visible' })
    const handle = dock.locator('.office-assistant-drag-handle')
    await handle.focus(); await page.keyboard.press('ArrowLeft'); await page.keyboard.press('ArrowUp')
    await inspect('floating', width, height)
    assert.equal(await input.inputValue(), pending)
    await toggle().click(); assert.equal(await dock.evaluate(node => node.classList.contains('is-office-assistant-floating')), false)
    assert.equal(await input.inputValue(), pending)
  }
  await page.setViewportSize({ width: 1550, height: 1100 }); await input.fill(savedInput)
  const close = dock.locator('.office-assistant-close:visible').first()
  await close.click(); await dock.waitFor({ state: 'hidden' })
  const entry = page.locator(format === 'pdf' ? '[data-source-command-id="genoffice.pdf.home.ai.openAssistant"]' : format === 'docx' ? '[data-action="word-read-ai"]' : '[data-action="office-read-ai"]')
  const returnTarget = format === 'pdf' ? page.locator('[data-source-command-id="genoffice.pdf.home.ai.summarize"]') : entry
  evidence.closeFocusRestored = await returnTarget.evaluate(node => node === document.activeElement)
  if (!evidence.closeFocusRestored) evidence.failures.push(`${format}: 关闭后未回到原入口`)
  await entry.click(); await dock.waitFor({ state: 'visible' })
  assert.equal(await input.inputValue(), savedInput)
  await writeFile(resolve(output, `${format}-window-layout.json`), JSON.stringify(evidence, null, 2))
  assert.deepEqual(await draft(), before)
  return evidence
}
