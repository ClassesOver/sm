// 固定 fixture：节点分支展开保留页面、已知图与失败重试。
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'

const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  let attempts = 0
  let release
  const longName = process.env.REPORT_EDITOR_LONG_PREVIEW === '1'
  const computationId = longName ? '华东地区各院区月度营业收入汇总与同期口径调整计算_用于核对登记输入和输出的详细计算名称' : 'comp-fixture-001'
  if (longName) await page.route('**/api/sources', async route => {
    const response = await route.fetch()
    const json = await response.json()
    json.subjects[0].computationId = computationId
    await route.fulfill({ response, json })
  })
  await page.route('**/api/computations/*?*', async route => {
    attempts += 1
    if (attempts === 1) return route.fulfill({ status: 409, json: { detail: { code: 'snapshot_integrity_failed' } } })
    await new Promise(resolve => { release = resolve })
    const response = await route.fetch({ url: route.request().url().replace(encodeURIComponent(computationId), 'comp-fixture-001') })
    return route.fulfill({ response, json: { ...await response.json(), computationId } })
  })
  await page.goto(process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
  const output = new URL('../../../../output/', import.meta.url)
  await mkdir(output, { recursive: true })
  let mobileMapHeight
  const auditPreview = async stage => {
    if (!longName) return
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
      if (width === 390 && !await page.locator('.evidence-relations.is-graph-view').count()) {
        await page.getByRole('button', { name: '查看关系图', exact: true }).click()
      }
      if (stage === 'empty') assert.equal(await page.locator('.evidence-preview-summary').count(), 0)
      else assert.equal(await page.locator('.evidence-preview-summary strong').textContent(), `预览：${computationId}`)
      const bounds = await page.locator('.evidence-preview').evaluate(preview => {
        const box = preview.getBoundingClientRect()
        const buttons = [...preview.querySelectorAll('button')].map(button => button.getBoundingClientRect())
        return {
          inside: buttons.every(button => button.left >= box.left && button.right <= box.right && button.top >= box.top && button.bottom <= box.bottom),
          separate: buttons.every((a, i) => buttons.slice(i + 1).every(b => a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top)),
          mapHeight: document.querySelector('.evidence-graph-scroll').clientHeight,
        }
      })
      assert.equal(bounds.inside, true, `${stage}/${width}: 预览控件应完整可见`)
      assert.equal(bounds.separate, true, `${stage}/${width}: 按钮不可重叠`)
      assert.ok(bounds.mapHeight > 100, `${stage}/${width}: 保留关系图操作空间`)
      if (width === 390) {
        if (mobileMapHeight === undefined) mobileMapHeight = bounds.mapHeight
        else assert.equal(bounds.mapHeight, mobileMapHeight, `${stage}: 状态切换不挤压画布`)
      }
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
      await page.locator('.evidence-relations').screenshot({ path: new URL(`report-editor-v6-preview-${stage}-${width}.png`, output).pathname })
    }
    await page.setViewportSize({ width: 1280, height: 900 })
  }
  await page.locator('[data-action="sources"]').click()
  await page.locator('.evidence-directory-item', { hasText: '正文引用' }).click()
  await page.getByRole('button', { name: '展开', exact: true }).click()
  const positions = () => page.locator('.evidence-node').evaluateAll(nodes => Object.fromEntries(
    nodes.map(node => [node.dataset.evidenceNode, [node.style.left, node.style.top]])))
  const original = await positions()
  const title = await page.locator('.evidence-object-title').textContent()
  await auditPreview('empty')
  const computationNode = page.locator(`[data-evidence-node="computation:${computationId}"]`)
  await computationNode.click()
  await auditPreview('selected')
  await page.locator('.evidence-branch-load').click()
  await page.getByRole('button', { name: '重试加载关系', exact: true }).waitFor()
  await auditPreview('error')
  assert.deepEqual(await positions(), original)
  await page.locator('.evidence-branch-load').click()
  await page.getByRole('button', { name: '关系加载中…', exact: true }).waitFor()
  assert.equal(await page.locator('.evidence-branch-load').isEnabled(), false)
  await page.waitForFunction(() => document.querySelector('.evidence-node.is-selected')?.textContent.includes('关系加载中'))
  await auditPreview('loading')
  while (!release) await new Promise(resolve => setTimeout(resolve, 20))
  release()
  await page.getByRole('button', { name: '已加载登记关系', exact: true }).waitFor()
  await auditPreview('loaded')
  assert.equal(await page.locator('.evidence-node').count(), 4)
  const expanded = await positions()
  for (const [id, position] of Object.entries(original)) assert.deepEqual(expanded[id], position)
  assert.equal(await page.locator('.evidence-object-title').textContent(), title)
  assert.equal(await page.locator('[data-evidence="back"]').isEnabled(), false)
  assert.equal(attempts, 2)
  await page.locator('.evidence-relations-toggle').click()
  await page.locator('.evidence-relations-toggle').click()
  assert.equal(await page.locator('.evidence-node').count(), 4)
  await page.locator('.evidence-relations').screenshot({ path: new URL('report-editor-v6-branch.png', output).pathname })
  await page.setViewportSize({ width: 390, height: 844 })
  if (!await page.locator('.evidence-relations.is-graph-view').count()) await page.getByRole('button', { name: '查看关系图', exact: true }).click()
  await page.getByRole('button', { name: '已加载登记关系', exact: true }).waitFor()
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  await page.screenshot({ path: new URL('report-editor-v6-branch-mobile.png', output).pathname })
  await page.getByRole('button', { name: '关闭预览', exact: true }).click()
  assert.equal(await computationNode.evaluate(node => node === document.activeElement), true)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ branchLoading: 'passed', longName, previewFocus: 'passed', attempts, nodes: 4 }))
} finally {
  await browser.close()
}
