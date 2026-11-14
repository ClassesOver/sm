// 完整冻结 native 宿主；真实来源图表经 UI 打开窗口，不直接构造组件或提交业务草稿。
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { createSlidesPanelsNativeFixture } from './slides-panels-native-fixture.mjs'

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
assert.ok(process.env.SLIDES_CHART_NATIVE_STATIC && process.env.SLIDES_CHART_NATIVE_MANIFEST && process.env.SLIDES_CHART_NATIVE_DIRECTORY,
  '显式指定 SLIDES_CHART_NATIVE_STATIC、SLIDES_CHART_NATIVE_MANIFEST、SLIDES_CHART_NATIVE_DIRECTORY')
const output = resolve(process.env.SLIDES_CHART_NATIVE_DIRECTORY); await mkdir(output, { recursive: true })
const fixture = await createSlidesPanelsNativeFixture({ frontend, staticRoot: resolve(process.env.SLIDES_CHART_NATIVE_STATIC),
  expectedManifest: process.env.SLIDES_CHART_NATIVE_MANIFEST,
  sourcePath: resolve(process.env.SLIDES_CHART_NATIVE_SOURCE ?? '/dev/shm/office-pptx-palette-guides-chart-built-20261112/source.pptx'), targetType: 'chart' })
const evidence = { scope: 'Complete frozen native PPTX host; actual source chart via context/file/preview/render-tree Python+Node routes, UI selection and chart-data command. Fixture authorization; no save/download or chart confirmation.', cases: [], errors: [] }
let browser, page
try {
  await fixture.server.listen(); browser = await chromium.launch({ headless: true }); page = await browser.newPage()
  page.on('pageerror', error => evidence.errors.push(error.message)); await fixture.setup(page)
  const initial = fixture.target, data = { categories: initial.chartCategories, series: initial.chartSeries }
  const expectedCurrent = async dialog => {
    assert.equal(await dialog.locator('[data-chart-category="0"]').inputValue(), data.categories[0])
    assert.equal(await dialog.locator('[data-chart-series="0"]').inputValue(), data.series[0].name)
    assert.equal(await dialog.locator('[data-chart-value="0:0"]').inputValue(), String(data.series[0].values[0]))
    assert.equal(await dialog.locator('[data-chart-value="1:1"]').inputValue(), String(data.series[1].values[1]))
  }
  const opener = () => page.locator('[data-command="chartData"]')
  for (const [width, height] of [[1440, 900], [320, 640], [640, 360], [390, 320]]) {
    await page.setViewportSize({ width, height }); await fixture.open(page)
    await page.locator('[data-ribbon-tab="chartDesign"]').click(); assert.equal(await opener().isEnabled(), true)
    const before = await fixture.draft(page)
    for (const kind of ['category', 'series']) for (const action of ['add', 'remove']) {
      await opener().click(); const dialog = page.getByRole('dialog', { name: '编辑图表数据', exact: true })
      await expectedCurrent(dialog); await dialog.locator('[data-chart-value="0:0"]').fill('27.5')
      const count = kind === 'category' ? data.categories.length : data.series.length
      const button = action === 'add' ? dialog.locator(`[data-chart-add-${kind}]`) : dialog.locator(`[data-chart-${kind}="1"]`).locator('..').getByRole('button', { name: kind === 'category' ? '删除类别' : '删除系列', exact: true })
      await button.focus(); await page.keyboard.press('Enter')
      const index = action === 'add' ? count : Math.min(1, count - 2), input = dialog.locator(`[data-chart-${kind}="${index}"]`)
      const focus = await input.evaluate(node => { const r = node.getBoundingClientRect(); return { focused: node === document.activeElement, value: node.value, x: r.x, y: r.y, right: r.right, bottom: r.bottom, hit: node === document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2) } })
      assert.ok(focus.focused && focus.hit && focus.x >= 0 && focus.y >= 0 && focus.right <= width + 1 && focus.bottom <= height + 1, JSON.stringify({ width, height, kind, action, focus }))
      assert.equal(await dialog.locator('[data-chart-value="0:0"]').inputValue(), '27.5')
      await page.screenshot({ path: resolve(output, `${kind}-${action}-${width}x${height}.png`) })
      await dialog.getByRole('button', { name: '取消', exact: true }).click(); assert.equal(await opener().evaluate(node => document.activeElement === node), true)
      assert.deepEqual(await fixture.draft(page), before)
      await opener().click(); await expectedCurrent(page.getByRole('dialog', { name: '编辑图表数据', exact: true })); await page.keyboard.press('Escape')
      assert.deepEqual(await fixture.draft(page), before)
      evidence.cases.push({ width, height, kind, action, focus, currentValue: '27.5', cancelDraftUnchanged: true, reopenedSourceValues: true })
    }
  }
  assert.deepEqual(evidence.errors, []); evidence.native = await fixture.finish(); evidence.ok = true
  await writeFile(resolve(output, 'evidence.json'), JSON.stringify(evidence, null, 2))
  console.log(JSON.stringify({ ok: true, cases: evidence.cases.length, resources: Object.keys(evidence.native.resources).length, saveRequests: evidence.native.saveRequests, downloadEvents: evidence.native.downloadEvents }))
} catch (error) {
  await page?.screenshot({ path: resolve(output, 'failure.png') }).catch(() => {})
  await writeFile(resolve(output, 'failure.json'), JSON.stringify({ error: String(error), stack: error.stack, evidence }, null, 2)); throw error
} finally { await browser?.close(); await fixture.server.close() }
