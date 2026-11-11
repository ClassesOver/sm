import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
let input = ''
for await (const chunk of process.stdin) input += chunk
const config = JSON.parse(input), origin = 'http://127.0.0.1:5199'
await mkdir(config.output, { recursive: true })
const html = (await readFile(new URL('../management.html', import.meta.url), 'utf8')).replace('src="/src/', 'src="/management/src/')
const server = await createServer({ configFile: 'vite.management.config.ts', server: { host: '127.0.0.1', port: 5199, strictPort: true } })
await server.listen()
const browser = await chromium.launch({ headless: true })
try {
 const page = await browser.newPage({ viewport: { width: 390, height: 1100 } })
 page.setDefaultTimeout(15000)
 await page.context().addCookies([{ name: 'report_management_session', value: config.token, url: origin + '/management/' }])
 const http = [], errors = [], widths = []
 let saves = 0, publications = 0, previews = 0
 page.on('pageerror', error => errors.push(error.message))
 await page.route('**/management/statistical-policies?**', route => route.fulfill({ contentType: 'text/html', body: html }))
 await page.route('**/management/api/v1/**', async route => {
  const req = route.request(), url = new URL(req.url())
  const result = await route.fetch({ url: config.apiOrigin + url.pathname + url.search, headers: { ...req.headers(), cookie: 'report_management_session=' + config.token } })
  const body = await result.json()
  http.push({ path: url.pathname, query: url.search, method: req.method(), status: result.status(), body: url.pathname.endsWith('/me') ? { username: body.username } : body })
  if (req.method() === 'PUT' || req.method() === 'POST') {
   assert.equal(result.status(), 200, JSON.stringify(body))
   assert.equal(req.postDataJSON().companyId, 'a')
   if (url.pathname.endsWith('/preview')) { previews++; assert.equal(body.calculationChanged, true); assert.equal(body.evidenceChanged, true);
    assert.ok(body.changedFields.includes('filters')); assert.ok(body.changedFields.includes('readinessPolicy')); return route.fulfill({ response: result }) }
   if (req.method() === 'PUT') {
    saves++; assert.equal(req.postDataJSON().expectedVersion, 1)
    assert.equal(req.postDataJSON().definition.scopeId, undefined); assert.equal(req.postDataJSON().definition.revision, undefined)
   } else { publications++; assert.ok(url.pathname.endsWith('/publish')); assert.equal(req.postDataJSON().expectedVersion, 2) }
   return route.abort('failed')
  }
  await route.fulfill({ response: result })
 })
 await page.goto(origin + '/management/statistical-policies?' + new URLSearchParams({ database: config.database, companyId: config.companyId, editPolicy: 'monthly-budget' }))
 await page.getByText('编辑统计口径 · monthly-budget', { exact: true }).waitFor()
 await page.locator('#policy-name').fill('修订预算口径')
 await page.locator('#policy-notes').fill('筛选项目B，明确全年期间和预期对象，采用明确修订的制度依据。')
 await page.getByRole('button', { name: '从已发布制度依据中选择', exact: true }).click()
 await page.getByRole('textbox', { name: '搜索制度依据集合', exact: true }).fill('修订预算管理制度')
 await page.getByRole('button', { name: '搜索集合', exact: true }).click()
 const previewSource = page.getByRole('button', { name: '预览原文 修订预算管理制度 修订 2', exact: true })
 await previewSource.click()
 const drawer = page.getByRole('dialog')
 await drawer.getByText('第2–2行', { exact: false }).waitFor()
 await drawer.getByText('项目B需单独核对全年期间。', { exact: false }).waitFor()
 await page.addScriptTag({ path: fileURLToPath(new URL('../node_modules/axe-core/axe.min.js', import.meta.url)) })
 const previewWidths = []
 for (const width of [1440, 1280, 768, 390]) {
  await page.setViewportSize({ width, height: 1100 })
  const axe = await page.evaluate(async () => (await window.axe.run('[role=dialog]')).violations.filter(i => ['serious', 'critical'].includes(i.impact)).map(i => i.id))
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  assert.deepEqual(axe, []); assert.equal(overflow, false)
  await page.screenshot({ path: config.output + '/source-preview-' + width + '.png', fullPage: true, animations: 'disabled' })
  previewWidths.push({ width, axe, overflow })
 }
 await page.keyboard.press('Escape'); await drawer.waitFor({ state: 'detached' })
 await previewSource.focus(); await page.keyboard.press('Enter'); await drawer.waitFor()
 await page.keyboard.press('Escape'); await drawer.waitFor({ state: 'detached' })
 await page.waitForFunction(() => document.activeElement?.textContent === '预览原文 修订预算管理制度 修订 2')
 await page.getByRole('button', { name: '选择集合 ' + config.targetEvidenceReleaseId, exact: true }).click()
 await page.getByText('已选择明确的制度依据集合', { exact: false }).waitFor()
 assert.equal(await page.locator('#policy-evidence').inputValue(), config.targetEvidenceReleaseId)
 await page.getByRole('textbox', { name: '筛选 1 值 1', exact: true }).fill('B')
 await page.getByRole('button', { name: '添加预期期间', exact: true }).click()
 await page.getByLabel('预期期间 1 开始', { exact: true }).fill('2026-01-01')
 await page.getByLabel('预期期间 1 结束', { exact: true }).fill('2027-01-01')
 await page.getByRole('button', { name: '添加预期分组', exact: true }).click()
 await page.getByRole('textbox', { name: '预期分组 1 维度 1', exact: true }).fill('project')
 await page.getByRole('textbox', { name: '预期分组 1 维度 1 值', exact: true }).fill('B')
 await page.getByRole('button', { name: '保存口径草稿', exact: true }).click()
 await page.getByText('口径提交结果待确认', { exact: false }).waitFor()
 await page.reload()
 const recover = page.getByRole('button', { name: '读取原口径提交结果', exact: true })
 await recover.waitFor(); await recover.focus(); await page.keyboard.press('Enter')
 await page.getByText('当前草稿与原提交一致', { exact: false }).waitFor()
 await page.getByRole('button', { name: '核对发布变更', exact: true }).click()
 await page.getByText('计算规则变化', { exact: true }).waitFor()
 await page.getByText('计算变化：筛选条件、数据充分性规则', { exact: true }).waitFor()
 await page.getByText('制度依据变化', { exact: true }).waitFor()
 const diff=page.getByRole('region',{name:'口径发布逐项差异',exact:true})
 await diff.getByText('当前发布：版本 1；目标发布：版本 2',{exact:false}).waitFor()
 for(const text of ['修订预算口径','文本「A」','文本「B」','2026-01-01 至 2027-01-01（结束不包含）','project="B"',config.targetEvidenceReleaseId])assert.ok((await diff.textContent()).includes(text),text)
 const diffText=await diff.textContent()
 await writeFile(config.output+'/release-diff-text.txt',diffText)

 await page.addScriptTag({ path: fileURLToPath(new URL('../node_modules/axe-core/axe.min.js', import.meta.url)) })
 for (const width of [1440, 1280, 768, 390]) {
  await page.setViewportSize({ width, height: 1100 })
  const axe = await page.evaluate(async () => (await window.axe.run('main')).violations.filter(i => ['serious', 'critical'].includes(i.impact)).map(i => i.id))
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  assert.deepEqual(axe, []); assert.equal(overflow, false)
  await page.screenshot({ path: config.output + '/policy-preview-' + width + '.png', fullPage: true, animations: 'disabled' })
  await diff.screenshot({ path: config.output + '/release-diff-' + width + '.png', animations: 'disabled' })
  widths.push({ width, axe, overflow })
 }
 await page.getByRole('checkbox', { name: '确认口径发布', exact: true }).check()
 await page.getByRole('button', { name: '发布口径版本', exact: true }).click()
 await page.getByText('口径提交结果待确认', { exact: false }).waitFor()
 await page.reload(); await recover.click()
 await page.getByText('当前发布与原提交一致', { exact: false }).waitFor()
 assert.equal(saves, 1); assert.equal(publications, 1); assert.equal(previews, 1); assert.deepEqual(errors, [])
 await page.getByRole('combobox', { name: '当前组织', exact: true }).click()
 await Promise.all([page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/statistical-policies') && new URL(response.url()).searchParams.get('companyId') === 'b'), page.getByText('组织B', { exact: true }).click()])
 await page.getByRole('region', { name: '统计口径定义编辑', exact: true }).waitFor({ state: 'detached' })
 await page.waitForLoadState('networkidle')
 await writeFile(config.output + '/http-evidence.json', JSON.stringify(http, null, 2))
 await writeFile(config.output + '/browser-evidence.json', JSON.stringify({ saves, publications, previews, errors, widths, previewWidths,
  targetEvidenceReleaseId: config.targetEvidenceReleaseId, exactRevisionPreview: 2, sourceKeyboardEscapeAndFocus: true, scopeSwitchClearsEditor: true, fullSavedReleaseDiff: true }, null, 2))
} finally { await browser.close(); await server.close() }
