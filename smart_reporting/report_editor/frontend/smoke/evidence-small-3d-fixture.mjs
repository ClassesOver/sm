// 5/9/15节点的全图可读性检查；截图需人工审查，无页面溢出不代表标签没有重叠。
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { chromium, firefox } from 'playwright'

const output = new URL('../../../../output/', import.meta.url)
const state = process.env.REPORT_EDITOR_SMALL_STATE ?? 'none'
assert.ok(['none', 'preview', 'pair', 'preview-relations', 'hub-preview', 'hub-relations', 'hub-star-relations'].includes(state))
const engine = process.env.REPORT_EDITOR_BROWSER ?? 'chromium'
assert.ok(['chromium', 'firefox'].includes(engine), `Unsupported browser: ${engine}`)
const hub = state.startsWith('hub-')
const indirectBranch = hub && state !== 'hub-star-relations'
const suffix = `${state === 'none' ? '' : `-${state}`}${process.env.REPORT_EDITOR_SCREENSHOT_SUFFIX ?? ''}`
await mkdir(output, { recursive: true })
const browser = await ({ chromium, firefox })[engine].launch({ headless: true })
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
          if (this.text && id && canvas && this.visible && this.parent.parent.visible) {
            const size = canvas.getBoundingClientRect();
            const camera = raycaster.camera;
            window.graphCamera = { position: camera.position.toArray(), quaternion: camera.quaternion.toArray(), up: camera.up.toArray(), aspect: camera.aspect };
            const world = this.position.clone().setFromMatrixPosition(this.matrixWorld);
            const depth = -world.clone().applyMatrix4(camera.matrixWorldInverse).z;
            const point = world.project(camera);
            const scale = this.scale.clone().setFromMatrixScale(this.matrixWorld);
            const factor = size.height / (2 * Math.tan(camera.fov * Math.PI / 360)) / (this.material.sizeAttenuation ? depth : 1);
            const width = scale.x * factor, height = scale.y * factor;
            const x = (point.x + 1) * size.width / 2, y = (1 - point.y) * size.height / 2;
            const links = this.parent.parent.parent.children.filter(object => object.__graphObjType === 'link');
            window.graphVisibleLinks = links.filter(object => object.visible).map(object => [object.__data.source.id, object.__data.target.id]);
            const icon = this.parent.children.find(object => object !== this && object.isSprite);
            window.graphLabelBounds.set(id, { id, text: this.text, x: x - this.center.x * width, y: y - (1 - this.center.y) * height, width, height, nodeX: x, nodeY: y,
              textOrder: this.renderOrder, iconOrder: icon?.renderOrder, linkOrder: links.length ? Math.max(...links.map(object => object.renderOrder)) : null });
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
        inputFactRefs: (factId === 'fact-fixture-001' ? indirectBranch ? inputs.slice(0, -1) : inputs
          : indirectBranch && factId === inputs[0] ? [inputs.at(-1)] : [])
          .map(factId => ({ analysisId: 'analysis-fixture-001', factId })),
      } })
    })
    await page.goto(process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
    await page.locator('[data-action="sources"]').click()
    await page.locator('.evidence-directory-item', { hasText: '正文引用' }).click()
    await page.locator('.evidence-subject-links button', { hasText: '事实' }).click()
    const canvas = page.locator('.evidence-graph-3d canvas')
    const picker = page.getByRole('combobox', { name: '选择 3D 节点预览' })
    const trace = page.getByRole('combobox', { name: '追踪预览关系端点' })
    const rootId = 'fact:analysis-fixture-001/fact-fixture-001'
    const leafId = `fact:analysis-fixture-001/${inputs[0]}`
    const tailId = `fact:analysis-fixture-001/${inputs.at(-1)}`
    const previewId = hub ? rootId : leafId
    const direct = state === 'preview-relations' || state === 'hub-relations' || state === 'hub-star-relations'
    const scoped = state === 'pair' || state === 'preview-relations'
    const expectedIds = (scoped ? [rootId, leafId] : [rootId,
      'subject:sub-fixture-001', 'computation:comp-fixture-001',
      ...inputs.map(name => `fact:analysis-fixture-001/${name}`)])
      .filter(id => state !== 'hub-relations' || id !== tailId).sort()
    const expectedLinks = [
      [rootId, 'subject:sub-fixture-001'], ['computation:comp-fixture-001', rootId],
      ['computation:comp-fixture-001', 'subject:sub-fixture-001'],
      ...(indirectBranch ? inputs.slice(0, -1) : inputs).map(name => [`fact:analysis-fixture-001/${name}`, rootId]),
      ...(indirectBranch ? [[tailId, leafId]] : []),
    ].filter(([from, to]) => expectedIds.includes(from) && expectedIds.includes(to)
      && (!direct || from === previewId || to === previewId)).sort()
    await canvas.waitFor()
    const title = await page.locator('.evidence-object-title').textContent()
    const back = await page.locator('[data-evidence="back"]').isEnabled()
    if (indirectBranch) {
      assert.equal(await picker.locator('option').count(), count, '间接端点尚未加载')
      await picker.selectOption(leafId)
      await page.locator('.evidence-branch-load').click()
      await page.getByRole('button', { name: '已加载登记关系', exact: true }).waitFor()
    }
    assert.equal(await page.getByRole('combobox', { name: '选择 3D 节点预览' }).locator('option').count(), count + 1)
    assert.equal(await page.getByRole('combobox', { name: '选择 3D 节点预览' }).evaluate((select, names) =>
      names.every(name => [...select.options].some(option => option.textContent.endsWith(name))), inputs), true,
    '紧凑画布名称不截断节点选择器中的完整业务名称')
    if (state !== 'none') {
      await picker.selectOption(previewId)
      await page.locator('.evidence-preview-summary').waitFor({ state: 'visible' })
      if (scoped || direct) {
        await trace.selectOption(state === 'pair' ? rootId : 'preview-relations')
        await page.locator(`.evidence-graph-3d[data-scope="${state === 'pair' ? 'pair' : 'preview'}"]`).waitFor()
      }
    }
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
        await page.getByRole('button', { name: state === 'pair' ? '适应追踪关系' : direct ? '适应预览' : '适应 3D', exact: true }).click()
        await page.waitForTimeout(650)
        const bounds = await canvas.boundingBox()
        await page.evaluate(() => window.graphLabelBounds.clear())
        await page.mouse.move(bounds.x + 2, bounds.y + 2)
        await page.waitForFunction(expected => window.graphLabelBounds.size === expected, expectedIds.length)
        await page.waitForTimeout(150)
        assert.equal((await page.locator('.evidence-graph-3d').getAttribute('data-hovered')) ?? '', '', '全图截图清除临时悬停追踪')
        const overlap = await page.evaluate(() => {
          const labels = [...window.graphLabelBounds.values()]
          const area = (a, b) => Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x)) *
            Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y))
          return { labels: labels.length, bounds: labels, links: window.graphVisibleLinks.sort(),
            informationAboveLinks: labels.every(label => label.linkOrder !== null && label.textOrder > label.linkOrder && label.iconOrder > label.textOrder),
            names: labels.flatMap((a, i) => labels.slice(i + 1).filter(b => area(a, b) > 1).map(b => [a.id, b.id])),
            icons: labels.flatMap(a => labels.filter(b => a.id !== b.id && area(a, { x: b.nodeX - 7, y: b.nodeY - 7, width: 14, height: 14 }) > 1).map(b => [a.id, b.id])) }
        })
        assert.equal(await picker.locator('option').count(), count + 1, '范围切换不丢失已加载节点身份')
        assert.equal(await picker.inputValue(), state === 'none' ? '' : previewId, '相机动作不改变预览身份')
        assert.equal(await trace.inputValue(), state === 'pair' ? rootId : direct ? 'preview-relations' : '', '相机动作不改变追踪范围')
        assert.equal(await page.locator('.evidence-object-title').textContent(), title, '预览和相机动作不导航主对象')
        assert.equal(await page.locator('[data-evidence="back"]').isEnabled(), back, '预览不写入探索历史')
        assert.deepEqual(overlap.bounds.map(label => label.id).sort(), expectedIds, '实际绘制名称身份与当前范围一致')
        assert.deepEqual(overlap.links, expectedLinks, '实际可见登记边身份及方向与当前范围一致')
        const current = overlap.bounds.find(label => label.id === rootId)
        assert.ok(current.text.includes('当前页'), '实际名称保留当前页状态')
        assert.match(current.text, new RegExp(`已加载\\s*${count - (indirectBranch ? 2 : 1)}\\s*条关系`), '缩小范围仍显示已加载关系数')
        assert.equal(overlap.informationAboveLinks, true, '实际名称与类型图标绘制在组件登记关系线上方')
        if (state !== 'none') {
          if (!hub) assert.ok(overlap.bounds.find(label => label.id === previewId).text.includes('预览'), '实际名称保留预览状态')
          assert.equal(await page.locator('.evidence-preview-summary strong').textContent(), `预览：${hub ? 'fact-fixture-001' : inputs[0]}`, '摘要保留完整业务名称')
        }
        collisions.push({ state, count, width, angle, names: overlap.names.length, icons: overlap.icons.length })
        geometry.push({ state, count, width, angle, canvasWidth: bounds.width, canvasHeight: bounds.height, ...overlap })
        await page.locator('.evidence-relations').screenshot({ path: new URL(`report-editor-v6-small-3d-${count}-${width}-angle-${angle}${suffix}.png`, output).pathname })
        // 失败也保留实际投影与截图，以便定位遮挡，不以应用布局输入代替渲染证据。
        await writeFile(new URL(`report-editor-v6-small-3d${suffix}-geometry.json`, output), `${JSON.stringify(geometry, null, 2)}\n`)
        assert.deepEqual(overlap.names, [], `${count}节点/${width}px/角度${angle}名称不重叠`)
        assert.deepEqual(overlap.icons, [], `${count}节点/${width}px/角度${angle}名称不覆盖其他节点图标`)
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
        if (hub && angle === 2) {
          // 旋转阻尼尚未归零时不能把后续微小运动归为模式恢复缺陷。
          await page.waitForTimeout(1500)
          const before = await canvas.screenshot()
          const beforeGeometry = await page.evaluate(() => ({ camera: window.graphCamera, labels: [...window.graphLabelBounds.values()] }))
          await page.waitForTimeout(150)
          const stable = await canvas.screenshot()
          if (!before.equals(stable)) {
            const base = `report-editor-v6-small-3d-${count}-${width}${suffix}-baseline`
            await writeFile(new URL(`${base}-before.png`, output), before)
            await writeFile(new URL(`${base}-after.png`, output), stable)
            const afterGeometry = await page.evaluate(() => ({ camera: window.graphCamera, labels: [...window.graphLabelBounds.values()] }))
            await writeFile(new URL(`${base}-geometry.json`, output), `${JSON.stringify({ before: beforeGeometry, after: afterGeometry }, null, 2)}\n`)
          }
          assert.equal(before.equals(stable), true, '恢复操作前3D基线已逐像素静止')
          await page.getByRole('button', { name: '切换到 2D 关系图', exact: true }).click()
          const ids = await page.locator('.evidence-node').evaluateAll(nodes => nodes.filter(node => node.style.display !== 'none').map(node => node.dataset.evidenceNode).sort())
          const pairs = await page.locator('.evidence-graph-edge').evaluateAll(edges => edges.filter(edge => edge.style.display !== 'none').map(edge => [edge.dataset.from, edge.dataset.to]).sort())
          assert.deepEqual(ids, expectedIds, '2D恢复同一多邻居范围的可见身份')
          assert.deepEqual(pairs, expectedLinks, '2D保留同一登记边身份及方向')
          await page.getByRole('button', { name: '切换到 3D 关系图', exact: true }).click()
          await canvas.waitFor()
          await page.waitForTimeout(650)
          const restored = await canvas.boundingBox()
          await page.mouse.move(restored.x + 2, restored.y + 2)
          await page.waitForTimeout(150)
          assert.equal(await picker.inputValue(), rootId, '模式往返保留中心对象预览')
          assert.equal(await trace.inputValue(), direct ? 'preview-relations' : '', '模式往返保留多邻居范围')
          const after = await canvas.screenshot()
          if (!before.equals(after)) {
            const base = `report-editor-v6-small-3d-${count}-${width}${suffix}-restore`
            await writeFile(new URL(`${base}-before.png`, output), before)
            await writeFile(new URL(`${base}-after.png`, output), after)
            const afterGeometry = await page.evaluate(() => ({ camera: window.graphCamera, labels: [...window.graphLabelBounds.values()] }))
            await writeFile(new URL(`${base}-geometry.json`, output), `${JSON.stringify({ before: beforeGeometry, after: afterGeometry }, null, 2)}\n`)
          }
          assert.equal(before.equals(after), true, '模式往返恢复3D相机、名称与范围像素')
          if (direct) {
            await trace.selectOption('')
            await page.evaluate(() => window.graphLabelBounds.clear())
            await page.waitForFunction(expected => window.graphLabelBounds.size === expected, count)
            await page.waitForTimeout(150)
            assert.equal(await page.locator('.evidence-graph-3d').getAttribute('data-scope'), 'all', '取消范围恢复全图')
            assert.equal(await page.evaluate(() => window.graphVisibleLinks.length), count, '取消范围恢复间接及非中心登记边')
            assert.equal(await picker.inputValue(), rootId, '取消范围不改变中心对象预览')
            await trace.selectOption('preview-relations')
            await page.waitForTimeout(150)
            assert.equal(before.equals(await canvas.screenshot()), true, '范围取消后重新选择恢复3D名称与范围像素')
          }
        }
      }
    }
    assert.deepEqual(errors, [])
    await page.close()
  }
  console.log(JSON.stringify({ state, nodes: [5, 9, 15], viewports: [1280, 390, 844], angles: 3, collisions, readability: 'manual review required' }))
  await writeFile(new URL(`report-editor-v6-small-3d${suffix}-geometry.json`, output), `${JSON.stringify(geometry, null, 2)}\n`)
} finally {
  await browser.close()
}
