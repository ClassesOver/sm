// 首次打开不操作相机，随后核对手动适应及隐藏/重建的现场恢复。
import assert from 'node:assert/strict'
import { chromium } from 'playwright'

const browser = await chromium.launch({ headless: true })
try {
  for (const width of [1280, 390]) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.goto(process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
    await page.locator('[data-action="sources"]').click()
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
    if (width === 390) await page.locator('.evidence-directory-toggle').click()
    await page.locator('.evidence-directory-item', { hasText: '正文引用' }).click()
    // 图先在收起区挂载，布局就绪后再打开；不能提前按隐藏容器尺寸初始化相机。
    await page.waitForTimeout(300)
    await page.getByRole('button', { name: width === 390 ? '查看关系图' : '展开', exact: true }).click()
    const canvas = page.locator('.evidence-graph-3d canvas')
    await canvas.waitFor()
    await page.waitForTimeout(650)
    const extent = await page.evaluate(async png => {
      const image = new Image()
      image.src = `data:image/png;base64,${png}`
      await image.decode()
      const probe = document.createElement('canvas')
      probe.width = image.width
      probe.height = image.height
      const context = probe.getContext('2d')
      context.drawImage(image, 0, 0)
      const { data } = context.getImageData(0, 0, probe.width, probe.height)
      let top = probe.height
      let bottom = -1
      for (let y = 2; y < probe.height - 2; y++) {
        for (let x = 2; x < probe.width - 2; x++) {
          const offset = (y * probe.width + x) * 4
          if ([247, 251, 253].some((value, channel) => Math.abs(data[offset + channel] - value) > 10)) {
            top = Math.min(top, y)
            bottom = Math.max(bottom, y)
          }
        }
      }
      return { ratio: (bottom - top) / probe.height, top, bottom, height: probe.height }
    }, (await canvas.screenshot()).toString('base64'))
    assert.equal(extent.top > 2 && extent.bottom < extent.height - 3, true, '初始图形未触及上下边界')
    assert.equal(extent.ratio >= (width === 1280 ? 0.45 : 0.2), true, `${width}px指定小图初始画面占用范围：${JSON.stringify(extent)}`)
    await page.locator('.evidence-relations').screenshot({ path: new URL(`../../../../output/report-editor-v6-3d-initial-${width}.png`, import.meta.url).pathname })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
    assert.equal(await canvas.evaluate(node => node.getBoundingClientRect().height > 100), true)
    // 预览/关闭缓存节点，避免把继续运行的力布局当成视角改变。
    const picker = page.getByRole('combobox', { name: '选择 3D 节点预览' })
    await picker.selectOption('computation:comp-fixture-001')
    await page.getByRole('button', { name: '关闭预览', exact: true }).click()
    await canvas.waitFor()
    await page.waitForTimeout(250)
    await page.getByRole('button', { name: '适应 3D', exact: true }).click()
    await page.waitForTimeout(650)
    // 初次力布局仍会继续收敛，手动适应可调整到新的范围，不能要求两个时刻像素相同。
    const fitted = await canvas.screenshot()
    await page.getByRole('button', { name: '放大关系图', exact: true }).click()
    await page.waitForTimeout(250)
    const zoomed = await canvas.screenshot()
    assert.equal(fitted.equals(zoomed), false)
    await page.getByRole('button', { name: '切换到关系列表', exact: true }).click()
    await page.getByRole('button', { name: '切换到关系图', exact: true }).click()
    await canvas.waitFor()
    await page.waitForTimeout(250)
    assert.equal(zoomed.equals(await canvas.screenshot()), true, '重新显示不覆盖用户缩放')
    await picker.selectOption('computation:comp-fixture-001')
    await page.getByRole('button', { name: '关闭预览', exact: true }).click()
    await canvas.waitFor()
    await page.waitForTimeout(250)
    assert.equal(zoomed.equals(await canvas.screenshot()), true, '组件重建恢复历史视角')
    assert.deepEqual(errors, [])
    await page.close()
  }
  console.log(JSON.stringify({ initialFit: 'passed', hiddenMount: 'passed', userZoom: 'passed', rebuild: 'passed' }))
} finally {
  await browser.close()
}
