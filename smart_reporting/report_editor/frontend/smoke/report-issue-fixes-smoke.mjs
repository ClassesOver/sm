import { chromium } from 'playwright'
import { fileURLToPath } from 'node:url'
import { mkdir, writeFile } from 'node:fs/promises'
const directory = fileURLToPath(new URL('../../../../docs/superpowers/reports/artifacts/2026-11-11-report-issue-fix-links/report-ui', import.meta.url))
await mkdir(directory, { recursive: true })
const browser = await chromium.launch({ headless: true })
const results = []
try {
 for (const width of [1440, 1280, 768, 390]) {
  const page = await browser.newPage({ viewport: { width, height: 1100 } })
  await page.route('**/reports/v1/editor/assets/', route => route.fulfill({ contentType: 'text/html', body: '<!doctype html><html lang="zh-CN"><head><title>报告问题反馈验收</title></head><body></body></html>' }))
  await page.goto('http://127.0.0.1:5187/reports/v1/editor/assets/')
  await page.evaluate(async () => {
   const { mountReportIssues } = await import('/reports/v1/editor/assets/src/evidence-issues.ts')
   const { ReportEditorClient } = await import('/reports/v1/editor/assets/src/api.ts')
   const style = document.createElement('link'); style.rel = 'stylesheet'; style.href = '/reports/v1/editor/assets/src/style.css'; document.head.append(style)
   document.body.style.cssText = 'margin:0;background:#f5f7fa;font-family:system-ui;color:#253044'
   document.body.innerHTML = '<main><aside style="width:min(340px,100%);padding:12px;box-sizing:border-box"><h1 style="font-size:18px">本报告计算依据</h1><div id="panel"></div></aside></main>'
   window.calls = []; window.submitted = null
   const client = new ReportEditorClient('/editor', async (input, init) => {
    window.calls.push({ url: String(input), method: init?.method ?? 'GET' })
    if (init?.method === 'POST') {
     window.submitted = JSON.parse(init.body)
     if (sessionStorage.getItem('browser-issues:report-issue') !== init.body) throw Error('cache missing')
     throw Error('accepted response lost')
    }
    return Response.json({ items: [{ version: 2, review: { ...window.submitted, status: 'accepted', decisionReason: '已用独立原始行核对，预算执行率应使用实际合计/预算合计。', correctedVersions: [{ assetType: 'metric', assetId: 'execution-rate', revision: 2 }, { assetType: 'evidence_release', assetId: 'release-correction', revision: null }] },
     proposal: { changeSummary: '使用分子与分母分别汇总后的比率，保留项目粒度。', counterexample: '预算100、200，实际90、100；平均比率70%有偏，190/300应为63.33%。' } }], nextCursor: null })
   })
   window.reopen = () => {
    const panel = document.querySelector('#panel'); panel.replaceChildren()
    mountReportIssues(panel, { client, storageKey: 'browser-issues', loadObjects: async () => [{ id: 'subject-rate', label: '预算执行率 · 本期合计' }] })
   }
   window.reopen()
  })
  await page.getByText('反馈报告问题', { exact: true }).click()
  await page.getByRole('button', { name: '选择对象并反馈', exact: true }).click()
  await page.getByLabel('问题关联对象').selectOption('subject-rate')
  await page.getByLabel('问题类型').selectOption('calculation')
  await page.getByLabel('问题描述与核对依据').fill('报告把两个项目执行率求平均得到70%，请核对是否应使用190/300=63.33%。')
  await page.getByRole('button', { name: '确认提交问题', exact: true }).focus()
  await page.screenshot({ path: `${directory}/submission-${width}.png`, fullPage: true })
  await page.addScriptTag({ path: fileURLToPath(new URL('../node_modules/axe-core/axe.min.js', import.meta.url)) })
  const scan = async () => page.evaluate(async () => (await window.axe.run('main')).violations.filter(v => ['serious', 'critical'].includes(v.impact)).map(v => v.id))
  const before = await scan()
  await page.keyboard.press('Enter')
  await page.getByText('提交结果未知', { exact: false }).waitFor()
  const focus = await page.evaluate(() => document.activeElement?.textContent)
  await page.evaluate(() => window.reopen())
  await page.getByText('查看原问题内容', { exact: true }).click()
  await page.getByRole('button', { name: '读取原问题', exact: true }).click()
  await page.getByText('已采纳，待修复', { exact: false }).waitFor()
  await page.getByText('已关联正式修复版本，仍待回归与重算核验', { exact: true }).click()
  await page.getByText('指标 · execution-rate · 修订 2', { exact: true }).waitFor()
  const after = await scan()
  const result = { width, focus, posts: await page.evaluate(() => window.calls.filter(call => call.method === 'POST').length),
   overflow: await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), seriousOrCritical: [...before, ...after] }
  await page.screenshot({ path: `${directory}/accepted-${width}.png`, fullPage: true })
  results.push(result)
  if (result.posts !== 1 || result.overflow || result.seriousOrCritical.length || focus !== '读取原问题') throw Error(JSON.stringify(result))
  await page.close()
 }
 await writeFile(`${directory}/browser-evidence.json`, JSON.stringify({ scope: '独立反馈组件，真实客户端与受控HTTP响应；不是完整Editor至真实管理PG连续验收', results }, null, 2))
 console.log(JSON.stringify(results))
} finally { await browser.close() }
