// 可在冻结真实宿主页面复用 assertChartAboveCells；组件模式仅构建独立入口。
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { createServer } from 'node:http'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { join, resolve } from 'node:path'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url))

export async function assertChartAboveCells(page, { screenshotPath, color = '#2F9E6E', expectedBars = 2, forbiddenColors = ['#FFBD37'] } = {}) {
  // 读取最终可见 canvas 像素；不读取图表绘制调用或模拟层级。
  const result = await page.evaluate(({ color, forbiddenColors }) => {
    const rgb = color.slice(1).match(/../g).map(value => parseInt(value, 16))
    const results = [...document.querySelectorAll('canvas')].filter(canvas => canvas.width && canvas.height && canvas.getBoundingClientRect().width).map(canvas => {
      const { width, height } = canvas
      const pixels = canvas.getContext('2d')?.getImageData(0, 0, width, height).data
      if (!pixels) return undefined
      const isColor = (index, value) => pixels[index * 4] === value[0] && pixels[index * 4 + 1] === value[1] && pixels[index * 4 + 2] === value[2] && pixels[index * 4 + 3] === 255
      const seen = new Uint8Array(width * height), bars = []
      for (let index = 0; index < seen.length; index++) {
        if (seen[index] || !isColor(index, rgb)) continue
        seen[index] = 1
        const queue = [index]; let count = 0, left = width, right = 0, top = height, bottom = 0
        for (let position = 0; position < queue.length; position++) {
          const current = queue[position], x = current % width, y = Math.floor(current / width)
          count++; left = Math.min(left, x); right = Math.max(right, x); top = Math.min(top, y); bottom = Math.max(bottom, y)
          for (const next of [x ? current - 1 : -1, x < width - 1 ? current + 1 : -1, y ? current - width : -1, y < height - 1 ? current + width : -1]) {
            if (next >= 0 && !seen[next] && isColor(next, rgb)) { seen[next] = 1; queue.push(next) }
          }
        }
        if (count > 500) bars.push({ left, right, top, bottom, pixels: count })
      }
      if (!bars.length) return undefined
      const frameColor = [154, 164, 173], frameMask = new Uint8Array(width * height)
      // 一像素图框的非整数末端会对白底抗锯齿；三通道必须共享同一 alpha。
      // 0.75 仅容纳通道量化误差，排除格线 #d6d8db 和近白色背景。
      const isFrame = index => {
        const alpha = pixels[index * 4 + 3] / 255
        let low = 0.4, high = 1
        for (let channel = 0; channel < 3; channel++) {
          const difference = 255 - frameColor[channel], value = (255 - pixels[index * 4 + channel]) * alpha
          low = Math.max(low, (value - 0.75) / difference)
          high = Math.min(high, (value + 0.75) / difference)
        }
        return low <= high
      }
      for (let index = 0; index < seen.length; index++) frameMask[index] = Number(isFrame(index))
      const barLeft = Math.min(...bars.map(bar => bar.left)), barRight = Math.max(...bars.map(bar => bar.right))
      const barTop = Math.min(...bars.map(bar => bar.top)), barBottom = Math.max(...bars.map(bar => bar.bottom))
      // 只从包围柱形的连续长边定位图框，避免页面其它控件的零散同色抗锯齿。
      const boundaries = []
      for (const horizontal of [true, false]) {
        const outerLength = horizontal ? height : width, innerLength = horizontal ? width : height
        for (let outer = 0; outer < outerLength; outer++) {
          let start = -1
          for (let inner = 0; inner <= innerLength; inner++) {
            const painted = inner < innerLength && frameMask[horizontal ? outer * width + inner : inner * width + outer]
            if (painted && start < 0) start = inner
            if (!painted && start >= 0) {
              const end = inner - 1
              if (horizontal ? end - start >= 150 && start <= barLeft && end >= barRight && (outer < barTop || outer > barBottom)
                : end - start >= 50 && start <= barTop && end >= barBottom && (outer < barLeft || outer > barRight)) {
                boundaries.push(horizontal ? { left: start, right: end, top: outer, bottom: outer } : { left: outer, right: outer, top: start, bottom: end })
              }
              start = -1
            }
          }
        }
      }
      if (!boundaries.length) return undefined
      const left = Math.min(...boundaries.map(edge => edge.left)), right = Math.max(...boundaries.map(edge => edge.right))
      const top = Math.min(...boundaries.map(edge => edge.top)), bottom = Math.max(...boundaries.map(edge => edge.bottom))
      const edge = (x0, y0, x1, y1) => {
        const length = Math.max(x1 - x0, y1 - y0) + 1; let painted = 0, gap = 0, maxGap = 0, sourceAlphaMin = 255
        for (let offset = 0; offset < length; offset++) {
          const index = (y0 + (y1 > y0 ? offset : 0)) * width + x0 + (x1 > x0 ? offset : 0)
          if (isFrame(index)) { painted++; gap = 0; sourceAlphaMin = Math.min(sourceAlphaMin, pixels[index * 4 + 3]) }
          else { gap++; maxGap = Math.max(maxGap, gap) }
        }
        return { painted, length, ratio: painted / length, maxGap, sourceAlphaMin }
      }
      const foreignPixels = Object.fromEntries(forbiddenColors.map(color => {
        const rgb = color.slice(1).match(/../g).map(value => parseInt(value, 16)); let count = 0
        for (let y = top; y <= bottom; y++) for (let x = left; x <= right; x++) if (isColor(y * width + x, rgb)) count++
        return [color, count]
      }))
      return { width, height, bars: bars.sort((a, b) => a.left - b.left), frame: { left, right, top, bottom, edges: [edge(left, top, right, top), edge(left, bottom, right, bottom), edge(left, top, left, bottom), edge(right, top, right, bottom)] }, foreignPixels }
    }).filter(Boolean)
    return results.sort((a, b) => b.bars.reduce((n, bar) => n + bar.pixels, 0) - a.bars.reduce((n, bar) => n + bar.pixels, 0))[0]
  }, { color, forbiddenColors })
  if (screenshotPath) await page.screenshot({ path: screenshotPath })
  assert.ok(result, '最终可见网格必须包含来源颜色的柱形')
  assert.equal(result.bars.length, expectedBars, `最终像素中的柱形数：${JSON.stringify(result)}`)
  assert.ok(result.frame.edges.every(edge => edge.ratio > 0.98 && edge.maxGap <= 1), `图框被单元格覆盖：${JSON.stringify(result)}`)
  assert.ok(Object.values(result.foreignPixels).every(count => count === 0), `图表内不应出现底层单元格颜色：${JSON.stringify(result.foreignPixels)}`)
  assert.ok(Math.abs((result.bars[0].bottom - result.bars[0].top + 1) / (result.bars[1].bottom - result.bars[1].top + 1) - 0.5) < 0.03, 'Q1/Q2 10:20 高度比例必须保留')
  return result
}

