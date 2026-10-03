// 与2D复杂图使用同一关系形态；仅验证固定前端数据，不验证后端权限。
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'

const analysisId = 'analysis-fixture-001'
const root = 'fact-fixture-001'
const layer = prefix => Array.from({ length: 12 }, (_, i) => `${prefix}-${i}`)
const first = layer('first')
const shared = layer('shared')
const branch = layer('branch')
const longLabels = process.env.REPORT_EDITOR_LONG_LABELS === '1'
const suffix = longLabels ? '-long' : ''
const labelCycles = Number(process.env.REPORT_EDITOR_LABEL_CYCLES ?? 1)
assert.ok(Number.isInteger(labelCycles) && labelCycles >= 1 && labelCycles <= 10)
if (longLabels) {
  first[0] = '跨院区收入与成本口径调整后月度汇总计算结果'.repeat(3)
  shared[0] = '医疗服务收入明细与患者来源渠道关联输入快照'.repeat(3)
}
const inputs = new Map([
  [root, first],
  [first[0], [...shared, root, first[0]]],
  [first[1], [...shared, ...branch]],
  [branch[0], [first[1], root]],
])
const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/facts/**', route => {
    const factId = decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-1))
    return route.fulfill({ json: {
      analysisId, factId, factKind: 'metric', displayValue: 12450,
      entry: { unit: '万元' }, inputFactRefs: (inputs.get(factId) ?? []).map(factId => ({ analysisId, factId })), warnings: [],
    } })
  })
  await page.goto(process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
  await page.locator('[data-action="sources"]').click()
  await page.locator('.evidence-directory-item', { hasText: '正文引用' }).click()
  await page.locator('.evidence-subject-links button', { hasText: '事实' }).click()
  const canvas = page.locator('.evidence-graph-3d canvas')
  // 检查真实渲染像素：内缩2px避开主题边框/截图舍入，标签或球体触边即视为裁切风险。
  const fitsCanvas = async () => page.evaluate(async png => {
    const image = new Image()
    image.src = `data:image/png;base64,${png}`
    await image.decode()
    const probe = document.createElement('canvas')
    probe.width = image.width
    probe.height = image.height
    const context = probe.getContext('2d')
    context.drawImage(image, 0, 0)
    const { data } = context.getImageData(0, 0, probe.width, probe.height)
    const background = (x, y) => {
      const offset = (y * probe.width + x) * 4
      return [247, 251, 253].every((value, channel) => Math.abs(data[offset + channel] - value) <= 2)
    }
    const pixel = (x, y) => ({ x, y, color: [...data.slice((y * probe.width + x) * 4, (y * probe.width + x) * 4 + 4)] })
    for (let x = 2; x < probe.width - 2; x++) {
      if (!background(x, 2)) return pixel(x, 2)
      if (!background(x, probe.height - 3)) return pixel(x, probe.height - 3)
    }
    for (let y = 2; y < probe.height - 2; y++) {
      if (!background(2, y)) return pixel(2, y)
      if (!background(probe.width - 3, y)) return pixel(probe.width - 3, y)
    }
    return true
  }, (await canvas.screenshot()).toString('base64'))
  const picker = page.getByRole('combobox', { name: '选择 3D 节点预览' })
  const trace = page.getByRole('combobox', { name: '追踪预览关系端点' })
  await canvas.waitFor()
  assert.equal(await picker.locator('option').count(), 16)
  const title = await page.locator('.evidence-object-title').textContent()
  const back = await page.locator('[data-evidence="back"]').isEnabled()
  for (const [key, count] of [[first[0], 27], [first[1], 39], [branch[0], 39]]) {
    await picker.selectOption(`fact:${analysisId}/${key}`)
    await page.locator('.evidence-branch-load').click()
    await page.getByRole('button', { name: '已加载登记关系', exact: true }).waitFor()
    assert.equal(await picker.locator('option').count(), count + 1)
    assert.equal(await page.locator('.evidence-object-title').textContent(), title)
    assert.equal(await page.locator('[data-evidence="back"]').isEnabled(), back)
  }
  // 对照2D累计图，确认两种模式共享39个身份和55条真实登记边。
  await page.getByRole('button', { name: '切换到 2D 关系图', exact: true }).click()
  assert.equal(await page.locator('.evidence-node').count(), 39)
  assert.equal(await page.locator('.evidence-graph-edge').count(), 55)
  const expectedPairs = await page.locator('.evidence-graph-map').evaluate(map => {
    const names = new Map([...map.querySelectorAll('.evidence-node')].map(node =>
      [node.dataset.evidenceNode, node.querySelector('.evidence-node-title').title]))
    const current = map.querySelector('.evidence-node.is-current').dataset.evidenceNode
    return [...map.querySelectorAll('.evidence-graph-edge')].map(edge => {
      const { from, to } = edge.dataset
      const endpoints = from === current ? [to] : to === current ? [from] : [from, to]
      return JSON.stringify(endpoints.map(id => names.get(id)))
    }).sort()
  })
  await page.getByRole('button', { name: '切换到 3D 关系图', exact: true }).click()
  await canvas.waitFor()
  assert.equal(await page.locator('.evidence-graph-3d').getAttribute('data-labels'), 'focus')
  await page.getByRole('button', { name: '显示全部节点名称', exact: true }).click()
  assert.equal(await page.locator('.evidence-graph-3d').getAttribute('data-labels'), 'all')
  await page.getByRole('button', { name: '只显示重点节点名称', exact: true }).click()
  assert.equal(await page.locator('.evidence-graph-3d').getAttribute('data-labels'), 'focus')
  const output = new URL('../../../../output/', import.meta.url)
  await mkdir(output, { recursive: true })
  await page.getByRole('button', { name: '适应 3D', exact: true }).click()
  await page.waitForTimeout(250)
  const beforeList = await canvas.screenshot()
  await page.getByRole('button', { name: '切换到关系列表', exact: true }).click()
  await page.getByRole('region', { name: '关系列表', exact: true }).waitFor()
  const listedPairs = await page.locator('.evidence-relation-pair').evaluateAll(pairs => pairs.map(pair =>
    JSON.stringify([...pair.querySelectorAll('.evidence-relation-label')].map(label => label.textContent))).sort())
  assert.equal(listedPairs.length, 55)
  assert.deepEqual(listedPairs, expectedPairs, '3D累计图与文字列表逐条有序端点一致')
  await page.getByRole('button', { name: '切换到关系图', exact: true }).click()
  await canvas.waitFor()
  assert.equal(await picker.inputValue(), `fact:${analysisId}/${branch[0]}`)
  await page.waitForTimeout(150)
  assert.equal(beforeList.equals(await canvas.screenshot()), true, '3D/列表往返保留相机和节点画面')
  for (const [width, height] of [[1280, 900], [390, 844], [844, 390]]) {
    await page.setViewportSize({ width, height })
    if (width === 390) await page.getByRole('button', { name: '查看关系图', exact: true }).click()
    await picker.selectOption(`fact:${analysisId}/${first[0]}`)
    // 自引用边仍登记，但不作为端点选项列出。
    assert.equal(await trace.locator(`option[value="fact:${analysisId}/${first[0]}"]`).count(), 0)
    await trace.selectOption(`fact:${analysisId}/${shared[0]}`)
    if (longLabels) {
      assert.equal(await picker.locator('option:checked').textContent(), `事实 · ${first[0]}`, '预览选择器保留完整名称')
      assert.equal(await trace.locator('option:checked').textContent(), `追踪：事实 · ${shared[0]}`, '追踪选择器保留完整名称')
      assert.equal((await page.locator('.evidence-preview-summary').textContent()).includes(first[0]), true)
    }
    await page.locator('.evidence-3d-trace-status', { hasText: '追踪 1 条登记关系' }).waitFor()
    await page.getByRole('button', { name: '适应追踪关系', exact: true }).click()
    await page.waitForTimeout(250)
    await page.locator('.evidence-relations').screenshot({ path: new URL(`report-editor-v6-complex-3d-trace-${width}${suffix}.png`, output).pathname })
    assert.equal(await fitsCanvas(), true, `${width}px追踪名称与图形不触及画布四边`)
    await page.getByRole('button', { name: '缩小关系图', exact: true }).click()
    await page.waitForTimeout(250)
    assert.equal(await fitsCanvas(), true, `${width}px缩小后名称与图形不触及画布四边`)
    await canvas.screenshot({ path: new URL(`report-editor-v6-complex-3d-trace-zoom-${width}${suffix}.png`, output).pathname })
    await page.getByRole('button', { name: '放大关系图', exact: true }).click()
    await page.waitForTimeout(250)
    assert.equal(await trace.inputValue(), `fact:${analysisId}/${shared[0]}`)
    await page.locator('.evidence-3d-trace-status', { hasText: '追踪 1 条登记关系' }).waitFor()
    // 使用组件真实相机控制检查代表性角度，不以正视截图代替旋转后的标签验收。
    for (let angle = 1; angle <= 3; angle++) {
      const bounds = await canvas.boundingBox()
      await page.mouse.move(bounds.x + 10, bounds.y + 10)
      await page.mouse.down()
      await page.mouse.move(bounds.x + 65, bounds.y + 35, { steps: 8 })
      await page.mouse.up()
      await page.waitForTimeout(650)
      await page.getByRole('button', { name: '适应追踪关系', exact: true }).click()
      await page.waitForTimeout(250)
      await canvas.screenshot({ path: new URL(`report-editor-v6-complex-3d-trace-angle-${angle}-${width}${suffix}.png`, output).pathname })
      assert.equal(await fitsCanvas(), true, `${width}px追踪角度${angle}名称与图形不触及画布四边`)
      assert.equal(await trace.inputValue(), `fact:${analysisId}/${shared[0]}`)
    }
    await trace.selectOption('')
    await page.getByRole('button', { name: '适应 3D', exact: true }).click()
    // 与真实鼠标旋转回放一致，留足组件相机/惯性结束的观察窗口。
    await page.waitForTimeout(650)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
    assert.equal(await canvas.evaluate(node => node.getBoundingClientRect().height > 100), true)
    assert.equal(await fitsCanvas(), true, `${width}px全图适应后名称与图形不触及画布四边`)
    if (width === 390) {
      const buttons = await page.locator('.evidence-graph-controls > button').evaluateAll(nodes => nodes
        .filter(node => !node.hidden).map(node => { const { top, width, height } = node.getBoundingClientRect(); return { top, width, height } }))
      assert.equal(new Set(buttons.map(button => Math.round(button.top))).size, 1, '竖屏图操作按钮保持一行')
      assert.equal(buttons.every(button => button.width >= 40 && button.height >= 40), true, '图操作保留40px触控目标')
      assert.equal(await canvas.evaluate(node => node.getBoundingClientRect().height >= 270), true, '长名称预览时竖屏画布保留至少270px')
    }
    await page.locator('.evidence-relations').screenshot({ path: new URL(`report-editor-v6-complex-3d-${width}${suffix}.png`, output).pathname })
    const labelBounds = await canvas.boundingBox()
    if (width !== 1280) {
      await page.mouse.move(labelBounds.x + 5, labelBounds.y + 5)
      await page.waitForTimeout(100)
      const beforeMobileList = await canvas.screenshot()
      await page.getByRole('button', { name: '切换到关系列表', exact: true }).click()
      const mobileList = page.getByRole('region', { name: '关系列表', exact: true })
      await mobileList.waitFor()
      assert.equal(await canvas.isVisible(), false, '独立视图显示列表时隐藏画布')
      assert.equal(await mobileList.locator('.evidence-relation-pair').count(), 55)
      await mobileList.evaluate(node => { node.scrollTop = node.scrollHeight })
      assert.equal(await mobileList.evaluate(node => node.scrollTop > 0 && node.getBoundingClientRect().bottom <= innerHeight), true, '55条关系在独立视图内部滚动')
      assert.equal(await page.getByRole('button', { name: '返回详情', exact: true }).isVisible(), true)
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
      await page.locator('.evidence-relations').screenshot({ path: new URL(`report-editor-v6-complex-3d-mobile-list-${width}${suffix}.png`, output).pathname })
      await page.getByRole('button', { name: '切换到关系图', exact: true }).click()
      await canvas.waitFor()
      await page.mouse.move(labelBounds.x + 5, labelBounds.y + 5)
      await page.waitForTimeout(150)
      assert.equal(beforeMobileList.equals(await canvas.screenshot()), true, '独立视图列表往返保持图现场')
    }
    const clearHover = async () => {
      await page.mouse.move(labelBounds.x + 5, labelBounds.y + 5)
      await page.waitForTimeout(100)
    }
    for (let cycle = 1; cycle <= labelCycles; cycle++) {
      const cycleSuffix = labelCycles > 1 ? `-cycle-${cycle}` : ''
      await clearHover()
      const beforeHover = await page.locator('.evidence-graph-3d').getAttribute('data-hovered')
      const focusedCanvas = await canvas.screenshot({ path: new URL(`report-editor-v6-complex-3d-focus-before-${width}${suffix}${cycleSuffix}.png`, output).pathname })
      await page.waitForTimeout(150)
      assert.equal(focusedCanvas.equals(await canvas.screenshot()), true, `${width}px名称开关前相机与画面已稳定`)
      await page.getByRole('button', { name: '显示全部节点名称', exact: true }).click()
      await clearHover()
      const allNamesCanvas = await canvas.screenshot({ path: new URL(`report-editor-v6-complex-3d-all-names-${width}${suffix}.png`, output).pathname })
      assert.equal(focusedCanvas.equals(allNamesCanvas), false, '名称开关实际改变画布')
      assert.equal(await picker.locator('option').count(), 40, '名称开关不隐藏业务节点')
      assert.equal(await picker.inputValue(), `fact:${analysisId}/${first[0]}`)
      await page.getByRole('button', { name: '只显示重点节点名称', exact: true }).click()
      await clearHover()
      const restoredCanvas = await canvas.screenshot({ path: new URL(`report-editor-v6-complex-3d-focus-restored-${width}${suffix}${cycleSuffix}.png`, output).pathname })
      const afterHover = await page.locator('.evidence-graph-3d').getAttribute('data-hovered')
      assert.equal(afterHover, beforeHover, `${width}px第${cycle}轮悬停状态一致`)
      if (!focusedCanvas.equals(restoredCanvas)) {
        const difference = await page.evaluate(async images => {
          const data = await Promise.all(images.map(async png => {
            const image = new Image()
            image.src = `data:image/png;base64,${png}`
            await image.decode()
            const canvas = document.createElement('canvas')
            canvas.width = image.width
            canvas.height = image.height
            const context = canvas.getContext('2d')
            context.drawImage(image, 0, 0)
            return context.getImageData(0, 0, canvas.width, canvas.height)
          }))
          if (data[0].width !== data[1].width || data[0].height !== data[1].height) return { dimensions: data.map(item => [item.width, item.height]) }
          const bounds = [data[0].width, data[0].height, -1, -1]
          let pixels = 0
          let maxDelta = 0
          for (let offset = 0; offset < data[0].data.length; offset += 4) {
            const delta = Math.max(...[0, 1, 2, 3].map(channel => Math.abs(data[0].data[offset + channel] - data[1].data[offset + channel])))
            if (!delta) continue
            pixels++
            maxDelta = Math.max(maxDelta, delta)
            const x = offset / 4 % data[0].width
            const y = Math.floor(offset / 4 / data[0].width)
            bounds[0] = Math.min(bounds[0], x); bounds[1] = Math.min(bounds[1], y)
            bounds[2] = Math.max(bounds[2], x); bounds[3] = Math.max(bounds[3], y)
          }
          return { pixels, maxDelta, bounds }
        }, [focusedCanvas.toString('base64'), restoredCanvas.toString('base64')])
        assert.fail(`${width}px第${cycle}轮名称开关画布差异：${JSON.stringify(difference)}`)
      }
    }
    assert.equal(await fitsCanvas(), true, `${width}px概览关注对象名称与图形不触及画布四边`)
    await page.getByRole('button', { name: '缩小关系图', exact: true }).click()
    await page.waitForTimeout(250)
    await canvas.screenshot({ path: new URL(`report-editor-v6-complex-3d-overview-zoom-${width}${suffix}.png`, output).pathname })
    assert.equal(await fitsCanvas(), true, `${width}px概览缩小后关注对象名称不触及画布四边`)
    await page.getByRole('button', { name: '放大关系图', exact: true }).click()
    await page.waitForTimeout(250)
    assert.equal(await picker.inputValue(), `fact:${analysisId}/${first[0]}`)
    assert.equal(await page.locator('.evidence-object-title').textContent(), title)
    assert.equal(await page.locator('[data-evidence="back"]').isEnabled(), back)
    await page.mouse.move(labelBounds.x + 5, labelBounds.y + 5)
    await page.waitForTimeout(100)
    const fullView = await canvas.screenshot()
    await trace.selectOption('preview-relations')
    await page.locator('.evidence-3d-trace-status', { hasText: '预览 15 条登记关系 · 仅显示预览直接关系' }).waitFor()
    assert.equal(await page.locator('.evidence-graph-3d').getAttribute('data-scope'), 'preview')
    assert.equal(await picker.locator('option').count(), 40, '直接关系视图保留全部节点身份')
    await page.waitForTimeout(100)
    assert.equal(fullView.equals(await canvas.screenshot()), false, '直接关系过滤实际改变画面')
    await trace.selectOption('')
    await page.waitForTimeout(100)
    assert.equal(fullView.equals(await canvas.screenshot()), true, '范围往返保持全部节点坐标和相机')
    await trace.selectOption('preview-relations')
    await page.getByRole('button', { name: '适应预览', exact: true }).click()
    await page.waitForTimeout(250)
    await page.locator('.evidence-relations').screenshot({ path: new URL(`report-editor-v6-complex-3d-preview-relations-${width}${suffix}.png`, output).pathname })
    assert.equal(await fitsCanvas(), true, `${width}px预览直接关系适应后不触边`)
    await trace.selectOption(`fact:${analysisId}/${shared[0]}`)
    await page.locator('.evidence-3d-trace-status', { hasText: '追踪 1 条登记关系 · 仅显示追踪关系' }).waitFor()
    await trace.selectOption('')
    assert.equal(await page.locator('.evidence-graph-3d').getAttribute('data-scope'), 'all')
    assert.equal(await picker.inputValue(), `fact:${analysisId}/${first[0]}`)
    assert.equal(await page.locator('.evidence-object-title').textContent(), title)
    assert.equal(await page.locator('[data-evidence="back"]').isEnabled(), back)
  }
  await page.getByRole('button', { name: '显示全部节点名称', exact: true }).click()
  await picker.focus()
  await picker.press('Enter')
  await page.locator('.evidence-object-title', { hasText: first[0] }).waitFor()
  await canvas.waitFor()
  assert.equal(await picker.locator('option').count(), 40, '进入对象后保留任务累计节点')
  await page.locator('[data-evidence="back"]').click()
  await page.locator('.evidence-object-title', { hasText: title }).waitFor()
  assert.equal(await picker.inputValue(), `fact:${analysisId}/${first[0]}`)
  assert.equal(await picker.locator('option').count(), 40, '后退恢复复杂图和预览')
  assert.equal(await page.locator('.evidence-graph-3d').getAttribute('data-labels'), 'all', '后退保留非默认名称偏好')
  for (const value of ['preview-relations', `fact:${analysisId}/${shared[0]}`]) {
    await trace.selectOption(value)
    await picker.focus()
    await picker.press('Enter')
    await page.locator('.evidence-object-title', { hasText: first[0] }).waitFor()
    await canvas.waitFor()
    assert.equal(await trace.inputValue(), '', '新对象页面不继承其他预览的端点')
    await page.locator('[data-evidence="back"]').click()
    await page.locator('.evidence-object-title', { hasText: title }).waitFor()
    assert.equal(await trace.inputValue(), value, '后退恢复直接关系或固定端点')
    await page.getByRole('button', { name: '切换到 2D 关系图', exact: true }).click()
    await page.getByRole('button', { name: '切换到 3D 关系图', exact: true }).click()
    await canvas.waitFor()
    assert.equal(await trace.inputValue(), value, '模式往返恢复3D追踪选择')
  }
  await picker.selectOption(`fact:${analysisId}/${first[1]}`)
  assert.equal(await trace.inputValue(), '', '更换预览不沿用旧对象追踪')
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ nodes: 39, edges: 55, longLabels, labelCycles, listIdentity: 'passed', listCamera: 'passed', traceBounds: 'passed', sharedIdentity: 'passed', batches: 'passed', tracing: 'passed', viewports: 'passed', navigation: 'passed', readability: 'manual review required', errors }))
} finally {
  await browser.close()
}
