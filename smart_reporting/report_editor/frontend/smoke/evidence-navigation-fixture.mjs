// 仅用于 fixture-server：验证 v6 导航和移动图，不测试真实后端权限。
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'

const browser = await chromium.launch({ headless: true })
const output = new URL('../../../../output/', import.meta.url)
const editorUrl = process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1'
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(editorUrl, { waitUntil: 'networkidle' })
  await page.locator('[data-action="sources"]').click()
  await page.locator('.evidence-directory-item', { hasText: '正文引用' }).click()
  await page.getByRole('button', { name: '展开', exact: true }).click()
  await page.getByRole('button', { name: '切换到 2D 关系图', exact: true }).click()
  const initialPositions = await page.locator('.evidence-node').evaluateAll(nodes =>
    Object.fromEntries(nodes.map(node => [node.dataset.evidenceNode, [node.style.left, node.style.top]])),
  )
  await page.locator('.evidence-subject-links button', { hasText: '事实' }).click()
  await page.locator('[data-evidence-node="computation:comp-fixture-001"]').waitFor({ state: 'visible' })
  await page.locator('[data-evidence-node="computation:comp-fixture-001"]').press('Enter')
  await page.locator('[data-evidence-node="dataset:dataset-fixture-001"]').press('Enter')
  await page.locator('.evidence-object-title', { hasText: '收入明细.csv' }).waitFor()
  const loadedPositions = await page.locator('.evidence-node').evaluateAll(nodes =>
    Object.fromEntries(nodes.map(node => [node.dataset.evidenceNode, [node.style.left, node.style.top]])),
  )
  for (const [id, position] of Object.entries(initialPositions)) assert.deepEqual(loadedPositions[id], position)
  assert.equal(Object.keys(loadedPositions).length, 4, '同一任务应累计引用、事实、计算与快照')
  await page.setViewportSize({ width: 390, height: 844 })
  // 在旧历史页展开累计图，保存独立滚动现场。
  await page.locator('.evidence-relations-toggle').click()
  const viewport = page.locator('.evidence-graph-scroll')
  await viewport.evaluate(node => { node.scrollLeft = 100; node.dispatchEvent(new Event('scroll')) })
  const scrollLeft = await viewport.evaluate(node => node.scrollLeft)
  assert.ok(scrollLeft > 0, 'fixture 图应可横向滚动')
  const handle = page.locator('.evidence-column-resize').first()
  await handle.focus()
  await handle.press('ArrowRight')
  const boxHandle = await handle.boundingBox()
  await page.mouse.move(boxHandle.x + boxHandle.width / 2, boxHandle.y + boxHandle.height / 2)
  await page.mouse.down()
  await page.mouse.move(boxHandle.x + boxHandle.width / 2 + 30, boxHandle.y + boxHandle.height / 2)
  await page.mouse.up()
  assert.equal(await page.locator('.evidence-table col').first().evaluate(node => node.style.width), '184px')
  await page.locator('.evidence-filter').fill('华北')
  await page.locator('.evidence-more').click()
  await page.locator('.evidence-dataset-scope', { hasText: '第 2 页' }).waitFor()
  assert.ok((await page.locator('.evidence-filter-count').textContent()).includes('本页匹配 2 / 2 行'))
  await page.locator('.evidence-table-wrap').evaluate(node => { node.scrollLeft = 60; node.dispatchEvent(new Event('scroll')) })
  await page.locator('.evidence-path-picker summary').click()
  const pathItems = page.locator('.evidence-path-items button')
  assert.equal(await pathItems.count(), 4, '完整路径不能遗漏折叠项')
  assert.equal(await page.locator('.evidence-crumb-middle').first().isVisible(), false)
  await mkdir(output, { recursive: true })
  await page.screenshot({ path: new URL('report-editor-v6-mobile-path.png', output).pathname })
  await pathItems.nth(2).click()
  await page.locator('.evidence-object-title', { hasText: '渠道收入汇总' }).waitFor()
  await page.locator('[data-evidence="back"]').click()
  await page.locator('.evidence-object-title', { hasText: '收入明细.csv' }).waitFor()
  assert.equal(await page.locator('.evidence-graph-scroll').evaluate(node => node.scrollLeft), scrollLeft, '后退应恢复该历史页图滚动')
  assert.ok((await page.locator('.evidence-dataset-scope').textContent()).includes('第 2 页'))
  assert.equal(await page.locator('.evidence-filter').inputValue(), '华北')
  assert.equal(await page.locator('.evidence-table col').first().evaluate(node => node.style.width), '184px')
  assert.equal(await page.locator('.evidence-table-wrap').evaluate(node => node.scrollLeft), 60)
  await page.reload({ waitUntil: 'networkidle' })
  await page.locator('[data-action="more"]').click()
  await page.locator('[data-action="sources"]').click()
  await page.locator('.evidence-dataset-scope', { hasText: '第 2 页' }).waitFor()
  assert.equal(await page.locator('.evidence-filter').inputValue(), '华北')
  assert.equal(await page.locator('.evidence-table col').first().evaluate(node => node.style.width), '184px')
  assert.equal(await page.locator('.evidence-table-wrap').evaluate(node => node.scrollLeft), 60)
  await page.locator('.evidence-task-picker summary').click()
  assert.notEqual(await page.locator('.evidence-task-picker').getAttribute('open'), null)
  await page.keyboard.press('Escape')
  assert.equal(await page.locator('.evidence-task-picker').getAttribute('open'), null)
  await page.locator('.evidence-directory-toggle').click()
  await page.locator('.evidence-directory-item', { hasText: '渠道收入汇总' }).click()
  await page.getByRole('button', { name: '查看关系图', exact: true }).click()
  const full = page.locator('.evidence-relations.is-graph-view')
  await full.waitFor({ state: 'visible' })
  await full.getByRole('button', { name: '切换到 2D 关系图', exact: true }).click()
  await page.locator('.evidence-node').first().waitFor({ state: 'visible' })
  assert.equal(await page.locator('.evidence-node').count(), 3, '目录新任务不能混入其他任务的图上下文')
  const box = await full.boundingBox()
  assert.ok(Math.abs(box.width - 390) <= 1 && Math.abs(box.y + box.height - 844) <= 1)
  await full.locator('[aria-label="适应关系图"]').click()
  const fitResult = await full.locator('.evidence-graph-scroll').evaluate(scroll => {
    const bounds = scroll.getBoundingClientRect()
    const map = scroll.querySelector('.evidence-graph-map')
    return {
      scale: Number(map.style.transform.match(/scale\(([^)]+)\)/)?.[1] ?? 1),
      nodesVisible: [...map.querySelectorAll('.evidence-node')].every(node => {
        const rect = node.getBoundingClientRect()
        return rect.left >= bounds.left && rect.right <= bounds.right
      }),
    }
  })
  const fittedScale = fitResult.scale
  assert.ok(fittedScale < 1, `390px 图视图应收缩宽图，实际缩放 ${fittedScale}`)
  assert.ok(fitResult.nodesVisible, '适应视图后全部节点应位于图视口内')
  await page.screenshot({ path: new URL('report-editor-v6-mobile-graph-fit.png', output).pathname })
  await full.locator('[aria-label="放大关系图"]').click()
  await full.locator('.evidence-node').nth(1).click()
  await full.locator('.evidence-preview', { hasText: '预览：' }).waitFor()
  await page.keyboard.press('Escape')
  await full.waitFor({ state: 'visible' })
  await full.locator('.evidence-preview', { hasText: '选择节点' }).waitFor()
  assert.equal(await full.locator('.evidence-node-tag[hidden]').first().isVisible(), false)
  await page.screenshot({ path: new URL('report-editor-v6-mobile-graph.png', output).pathname })
  await full.getByRole('button', { name: '返回详情', exact: true }).click()
  await page.waitForFunction(() => document.activeElement?.classList.contains('evidence-mobile-graph-open'))
  const sizes = await page.evaluate(() => [innerWidth, document.documentElement.scrollWidth])
  assert.equal(sizes[1], sizes[0], '390px 证据页不能出现整页横向溢出')
  // 让 fixture 保存失败，确认未保存内容与正文选区在证据切换中保留。
  await page.locator('.evidence-tab-report').click()
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.route('**/api/document', route => route.request().method() === 'PUT'
    ? route.fulfill({ status: 503, json: { detail: { code: 'fixture-save-unavailable' } } }) : route.continue())
  const editor = page.locator('.ProseMirror')
  await editor.click()
  await page.keyboard.press('Control+End')
  await page.keyboard.type('现场草稿')
  await editor.evaluate(node => {
    node.style.minHeight = '1800px'
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT)
    let text
    while ((text = walker.nextNode())) {
      const start = text.textContent.indexOf('现场草稿')
      if (start < 0) continue
      const range = document.createRange()
      range.setStart(text, start)
      range.setEnd(text, start + 4)
      const selection = window.getSelection()
      selection.removeAllRanges()
      selection.addRange(range)
      break
    }
    window.scrollTo({ top: 180, behavior: 'auto' })
  })
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  assert.equal(await page.evaluate(() => window.getSelection().toString()), '现场草稿')
  const editorTop = await page.evaluate(() => scrollY)
  await page.locator('[data-action="sources"]').click()
  await page.locator('.evidence-object-title').waitFor({ state: 'visible' })
  await page.locator('.evidence-tab-report').click()
  assert.equal(await page.evaluate(() => window.getSelection().toString()), '现场草稿')
  assert.equal(await page.evaluate(() => scrollY), editorTop)
  assert.ok((await editor.innerText()).includes('现场草稿'))
  const saved = await (await page.request.get(`${editorUrl}/api/document`)).json()
  assert.equal(saved.markdown.includes('现场草稿'), false)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ evidenceNavigation: 'passed', mobileWidth: sizes[0], screenshots: output.pathname }))
} finally {
  await browser.close()
}
