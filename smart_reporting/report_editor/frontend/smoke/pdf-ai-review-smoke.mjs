import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdir, readFile, writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'

// 使用已完成的实际构建；本辅助不执行 build，不调用真实 provider。
const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
const directory = process.env.PDF_AI_REVIEW_SMOKE_DIRECTORY ?? '/tmp/pdf-ai-review-built-20261111'
const port = Number(process.env.PDF_AI_REVIEW_SMOKE_PORT ?? 4287), origin = 'http://127.0.0.1:' + port
const normalPreview = process.env.PDF_AI_REVIEW_SMOKE_NORMAL_PREVIEW === '1'
const pendingPreview = process.env.PDF_AI_REVIEW_SMOKE_PENDING === '1'
const cases = pendingPreview ? ['pending'] : normalPreview ? ['normal'] : ['normal', 'overflow', 'clarify', 'discussion', 'cancel']
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
await mkdir(directory, {recursive:true})
const manifest = await readFile(join(frontend, '../static/.vite/manifest.json'))
await writeFile(join(directory, 'build-manifest.json'), manifest, {flag:'wx'})
const server = spawn(join(repo, '.venv/bin/python'), [join(frontend, 'smoke/pdf-ai-review-server.py'), '--directory', directory, '--port', String(port)], {cwd:repo, env:{...process.env, PYTHONPATH:repo}, stdio:'pipe'})
let serverLog = '', browser, page, stage = 'startup'
server.stdout.on('data', data => {serverLog += data}); server.stderr.on('data', data => {serverLog += data})
const errors = [], consoleErrors = [], httpErrors = [], assets = new Map(), assetChecks = [], starts = [], results = []
const previewRequests = [], previewResponses = [], previewChecks = []
const state = async () => (await fetch(origin + '/__smoke__/state')).json()
try {
  for (let index=0;;index++) {
    assert.equal(server.exitCode, null, serverLog)
    try {if ((await fetch(origin + '/__smoke__/state')).ok) break} catch {}
    assert(index < 200, serverLog); await delay(250)
  }
  const info = JSON.parse(await readFile(join(directory, 'server-info.json'), 'utf8'))
  browser = await chromium.launch({headless:true}); page = await browser.newPage({viewport:{width:1550, height:1100}})
  const network = await page.context().newCDPSession(page)
  await network.send('Network.enable')
  await network.send('Network.setCacheDisabled', {cacheDisabled:true})
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => {if (message.type() === 'error') consoleErrors.push(message.text())})
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (response.status() >= 400) httpErrors.push({path, status:response.status()})
    if (path.endsWith('/api/ai/review/start')) starts.push(response.request().postDataJSON())
    if (response.request().method() === 'POST' && (path.endsWith('/api/preview') || path.endsWith('/api/preview.pdf'))) {
      previewRequests.push({path, status:response.status(), body:response.request().postDataJSON()})
      if (path.endsWith('/api/preview.pdf')) {
        const check = (async () => {
          assert.equal(response.status(), 200)
          const bytes = await response.body()
          await writeFile(join(directory, 'normal-ui-preview.pdf'), bytes)
          previewResponses.push({path, sha256:sha(bytes), size:bytes.length, previewDigest:response.headers()['x-native-preview-digest']})
        })()
        check.catch(() => {}); previewChecks.push(check)
      }
    }
    if (!path.startsWith('/reports/v1/editor/assets/') || !path.endsWith('.js')) return
    const check = (async () => {
      assert.equal(response.status(), 200)
      const actual = await response.body(), disk = await readFile(join(frontend, '../static', path.slice('/reports/v1/editor/assets/'.length)))
      assert.equal(sha(actual), sha(disk)); assets.set(path, sha(actual))
    })()
    check.catch(() => {}) // 稍后统一检查并写诊断，避免事件回调提前退出而丢失失败证据。
    assetChecks.push(check)
  })
  await page.goto(origin + info.openPath)
  const ready = () => page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, {timeout:60000})
  await ready()
  const context = info.context
  const key = 'native-editor-draft:v1:' + JSON.stringify([context.scope.database, context.scope.companyId, context.scope.userId, context.scope.threadId, context.documentId, context.revision, info.sourceSha256])
  for (const mode of cases) {
    stage = mode
    await fetch(origin + '/__smoke__/mode/' + mode, {method:'POST'})
    const pendingRoot = {kind:'addTextAnnotation',pageId:'sha256:'+info.sourceSha256+':page:0',rect:[30,170,50,190],text:'Change Amount due 500 to Amount due 700.',createdMs:0}
    const pendingBase = [{...pendingRoot},{...pendingRoot}]
    const initialDraft = {version:1, identity:{documentId:context.documentId,revision:context.revision,sourceSha256:info.sourceSha256,scope:context.scope}, operations:pendingBase}
    await page.evaluate(({key,initialDraft,pendingPreview}) => {localStorage.removeItem(key); if(pendingPreview)localStorage.setItem(key,JSON.stringify(initialDraft))}, {key,initialDraft,pendingPreview})
    await page.reload(); await ready()
    await page.locator('[data-pdf-ribbon-tab="annotate"]').click()
    const entry = page.locator('[data-source-command-id="genoffice.pdf.annotate.aiReview.processNotes"]')
    assert.equal(await entry.isVisible(), true); assert.equal(await entry.isDisabled(), false)
    assert.match(await entry.innerText(), /批注/); assert.equal(await entry.locator('svg').count(), 1)
    await entry.click()
    const panel = page.locator('.native-pdf-review')
    await panel.waitFor({state:'visible'})
    assert.equal(await panel.getByLabel('PDF 批注处理补充要求').isEditable(), true)
    const before = (await state()).jobs.length
    await panel.locator('[data-pdf-review="start"]').click()
    if (mode === 'cancel') {
      for (let index=0;!(await state()).blockedEntered;index++) {assert(index < 200); await delay(100)}
      await panel.locator('[data-pdf-review="cancel"]').click()
      for (let index=0;;index++) {
        const current = await state(), job = current.jobs.at(-1)
        if (job?.status === 'cancelled') {
          assert.equal(current.blockedCancelled, true); assert.equal('proposal' in job, false)
          results.push({mode, job, swallowedCancellationCannotRevive:true}); break
        }
        assert(index < 200); await delay(100)
      }
    } else {
      let current, job
      for (let index=0;;index++) {
        current = await state(); job = current.jobs.at(-1)
        if (current.jobs.length > before && job?.status !== 'running') break
        assert(index < 400); await delay(100)
      }
      assert.equal(job.status, 'succeeded', JSON.stringify(job))
      await panel.locator('[role="status"]').filter({hasText:'处理建议已核验'}).waitFor()
      if(pendingPreview) assert.deepEqual(JSON.parse(await page.evaluate(key => localStorage.getItem(key), key)).operations,pendingBase)
      else assert.equal(await page.evaluate(key => localStorage.getItem(key), key), null)
      const proposal = job.proposal
      assert.equal(proposal.coverage.annotationsReadComplete, true)
      assert.equal(proposal.notes.length, pendingPreview ? 5 : 3)
      assert(proposal.notes.some(note => note.author === 'AI Assistant' && note.status === 'skipped'))
      if(!pendingPreview)assert(proposal.notes.some(note => /纯讨论/.test(note.reason) && note.status === 'skipped'))
      let stored, verification
      if (mode === 'normal' || mode === 'clarify' || mode === 'pending') {
        await panel.locator('[data-pdf-review="accept"]').click()
        await panel.locator('[role="status"]').filter({hasText:'建议已进入草稿'}).waitFor()
        await page.waitForFunction(key => Boolean(localStorage.getItem(key)), key)
        stored = JSON.parse(await page.evaluate(key => localStorage.getItem(key), key))
        assert.deepEqual(stored.operations, proposal.operations)
      }
      const operations = stored?.operations ?? proposal.operations
      verification = await (await fetch(origin + '/__smoke__/verify', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({editId:job.editId, operations})})).json()
      assert.equal(verification.previewDigest, proposal.previewDigest)
      if (mode === 'normal' || mode === 'pending') {
        assert.match(verification.text, /Amount due 700/); assert.doesNotMatch(verification.text, /Amount due 500/)
        assert.deepEqual(verification.replyAuthors, ['AI Assistant']); assert.deepEqual(proposal.appliedOperationIndices, pendingPreview ? [0,1,2,3] : [0, 1])
        if(pendingPreview){
          assert.deepEqual(stored.operations.map(op=>op.kind),['addTextAnnotation','addTextAnnotation','replaceText','replyPendingNote'])
          assert.deepEqual(stored.operations[0],pendingBase[0])
          const {localId,...root}=stored.operations[1];assert.deepEqual(root,pendingBase[1]);assert.equal(stored.operations[3].parentLocalId,localId)
          const exact=verification.pendingNoteMapping.find(m=>m.operationIndex===1),other=verification.pendingNoteMapping.find(m=>m.operationIndex===0)
          assert(exact&&other);assert.deepEqual(verification.replyParentRefs,[exact.sourceRef]);assert.notEqual(exact.sourceRef,other.sourceRef)
        }
      } else if (mode === 'clarify') {
        assert.match(verification.text, /Amount due 500/); assert.deepEqual(verification.replyAuthors, ['AI Assistant'])
        assert.match(verification.replyContents[0], /请确认/)
      } else if (mode === 'overflow') {
        assert.match(verification.text, /Amount due 500/); assert.deepEqual(verification.replyAuthors, [])
        assert.equal(proposal.skippedOperations.length, 1); assert(proposal.notes.some(note => note.replyOmittedReason))
      } else {
        assert.deepEqual(proposal.operations, []); assert.deepEqual(verification.replyAuthors, [])
      }
      let uiPreview
      if (normalPreview || pendingPreview) {
        stage = pendingPreview ? 'pending-user-preview' : 'normal-user-preview'
        await page.locator('[data-pdf-ribbon-tab="edit"]').click()
        await page.getByRole('button', {name:'校验当前修改', exact:true}).click()
        await page.locator('.native-pdf-editor[data-pdf-preview="true"]').waitFor()
        await page.waitForFunction(() => {
          const layers = [...document.querySelectorAll('.pdf-document-pages .textLayer')].map(layer => layer.textContent ?? '').join('\n')
          return layers.includes('Amount due 700') && !layers.includes('Amount due 500')
        }, null, {timeout:60000})
        const review = page.locator('.pdf-preview-review')
        await review.waitFor({state:'visible'})
        const execution = await review.locator('li').allTextContents()
        assert(execution.some(item => /已执行.*原位改字/.test(item)))
        assert(execution.some(item => /已执行.*便签回复/.test(item)))
        assert.equal(execution.length, pendingPreview ? 4 : 2)
        assert.equal(await review.locator('input[type="checkbox"]').isChecked(), false)
        await Promise.all(previewChecks)
        assert.equal(previewResponses.length, 1)
        assert.equal(previewResponses[0].sha256, verification.sha256)
        assert.equal(previewResponses[0].previewDigest, proposal.previewDigest)
        const batch = previewRequests.filter(request => JSON.stringify(request.body.operations) === JSON.stringify(stored.operations))
        assert(batch.some(request => request.path.endsWith('/api/preview') && request.status === 200))
        assert(batch.some(request => request.path.endsWith('/api/preview.pdf') && request.status === 200))
        uiPreview = {execution, confirmed:false, textLayer:await page.locator('.pdf-document-pages .textLayer').allTextContents(), requests:batch, response:previewResponses[0]}
        await page.screenshot({path:join(directory, 'normal-ui-preview.png'), fullPage:true})
      }
      results.push({mode, job, stored, verification, uiPreview, sourceUnchanged:true})
    }
    const current = await state()
    assert.equal(current.sourceSha256, info.sourceSha256)
    assert.equal(current.requests.some(request => request.method === 'POST' && /\/(save|export)$/.test(request.path)), false)
    const layout = await panel.evaluate(element => {
      const style = getComputedStyle(element), rect = element.getBoundingClientRect()
      const next = [...document.querySelectorAll('.native-ai')].find(other => other !== element &&
        !other.hasAttribute('hidden') && getComputedStyle(other).display !== 'none' &&
        (element.compareDocumentPosition(other) & Node.DOCUMENT_POSITION_FOLLOWING))
      const nextRect = next?.getBoundingClientRect()
      const previous = element.scrollTop
      element.scrollTop = element.scrollHeight
      const scrolled = element.scrollTop
      element.scrollTop = previous
      return {height:rect.height, clientHeight:element.clientHeight, scrollHeight:element.scrollHeight,
        maxHeight:style.maxHeight, overflowY:style.overflowY, flexShrink:style.flexShrink,
        padding:parseFloat(style.paddingTop) + parseFloat(style.paddingBottom),
        nextTop:nextRect?.top, bottom:rect.bottom, scrolled}
    })
    assert.equal(layout.overflowY, 'auto'); assert.equal(layout.flexShrink, '1')
    assert(layout.height > 0 && layout.clientHeight > 0)
    assert(Number.isFinite(parseFloat(layout.maxHeight)))
    assert(layout.clientHeight <= Math.ceil(parseFloat(layout.maxHeight)) + layout.padding + 2)
    assert.notEqual(layout.nextTop, undefined, '必须实际找到后方选区助手以核对不重叠')
    assert(layout.nextTop >= layout.bottom - 1, JSON.stringify(layout))
    if (layout.scrollHeight > layout.clientHeight) assert(layout.scrolled > 0)
    if (mode === 'normal' || mode === 'pending') {
      assert(layout.scrollHeight > layout.clientHeight, '三条实际批注应在原视口中可滚动')
      await panel.evaluate(element => {element.scrollTop = element.scrollHeight})
      await page.screenshot({path:join(directory, mode + '-scrolled.png'), fullPage:true})
      await panel.evaluate(element => {element.scrollTop = 0})
    }
    results.at(-1).layout = layout
    await page.screenshot({path:join(directory, mode + '.png'), fullPage:true})
    await writeFile(join(directory, mode + '-result.json'), JSON.stringify(results.at(-1), null, 2))
  }
  await Promise.all(assetChecks)
  assert.deepEqual(errors, []); assert.deepEqual(consoleErrors, []); assert.deepEqual(httpErrors, [])
  assert(starts.length === cases.length && starts.every(start => !('selection' in start) && start.operations.length === (pendingPreview ? 2 : 0)))
  assert.deepEqual(await readFile(join(frontend, '../static/.vite/manifest.json')), manifest)
  const final = await state()
  const summary = {ok:true, directory, validationMode:pendingPreview ? 'pending-user-preview' : normalPreview ? 'normal-user-preview' : 'five-cases', browserVersion:browser.version(), manifestSha256:sha(manifest), sourceSha256:info.sourceSha256,
    provider:'ScriptedModel through real Agno; not a real provider', http:'Real HTTP/cookie/CSRF/workspace/engine; scoped in-memory revision lookup',
    results, assets:Object.fromEntries(assets), starts, providerCalls:final.providerCalls, errors, consoleErrors, httpErrors}
  await writeFile(join(directory, 'summary.json'), JSON.stringify(summary, null, 2))
  console.log(JSON.stringify({ok:true, directory, cases:results.length, assets:assets.size}))
} catch (error) {
  if (page) {await writeFile(join(directory, 'failure.html'), await page.content()).catch(() => {}); await page.screenshot({path:join(directory, 'failure.png'), fullPage:true}).catch(() => {})}
  console.error(JSON.stringify({stage, directory})); throw error
} finally {
  const assetResults = await Promise.allSettled(assetChecks)
  await writeFile(join(directory, 'diagnostics.json'), JSON.stringify({stage, manifestSha256:sha(manifest), assets:Object.fromEntries(assets),
    assetFailures:assetResults.filter(result => result.status === 'rejected').map(result => String(result.reason)),
    starts, previewRequests, previewResponses, errors, consoleErrors, httpErrors}, null, 2))
  await browser?.close(); server.kill(); await writeFile(join(directory, 'server.log'), serverLog)
}