async function runComponent() {
  const directory = process.env.XLSX_LAYERING_DIRECTORY
  assert.ok(directory, '显式指定 XLSX_LAYERING_DIRECTORY 证据目录')
  await mkdir(directory, { recursive: true })
  await build({ absWorkingDir: frontend, entryPoints: ['smoke/office-xlsx-chart-layering-component.ts'], bundle: true, format: 'esm', outdir: directory, entryNames: 'component', loader: { '.png': 'dataurl', '.svg': 'dataurl', '.woff': 'dataurl', '.woff2': 'dataurl' }, metafile: true }).then(result => writeFile(join(directory, 'metafile.json'), JSON.stringify(result.metafile, null, 2)))
  const server = createServer(async (request, response) => {
    const name = request.url === '/component.js' ? 'component.js' : request.url === '/component.css' ? 'component.css' : undefined
    response.setHeader('content-type', name?.endsWith('.js') ? 'text/javascript' : name ? 'text/css' : 'text/html')
    response.end(name ? await readFile(join(directory, name)) : '<html><head><link rel="stylesheet" href="/component.css"></head><body style="margin:0"><div id="workbook-grid" style="width:1100px;height:720px"></div><script type="module" src="/component.js"></script></body></html>')
  })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1100, height: 720 }, deviceScaleFactor: 1 }), errors = []
  page.on('pageerror', error => errors.push(error.message))
  let diagnostics
  try {
    await page.goto(`http://127.0.0.1:${server.address().port}`)
    await page.waitForFunction(() => window.__sheetsWebCharts?.draws > 0, { timeout: 60000 })
    await page.waitForTimeout(500)
    diagnostics = await page.evaluate(() => window.layeringComponent.diagnostics())
    await writeFile(join(directory, 'diagnostics.json'), JSON.stringify({ diagnostics, errors }, null, 2))
    const pixels = await assertChartAboveCells(page, { screenshotPath: join(directory, 'final.png'), forbiddenColors: ['#F97316', '#0000FF', '#D00000'] })
    assert.deepEqual(errors, [])
    const evidence = { ok: true, browserVersion: browser.version(), diagnostics, pixels, errors }
    await writeFile(join(directory, 'evidence.json'), JSON.stringify(evidence, null, 2)); console.log(JSON.stringify(evidence))
  } catch (error) {
    await page.screenshot({ path: join(directory, 'failure.png') })
    await writeFile(join(directory, 'failure.json'), JSON.stringify({ error: String(error), diagnostics, errors }, null, 2)); throw error
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)) }
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) await runComponent()
