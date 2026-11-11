import { chromium } from 'playwright'
import { fileURLToPath } from 'node:url'
import { mkdir, writeFile } from 'node:fs/promises'
// 独立组件验收，HTTP响应受控；不替代真实报告全链路与业务签认。
const directory = fileURLToPath(new URL('../../../../docs/superpowers/reports/artifacts/2026-11-11-policy-recovery-ui', import.meta.url))
await mkdir(directory, { recursive: true })
const browser = await chromium.launch({ headless: true })
const results = []
try {
 for (const width of [1440, 1280, 768, 390]) {
  const page = await browser.newPage({ viewport: { width, height: 1100 } })
  await page.route('**/reports/v1/editor/assets/', route => route.fulfill({ contentType: 'text/html', body: '<!doctype html><html lang="zh-CN"><head><title>新口径恢复组件验收</title></head><body></body></html>' }))
  await page.goto('http://127.0.0.1:5187/reports/v1/editor/assets/')
  await page.evaluate(async () => {
   const { mountPolicyAdoption } = await import('/reports/v1/editor/assets/src/evidence-policy-adoption.ts')
   const { ReportEditorClient } = await import('/reports/v1/editor/assets/src/api.ts')
   const style = document.createElement('link'); style.rel = 'stylesheet'; style.href = '/reports/v1/editor/assets/src/style.css'; document.head.append(style)
   document.body.style.cssText = 'margin:0;background:#f5f7fa;font-family:system-ui;color:#253044'
   document.body.innerHTML = '<main><aside style="width:min(340px,100%);padding:12px;box-sizing:border-box"><h1 style="font-size:18px">本报告计算依据</h1><div id="panel"></div></aside></main>'
   sessionStorage.setItem('browser-recovery:policy-adoption', JSON.stringify({ requestId: 'confirmed', parentRevision: 2, expectedSha256: 'a'.repeat(64), operation: 'adopt_policy', confirmation: { requestId: 'confirmed', previewHash: 'b'.repeat(64), targetPolicyVersion: { policyId: 'budget', revision: 2 }, questionChoices: [{ questionId: 'budget', metricVersion: null, reason: '暂无适用指标' }] } }))
   window.calls = []; window.delivered = false
   const task = () => ({ taskId: 'task', status: window.delivered ? 'completed' : 'pending', result: null, execution: { runId: 'original', status: 'error', issueCodes: [] } })
   const client = new ReportEditorClient('/editor', async (input, init) => {
    const url = String(input); window.calls.push({ url, method: init?.method ?? 'GET' })
    if (url.endsWith('/preparation/resume')) {
     const cached = JSON.parse(sessionStorage.getItem('browser-recovery:policy-adoption:preparation-recovery'))
     if (cached?.recoveryId !== 'fixed-recovery' || cached.confirmation.identity.sha256 !== 'c'.repeat(64)) throw Error('cache missing')
     throw Error('accepted but response lost')
    }
    if (url.endsWith('/recoveries/fixed-recovery')) return Response.json({ taskId: 'task', recoveryId: 'fixed-recovery', status: 'completed', deliveryStatus: 'pending', issueCodes: ['policy_recovery_completion_unconfirmed'] })
    if (url.endsWith('/preparation')) return Response.json({ taskId: 'task', runId: 'new', outputRevision: 3, stateVersion: 7,
     analysis: { status: 'awaiting_confirmation', identity: { path: '报表/智能分析/恢复运行标识/policy-adoption/analysis-preparation.json', size: 128, sha256: 'c'.repeat(64) }, recoveryId: 'fixed-recovery', issueCodes: [] }, document: { status: 'not_applicable', issueCodes: [] } })
    if (url.endsWith('/delivery')) return Response.json({ task: task(), delivery: { revision: 3, validation: { ok: false, issues: [{ message: '业务核对尚未完成，文件可下载。' }] }, ...Object.fromEntries(['pdf', 'word', 'pptx', 'xlsx'].map(format => [format, { downloadUrl: '/download/' + format }])), editor: { openUrl: '/editor/new' } } })
    return Response.json(task())
   })
   window.reopen = () => { const panel = document.querySelector('#panel'); panel.replaceChildren(); mountPolicyAdoption(panel, { client, storageKey: 'browser-recovery', getDraft: () => ({ markdown: '报告' }) }) }
   window.reopen()
  })
  await page.getByRole('button', { name: '读取新口径任务进度', exact: true }).click()
  await page.getByRole('button', { name: '读取准备状态', exact: true }).click()
  await page.getByText('查看文件核对信息', { exact: true }).click()
  const resume = page.getByRole('button', { name: '确认分析准备并继续', exact: true })
  await resume.focus()
  await page.screenshot({ path: `${directory}/confirmation-${width}.png`, fullPage: true })
  await page.addScriptTag({ path: fileURLToPath(new URL('../node_modules/axe-core/axe.min.js', import.meta.url)) })
  const axe = async () => page.evaluate(async () => (await window.axe.run('main')).violations.filter(v => ['serious', 'critical'].includes(v.impact)).map(v => v.id))
  const before = await axe()
  await page.keyboard.press('Enter')
  await page.getByText('续跑结果未知', { exact: false }).waitFor()
  const focusAfterSubmit = await page.evaluate(() => document.activeElement?.textContent)
  await page.evaluate(() => window.reopen())
  const noAutoPost = await page.evaluate(() => window.calls.filter(call => call.method === 'POST').length === 1)
  await page.getByRole('button', { name: '读取新口径任务进度', exact: true }).click()
  await page.getByRole('button', { name: '读取续跑进度', exact: true }).click()
  await page.getByText('报告交付尚未确认', { exact: false }).waitFor()
  await page.screenshot({ path: `${directory}/unconfirmed-${width}.png`, fullPage: true })
  await page.evaluate(() => { window.delivered = true })
  await page.getByRole('button', { name: '读取新口径任务进度', exact: true }).click()
  await page.getByText('报告交付尚未确认', { exact: false }).waitFor({ state: 'hidden' })
  await page.getByRole('button', { name: '读取已生成文件', exact: true }).click()
  await page.getByRole('link', { name: '下载 XLSX · 修订 3', exact: true }).waitFor()
  const after = await axe()
  const result = { width, noAutoPost, focusAfterSubmit, overflow: await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
   seriousOrCritical: [...before, ...after], links: await page.getByRole('link').count(), posts: await page.evaluate(() => window.calls.filter(call => call.method === 'POST').length) }
  await page.screenshot({ path: `${directory}/delivery-${width}.png`, fullPage: true })
  results.push(result)
  if (!noAutoPost || result.posts !== 1 || result.links !== 5 || result.overflow || result.seriousOrCritical.length || focusAfterSubmit !== '读取续跑进度') throw Error(JSON.stringify(result))
  await page.close()
 }
 await writeFile(`${directory}/browser-evidence.json`, JSON.stringify({ scope: '独立Editor组件，真实客户端、受控HTTP响应；不等同完整Editor、真实报告或业务验收', results }, null, 2))
 console.log(JSON.stringify(results))
} finally { await browser.close() }
