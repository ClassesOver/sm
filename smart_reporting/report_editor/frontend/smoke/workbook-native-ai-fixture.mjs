// planner 与 HTTP 授权均为路由夹具；真实浏览器、XLSX patch/inspect 和下载回读。
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
const sha = value => createHash('sha256').update(value).digest('hex')
export async function installWorkbookNativeAIFixture({ page, sourceBytes, sourceSha, python }) {
  const staticRoot = resolve(process.env.WORKBOOK_SMOKE_STATIC_ROOT ?? '../static')
  const manifestSha256 = sha(await readFile(join(staticRoot,'.vite/manifest.json')))
  if (process.env.WORKBOOK_EXPECTED_MANIFEST_SHA256) assert.equal(manifestSha256, process.env.WORKBOOK_EXPECTED_MANIFEST_SHA256)
  page.on('pageerror', error => { if (error.message.includes('getUnitId')) console.error(JSON.stringify({ pageErrorStack: error.stack })) })
  page.on('console', async message => { if (message.type() === 'error' && message.text().includes('getUnitId')) console.error(JSON.stringify({ consoleLocation: message.location(), consoleArguments: await Promise.all(message.args().map(argument => argument.evaluate(value => value?.stack ?? String(value)).catch(() => 'unreadable'))) })) })
  const jobs = new Map(), tombstones = new Set(), starts = [], runtimeJavaScript = new Map(), responseTasks = []
  let accepted = 0, cancelled = 0
  page.on('response', response => { if (/\.js(?:\?|$)/.test(response.url())) responseTasks.push((async () => { const bytes = await response.body(), path = new URL(response.url()).pathname; runtimeJavaScript.set(path, { path, size: bytes.length, sha256: sha(bytes) }) })().catch(() => {})) })
  await page.route('**/reports/v1/native/fixture-gui/1/api/workbook-ai/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname.split('/api/workbook-ai/')[1]
    if (request.method() === 'POST') assert.equal(request.headers()['x-csrf-token'], 'csrf')
    if (path === 'cancel-request') { cancelled++; tombstones.add(request.postDataJSON().clientRequestId); return route.fulfill({ json: { status: 'cancelled' } }) }
    if (path === 'start') {
      const payload = request.postDataJSON(); starts.push(payload)
      assert.equal(payload.expectedSha256, sourceSha); assert.equal(payload.scope, 'range')
      assert.deepEqual(payload.selection, { sheetName: 'Summary', startRow: 0, endRow: 0, startColumn: 0, endColumn: 0 })
      const operation = { kind: 'applyCellEdits', edits: [{ sheetName: 'Summary', row: 0, column: 0, writeValue: true, cell: { value: 'AI候选标题' } }] }
      const combined = [...payload.operations, operation]
      python({ mode: 'patch', bytes: sourceBytes.toString('base64'), operations: combined })
      const job = { editId: 'job-' + starts.length, status: 'succeeded', snapshotSha256: sha(JSON.stringify(payload.operations)), proposal: { summary: '修改所选标题', operations: [operation] }, base: payload.operations, combined }
      jobs.set(job.editId, job)
      if (payload.instruction === '取消任务') { await delay(350); job.status = tombstones.has(payload.clientRequestId) ? 'cancelled' : 'running' }
      return route.fulfill({ json: job }).catch(() => {})
    }
    const [id, action] = path.split('/'), job = jobs.get(id); assert.ok(job)
    if (action === 'cancel') { job.status = 'cancelled'; return route.fulfill({ json: job }) }
    if (action === 'accept') { const payload = request.postDataJSON(); assert.deepEqual(payload.operations, job.base); assert.equal(payload.snapshotSha256, job.snapshotSha256); accepted++; return route.fulfill({ json: { accepted: true, operations: job.combined } }) }
    return route.fulfill({ json: job })
  })
  return async function run({ command, browser, getSavedBytes, pageErrors }) {
    const panel = page.locator('.workbook-native-ai'); await panel.waitFor({state:'attached'})
    await page.locator('[data-action="office-edit-ai"]').click()
    await panel.waitFor()
    const dockChecks = {}
    if(process.env.WORKBOOK_SMOKE_DOCK === '1') {
      const dock=page.locator('.office-task-dock'),main=page.locator('.office-task-main'),divider=dock.getByRole('separator')
      assert.equal(await dock.isVisible(),true);assert.equal(await panel.isVisible(),true)
      if(process.env.WORKBOOK_SMOKE_DOCK_ONLY === '1') {
        assert.equal(await page.locator('.office-task-workspace .workbook-ribbon').count(),0)
        assert.equal(await main.evaluate(element=>element.classList.contains('workbook-grid-frame')),true)
        assert.ok((await page.locator('.workbook-ribbon').boundingBox()).width>(await main.boundingBox()).width)
        const header=await panel.locator('.office-assistant-header').boundingBox(),body=await panel.locator('.office-assistant-body').boundingBox(),composer=await panel.locator('.office-assistant-composer').boundingBox()
        assert.ok(header.y+header.height<=body.y+2)
        assert.ok(body.y+body.height<=composer.y+2)
        assert.ok(composer.y>(await dock.boundingBox()).y+(await dock.boundingBox()).height/2)
        assert.equal(await panel.locator('.office-assistant-body').evaluate(element=>getComputedStyle(element).overflowY),'auto')
        Object.assign(dockChecks,{ribbonOutside:true,headerBodyComposerOrder:true,bottomComposer:true,middleScroll:true})
      }
      assert.ok((await dock.boundingBox()).x >= (await main.boundingBox()).x+(await main.boundingBox()).width-2)
      const width=Number(await divider.getAttribute('aria-valuenow'));await divider.focus();await page.keyboard.press('ArrowLeft');assert.ok(Number(await divider.getAttribute('aria-valuenow'))>width)
      await dock.locator('[data-office-ai-mode="read"]').click();await page.locator('.native-office-assistant').waitFor();assert.equal(await panel.isVisible(),false)
      await page.locator('.native-office-assistant .office-assistant-close').click();await dock.waitFor({state:'hidden'})
      await page.locator('.workbook-ribbon [data-action="ai-assistant"]').click();await page.locator('.native-office-assistant').waitFor()
      assert.equal(await dock.isVisible(),true)
      await dock.locator('[data-office-ai-mode="edit"]').click();await panel.waitFor()
      if(process.env.WORKBOOK_SMOKE_EVIDENCE_DIR){const root=resolve(process.env.WORKBOOK_SMOKE_EVIDENCE_DIR);await mkdir(root,{recursive:true});await page.screenshot({path:join(root,'dock-wide.png'),fullPage:true})}
      await page.setViewportSize({width:700,height:900});await delay(300)
      assert.ok((await dock.boundingBox()).width<=700);assert.equal(await panel.isVisible(),true)
      if(process.env.WORKBOOK_SMOKE_EVIDENCE_DIR)await page.screenshot({path:join(resolve(process.env.WORKBOOK_SMOKE_EVIDENCE_DIR),'dock-narrow.png'),fullPage:true})
      await page.setViewportSize({width:1440,height:1000});await delay(300)
      await dock.getByRole('button',{name:'收起 AI 助手',exact:true}).click();await dock.waitFor({state:'hidden'})
      await page.locator('[data-action="office-edit-ai"]').click();await panel.waitFor()
      Object.assign(dockChecks,{readAndEditModes:true,ribbonReadEntry:true,keyboardResize:true,narrowViewport:true,collapseAndReopen:true})
    }
    await page.locator('[data-ribbon-tab="Home"]').click(); await command('goto-open'); await page.locator('[data-goto-reference]').fill('A1'); await page.locator('.workbook-ribbon-goto-dialog .workbook-ribbon-format-apply').click()
    await command('bold')
    const draft = () => page.evaluate(() => JSON.parse(localStorage.getItem(Object.keys(localStorage).find(key => key.startsWith('native-editor-draft:')))).operations)
    await page.waitForFunction(() => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.length))
    const manual = await draft()
    await panel.locator('textarea').fill('修改标题'); await panel.locator('[type=submit]').click(); await panel.locator('.native-ai-preview').waitFor()
    assert.deepEqual(await draft(), manual); assert.match(await panel.innerText(), /alpha.*AI候选标题/s)
    assert.ok(starts[0].operations.some(op => op.kind === 'applyCellEdits' && op.edits.some(edit => edit.style?.bold === false)))
    if(process.env.WORKBOOK_SMOKE_DOCK_ONLY !== '1') {
      await command('italic'); await panel.locator('.native-ai-accept').click()
      await page.waitForFunction(() => document.querySelector('.workbook-native-ai .native-ai-status')?.textContent?.includes('完整草稿已变化')); assert.equal(accepted, 0)
      await panel.locator('[type=submit]').click(); await panel.locator('.native-ai-preview').waitFor()
    }
    await panel.locator('.native-ai-accept').click()
    await page.waitForFunction(() => document.querySelector('.workbook-native-ai .native-ai-status')?.textContent?.includes('候选已加入草稿')); assert.equal(accepted, 1)
    if (process.env.WORKBOOK_NATIVE_AI_DIAGNOSTIC === '1') {
      await delay(1000)
      if (process.env.WORKBOOK_SMOKE_EVIDENCE_DIR) { const root = resolve(process.env.WORKBOOK_SMOKE_EVIDENCE_DIR); await mkdir(root, { recursive: true }); await page.screenshot({ path: join(root, 'after-first-accept.png'), fullPage: true }) }
      console.error(JSON.stringify({ diagnostic: true, pageErrors })); assert.deepEqual(pageErrors, []); return
    }
    const adopted = await draft()
    if(process.env.WORKBOOK_SMOKE_DOCK_ONLY !== '1') {
    await panel.locator('.native-ai-undo').click(); await page.waitForFunction(() => !Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.stringify(JSON.parse(localStorage.getItem(key)).operations).includes('AI候选标题')))
    await panel.locator('.native-ai-redo').click(); await page.waitForFunction(() => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.stringify(JSON.parse(localStorage.getItem(key)).operations).includes('AI候选标题')))
    assert.deepEqual(await draft(), adopted)
    await page.waitForFunction(() => document.querySelector('#report-editor')?.inert === false)
    await panel.locator('textarea').fill('取消任务'); await panel.locator('[type=submit]').click(); await panel.locator('.native-ai-cancel').click()
    await page.waitForFunction(() => document.querySelector('.workbook-native-ai .native-ai-status')?.textContent?.includes('已放弃')); await delay(500)
    assert.ok(cancelled >= 1); assert.deepEqual(await draft(), adopted)
    }
    const buttons = await panel.locator('button').evaluateAll(elements => elements.map(button => ({ text: button.textContent, icons: button.querySelectorAll('svg[aria-hidden="true"]').length })))
    assert.ok(buttons.every(button => button.icons === 1))
    await page.locator('[data-action="save"]').click(); await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2', null, { timeout: 60000 })
    const downloadUrl = await page.locator('[data-action="xlsx-download"]').getAttribute('href')
    const downloaded = Buffer.from(await page.evaluate(async url => Array.from(new Uint8Array(await (await fetch(url)).arrayBuffer())), downloadUrl))
    assert.equal(sha(downloaded), sha(getSavedBytes()))
    const reopened = JSON.parse(python({ mode: 'inspect', bytes: downloaded.toString('base64') })); assert.equal(reopened.A1[0], 'AI候选标题'); assert.equal(reopened.A1[1], false); assert.equal(reopened.colB, 30)
    await Promise.all(responseTasks)
    if(process.env.WORKBOOK_SMOKE_STATIC_ROOT)for(const asset of runtimeJavaScript.values()){const file=asset.path.split('/reports/v1/editor/assets/')[1];assert.ok(file);assert.equal(asset.sha256,sha(await readFile(join(staticRoot,file))))}
    const receipt = { ok: pageErrors.length === 0, planner: 'deterministic-route-fixture', authentication: 'HTTP route fixture; server authorization covered by backend tests', staticRoot, dockChecks, manifestSha256, browserVersion: browser.version(), sourceSha256: sourceSha, downloadedSha256: sha(downloaded), runtimeJavaScript: [...runtimeJavaScript.values()].sort((a,b) => a.path.localeCompare(b.path)), explicitAccepts: accepted, cancelRequests: cancelled, frozenSelection: starts[0].selection, fullDraftStaleRejected: process.env.WORKBOOK_SMOKE_DOCK_ONLY !== '1', undoRedo: process.env.WORKBOOK_SMOKE_DOCK_ONLY !== '1', dockOnly:process.env.WORKBOOK_SMOKE_DOCK_ONLY === '1', revision: 2, downloadUrl, reopened, buttons, pageErrors }
    if (process.env.WORKBOOK_SMOKE_EVIDENCE_DIR) { const root = resolve(process.env.WORKBOOK_SMOKE_EVIDENCE_DIR); await mkdir(root, { recursive: true }); await writeFile(join(root, 'source.xlsx'), sourceBytes); await writeFile(join(root, 'downloaded.xlsx'), downloaded); await page.screenshot({ path: join(root, 'after-edit.png'), fullPage: true }); await writeFile(join(root, 'evidence.json'), JSON.stringify(receipt, null, 2) + '\n') }
    assert.deepEqual(pageErrors, [])
    console.log(JSON.stringify(receipt))
  }
}
