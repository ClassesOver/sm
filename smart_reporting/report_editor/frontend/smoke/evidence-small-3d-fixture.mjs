// 5/9/15节点的全图可读性检查；截图需人工审查，无页面溢出不代表标签没有重叠。
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { chromium } from 'playwright'

const output = new URL('../../../../output/', import.meta.url)
const suffix = process.env.REPORT_EDITOR_SCREENSHOT_SUFFIX ?? ''
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true })
const collisions = []
const geometry = []
try {
  for (const count of [5, 9, 15]) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    // 读取原生Sprite实际投影，而不是将应用布局结果当作验收答案；保留原生拾取。
    await page.route('**/assets/evidence-3d-primitives-*.js', async route => {
      const response = await route.fetch()
      const source = await response.text()
      const sprite = source.match(/(\w+) as Sprite(?:,|})/)
      assert.ok(sprite, '原生Sprite导出可供投影检查')
      await route.fulfill({ response, body: `${source}\n
        window.graphLabelBounds = new Map();
        const nativeSpriteRaycast = ${sprite[1]}.prototype.raycast;
        ${sprite[1]}.prototype.raycast = function(raycaster, intersects) {
          const result = nativeSpriteRaycast.call(this, raycaster, intersects);
          const id = this.parent?.parent?.__data?.id;
          const canvas = document.querySelector('.evidence-graph-3d canvas');
          if (this.text && id && canvas && this.visible) {
            const size = canvas.getBoundingClientRect();
            const camera = raycaster.camera;
            const world = this.position.clone().setFromMatrixPosition(this.matrixWorld);
            const depth = -world.clone().applyMatrix4(camera.matrixWorldInverse).z;
            const point = world.project(camera);
            const scale = this.scale.clone().setFromMatrixScale(this.matrixWorld);
            const factor = size.height / (2 * Math.tan(camera.fov * Math.PI / 360)) / (this.material.sizeAttenuation ? depth : 1);
            const width = scale.x * factor, height = scale.y * factor;
            const x = (point.x + 1) * size.width / 2, y = (1 - point.y) * size.height / 2;
            window.graphLabelBounds.set(id, { id, x: x - this.center.x * width, y: y - (1 - this.center.y) * height, width, height, nodeX: x, nodeY: y });
          }
          return result;
        };
      ` })
    })
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
        const overlap = await page.evaluate(() => {
          const labels = [...window.graphLabelBounds.values()]
          const area = (a, b) => Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x)) *
            Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y))
          return { labels: labels.length, bounds: labels,
            names: labels.flatMap((a, i) => labels.slice(i + 1).filter(b => area(a, b) > 1).map(b => [a.id, b.id])),
            icons: labels.flatMap(a => labels.filter(b => area(a, { x: b.nodeX - 7, y: b.nodeY - 7, width: 14, height: 14 }) > 1).map(b => [a.id, b.id])) }
        })
        assert.equal(overlap.labels, count, '全部节点名称保留并参与原生投影检查')
        collisions.push({ count, width, angle, names: overlap.names.length, icons: overlap.icons.length })
        geometry.push({ count, width, angle, canvasWidth: bounds.width, canvasHeight: bounds.height, ...overlap })
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
  console.log(JSON.stringify({ nodes: [5, 9, 15], viewports: [1280, 390, 844], angles: 3, collisions, readability: 'manual review required' }))
  await writeFile(new URL(`report-editor-v6-small-3d${suffix}-geometry.json`, output), `${JSON.stringify(geometry, null, 2)}\n`)
} finally {
  await browser.close()
}
