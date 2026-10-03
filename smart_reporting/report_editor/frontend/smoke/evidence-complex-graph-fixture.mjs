// 固定复杂关系：共享输入、反馈环、自引用与多批次追加，不测试后端权限。
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'

const analysisId = 'analysis-fixture-001'
const root = 'fact-fixture-001'
const refs = keys => keys.map(factId => ({ analysisId, factId }))
const layer = prefix => Array.from({ length: 12 }, (_, i) => `${prefix}-${i}`)
const first = layer('first')
const shared = layer('shared')
const branch = layer('branch')
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
      entry: { unit: '万元' }, inputFactRefs: refs(inputs.get(factId) ?? []), warnings: [],
    } })
  })
  await page.goto(process.env.REPORT_EDITOR_URL ?? 'http://127.0.0.1:4173/reports/v1/editor/fixture-report/1', { waitUntil: 'networkidle' })
  await page.locator('[data-action="sources"]').click()
  await page.locator('.evidence-directory-item', { hasText: '正文引用' }).click()
  await page.locator('.evidence-subject-links button', { hasText: '事实' }).click()
  const positions = () => page.locator('.evidence-node').evaluateAll(nodes => Object.fromEntries(
    nodes.map(node => [node.dataset.evidenceNode, [node.style.left, node.style.top]])))
  await page.getByRole('button', { name: '切换到 2D 关系图', exact: true }).waitFor()
  await page.getByRole('button', { name: '切换到 2D 关系图', exact: true }).click()
  await page.waitForFunction(() => document.querySelectorAll('.evidence-node').length === 15)
  let previous = await positions()
  const title = await page.locator('.evidence-object-title').textContent()
  for (const [key, count] of [[first[0], 27], [first[1], 39], [branch[0], 39]]) {
    await page.locator(`[data-evidence-node="fact:${analysisId}/${key}"]`).click()
    await page.locator('.evidence-branch-load').click()
    await page.getByRole('button', { name: '已加载登记关系', exact: true }).waitFor()
    const next = await positions()
    assert.equal(Object.keys(next).length, count)
    for (const [id, position] of Object.entries(previous)) assert.deepEqual(next[id], position)
    assert.equal(await page.locator('.evidence-object-title').textContent(), title)
    previous = next
  }
  assert.equal(await page.locator('.evidence-graph-edge').count(), 55)
  assert.equal(await page.locator('.evidence-node').evaluateAll(nodes => nodes.every(node => {
    const id = node.dataset.evidenceNode
    const count = [...document.querySelectorAll('.evidence-graph-edge')].filter(path => path.dataset.from === id || path.dataset.to === id).length
    const info = node.querySelector('.evidence-node-info')
    const bounds = node.getBoundingClientRect()
    return node.querySelector('.evidence-node-heading svg[aria-hidden="true"]') !== null &&
      info.textContent.endsWith(`已加载 ${count} 条关系`) &&
      [...node.children].filter(child => !child.hidden).every(child => {
        const box = child.getBoundingClientRect()
        return box.right <= bounds.right && box.bottom <= bounds.bottom
      })
  })), true, '节点类型图标、已加载关系数及内容边界')
  const geometry = await page.locator('.evidence-graph-map').evaluate(map => {
    const boxes = [...map.querySelectorAll('.evidence-node')].map(node => ({
      id: node.dataset.evidenceNode, x: node.offsetLeft, y: node.offsetTop,
      w: node.offsetWidth, h: node.offsetHeight,
    }))
    const overlaps = boxes.flatMap((box, i) => boxes.slice(i + 1).filter(other =>
      box.x < other.x + other.w && other.x < box.x + box.w &&
      box.y < other.y + other.h && other.y < box.y + box.h))
    const contains = (box, point, margin = 0) => point.x >= box.x - margin && point.x <= box.x + box.w + margin &&
      point.y >= box.y - margin && point.y <= box.y + box.h + margin
    let obstructedEdges = 0
    for (const path of map.querySelectorAll('.evidence-graph-edge')) {
      const length = path.getTotalLength()
      const start = path.getPointAtLength(0)
      const end = path.getPointAtLength(length)
      const obstacles = boxes.filter(box => !contains(box, start, 1) && !contains(box, end, 1))
      for (let offset = 0; offset < length; offset += 4) {
        const point = path.getPointAtLength(offset)
        if (obstacles.some(box => contains(box, point))) { obstructedEdges += 1; break }
      }
    }
    return { overlaps: overlaps.length, obstructedEdges }
  })
  assert.equal(geometry.overlaps, 0)
  assert.equal(geometry.obstructedEdges, 0, '连线不应穿过非端点节点')
  const previewKey = `fact:${analysisId}/${branch[0]}`
  const connected = page.locator(`.evidence-graph-edge[data-from="${previewKey}"], .evidence-graph-edge[data-to="${previewKey}"]`)
  assert.equal(await connected.count(), 3)
  assert.equal(await page.locator('.evidence-graph-edge.is-preview').count(), 3)
  assert.equal(await page.locator('.evidence-graph-edge.is-muted').count(), 52)
  await page.mouse.move(0, 0)
  assert.equal(await page.locator('.evidence-graph-edge.is-preview').first().evaluate(edge => getComputedStyle(edge).opacity), '1')
  assert.equal(await page.locator('.evidence-graph-edge.is-muted').first().evaluate(edge => getComputedStyle(edge).opacity), '0.2')
  assert.deepEqual(await page.locator('.evidence-node.is-related').evaluateAll(nodes =>
    nodes.map(node => node.dataset.evidenceNode).sort()), [
    `fact:${analysisId}/${root}`, `fact:${analysisId}/${first[1]}`,
  ].sort())
  assert.equal(await page.locator('.evidence-node-tag[hidden]').evaluateAll(tags =>
    tags.every(tag => getComputedStyle(tag).display === 'none')), true, '空状态徽章不可显示成蓝色块')
  assert.equal(await page.locator('.evidence-graph-edges').evaluate(svg =>
    [...svg.querySelectorAll('.evidence-graph-edge')].slice(-3).every(edge => edge.classList.contains('is-preview'))), true)
  const output = new URL('../../../../output/', import.meta.url)
  await mkdir(output, { recursive: true })
  await page.locator('.evidence-relations').scrollIntoViewIfNeeded()
  await page.locator(`[data-evidence-node="fact:${analysisId}/${root}"]`).hover()
  assert.equal(await page.locator('.evidence-graph-edge.is-traced').count(), 1)
  assert.equal(await page.locator('.evidence-graph-edge.is-traced').getAttribute('data-from'), `fact:${analysisId}/${root}`)
  assert.equal(await page.locator('.evidence-graph-edge.is-traced').getAttribute('data-to'), previewKey)
  assert.equal(await page.locator('.evidence-graph-edge:not(.is-traced)').evaluateAll(edges =>
    edges.every(edge => getComputedStyle(edge).opacity === '0.12')), true)
  assert.equal(await page.locator('.evidence-node.is-trace-related').count(), 2)
  assert.ok(await page.locator('.evidence-node.is-trace-dim').count() > 0)
  assert.equal(await page.locator('.evidence-node.is-current').evaluate(node => node.classList.contains('is-trace-dim')), false)
  assert.equal(await page.locator('.evidence-node.is-selected').evaluate(node => node.classList.contains('is-trace-dim')), false)
  await page.locator('.evidence-relations').screenshot({ path: new URL('report-editor-v6-graph-trace-hover.png', output).pathname })
  assert.equal(await page.locator('.evidence-graph-edge.is-traced').count(), 1)
  await page.mouse.move(0, 0)
  assert.equal(await page.locator('.evidence-node.is-trace-dim').count(), 0)
  const neighbour = page.locator(`[data-evidence-node="fact:${analysisId}/${first[1]}"]`)
  await neighbour.focus()
  assert.equal(await page.locator('.evidence-graph-edge.is-traced').count(), 2)
  assert.equal(await page.locator('.evidence-graph-edges').evaluate(svg =>
    [...svg.querySelectorAll('.evidence-graph-edge')].slice(-2).every(edge => edge.classList.contains('is-traced'))), true)
  assert.equal(await page.locator('.evidence-object-title').textContent(), title)
  assert.equal(await page.locator('.evidence-node.is-selected').getAttribute('data-evidence-node'), previewKey)
  assert.deepEqual(await positions(), previous)
  await page.locator('.evidence-relations').screenshot({ path: new URL('report-editor-v6-graph-trace-focus.png', output).pathname })
  assert.equal(await page.locator('.evidence-graph-edge.is-traced').count(), 2)
  await page.mouse.move(0, 0)
  const tracePicker = page.getByRole('combobox', { name: '追踪预览关系端点' })
  await tracePicker.focus()
  await tracePicker.selectOption(`fact:${analysisId}/${root}`)
  assert.equal(await page.locator('.evidence-graph-edge.is-traced').count(), 1)
  assert.equal(await page.locator('.evidence-node.is-selected').getAttribute('data-evidence-node'), previewKey)
  assert.deepEqual(await positions(), previous)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '查看关系图', exact: true }).click()
  await tracePicker.selectOption(`fact:${analysisId}/${root}`)
  assert.ok((await tracePicker.locator('option:checked').textContent()).startsWith('追踪：'))
  assert.equal(await tracePicker.evaluate(node => {
    const bounds = node.getBoundingClientRect()
    return bounds.width >= 300 && bounds.height >= 40 && bounds.right <= innerWidth
  }), true, '窄屏追踪控件完整可操作')
  await page.getByRole('button', { name: '适应追踪关系', exact: true }).click()
  assert.equal(await page.locator('.evidence-graph-scroll').evaluate(scroll => {
    const bounds = scroll.getBoundingClientRect()
    const contains = box => box.left >= bounds.left && box.right <= bounds.right && box.top >= bounds.top && box.bottom <= bounds.bottom
    const selected = scroll.querySelector('.evidence-node.is-selected')
    const endpointId = document.querySelector('.evidence-trace-picker').value
    const endpoint = [...scroll.querySelectorAll('.evidence-node')].find(node => node.dataset.evidenceNode === endpointId)
    const svg = scroll.querySelector('.evidence-graph-edges')
    const svgBounds = svg.getBoundingClientRect()
    const scale = svgBounds.width / svg.viewBox.baseVal.width
    return [selected, endpoint].every(node => contains(node.getBoundingClientRect())) &&
      [...scroll.querySelectorAll('.is-traced')].every(path => {
        const length = path.getTotalLength()
        for (let distance = 0; distance <= length; distance += 4) {
          const point = path.getPointAtLength(distance)
          const x = svgBounds.left + point.x * scale
          const y = svgBounds.top + point.y * scale
          if (x < bounds.left || x > bounds.right || y < bounds.top || y > bounds.bottom) return false
        }
        return true
      })
  }), true, '主动适应追踪关系后，两端和连线均在画布内')
  assert.deepEqual(await positions(), previous)
  assert.equal(await page.locator('.evidence-node.is-selected').getAttribute('data-evidence-node'), previewKey)
  await page.screenshot({ path: new URL('report-editor-v6-graph-trace-picker-mobile.png', output).pathname })
  assert.equal(await page.locator('.evidence-graph-edge.is-traced').count(), 1)
  await tracePicker.selectOption('')
  assert.equal(await page.locator('.evidence-graph-edge.is-traced').count(), 0)
  await tracePicker.focus()
  await tracePicker.press('ArrowDown')
  assert.equal(await tracePicker.inputValue(), `fact:${analysisId}/${root}`)
  assert.equal(await page.locator('.evidence-graph-edge.is-traced').count(), 1)
  await tracePicker.press('ArrowUp')
  assert.equal(await tracePicker.inputValue(), '')
  assert.equal(await page.locator('.evidence-graph-edge.is-traced').count(), 0)
  await page.getByRole('button', { name: '返回详情', exact: true }).click()
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.locator(`[data-evidence-node="fact:${analysisId}/${branch[0]}"]`).press('Enter')
  await page.locator('.evidence-object-title', { hasText: branch[0] }).waitFor()
  await page.locator('[data-evidence="back"]').click()
  await page.locator('.evidence-object-title', { hasText: title }).waitFor()
  assert.deepEqual(await positions(), previous)
  const overview = await page.locator('.evidence-graph-map').evaluate(map => {
    const paths = [...map.querySelectorAll('.evidence-graph-edge')]
    const segments = paths.flatMap((path, index) => {
      const points = [...path.getAttribute('d').matchAll(/[ML] ([\d.]+) ([\d.]+)/g)].map(match => [Number(match[1]), Number(match[2])])
      return points.slice(1).map((end, i) => ({ index, start: points[i], end }))
    })
    let sharedChannelPairs = 0
    const hotspots = new Map()
    for (const [i, a] of segments.entries()) {
      for (const b of segments.slice(i + 1)) {
        if (a.index === b.index) continue
        const vertical = a.start[0] === a.end[0] && b.start[0] === b.end[0] && a.start[0] === b.start[0]
        const horizontal = a.start[1] === a.end[1] && b.start[1] === b.end[1] && a.start[1] === b.start[1]
        const axis = vertical ? 1 : horizontal ? 0 : -1
        if (axis < 0) continue
        const overlap = Math.min(Math.max(a.start[axis], a.end[axis]), Math.max(b.start[axis], b.end[axis])) -
          Math.max(Math.min(a.start[axis], a.end[axis]), Math.min(b.start[axis], b.end[axis]))
        if (overlap > 12) {
          sharedChannelPairs += 1
          const key = vertical ? `x=${a.start[0]}` : `y=${a.start[1]}`
          hotspots.set(key, (hotspots.get(key) ?? 0) + 1)
        }
      }
    }
    return { width: map.offsetWidth, height: map.offsetHeight, sharedChannelPairs,
      hotspots: [...hotspots].sort((a, b) => b[1] - a[1]).slice(0, 6) }
  })
  // 独立导出布局，避免滚动容器裁剪；不是产品视口截图。
  await page.locator('.evidence-graph-map').evaluate(map => {
    const copy = map.cloneNode(true)
    copy.id = 'graph-layout-audit'
    Object.assign(copy.style, { position: 'absolute', left: '0', top: '0', zIndex: '10000',
      width: `${map.offsetWidth}px`, height: `${map.offsetHeight}px`, transform: 'none', background: '#fff' })
    document.body.append(copy)
  })
  await page.locator('#graph-layout-audit').screenshot({ path: new URL('report-editor-v6-complex-graph-full-map.png', output).pathname })
  await page.locator('#graph-layout-audit').evaluate(map => map.remove())
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
  await page.getByRole('button', { name: '切换到关系列表', exact: true }).click()
  assert.equal(await page.locator('.evidence-relation-pair').count(), 55)
  const listedPairs = await page.locator('.evidence-relation-pair').evaluateAll(pairs => pairs.map(pair =>
    JSON.stringify([...pair.querySelectorAll('.evidence-relation-label')].map(label => label.textContent))).sort())
  assert.deepEqual(listedPairs, expectedPairs, '文字列表必须包含图中每条已加载关系的有序端点')
  await page.getByRole('button', { name: '切换到关系图', exact: true }).click()
  await page.locator('.evidence-relations').screenshot({ path: new URL('report-editor-v6-complex-graph.png', output).pathname })
  await page.getByRole('button', { name: '适应关系图', exact: true }).click()
  const fit = await page.locator('.evidence-graph-scroll').evaluate(scroll => {
    const bounds = scroll.getBoundingClientRect()
    const map = scroll.querySelector('.evidence-graph-map')
    return {
      scale: Number(map.style.transform.match(/scale\(([^)]+)\)/)?.[1] ?? 1),
      allNodesInWidth: [...map.querySelectorAll('.evidence-node')].every(node => {
        const rect = node.getBoundingClientRect()
        return rect.left >= bounds.left && rect.right <= bounds.right
      }),
    }
  })
  assert.ok(fit.scale < 1 && fit.allNodesInWidth, '39 节点适应视图应完整落入桌面图视口宽度')
  await page.locator('.evidence-relations').screenshot({ path: new URL('report-editor-v6-complex-graph-fit.png', output).pathname })
  await page.getByRole('button', { name: '重置视图', exact: true }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '查看关系图', exact: true }).click()
  await page.getByRole('button', { name: '缩小关系图', exact: true }).click()
  await page.locator(`[data-evidence-node="fact:${analysisId}/${branch.at(-1)}"]`).click()
  await page.locator('.evidence-preview-enter').waitFor()
  await page.getByRole('button', { name: '定位当前对象', exact: true }).click()
  assert.equal(await page.locator('.evidence-graph-edge.is-preview').count(), 1)
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  await page.screenshot({ path: new URL('report-editor-v6-complex-graph-mobile.png', output).pathname })
  await page.setViewportSize({ width: 844, height: 390 })
  const landscape = await page.evaluate(() => {
    const bounds = selector => {
      const rect = document.querySelector(selector).getBoundingClientRect()
      return { top: rect.top, bottom: rect.bottom, height: rect.height }
    }
    return { viewport: innerHeight, relations: bounds('.evidence-relations'),
      head: bounds('.evidence-relations-head'), controls: bounds('.evidence-graph-controls'),
      scroll: bounds('.evidence-graph-scroll'), legend: bounds('.evidence-graph-legend'),
      preview: bounds('.evidence-preview') }
  })
  assert.ok(landscape.relations.top <= 60 && landscape.relations.bottom <= landscape.viewport,
    '横屏独立关系图应留在首屏内')
  assert.ok(landscape.scroll.height >= 150 && landscape.preview.top < landscape.scroll.bottom,
    '横屏预览应停靠图侧边，保留可操作画布')
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  await page.screenshot({ path: new URL('report-editor-v6-complex-graph-landscape.png', output).pathname })
  await page.getByRole('button', { name: '返回详情', exact: true }).click()
  assert.equal(await page.locator('.evidence-relations.is-graph-view').count(), 0)
  console.log(JSON.stringify({ landscape }))
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ complexGraph: 'navigation passed', nodes: 39, edges: 55, ...geometry, ...overview }))
} finally {
  await browser.close()
}
