import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

export const commentsLongText = '保留的来源长批注😀 <&>：本季度收入、成本与预算执行情况均需结合完整来源解释。\n'.repeat(32)
export const commentsLongAuthor = 'Bob 鲍勃 · 经营分析与预算管理联合复核小组'

export async function inspectPptxCommentsLayout(page, { output, viewports, phase, readonly = false, draft }) {
  const evidence = { phase, cases: [], failures: [] }, original = await draft()
  const pane = () => page.locator('.slides-comments-pane'), input = () => pane().locator('[data-comment-text]')
  const action = name => pane().locator(`[data-comment-action="${name}"]`)
  const reopen = async () => { await page.locator('[data-ribbon-tab="review"]').click(); await page.locator('[data-command="commentsPane"]').click(); await pane().waitFor({ state: 'visible' }) }
  const inspect = async (label, width, height) => {
    const check = (ok, message) => { if (!ok) evidence.failures.push(`${label} ${width}x${height}: ${message}`) }
    const before = await draft()
    await pane().scrollIntoViewIfNeeded(); await page.evaluate(() => document.fonts.ready)
    const geometry = await pane().evaluate(node => {
      const r = node.getBoundingClientRect(), list = node.querySelector('.comments-list'), c = node.querySelector('[data-comment-action="close"]').getBoundingClientRect()
      return { x: r.x, right: r.right, width: r.width, horizontalOverflow: node.scrollWidth > node.clientWidth + 1,
        font: getComputedStyle(node).fontFamily, close: { width: c.width, height: c.height },
        texts: [...node.querySelectorAll('.comment-text')].map(text => ({ height: text.clientHeight, readonly: text.getAttribute('aria-readonly'), tabindex: text.tabIndex, overflow: getComputedStyle(text).overflowY })),
        controls: [...node.querySelectorAll('button,textarea')].map(control => { const b = control.getBoundingClientRect(); return { tag: control.tagName, x: b.x, right: b.right, height: b.height, font: getComputedStyle(control).fontFamily } }),
        authorTitles: [...node.querySelectorAll('.comment-author')].every(author => author.title === author.textContent), listHeight: list.clientHeight }
    })
    check(geometry.x >= 0 && geometry.right <= width + 1 && !geometry.horizontalOverflow, '窗格横向溢出')
    if (width === 640) check(geometry.width >= width - 32, '中屏窗格未占满可用列')
    check(geometry.close.width === 28 && geometry.close.height === 28, '标题关闭尺寸不符合PC主题')
    check(geometry.font.includes('Noto Sans') && geometry.controls.every(c => c.font.includes('Noto Sans')), '字体未继承Office主题')
    check(geometry.controls.every(c => c.x >= geometry.x && c.right <= geometry.right + 1 && (c.tag === 'TEXTAREA' ? c.height >= 64 && c.height <= 180 : c.height >= 28 && c.height <= 34)), '控件尺寸或横向边界错误')
    check(geometry.authorTitles, '完整作者名未进入提示')
    check(geometry.texts.every(t => t.readonly === 'true' && t.tabindex === 0 && t.height <= (height <= 400 ? 96 : 180) + 1 && ['auto','scroll'].includes(t.overflow)), '批注正文不可键盘阅读或未限制长文高度')
    const controls = await pane().locator('button:enabled,textarea:enabled,.comment-text').all(), reachability = []
    for (const control of controls) {
      await control.focus(); await page.keyboard.press('Tab'); await page.keyboard.press('Shift+Tab')
      await control.evaluate(node => node.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' }))
      const state = await control.evaluate(node => {
        const r = node.getBoundingClientRect(), s = getComputedStyle(node)
        const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)
        return { action: node.dataset.commentAction ?? node.getAttribute('aria-label') ?? node.tagName,
          focused: node === document.activeElement, hit: node.contains(hit), ring: s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 2,
          rect: { x: r.x, y: r.y, width: r.width, height: r.height }, hitElement: hit?.className?.baseVal ?? hit?.className ?? null }
      })
      check(state.focused && state.hit && state.ring, `${state.action}不可命中、聚焦或无焦点环`)
      if (await control.evaluate(node => node.classList.contains('comment-text') && node.scrollHeight > node.clientHeight + 1)) {
        await page.keyboard.press('End')
        check(await control.evaluate(node => node.scrollTop + node.clientHeight >= node.scrollHeight - 1), '长批注End未到末尾')
        await page.keyboard.press('Home')
        check(await control.evaluate(node => node.scrollTop <= 1), '长批注Home未返回开头')
        state.longTextScrolled = true
      }
      reachability.push(state)
    }
    evidence.cases.push({ label, width, height, geometry, reachability })
    await writeFile(resolve(output, `${phase}-layout-evidence.json`), JSON.stringify(evidence, null, 2))
    await action('close').scrollIntoViewIfNeeded()
    await page.screenshot({ path: resolve(output, `${phase}-${label}-${width}x${height}.png`) })
    await action('close').click(); check(await pane().isHidden(), '关闭后窗格仍可见')
    const opener = page.locator('[data-command="commentsPane"]')
    check(await opener.getAttribute('aria-pressed') === 'false' && await opener.evaluate(node => node === document.activeElement), '关闭未恢复入口状态和焦点')
    assert.deepEqual(await draft(), before)
    await reopen()
    await writeFile(resolve(output, `${phase}-layout-evidence.json`), JSON.stringify(evidence, null, 2))
  }
  const pendingText = '用于布局验收、结束后撤回的临时长批注。\n'.repeat(40)
  for (const viewport of viewports.split(',')) {
    const [width, height] = viewport.split('x').map(Number); await page.setViewportSize({ width, height })
    await inspect(readonly ? 'readonly' : 'source', width, height)
    if (readonly) {
      assert.equal(await pane().locator('[data-comment-action="delete"]:enabled,[data-comment-action="compose"],[data-comment-text]').count(), 0)
      continue
    }
    const kept = pane().locator('[data-comment-author-id="1"][data-comment-idx="1"] .comment-text')
    assert.equal(await kept.textContent(), commentsLongText)
    await page.locator('[data-command="newComment"]').click()
    assert.equal(await action('add').isDisabled(), true)
    await input().evaluate(node => { node.value = 'x'.repeat(10001); node.dispatchEvent(new Event('input', { bubbles: true })) })
    assert.equal(await action('add').isDisabled(), true)
    // Continue collecting the visual evidence even on the unadapted baseline.
    if (await input().getAttribute('aria-invalid') !== 'true') evidence.failures.push(`${viewport}: 无效输入缺少aria-invalid`)
    assert.ok((await pane().locator('.comments-status').textContent()).includes('10000'))
    await input().fill(pendingText); await inspect('composer', width, height)
    assert.equal(await input().inputValue(), pendingText)
    await action('cancel').click()
    if (!await action('compose').evaluate(node => node === document.activeElement)) evidence.failures.push(`${viewport}: 取消编辑后焦点丢失`)
    assert.deepEqual(await draft(), original)
    await action('compose').click(); await input().fill(pendingText); await action('add').click()
    if (!await action('compose').evaluate(node => node === document.activeElement)) evidence.failures.push(`${viewport}: 发布后焦点丢失`)
    const added = pane().locator('[data-comment-client-id]'); assert.equal(await added.locator('.comment-text').textContent(), pendingText)
    await inspect('pending', width, height)
    await pane().locator('[data-comment-client-id] [data-comment-action="withdraw"]').click()
    assert.deepEqual(await draft(), original)
    await page.locator('.slide-open').nth(1).click(); await action('delete').click()
    assert.equal(await pane().locator('.comment-card').count(), 0)
    await inspect('empty', width, height)
    await page.locator('[data-source-action="onUndo"]').click(); assert.deepEqual(await draft(), original)
    await page.locator('.slide-open').nth(0).click()
  }
  await page.setViewportSize({ width: 1600, height: 1100 })
  assert.deepEqual(await draft(), original)
  await writeFile(resolve(output, `${phase}-layout-evidence.json`), JSON.stringify(evidence, null, 2))
  assert.deepEqual(evidence.failures, [], JSON.stringify(evidence.failures))
  return evidence
}
