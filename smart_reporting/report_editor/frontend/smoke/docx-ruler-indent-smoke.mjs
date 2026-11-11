// 只启动 preview；冻结源码并统一构建后执行。
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
assert.match(process.env.DOCX_EXPECTED_MANIFEST_SHA256 ?? '', /^[a-f0-9]{64}$/, '必须提供 DOCX_EXPECTED_MANIFEST_SHA256 冻结构建身份')
const staticRoot = resolve(process.env.DOCX_TEST_DIST ?? join(frontend, '../static'))
const runtime = resolve(process.env.DOCX_TEST_ENGINE ?? join(repo, 'smart_reporting/reporting/doc_engine'))
const manifestPath = join(staticRoot, '.vite/manifest.json'), bridgePath = join(runtime, 'dist/edit-docx.mjs')
const hash = bytes => createHash('sha256').update(bytes).digest('hex')
const manifest = await readFile(manifestPath), bridgeSha256 = hash(await readFile(bridgePath))
assert.equal(hash(manifest), process.env.DOCX_EXPECTED_MANIFEST_SHA256, '冻结 manifest 身份不一致')
const port = Number(process.env.DOCX_TEST_PORT ?? process.env.DOCX_RULER_INDENT_SMOKE_PORT ?? 4288)
const base = 'http://127.0.0.1:' + port
const temporary = process.env.DOCX_TEST_OUTPUT ? resolve(process.env.DOCX_TEST_OUTPUT) : '/tmp/sr-word-ruler-indent-20261111'
await mkdir(temporary, { recursive: true })
const fixture = spawnSync(join(repo, '.venv/bin/python'), ['-c', [
  'import base64,json', 'from io import BytesIO', 'from docx.shared import Twips', 'from docx import Document', 'from docx.oxml.ns import qn', 'from docx.oxml import OxmlElement', 'from docx.enum.style import WD_STYLE_TYPE',
  'from smart_reporting.reporting.delivery.docx_native import inspect_docx', 'doc=Document()',
  'doc.sections[0].page_width=Twips(12240);doc.sections[0].left_margin=Twips(1440);doc.sections[0].right_margin=Twips(1440)',
  "doc.sections[0].header.paragraphs[0].text='HEADER-UNTOUCHED'",
  "p=doc.add_paragraph();p.add_run('DIRECT-').bold=True;p.add_run('INDENT').italic=True;p.paragraph_format.left_indent=Twips(720);p.paragraph_format.first_line_indent=Twips(360)",
  "p._p.get_or_add_pPr().find(qn('w:ind')).set('{urn:ruler-smoke}keep','opaque')",
  "st=doc.styles.add_style('InheritedIndent',WD_STYLE_TYPE.PARAGRAPH);st.paragraph_format.left_indent=Twips(540);st.paragraph_format.first_line_indent=Twips(-180)",
  "doc.add_paragraph('INHERITED-HANGING',style='InheritedIndent')",
  "p=doc.add_paragraph('UNCHANGED-RUNS');p.add_run(' 漢字 😀 é').bold=True",
  "p=doc.add_paragraph('CHARACTER-INDENT');ind=OxmlElement('w:ind');ind.set(qn('w:leftChars'),'200');p._p.get_or_add_pPr().append(ind)",
  "p=doc.add_paragraph('RTL-INDENT');p._p.get_or_add_pPr().append(OxmlElement('w:bidi'))",
  "table=doc.add_table(rows=1,cols=1);table.cell(0,0).text='TABLE-PRESERVED'",
  'buf=BytesIO();doc.save(buf);data=buf.getvalue()',
  "print(json.dumps({'uniform':{'base64':base64.b64encode(data).decode(),'model':inspect_docx(data)}}))",
].join('\n')], { cwd: repo, env: { ...process.env, PYTHONPATH: repo, AGENT_REPORTING_DOC_ENGINE_DIR: runtime }, encoding: 'utf8', maxBuffer: 10 * 1024 * 1024, timeout: 120000 })
assert.equal(fixture.status, 0, fixture.stderr)
const sources = JSON.parse(fixture.stdout)
let saved
for (const [name, value] of Object.entries(sources)) await writeFile(join(temporary, 'source-' + name + '.docx'), Buffer.from(value.base64, 'base64'))
const sourceFor = url => url.includes('/2') ? saved : sources.uniform
const bytesFor = url => Buffer.from(sourceFor(url).base64, 'base64')
let server, browser, page, stage = 'start'
const errors = [], chunkChecks = [], chunks = new Map(), savePayloads = []
try {
  server = spawn('./node_modules/.bin/vite', ['preview', '--outDir', staticRoot, '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'pipe' })
  let log = ''; server.stderr.on('data', chunk => { log += chunk })
  for (let attempt = 0; ; attempt++) {
    assert.equal(server.exitCode, null, log)
    try { if ((await fetch(base + '/reports/v1/editor/assets/native.html')).ok) break } catch {}
    if (attempt === 120) throw new Error('preview timeout: ' + log)
    await delay(250)
  }
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    const prefix = '/reports/v1/editor/assets/'
    if (!path.startsWith(prefix) || !path.endsWith('.js')) return
    chunkChecks.push((async () => {
      assert.equal(response.status(), 200)
      const file = path.slice(prefix.length), actual = await response.body()
      const diskPath = resolve(staticRoot, file)
      assert.ok(diskPath.startsWith(staticRoot + '/'), 'JS 必须位于冻结目录')
      assert.equal(hash(actual), hash(await readFile(diskPath)), '浏览器 JS 身份 ' + file)
      chunks.set(file, hash(actual))
    })())
  })
  await page.route('**/reports/v1/native/fixture-ruler-*/*/api/context', route => { const bytes = bytesFor(route.request().url()), revision = route.request().url().includes('/2/') ? 2 : 1; return route.fulfill({ json: {
    context: { documentId: new URL(route.request().url()).pathname.split('/')[4], format: 'docx', revision, parentRevision: revision === 2 ? 1 : null,
      scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' }, sourceFile: { path: 'ruler.docx', size: bytes.length, sha256: hash(bytes), mediaType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }, origin: 'report' },
    csrfToken: 'csrf', capabilities: { docx_editor: true }, editingEnabled: !route.request().url().includes('readonly'),
  } }) })
  await page.route('**/reports/v1/native/fixture-ruler-*/*/api/file', route => route.fulfill({ body: bytesFor(route.request().url()), contentType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }))
  await page.route('**/reports/v1/native/fixture-ruler-*/*/api/preview', route => { const model = sourceFor(route.request().url()).model; return route.fulfill({ json: { sourceSha256: model.sourceSha256, draftSha256: model.sourceSha256, model } }) })
  await page.route('**/reports/v1/native/fixture-ruler-editable/1/api/save', route => {
    const payload = route.request().postDataJSON(); savePayloads.push(payload)
    const result = spawnSync(join(repo, '.venv/bin/python'), ['-c', [
      'import base64,json,sys', 'from io import BytesIO', 'from zipfile import ZipFile', 'from lxml import etree as E',
      'from smart_reporting.reporting.delivery.docx_native import patch_docx,inspect_docx',
      'p=json.load(sys.stdin);original=base64.b64decode(p["base64"]);data=patch_docx(original,p["operations"])',
      'before=ZipFile(BytesIO(original));after=ZipFile(BytesIO(data));names=lambda z:{n for n in z.namelist() if not n.endswith("/")};assert names(before)==names(after)',
      'unchanged=[n for n in names(before) if n not in ("word/document.xml","docProps/core.xml")];assert all(before.read(n)==after.read(n) for n in unchanged)',
      'core0=E.fromstring(before.read("docProps/core.xml"));core1=E.fromstring(after.read("docProps/core.xml"))',
      'for root in (core0,core1):',
      '  for child in list(root):',
      '    if E.QName(child).localname in ("modified","revision"): root.remove(child)',
      'assert E.tostring(core0,method="c14n")==E.tostring(core1,method="c14n"),"非预期core属性变化"',
      'ns={"w":"http://schemas.openxmlformats.org/wordprocessingml/2006/main"};w="{"+ns["w"]+"}"',
      'root0=E.fromstring(before.read("word/document.xml"));root1=E.fromstring(after.read("word/document.xml"))',
      'ps0=root0.find(w+"body").findall(w+"p");ps1=root1.find(w+"body").findall(w+"p")',
      'a=ps1[0].find(w+"pPr/"+w+"ind");b=ps1[1].find(w+"pPr/"+w+"ind")',
      'assert a.get(w+"left")=="810" and a.get(w+"firstLine")=="450",E.tostring(a)',
      'assert a.get("{urn:ruler-smoke}keep")=="opaque"',
      'assert b.get(w+"left")=="630" and b.get(w+"hanging")=="270" and b.get(w+"firstLine") is None,E.tostring(b)',
      'for old,new in zip(ps0[:2],ps1[:2]):',
      '  ts0=old.findall(".//"+w+"t");ts1=new.findall(".//"+w+"t");assert len(ts0)==len(ts1)',
      '  for t0,t1 in zip(ts0,ts1):',
      '    space="{http://www.w3.org/XML/1998/namespace}space"',
      '    if t0.get(space)!=t1.get(space):',
      '      assert t0.get(space) is None and t1.get(space)=="preserve","只允许既有writer添加xml:space=preserve";t0.set(space,"preserve")',
      '  for tag in ("r",): assert [E.tostring(x) for x in old.findall(w+tag)]==[E.tostring(x) for x in new.findall(w+tag)]',
      '  for parent in (old,new):',
      '    pr=parent.find(w+"pPr");ind=pr.find(w+"ind")',
      '    if ind is not None: pr.remove(ind)',
      'assert E.tostring(root0,method="c14n")==E.tostring(root1,method="c14n"),"缩进以外的正文/未知XML变化"',
      'print(json.dumps({"base64":base64.b64encode(data).decode(),"model":inspect_docx(data),"independentZipXml":True,"unchangedParts":unchanged}))',
    ].join('\n')], { cwd: repo, env: { ...process.env, PYTHONPATH: repo, AGENT_REPORTING_DOC_ENGINE_DIR: runtime }, input: JSON.stringify({ base64: sources.uniform.base64, operations: payload.operations }), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024, timeout: 120000 })
    assert.equal(result.status, 0, result.stderr); saved = JSON.parse(result.stdout)
    assert.equal(payload.operations.length, 2)
    for (const op of payload.operations) {
      assert.equal(op.kind, 'setParagraphRulerIndent'); assert.match(op.expectedObjectSha256, /^[a-f0-9]{64}$/)
      assert.equal(typeof op.blockId, 'string')
    }
    for (const [index, text] of ['DIRECT-INDENT', 'INHERITED-HANGING'].entries()) {
      const anchor = sources.uniform.model.blocks.find(block => block.text === text)
      assert.ok(anchor, text + ' 来源锚点')
      assert.equal(payload.operations[index].blockId, anchor.blockId)
      assert.equal(payload.operations[index].expectedObjectSha256, anchor.expectedObjectSha256)
    }
    assert.deepEqual(payload.operations.map(({leftTwips,firstLineTwips}) => ({leftTwips,firstLineTwips})), [
      {leftTwips:810,firstLineTwips:450}, {leftTwips:630,firstLineTwips:-270},
    ])
    return route.fulfill({ json: { documentId: 'fixture-ruler-editable', revision: 2, parentRevision: 1, revisionRegistered: true,
      artifacts: { word: { downloadUrl: '/fixture-ruler-revision-2.docx', size: Buffer.from(saved.base64, 'base64').length, sha256: saved.model.sourceSha256 } },
      editor: { openUrl: '/reports/v1/native/fixture-ruler-editable/2' }, validation: { ok: false, issues: [{ code: 'fixture_review', message: '尺规验收待复核，保留 Word 下载' }] } } })
  })
  await page.route('**/fixture-ruler-revision-2.docx', route => route.fulfill({ body: Buffer.from(saved.base64, 'base64'), contentType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', headers: { 'Content-Disposition': 'attachment; filename="ruler-revision-2.docx"' } }))
  await page.route(/\/reports\/v1\/native\/fixture-ruler-[a-z]+\/[12]$/, async route => route.fulfill({ response: await route.fetch({ url: base + '/reports/v1/editor/assets/native.html' }) }))
  const body = () => page.getByRole('textbox', { name: 'Word 文档编辑区' })
  const snapshot = () => page.evaluate(() => ({
    draft: Object.fromEntries(Object.entries(localStorage)),
    text: document.querySelector('[aria-label="Word 文档编辑区"]')?.textContent,
    columnCount: getComputedStyle(document.querySelector('[aria-label="Word 文档编辑区"]')).columnCount,
    style: document.querySelector('[aria-label="Word 文档编辑区"]')?.getAttribute('style'),
    status: document.querySelector('.save-state-label')?.textContent,
    // PM 移除 decoration 后可能留下 style=""；比较 CSS 声明，避免把它与无 style 属性误判为布局变化。
    layout: [...document.querySelector('[aria-label="Word 文档编辑区"]').children].map(node => ({ idx: node.getAttribute('data-idx'), style: node.style.cssText, text: node.textContent })),
  }))
  const geometry = () => page.evaluate(() => {
    const ruler = document.querySelector('.ruler').getBoundingClientRect(), paper = document.querySelector('[aria-label="Word 文档编辑区"]').getBoundingClientRect()
    return { ruler: { left: ruler.left, width: ruler.width }, paper: { left: paper.left, width: paper.width } }
  })
  const assertAligned = async () => { const g = await geometry(); assert.ok(Math.abs(g.ruler.left - g.paper.left) < 2, JSON.stringify(g)); assert.ok(Math.abs(g.ruler.width - g.paper.width) < 2, JSON.stringify(g)); return g }
  const select = async text => { await body().locator('p').filter({ hasText: new RegExp('^' + text + '$') }).click() }
  const markers = async () => Object.fromEntries(await Promise.all(['left', 'firstLine', 'hanging'].map(async name => [name, Number(await page.locator('.ruler-ind-' + name).getAttribute('aria-valuenow'))])))
  const expectMarkers = async expected => {
    await page.waitForFunction(values => Object.entries(values).every(([name, value]) => Number(document.querySelector('.ruler-ind-' + name)?.getAttribute('aria-valuenow')) === value), expected)
    assert.deepEqual(await markers(), expected)
  }
  const drags = []
  const dragMarker = async (name, writeOnRelease = true) => {
    const marker = await page.locator('.ruler-ind-' + name).boundingBox(), ruler = await geometry()
    assert.ok(marker, name + '拖动目标可见')
    const x = marker.x + marker.width / 2, y = marker.y + marker.height / 2
    await page.mouse.move(x, y); await page.mouse.down()
    const before = await snapshot()
    await page.mouse.move(x + 90 / 12240 * ruler.ruler.width, y, {steps:4})
    assert.deepEqual(await snapshot(), before, '鼠标移动只显示引导线，松开前不写草稿')
    await page.mouse.up()
    drags.push({name,deltaTwips:90,writeOnRelease})
  }
  const show = async () => {
    await page.locator('[data-tab-id="view"]').click()
    const toggle = page.locator('[data-action="ruler-toggle"]')
    if (await toggle.getAttribute('aria-pressed') !== 'true') await toggle.click()
    await page.locator('.ruler').waitFor()
  }
  const results = []
  for (const mode of process.env.DOCX_RULER_CASE ? [process.env.DOCX_RULER_CASE] : ['readonly', 'editable']) {
    stage = mode
    await page.goto(base + '/reports/v1/native/fixture-ruler-' + mode + '/1')
    await page.locator('.docx-source-home').waitFor({ timeout: 60000 }); await select('DIRECT-INDENT')
    const before = await snapshot(); await show()
    assert.deepEqual(await snapshot(), before, '显示尺规不改正文、草稿与保存状态')
    await expectMarkers({left:2160,firstLine:2520,hanging:2160})
    const initial = await assertAligned()
    assert.equal(await page.locator('.ruler-tab-type').getAttribute('aria-disabled'), 'true')
    if (mode === 'readonly') {
      for (const name of ['left','firstLine','hanging','right']) {
        const marker = page.locator('.ruler-ind-' + name)
        assert.equal(await marker.getAttribute('aria-disabled'), 'true'); assert.ok(await marker.getAttribute('title'))
        await marker.dispatchEvent('keydown', {key:'ArrowRight'})
      }
      for (const name of ['left','firstLine','hanging']) await dragMarker(name, false)
      await expectMarkers({left:2160,firstLine:2520,hanging:2160})
      assert.deepEqual(await snapshot(), before, '只读键盘不能写回')
    } else {
      for (const name of ['left','firstLine','hanging']) assert.equal(await page.locator('.ruler-ind-' + name).getAttribute('aria-disabled'), 'false')
      // 源 left 方块移动所有行；firstLine 三角只移动首行。
      await page.locator('.ruler-ind-left').press('ArrowRight')
      await expectMarkers({left:2250,firstLine:2610,hanging:2250})
      await body().focus(); await page.keyboard.press('Control+z')
      await expectMarkers({left:2160,firstLine:2520,hanging:2160})
      await body().focus(); await page.keyboard.press('Control+Shift+z')
      await expectMarkers({left:2250,firstLine:2610,hanging:2250})
      await dragMarker('firstLine')
      await expectMarkers({left:2250,firstLine:2700,hanging:2250})
      await select('INHERITED-HANGING'); await expectMarkers({left:1980,firstLine:1800,hanging:1980})
      // hanging 只移动后续行，保持首行绝对位置，signed firstLine 随之减少。
      await dragMarker('hanging')
      await expectMarkers({left:2070,firstLine:1800,hanging:2070})
      for (const text of ['CHARACTER-INDENT','RTL-INDENT']) {
        await select(text); const locked = await snapshot()
        await page.waitForFunction(() => ['left','firstLine','hanging'].every(name => document.querySelector('.ruler-ind-' + name)?.getAttribute('aria-disabled') === 'true'))
        for (const name of ['left','firstLine','hanging']) {
          const marker = page.locator('.ruler-ind-' + name)
          assert.equal(await marker.getAttribute('aria-disabled'), 'true', text + ':' + name)
          assert.ok(await marker.getAttribute('title')); await marker.dispatchEvent('keydown', {key:'ArrowRight'})
        }
        assert.deepEqual(await snapshot(), locked, text + '拒绝不可还原缩进')
      }
      const persisted = await page.evaluate(() => Object.fromEntries(Object.entries(localStorage)))
      assert.ok(Object.values(persisted).some(raw => raw.includes('setParagraphRulerIndent')), '真实草稿持久化')
      await page.reload(); await page.locator('.docx-source-home').waitFor({timeout:60000})
      await select('DIRECT-INDENT'); await show(); await expectMarkers({left:2250,firstLine:2700,hanging:2250})
      await select('INHERITED-HANGING'); await expectMarkers({left:2070,firstLine:1800,hanging:2070})
      await page.screenshot({path:join(temporary,'editable-restored-ruler.png'),fullPage:true})
      await page.locator('[data-action="save"]').click()
      await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent === '已保存修订 2')
      await page.getByText('尺规验收待复核，保留 Word 下载', {exact:true}).waitFor()
      const event = page.waitForEvent('download'); await page.getByRole('link', {name:'下载 Word',exact:true}).click()
      const download = await event, path = join(temporary,'ruler-indent-revision-2.docx'); await download.saveAs(path)
      assert.equal(hash(await readFile(path)),saved.model.sourceSha256)
      await page.goto(base + '/reports/v1/native/fixture-ruler-editable/2')
      await page.locator('.docx-source-home').waitFor({timeout:60000}); await select('DIRECT-INDENT'); await show()
      await expectMarkers({left:2250,firstLine:2700,hanging:2250})
      await select('INHERITED-HANGING'); await expectMarkers({left:2070,firstLine:1800,hanging:2070})
      await assertAligned(); await page.screenshot({path:join(temporary,'reopened-ruler.png'),fullPage:true})
    }
    await page.screenshot({path:join(temporary,mode+'-ruler.png'),fullPage:true})
    results.push({mode,initial,sourceMarkers:true,...(mode==='editable'?{draftRestored:true,undoRedo:true,independentZipXml:saved.independentZipXml,unchangedParts:saved.unchangedParts,downloadedAndReopened:true}:{readonlyWritesBlocked:true})})
  }
  assert.equal(hash(await readFile(join(temporary,'source-uniform.docx'))),sources.uniform.model.sourceSha256,'原始 DOCX 文件不可覆盖')
  await Promise.all(chunkChecks)
  assert.ok([...chunks.keys()].some(file => file.startsWith('assets/lazy-docx-main-') && file.endsWith('.js')))
  assert.equal(hash(await readFile(manifestPath)), hash(manifest), 'smoke 期间构建身份不变')
  const bridgeAfterSha256 = hash(await readFile(bridgePath))
  assert.equal(bridgeAfterSha256, bridgeSha256, 'smoke 期间 engine 身份不变')
  assert.deepEqual(errors, [])
  const result = { ok: true, temporary, staticRoot, runtime, mouseDrags: drags, sourceSha256: Object.fromEntries(Object.entries(sources).map(([key, value]) => [key, value.model.sourceSha256])), manifestSha256: hash(manifest), bridgeSha256, bridgeAfterSha256, loadedChunks: Object.fromEntries(chunks), results, saveExportRequests: savePayloads, errors }
  await writeFile(join(temporary, 'result.json'), JSON.stringify(result, null, 2)); console.log(JSON.stringify(result))
} catch (error) {
  if (page) { await writeFile(join(temporary, 'failure.html'), await page.content()); await page.screenshot({ path: join(temporary, 'failure.png'), fullPage: true }) }
  console.error(JSON.stringify({ stage, temporary })); throw error
} finally { await browser?.close(); server?.kill() }
