import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import AxeBuilder from '@axe-core/playwright'

// 仅操作真实宿主中的源对象和产品窗格；布局检查不得产生底稿修改。
export async function inspectGeometryPane(page, { output, viewports, targets, draft }) {
  const evidence = { cases: [], interactions: [], ribbonCases: [], failures: [] }, before = await draft()
  const pane = page.locator('.slides-geometry-pane')
  const check = (ok, message) => { if (!ok) evidence.failures.push(message) }
  for (const target of targets) {
    await page.locator('#object-select').selectOption(target.id)
    if (target.type === 'picture') await page.waitForFunction(() => !document.querySelector('[data-geometry-original]').disabled)
    for (const viewport of viewports.split(',')) {
      const [width, height] = viewport.split('x').map(Number), label = `${target.type}/${viewport}`
      await page.setViewportSize({ width, height })
      await pane.scrollIntoViewIfNeeded(); await page.evaluate(() => document.fonts.ready)
      const geometry = await pane.evaluate(node => {
        const r = node.getBoundingClientRect()
        return { x: r.x, right: r.right, width: r.width, horizontalOverflow: node.scrollWidth > node.clientWidth + 1,
          groups: [...node.querySelectorAll('fieldset')].map(group => ({ name: group.querySelector('legend')?.textContent, count: group.querySelectorAll('input,select,button').length })),
          font: getComputedStyle(node).fontFamily,
          workspaceHeight: document.querySelector('.slides-workspace').getBoundingClientRect().height,
          inspectorHeight: node.closest('.slides-inspector').getBoundingClientRect().height,
          ribbonHeight: document.querySelector('.slides-native-ribbon').getBoundingClientRect().height,
          rows: [...node.querySelectorAll('.geometry-cm-row')].map(row => { const label = row.querySelector('span').getBoundingClientRect(), field = row.querySelector('input').getBoundingClientRect(); return { labelRight: label.right, inputLeft: field.left, inputWidth: field.width } }) }
      })
      check(geometry.x >= 0 && geometry.right <= width + 1 && !geometry.horizontalOverflow, `${label}: 窗格横向溢出`)
      check(geometry.font.includes('Noto Sans'), `${label}: 未继承主题字体`)
      check(geometry.workspaceHeight >= 90, `${label}: 宿主工作区高度不足90px`)
      check(geometry.inspectorHeight >= 90, `${label}: 对象窗格高度不足90px`)
      check(geometry.groups.length === 3 && geometry.groups.every(group => group.name && group.count > 0), `${label}: 尺寸、缩放、位置缺少可辨识分组`)
      check(geometry.rows.every(row => row.inputWidth >= 40 && row.inputLeft > row.labelRight), `${label}: 字段过窄或标签未在左侧`)
      const states = []
      for (const control of await pane.locator('input:enabled,select:enabled,button:enabled').all()) {
        await control.focus(); await page.keyboard.press('Tab'); await page.keyboard.press('Shift+Tab'); await control.scrollIntoViewIfNeeded()
        const state = await control.evaluate(node => {
          const r = node.getBoundingClientRect(), s = getComputedStyle(node), hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)
          return { label: node.getAttribute('aria-label') ?? node.closest('label')?.textContent, type: node.type,
            font: s.fontFamily, focused: node === document.activeElement, hit: node.contains(hit), ring: s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 2,
            exposed: [[r.x+3,r.y+3],[r.right-3,r.y+3],[r.x+3,r.bottom-3],[r.right-3,r.bottom-3]].every(([x,y]) => node.contains(document.elementFromPoint(x,y))),
            x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height }
        })
        check(state.focused && state.hit && state.ring, `${label}: ${state.label}焦点、命中或焦点环失败`)
        check(state.exposed, `${label}: ${state.label}边缘被遮挡或裁切`)
        check(state.x >= 0 && state.y >= 0 && state.right <= width + 1 && state.bottom <= height + 1, `${label}: ${state.label}不能滚动到视口内`)
        check(state.font.includes('Noto Sans'), `${label}: ${state.label}字体不同`)
        if (state.type !== 'checkbox') check(state.height >= 26 && state.height <= 32, `${label}: ${state.label}未采用紧凑字段`)
        states.push(state)
      }
      const ratio = () => pane.locator('[data-geometry-ratio]')
      await ratio().focus(); await page.keyboard.press('Space')
      const ratioFocused = await ratio().evaluate(node => node.checked && node === document.activeElement)
      check(ratioFocused, `${label}: 键盘切换比例后焦点丢失`)
      await ratio().focus(); await page.keyboard.press('Space')
      const reference = () => pane.locator('[data-geometry-reference="x"]')
      await reference().focus(); await reference().selectOption('center')
      const referenceFocused = await reference().evaluate(node => node.value === 'center' && node === document.activeElement)
      check(referenceFocused, `${label}: 切换参考点后焦点丢失`)
      await reference().selectOption('tl')
      const field = () => pane.locator('[data-geometry="width"]'), initial = await field().inputValue()
      const ime = []
      await field().fill('7.62')
      for (const key of ['Enter', 'Escape']) for (const protection of ['composition', 'legacy', 'handled']) {
        const result = await field().evaluate((node, { key, protection }) => {
          const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, isComposing: protection === 'composition', keyCode: protection === 'legacy' ? 229 : 0 })
          if (protection === 'handled') event.preventDefault()
          node.dispatchEvent(event)
          return { key, protection, connected: node.isConnected, focused: node === document.activeElement, value: node.value }
        }, { key, protection })
        check(result.connected && result.focused && result.value === '7.62', `${label}: ${key}/${protection}撤回或提交了输入中的草稿`)
        assert.deepEqual(await draft(), before); ime.push(result)
      }
      await field().press('Escape')
      await field().fill('0'); await field().press('Enter')
      check(await field().getAttribute('aria-invalid') === 'true', `${label}: 越界字段缺少无效标记`)
      const invalidBorder = await field().evaluate(node => {
        const sample = document.createElement('span'); sample.style.color = 'var(--color-danger, #b42318)'; node.parentElement.append(sample)
        const result = { actual: getComputedStyle(node).borderTopColor, expected: getComputedStyle(sample).color }; sample.remove(); return result
      })
      check(invalidBorder.actual === invalidBorder.expected, `${label}: 无效字段边框被通用主题覆盖`)
      const status = pane.getByRole('status', { name: '大小与位置状态' })
      check((await status.textContent()).includes('至少'), `${label}: 未说明越界原因`)
      check(await field().getAttribute('aria-describedby') === await status.getAttribute('id'), `${label}: 字段未关联错误说明`)
      await status.focus(); await status.scrollIntoViewIfNeeded()
      const readable = await status.evaluate(node => { const r=node.getBoundingClientRect(),s=getComputedStyle(node);return {focused:node===document.activeElement,ring:parseFloat(s.outlineWidth)>=2,visible:r.top>=0&&r.bottom<=innerHeight,hit:node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))} })
      check(readable.focused && readable.ring && readable.visible && readable.hit, `${label}: 错误说明无法键盘阅读`)
      const axe = await new AxeBuilder({page}).include('.slides-geometry-pane').analyze()
      check(axe.violations.length === 0, `${label}: 几何面板无障碍违规 ${axe.violations.map(item=>item.id).join(',')}`)
      await page.screenshot({path:join(output,`geometry-${target.type}-${viewport}-validation.png`)})
      await field().focus(); await field().press('Escape')
      check(!await field().getAttribute('aria-invalid') && await pane.locator('[role="status"]').textContent() === '', `${label}: 撤回后错误未清除`)
      await field().fill('invalid'); await page.keyboard.press('Escape')
      const cancelled = await field().inputValue() === initial, fieldFocused = await field().evaluate(node => node === document.activeElement)
      check(cancelled && fieldFocused, `${label}: Escape撤回后焦点丢失或内容未恢复`)
      assert.deepEqual(await draft(), before)
      if (height <= 480) {
        const tabs = target === targets[0]
          ? await page.locator('.slides-native-ribbon-tabs [data-ribbon-tab]:not([hidden])').evaluateAll(nodes => nodes.map(node => node.dataset.ribbonTab))
          : ['pictureFormat']
        for (const tab of tabs) {
          await page.locator(`[data-ribbon-tab="${tab}"]`).click()
          const ribbonStates = []
          for (const control of await page.locator(`.slides-native-ribbon > [data-ribbon-panel="${tab}"]`).locator('input,select,button').all()) {
            if (!await control.isVisible()) continue
            if (await control.isEnabled()) await control.focus()
            await control.scrollIntoViewIfNeeded()
            const state = await control.evaluate(node => {
              const r = node.getBoundingClientRect()
              return { label:node.getAttribute('aria-label') || node.title || node.textContent, disabled:node.disabled, focused:node === document.activeElement,
                exposed:[[r.x+3,r.y+3],[r.right-3,r.y+3],[r.x+3,r.bottom-3],[r.right-3,r.bottom-3]].every(([x,y]) => node.contains(document.elementFromPoint(x,y))) }
            })
            check((state.disabled || state.focused) && state.exposed, `${label}: ${tab}/${state.label}不能完整滚动访问`)
            ribbonStates.push(state)
          }
          check(ribbonStates.length > 0, `${label}: ${tab}功能区没有检查命令`)
          evidence.ribbonCases.push({ width,height,tab,states:ribbonStates })
        }
        await page.locator('[data-ribbon-tab="home"]').click()
        await page.locator('[data-ribbon-panel="home"]').evaluate(node => node.scrollTo({top:0,left:0,behavior:'instant'}))
        assert.deepEqual(await draft(), before)
      }
      const screenshots = []
      for (const [phase, control] of [['first', field()], ['last', pane.locator('[data-geometry-reference="y"]')]]) {
        await control.focus(); await control.scrollIntoViewIfNeeded()
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
        const visible = await control.evaluate(node => {
          const r = node.getBoundingClientRect()
          return { focused: node === document.activeElement, hit: node.contains(document.elementFromPoint(r.x+r.width/2, r.y+r.height/2)), y:r.y, bottom:r.bottom }
        })
        check(visible.focused && visible.hit && visible.y >= 0 && visible.bottom <= height+1, `${label}: ${phase}截图中的字段不可访问`)
        const file = `geometry-${target.type}-${viewport}-${phase}.png`
        await page.screenshot({ path: join(output, file) })
        screenshots.push({ phase, file, ...visible })
      }
      evidence.cases.push({ target: target.name, type: target.type, width, height, geometry, states, screenshots })
      evidence.interactions.push({ target: target.name, width, height, ratioFocused, referenceFocused, cancelled, fieldFocused, draftUnchanged: true, ime, readable, axeViolations:axe.violations })
      if (width >= 1000 && height >= 600) await pane.screenshot({ path: join(output, `geometry-${target.type}-${viewport}.png`) })
      await writeFile(join(output, 'geometry-layout.json'), JSON.stringify(evidence, null, 2))
    }
  }
  await page.setViewportSize({ width: 1440, height: 1100 })
  return evidence
}
