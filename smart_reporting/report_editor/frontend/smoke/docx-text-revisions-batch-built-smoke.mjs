// 正文批量修订 built GUI：原生单事务、刷新恢复、真实 Python patch 与下载 XML 独立回读。
// 不构建。DOCX_TEXT_REVISION_BATCH_SMOKE_DIR 可复用 checkpoint，避免已经成功的保存重复提交。
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const staticRoot = resolve(process.env.DOCX_TEST_DIST ?? join(frontend, '../static'))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.DOCX_TEXT_REVISION_BATCH_SMOKE_PORT ?? 4256)
const baseUrl = `http://127.0.0.1:${port}`
const documentId = 'fixture-text-revisions-batch-built'
const mediaType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex')
const manifestPath = join(staticRoot, '.vite/manifest.json')
const manifestBefore = sha256(await readFile(manifestPath))
const temporary = process.env.DOCX_TEXT_REVISION_BATCH_SMOKE_DIR ?? await mkdtemp(join(tmpdir(), 'docx-text-revisions-batch-built-'))
await mkdir(temporary, { recursive: true })
const checkpointPath = join(temporary, 'checkpoint.json')
let checkpoint
try { checkpoint = JSON.parse(await readFile(checkpointPath, 'utf8')) } catch { checkpoint = { cases: {} } }
const persist = () => writeFile(checkpointPath, JSON.stringify(checkpoint, null, 2))
const runPython = input => {
  const result = spawnSync(join(repo, '.venv/bin/python'), ['-c', String.raw`
import base64,json,re,sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
from hashlib import sha256
from lxml import etree as E
from smart_reporting.reporting.delivery.docx_native import inspect_docx,patch_docx
p=json.load(sys.stdin)
NS='http://schemas.openxmlformats.org/wordprocessingml/2006/main';ns={'w':NS}
def details(data):
 with ZipFile(BytesIO(data)) as z:
  assert z.testzip() is None
  for name in z.namelist():
   if name.endswith(('.xml','.rels')):E.fromstring(z.read(name))
  xml=z.read('word/document.xml').decode();root=E.fromstring(xml.encode());paras=root.findall('w:body/w:p',ns)
  target=paras[1]
  return {'xml':xml,'paragraph':E.tostring(target).decode(),'paragraphC14n':E.tostring(target,method='c14n').decode(),
   'text':''.join(target.itertext()),'remainingTypes':[E.QName(n).localname for n in target if E.QName(n).localname in ['ins','del']],
   'parts':{n:sha256(z.read(n)).hexdigest() for n in z.namelist() if n!='word/document.xml' and not n.endswith('/')},
   'nonTargetParagraphs':[E.tostring(n,method='c14n').decode() for i,n in enumerate(paras) if i!=1]}
if p['mode']=='fixture':
 from docx import Document
 doc=Document();doc.sections[0].header.paragraphs[0].text='HEADER-KEEP';doc.sections[0].footer.paragraphs[0].text='FOOTER-KEEP';buf=BytesIO();doc.save(buf)
 def run(text,deleted=False):return '<w:r><w:'+('delText' if deleted else 't')+' xml:space="preserve">'+text+'</w:'+('delText' if deleted else 't')+'></w:r>'
 def revision(kind,text):return '<w:'+kind+' w:id="7" w:author="同一作者" w:date="2026-11-10T00:00:00Z">'+run(text,kind=='del')+'</w:'+kind+'>'
 paragraph='<w:p w:rsidR="00ABCDEF"><w:pPr><w:spacing w:after="0"/></w:pPr>'+run('前😀|')+revision('ins','中文😀同')+revision('ins','中文😀同')+revision('del','删一😀')+revision('del','删二😀')+run('|后')+'</w:p>'
 with ZipFile(BytesIO(buf.getvalue())) as zin,ZipFile(p['outputPath'],'w') as zout:
  for name in zin.namelist():
   data=zin.read(name)
   if name=='word/document.xml':
    xml=data.decode();xml=re.sub(r'(<w:body>)[\s\S]*?(<w:sectPr\b)',lambda m:m[1]+'<w:p>'+run('NON-TARGET-BEFORE')+'</w:p>'+paragraph+'<w:p>'+run('NON-TARGET-AFTER 中文😀')+'</w:p><w:p><w:pPr><w:pPrChange w:id="88" w:author="复杂作者" w:date="2026-11-10T00:00:00Z"><w:pPr><w:spacing w:after="120"/></w:pPr></w:pPrChange></w:pPr>'+run('COMPLEX-REVISION-KEEP')+'</w:p>'+m[2],xml,count=1);data=xml.encode()
   zout.writestr(name,data)
  zout.writestr('customXml/text-revisions-opaque.xml','<keep xmlns="urn:text-revisions-probe">非目标😀</keep>')
 print('ok')
elif p['mode']=='patch':
 data=patch_docx(Path(p['sourcePath']).read_bytes(),p['operations']);Path(p['outputPath']).write_bytes(data);print(base64.b64encode(data).decode())
elif p['mode']=='verify':
 source=Path(p['sourcePath']).read_bytes();actual=Path(p['path']).read_bytes();a=details(source);b=details(actual)
 assert a['parts']==b['parts'],'non-target ZIP parts changed'
 assert a['nonTargetParagraphs']==b['nonTargetParagraphs'],'non-target paragraphs changed'
 with ZipFile(BytesIO(source)) as z:root=E.fromstring(z.read('word/document.xml'))
 target=root.findall('w:body/w:p',ns)[1];wrappers=[n for n in target if E.QName(n).localname in ['ins','del']]
 for decision in sorted(p['decisions'],key=lambda d:d['index'],reverse=True):
  node=wrappers[decision['index']];kind=E.QName(node).localname;keep=(kind=='ins')==(decision['action']=='accept');index=target.index(node)
  if keep:
   for child in list(node):
    for text in child.iter('{'+NS+'}delText'):text.tag='{'+NS+'}t'
    target.insert(index,child);index+=1
  target.remove(node)
 expected=E.tostring(target,method='c14n').decode()
 assert expected==b['paragraphC14n'],'target differs from independent XML decision'
 expectedXml=E.tostring(root,method='c14n')
 with ZipFile(BytesIO(actual)) as z:assert expectedXml==E.tostring(E.fromstring(z.read('word/document.xml')),method='c14n'),'document changed beyond selected wrappers'
 print(json.dumps({'ok':True,'sha256':sha256(actual).hexdigest(),'remainingTypes':b['remainingTypes'],'text':b['text'],'nonTargetParts':len(b['parts']),'onlySelectedWrappersChanged':True},ensure_ascii=False))
else:
 data=Path(p['path']).read_bytes();print(json.dumps({'model':inspect_docx(data),'details':details(data)},ensure_ascii=False))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 30 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr || `python exited ${result.status}`)
  return result.stdout.trim()
}
const cases = ['accept','reject'].map((action,index)=>({name:`batch-${action}`,revision:1+index*10,action,decisions:[0,1,2,3].map(index=>({index,action}))}))
const revisions = new Map(), inspections = new Map(), downloadRevisions = new Map(), savePayloads = []
let server, browser, page, stage = 'setup', routeError
const downloadServer = createServer((request, response) => {
  const match = /^\/revision-(\d+)\.docx$/.exec(request.url ?? ''), bytes = match && downloadRevisions.get(Number(match[1]))
  if (!bytes) { response.writeHead(404); response.end(); return }
  response.writeHead(200, { 'Content-Type': mediaType, 'Content-Disposition': 'attachment; filename=text-revisions.docx', 'Content-Length': bytes.length }); response.end(bytes)
})
await new Promise(resolve => downloadServer.listen(0, '127.0.0.1', resolve))
const downloadBase = `http://127.0.0.1:${downloadServer.address().port}`
try {
  for (const entry of cases) {
    const path = join(temporary, `revision-${entry.revision}.docx`)
    try { await readFile(path) } catch { runPython({ mode: 'fixture', outputPath: path }) }
    revisions.set(entry.revision, await readFile(path)); inspections.set(entry.revision, JSON.parse(runPython({ mode: 'inspect', path })))
    const saved = checkpoint.cases[entry.name]
    if (saved?.saved) {
      const next = entry.revision + 1, output = join(temporary, `revision-${next}.docx`)
      const bytes = await readFile(output); assert.equal(sha256(bytes), saved.sha256, 'checkpoint identity')
      revisions.set(next, bytes); downloadRevisions.set(next, bytes); inspections.set(next, JSON.parse(runPython({ mode: 'inspect', path: output })))
    }
    const targets = inspections.get(entry.revision).model.blocks.flatMap(block => block.reviewTargets ?? [])
    assert.equal(targets.length, 4, JSON.stringify(inspections.get(entry.revision).model.blocks))
    assert.equal(new Set(targets.map(target => target.revisionId)).size, 4)
    assert.equal(new Set(targets.map(target => target.originalRevisionId)).size, 1, '重复 w:id 不能合并目标')
    assert.deepEqual(targets.map(target => target.type), ['insertion', 'insertion', 'deletion', 'deletion'])
  }
  await persist()
  if (process.env.DOCX_TEXT_REVISION_BATCH_SMOKE_FIXTURE_ONLY === '1') {
    console.log(JSON.stringify({ ok: true, fixtureOnly: true, temporary, targetsPerSource: 4, sources: cases.length }))
    process.exit(0)
  }
  server = spawn('./node_modules/.bin/vite', ['preview', '--outDir', staticRoot, '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'pipe' })
  let serverLog = ''; server.stderr.on('data', chunk => { serverLog += chunk })
  for (let attempt = 0; ; attempt++) {
    if (server.exitCode !== null) throw new Error(`preview exited: ${serverLog}`)
    try { if ((await fetch(`${baseUrl}/reports/v1/editor/assets/native.html`)).ok) break } catch {}
    if (attempt === 120) throw new Error(`preview timeout: ${serverLog}`)
    await delay(250)
  }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
  const errors = [], checks = [], chunks = new Map()
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('dialog', dialog => dialog.accept())
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (!path.startsWith('/reports/v1/editor/assets/assets/') || !path.endsWith('.js')) return
    checks.push((async () => {
      assert.equal(response.status(), 200)
      const file = path.split('/').at(-1), actual = await response.body(), expected = await readFile(join(staticRoot, 'assets', file))
      assert.equal(sha256(actual), sha256(expected), `浏览器构建文件身份：${file}`); chunks.set(file, sha256(actual))
    })())
  })
  const revisionOf = request => Number(new URL(request.url()).pathname.split('/')[5])
  await page.route(`**/reports/v1/native/${documentId}/*/api/context`, route => {
    const revision = revisionOf(route.request()), bytes = revisions.get(revision)
    return route.fulfill({ json: { context: { documentId, format: 'docx', revision, parentRevision: null, scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' }, sourceFile: { path: `revision-${revision}.docx`, size: bytes.length, sha256: sha256(bytes), mediaType }, origin: 'report' }, csrfToken: 'csrf', capabilities: { docx_editor: true }, editingEnabled: true } })
  })
  await page.route(`**/reports/v1/native/${documentId}/*/api/file`, route => route.fulfill({ body: revisions.get(revisionOf(route.request())), contentType: mediaType }))
  await page.route(`**/reports/v1/native/${documentId}/*/api/preview`, route => { const model = inspections.get(revisionOf(route.request())).model; return route.fulfill({ json: { sourceSha256: model.sourceSha256, draftSha256: model.sourceSha256, model } }) })
  await page.route(`**/reports/v1/native/${documentId}/*/api/save`, async route => {
    try {
      const revision = revisionOf(route.request()), next = revision + 1, payload = route.request().postDataJSON(), entry = cases.find(entry => entry.revision === revision)
      assert.ok(entry); assert.ok(!checkpoint.cases[entry.name]?.saved, '禁止重复保存已完成 checkpoint')
      const source = inspections.get(revision), targets = source.model.blocks.flatMap(block => block.reviewTargets ?? [])
      const expected = entry.decisions.map(decision => ({ kind: 'resolveTextRevision', blockId: targets[decision.index].blockId, expectedObjectSha256: targets[decision.index].expectedObjectSha256, revisionId: targets[decision.index].revisionId, action: decision.action }))
      assert.deepEqual(payload.operations, expected, '公开 save 仅携带精确授权目标，无整段替换')
      savePayloads.push({ revision, operations: payload.operations })
      const outputPath = join(temporary, `revision-${next}.docx`), sourcePath = join(temporary, `revision-${revision}.docx`)
      const bytes = Buffer.from(runPython({ mode: 'patch', sourcePath, outputPath, operations: payload.operations }), 'base64')
      const verified = JSON.parse(runPython({ mode: 'verify', sourcePath, path: outputPath, decisions: entry.decisions }))
      revisions.set(next, bytes); downloadRevisions.set(next, bytes); inspections.set(next, JSON.parse(runPython({ mode: 'inspect', path: outputPath })))
      checkpoint.cases[entry.name] = { saved: true, sha256: sha256(bytes), revision, next, operations: payload.operations, verified }; await persist()
      await route.fulfill({ json: { documentId, revision: next, parentRevision: revision, revisionRegistered: true, artifacts: { word: { downloadUrl: `${downloadBase}/revision-${next}.docx`, size: bytes.length, sha256: sha256(bytes) } }, editor: { openUrl: `/reports/v1/native/${documentId}/${next}` }, validation: { ok: true, issues: [] } } })
    } catch (error) { routeError = String(error); await route.fulfill({ status: 500, json: { detail: routeError } }) }
  })
  await page.route(new RegExp(`/reports/v1/native/${documentId}/[0-9]+$`), async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
  const open = async revision => { await page.goto(`${baseUrl}/reports/v1/native/${documentId}/${revision}`); await page.locator('.docx-source-home').waitFor({ timeout: 60000 }) }
  const dialog = () => page.getByRole('dialog', { name: '正文修订列表', exact: true })
  const list = async () => { await page.locator('[data-tab-id="review"]').click(); await page.locator('[data-action="text-revision-list"]').click(); await dialog().waitFor(); return dialog() }
  const close = async () => { await dialog().getByRole('button', { name: '关闭正文修订列表', exact: true }).click(); await dialog().waitFor({ state: 'detached' }) }
  const row = id => dialog().locator(`[data-revision-id="${id}"]`)
  const editor = () => page.getByRole('textbox', { name: 'Word 文档编辑区' })
  const body = () => editor().evaluate(node => node.innerHTML)
  const selection = () => page.evaluate(() => {
    const selection = getSelection(), range = selection?.rangeCount ? selection.getRangeAt(0) : null
    const element = range?.startContainer.nodeType === Node.ELEMENT_NODE ? range.startContainer : range?.startContainer.parentElement
    const paragraph = element?.closest('p')
    if (!range || !paragraph) return null
    const prefix = document.createRange(); prefix.selectNodeContents(paragraph); prefix.setEnd(range.startContainer, range.startOffset)
    return { text: selection.toString(), from: prefix.toString().length, to: prefix.toString().length + selection.toString().length }
  })
  for (const entry of cases) {
    const source = inspections.get(entry.revision), targets = source.model.blocks.flatMap(block => block.reviewTargets ?? [])
    let saved = checkpoint.cases[entry.name]
    if (!saved?.saved) {
      stage = `${entry.name}:open`; await open(entry.revision); const before = await body(); await list()
      assert.equal(await dialog().locator('[data-revision-id]').count(), 4)
      await row(targets[1].revisionId).locator('[data-action="locate"]').click()
      assert.deepEqual(await selection(), { text: '中文😀同', from: targets[1].sourceRange.from, to: targets[1].sourceRange.to }, '相邻同 mark 重复文字第二个 wrapper 的 UTF16 定位精确')
      await dialog().locator('[data-action="next"]').click()
      assert.deepEqual(await selection(), { text: '删一😀', from: targets[2].sourceRange.from, to: targets[2].sourceRange.to }, 'next 定位下一未决目标')
      await close(); assert.equal(await body(), before, '定位不改变正文')
      await list()
      assert.ok((await dialog().innerText()).includes('复杂修订和页眉、页脚、脚注等其他故事中的修订均保留'))
      const batch=dialog().locator(`[data-action="${entry.action}-all"]`)
      assert.equal(await batch.isDisabled(),false)
      await batch.click()
      for (const decision of entry.decisions) assert.equal(await row(targets[decision.index].revisionId).locator('[data-action="accept"]').isDisabled(),true)
      assert.equal(await batch.isDisabled(),true)
      await close()
      const changed = await body(); assert.notEqual(changed, before)
      stage = `${entry.name}:undo-redo`; await editor().click(); await page.keyboard.press('Control+z')
      const undone = await body(); assert.notEqual(undone, changed, '一次撤销移除最后一个精确决策')
      assert.equal(undone, before, '整批一次撤销恢复全部来源 wrapper')
      await page.keyboard.press('Control+Shift+z'); assert.equal(await body(), changed, 'Redo 恢复精确投影')
      stage = `${entry.name}:draft`; await page.reload(); await page.locator('.docx-source-home').waitFor({ timeout: 60000 }); assert.equal(await body(), changed, 'local draft 刷新回放')
      await list(); for (const decision of entry.decisions) assert.equal(await row(targets[decision.index].revisionId).locator('[data-action="accept"]').isDisabled(), true); await close()
      await page.screenshot({ path: join(temporary, `${entry.name}-draft.png`), fullPage: true })
      stage = `${entry.name}:save`; await page.locator('[data-action="save"]').click()
      await page.waitForFunction(next => (document.querySelector('.save-state-label')?.textContent ?? '').includes(`已保存修订 ${next}`), entry.revision + 1, { timeout: 60000 }).catch(error => { throw Error(`${error};route=${routeError}`) })
      assert.equal(routeError, undefined)
      const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: '下载 Word', exact: true }).click()])
      const downloaded = await readFile(await download.path()); assert.equal(sha256(downloaded), sha256(revisions.get(entry.revision + 1)))
      const path = join(temporary, `${entry.name}-download.docx`); await writeFile(path, downloaded)
      const verified = JSON.parse(runPython({ mode: 'verify', sourcePath: join(temporary, `revision-${entry.revision}.docx`), path, decisions: entry.decisions }))
      saved = checkpoint.cases[entry.name]; saved.downloadVerified = verified; await persist()
    }
    if (!saved.downloadVerified) {
      // 上轮可能在已登记保存与下载之间退出；复用保存产物，绝不再次发送 save。
      stage = `${entry.name}:resume-download`
      const [download] = await Promise.all([page.waitForEvent('download'), page.goto(`${downloadBase}/revision-${entry.revision + 1}.docx`).catch(error => { if (!String(error).includes('ERR_ABORTED') && !String(error).includes('Download is starting')) throw error })])
      const downloaded = await readFile(await download.path()); assert.equal(sha256(downloaded), saved.sha256)
      const path = join(temporary, `${entry.name}-download.docx`); await writeFile(path, downloaded)
      saved.downloadVerified = JSON.parse(runPython({ mode: 'verify', sourcePath: join(temporary, `revision-${entry.revision}.docx`), path, decisions: entry.decisions })); saved.resumedDownload = true; await persist()
    }
    stage = `${entry.name}:reopen`; await open(entry.revision + 1); await list()
    const reopened = inspections.get(entry.revision + 1).model.blocks.flatMap(block => block.reviewTargets ?? [])
    assert.equal(reopened.length, 4 - entry.decisions.length)
    assert.equal(await dialog().locator('[data-revision-id]').count(), reopened.length, '明确新修订重开只列剩余目标')
    for (const decision of entry.decisions) assert.equal(reopened.some(target => target.revisionId === targets[decision.index].revisionId), false, '旧目标不再签发')
    if (!reopened.length) assert.equal(await dialog().locator('[data-action="next"]').isDisabled(), true)
    await page.screenshot({ path: join(temporary, `${entry.name}-reopened.png`), fullPage: true }); await close()
    assert.ok((await editor().innerText()).includes('COMPLEX-REVISION-KEEP'), '不支持的复杂修订文本保留'); saved.reopened = true; saved.remainingTargets = reopened.length; await persist()
  }
  await Promise.all(checks)
  assert.ok([...chunks.keys()].some(file => /^lazy-docx-main-.*\.js$/.test(file)))
  assert.ok([...chunks.keys()].some(file => /^lazy-native-docx-engine-.*\.js$/.test(file)))
  assert.deepEqual(errors, [])
  const manifestAfter = sha256(await readFile(manifestPath))
  assert.equal(manifestAfter, manifestBefore, '冻结构建 manifest 在 smoke 前后必须一致')
  const result = { ok: true, temporary, staticRoot, manifestBefore, manifestAfter, browserVersion: browser.version(), cases: checkpoint.cases, savesThisRun: savePayloads, loadedChunks: Object.fromEntries(chunks), errors }
  await writeFile(join(temporary, 'result.json'), JSON.stringify(result, null, 2)); console.log(JSON.stringify(result))
} catch (error) {
  if (page) { await writeFile(join(temporary, 'failure.html'), await page.content()).catch(() => {}); await page.screenshot({ path: join(temporary, 'failure.png'), fullPage: true }).catch(() => {}) }
  console.error(JSON.stringify({ stage, temporary, routeError, status: await page?.locator('.save-state-label').textContent().catch(() => null) })); throw error
} finally {
  await browser?.close(); server?.kill(); await new Promise(resolve => downloadServer.close(resolve))
  assert.equal(sha256(await readFile(manifestPath)), manifestBefore, '冻结构建 manifest 在 smoke 结束时必须保持原身份')
}
