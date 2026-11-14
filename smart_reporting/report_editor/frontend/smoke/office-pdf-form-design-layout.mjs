import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { protectedPdfKey } from './pdf-gesture-keyboard-checks.mjs'

// 产品面板与真实 PDF 宿主；只检查，不修改模型或草稿。
export async function checkPdfFormDesignLayout(page, directory) {
  const panel = page.locator('.pdf-form-design-panel'), failures = [], cases = []
  const record = (condition, message) => { if (!condition) failures.push(message) }
  const draft = () => page.evaluate(() => Object.entries(localStorage).filter(([key]) => key.startsWith('native-editor-draft:')))
  const before = await draft()
  for (const viewport of [{ width: 1440, height: 900 }, { width: 320, height: 640 }, { width: 640, height: 360 }, { width: 390, height: 320 }, { width: 1440, height: 360 }]) {
    await page.setViewportSize(viewport)
    const key = `${viewport.width}x${viewport.height}`, command = page.locator('[data-source-command-id="genoffice.pdf.formDesign.deleteField"]')
    if (await panel.isHidden()) { await command.focus(); await command.click() }
    const structure = await panel.evaluate(element => ({
      header: !!element.querySelector('header h3'), hidden: getComputedStyle(element).display === 'none',
      scrollable: ['auto', 'scroll'].includes(getComputedStyle(element).overflowY),
      width: element.getBoundingClientRect().width, overflow: element.scrollWidth > element.clientWidth + 1,
      reasons: element.querySelectorAll('.pdf-form-design-reason').length,
      buttons: [...element.querySelectorAll('button')].map(button => ({ text: button.textContent, disabled: button.disabled })),
    }))
    record(structure.header, `${key}: missing desktop header`)
    record(structure.scrollable, `${key}: unbounded panel`)
    record(!structure.overflow && structure.width <= viewport.width + 1, `${key}: horizontal overflow`)
    record(structure.reasons > 0, `${key}: reason not separated`)
    const controls = panel.locator('button'), checks = []
    for (let index = 0; index < await controls.count(); index++) {
      const control = controls.nth(index)
      await control.scrollIntoViewIfNeeded()
      const state = await control.evaluate(element => {
        const box = element.getBoundingClientRect(), style = getComputedStyle(element)
        return { height: box.height, font: style.fontFamily, themeFont: getComputedStyle(element.closest('.native-pdf-editor')).fontFamily, disabled: element.disabled,
          hits: [[.5,.5],[.12,.12],[.88,.12],[.12,.88],[.88,.88]].every(([x,y]) => element.contains(document.elementFromPoint(box.x+box.width*x,box.y+box.height*y))) }
      })
      record(state.height >= 26 && state.height <= 32, `${key}/${index}: control height ${state.height}`)
      record(state.hits, `${key}/${index}: hit obstruction`)
      record(state.font === state.themeFont, `${key}/${index}: theme font ${state.font}`)
      if (!state.disabled) {
        await control.focus(); await page.keyboard.press('Tab'); await page.keyboard.press('Shift+Tab')
        const focus = await control.evaluate(element => ({ active: document.activeElement === element,
          ring: parseFloat(getComputedStyle(element).outlineWidth) >= 2 && getComputedStyle(element).outlineStyle !== 'none' }))
        record(focus.active && focus.ring, `${key}/${index}: keyboard focus or ring`)
        state.focus = focus
      }
      checks.push(state)
    }
    const reason = panel.locator('.pdf-form-design-reason').last()
    if (await reason.count()) {
      await reason.scrollIntoViewIfNeeded()
      record(await reason.evaluate(element => {
        const box = element.getBoundingClientRect()
        return box.width > 0 && element.contains(document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2))
      }), `${key}: reason obscured`)
    }
    await page.screenshot({ path: join(directory, `form-design-${key}-end.png`) })
    await panel.evaluate(element => { element.scrollTop = 0 })
    await page.screenshot({ path: join(directory, `form-design-${key}.png`) })
    const close = panel.locator('button').first()
    const keyboard = []
    for (const mode of ['composing', 'legacy229', 'consumed']) {
      await close.focus()
      keyboard.push({ mode, ...await protectedPdfKey(close, 'Escape', mode) })
      record(await panel.isVisible(), `${key}: ${mode} Escape closed the panel`)
      record(await close.evaluate(element => document.activeElement === element), `${key}: ${mode} Escape moved focus`)
      assert(await panel.isVisible(), `${key}: ${mode} Escape must preserve field design`)
    }
    await close.evaluate(element => element.addEventListener('keydown', event => event.preventDefault(), { once: true }))
    await page.keyboard.press('Escape')
    record(await panel.isVisible(), `${key}: target-consumed real Escape closed the panel`)
    await close.focus(); await page.keyboard.press('Escape')
    record(await panel.isHidden(), `${key}: Escape did not close`)
    record(await command.evaluate(element => document.activeElement === element), `${key}: opener focus not returned`)
    // 旧构建不支持 Escape，确保后续视口仍检查同一真实入口。
    if (await panel.isVisible()) await close.click()
    cases.push({ viewport, structure, controls: checks, keyboard })
  }
  assert.deepEqual(await draft(), before, 'layout changed the draft')
  const result = { cases, failures, draftUnchanged: true }
  await writeFile(join(directory, 'layout.json'), JSON.stringify(result, null, 2))
  assert.deepEqual(failures, [], 'PC form design layout')
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.locator('[data-source-command-id="genoffice.pdf.formDesign.deleteField"]').click()
  return result
}
