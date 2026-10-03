// 5/9/15节点的全图可读性检查；截图需人工审查，无页面溢出不代表标签没有重叠。
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'

const output = new URL('../../../../output/', import.meta.url)
const suffix = process.env.REPORT_EDITOR_SCREENSHOT_SUFFIX ?? ''
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true })
try {
  for (const count of [5, 9, 15]) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    const inputs = Array.from({ length: count - 3 }, (_, i) => `月度收入成本口径调整输入-${i + 1}`)
    await page.route('**/api/facts/**', route => {
      const factId = decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-1))
      return route.fulfill({ json: {
        analysisId: 'analysis-fixture-001', factId, factKind: 'metric', displayValue: 12450,
        entry: { unit: '万元' }, warnings: [],
        inputFactRefs: factId === 'fact-fixture-001'
          ? inputs.map(factId => ({ analysisId: 'analysis-fixture-001', factId })) : [],
      } })
    })
    await page.goto(process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
    await page.locator('[data-action="sources"]').click()
    await page.locator('.evidence-directory-item', { hasText: '正文引用' }).click()
    await page.locator('.evidence-subject-links button', { hasText: '事实' }).click()
    const canvas = page.locator('.evidence-graph-3d canvas')
    await canvas.waitFor()
    assert.equal(await page.getByRole('combobox', { name: '选择 3D 节点预览' }).locator('option').count(), count + 1)
    for (const [width, height] of [[1280, 900], [390, 844], [844, 390]]) {
      await page.setViewportSize({ width, height })
      if (width === 390) await page.getByRole('button', { name: '查看关系图', exact: true }).click()
      for (let angle = 0; angle < 3; angle++) {
        if (angle) {
          const bounds = await canvas.boundingBox()
          await page.mouse.move(bounds.x + 10, bounds.y + 10)
          await page.mouse.down()
          await page.mouse.move(bounds.x + 65, bounds.y + 35, { steps: 8 })
          await page.mouse.up()
        }
        await page.getByRole('button', { name: '适应 3D', exact: true }).click()
        await page.waitForTimeout(650)
        const bounds = await canvas.boundingBox()
        await page.mouse.move(bounds.x + 2, bounds.y + 2)
        await page.waitForTimeout(150)
        assert.equal((await page.locator('.evidence-graph-3d').getAttribute('data-hovered')) ?? '', '', '全图截图清除临时悬停追踪')
        await page.locator('.evidence-relations').screenshot({ path: new URL(`report-editor-v6-small-3d-${count}-${width}-angle-${angle}${suffix}.png`, output).pathname })
        const clipped = await page.evaluate(async png => {
          const image = new Image()
          image.src = `data:image/png;base64,${png}`
          await image.decode()
          const probe = document.createElement('canvas')
          probe.width = image.width
          probe.height = image.height
          const context = probe.getContext('2d')
          context.drawImage(image, 0, 0)
          const { data } = context.getImageData(0, 0, probe.width, probe.height)
          const ink = (x, y) => [247, 251, 253].some((value, channel) =>
            Math.abs(data[(y * probe.width + x) * 4 + channel] - value) > 2)
          for (let x = 2; x < probe.width - 2; x++) {
            if (ink(x, 2) || ink(x, probe.height - 3)) return true
          }
          for (let y = 2; y < probe.height - 2; y++) {
            if (ink(2, y) || ink(probe.width - 3, y)) return true
          }
          return false
        }, (await canvas.screenshot()).toString('base64'))
        assert.equal(clipped, false, `${count}节点/${width}px/角度${angle}名称与图形不触及画布四边`)
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
      }
    }
    assert.deepEqual(errors, [])
    await page.close()
  }
  console.log(JSON.stringify({ nodes: [5, 9, 15], viewports: [1280, 390, 844], angles: 3, readability: 'manual review required' }))
} finally {
  await browser.close()
}
