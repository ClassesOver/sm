import { chromium } from 'playwright'
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
const browser = await chromium.launch()
const runs = []
for (let index = 0; index < 5; index++) {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    reducedMotion: 'reduce',
  })
  const page = await context.newPage(),
    cdp = await context.newCDPSession(page)
  await cdp.send('Network.enable')
  await cdp.send('Network.setCacheDisabled', { cacheDisabled: true })
  await cdp.send('Network.emulateNetworkConditions', {
    offline: false,
    latency: 100,
    downloadThroughput: 1250000,
    uploadThroughput: 1250000,
  })
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 })
  await page.addInitScript(() => {
    window.__managementLcp = 0
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries())
        window.__managementLcp = entry.startTime
    }).observe({ type: 'largest-contentful-paint', buffered: true })
  })
  await page.goto('http://127.0.0.1:7789/management/login')
  await page.getByRole('heading', { name: '欢迎登录' }).waitFor()
  await page.bringToFront()
  await page.screenshot()
  await page.waitForFunction(() => window.__managementLcp > 0)
  await page.waitForLoadState('networkidle')
  runs.push(
    await page.evaluate(() => ({
      lcp: window.__managementLcp,
      resources: performance
        .getEntriesByType('resource')
        .map((r) => ({
          name: new URL(r.name).pathname,
          duration: r.duration,
          transferSize: r.transferSize,
        })),
      navigation: performance
        .getEntriesByType('navigation')
        .map((n) => ({
          ttfb: n.responseStart - n.requestStart,
          domContentLoaded: n.domContentLoadedEventEnd,
        })),
    })),
  )
  await context.close()
}
const sorted = runs.map((r) => r.lcp).sort((a, b) => a - b),
  median = sorted[2]
const credentials = JSON.parse(
  readFileSync(
    process.env.MANAGEMENT_E2E_CREDENTIALS ||
      '/tmp/management-depth-credentials.json',
    'utf8',
  ),
)
const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  }),
  page = await context.newPage()
await page.goto('http://127.0.0.1:7789/management/login')
await page.getByLabel('密码', { exact: true }).fill(credentials.password)
await page.getByRole('button', { name: '登录', exact: true }).click()
await page.waitForURL('**/sources')
await page.goto(
  'http://127.0.0.1:7789/management/sources?database=warehouse&companyId=100',
)
await page.getByText('已加载 50 条').waitFor()
const interaction = await page
  .getByRole('searchbox', { name: '搜索数据源' })
  .evaluate(
    (input) =>
      new Promise((resolve) => {
        const start = performance.now()
        const setter = Object.getOwnPropertyDescriptor(
          HTMLInputElement.prototype,
          'value',
        ).set
        setter.call(input, '查找')
        input.dispatchEvent(new Event('input', { bubbles: true }))
        requestAnimationFrame(() => resolve(performance.now() - start))
      }),
  )
const report = {
  browser: browser.version(),
  viewport: [1440, 900],
  cpuSlowdown: 4,
  network: { mbps: 10, latencyMs: 100 },
  runs,
  medianLcpMs: median,
  localInputFrameMs: interaction,
  passed: median > 0 && median <= 2500 && interaction <= 200,
}
const output = resolve('../../../output/management-depth')
mkdirSync(output, { recursive: true })
writeFileSync(
  resolve(output, 'performance.json'),
  JSON.stringify(report, null, 2),
)
console.log(
  JSON.stringify({
    medianLcpMs: median,
    localInputFrameMs: interaction,
    passed: report.passed,
  }),
)
await browser.close()
if (!report.passed) process.exitCode = 1
