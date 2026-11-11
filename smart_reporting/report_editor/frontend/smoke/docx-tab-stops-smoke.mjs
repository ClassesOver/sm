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
const port = Number(process.env.DOCX_TEST_PORT ?? process.env.DOCX_TABS_SMOKE_PORT ?? 4293)
const base = 'http://127.0.0.1:' + port
const temporary = process.env.DOCX_TEST_OUTPUT ? resolve(process.env.DOCX_TEST_OUTPUT) : '/tmp/sr-word-tabs-20261111'
await mkdir(temporary, { recursive: true })
const fixture = spawnSync(join(repo, '.venv/bin/python'), ['-c', [
  'import base64,json', 'from io import BytesIO', 'from docx.shared import Twips', 'from docx import Document', 'from docx.oxml.ns import qn', 'from docx.oxml import OxmlElement', 'from docx.enum.style import WD_STYLE_TYPE',
  'from smart_reporting.reporting.delivery.docx_native import inspect_docx', 'doc=Document()',
  'doc.sections[0].page_width=Twips(12240);doc.sections[0].left_margin=Twips(1440);doc.sections[0].right_margin=Twips(1440)',
  "doc.sections[0].header.paragraphs[0].text='HEADER-UNTOUCHED'",
  "p=doc.add_paragraph();p.add_run('DIRECT-').bold=True;p.add_run('TABS\\tVALUE').italic=True",
  "p.paragraph_format.tab_stops.add_tab_stop(Twips(2160));p.paragraph_format.tab_stops.add_tab_stop(Twips(4320))",
  "tabs=p._p.pPr.find(qn('w:tabs'));tabs[0].set(qn('w:leader'),'dot');tabs[1].set(qn('w:val'),'right');tabs[1].set(qn('w:leader'),'hyphen')",
  "st=doc.styles.add_style('InheritedTabs',WD_STYLE_TYPE.PARAGRAPH);st.paragraph_format.tab_stops.add_tab_stop(Twips(2880))",
  "doc.add_paragraph('INHERITED-TABS\\tVALUE',style='InheritedTabs')",
  "doc.add_paragraph('UNCHANGED-RUNS 漢字 😀 é')",
  "p=doc.add_paragraph('UNKNOWN-TABS');p.paragraph_format.tab_stops.add_tab_stop(Twips(2160));p._p.pPr.find(qn('w:tabs'))[0].set('{urn:tab-smoke}keep','opaque')",
  "p=doc.add_paragraph('RTL-TABS');p._p.get_or_add_pPr().append(OxmlElement('w:bidi'))",
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
  await page.route('**/reports/v1/native/fixture-tabs-*/*/api/context', route => { const bytes = bytesFor(route.request().url()), revision = route.request().url().includes('/2/') ? 2 : 1; return route.fulfill({ json: {
    context: { documentId: new URL(route.request().url()).pathname.split('/')[4], format: 'docx', revision, parentRevision: revision === 2 ? 1 : null,
      scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' }, sourceFile: { path: 'ruler.docx', size: bytes.length, sha256: hash(bytes), mediaType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }, origin: 'report' },
    csrfToken: 'csrf', capabilities: { docx_editor: true }, editingEnabled: !route.request().url().includes('readonly'),
  } }) })
  await page.route('**/reports/v1/native/fixture-tabs-*/*/api/file', route => route.fulfill({ body: bytesFor(route.request().url()), contentType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }))
  await page.route('**/reports/v1/native/fixture-tabs-*/*/api/preview', route => { const model = sourceFor(route.request().url()).model; return route.fulfill({ json: { sourceSha256: model.sourceSha256, draftSha256: model.sourceSha256, model } }) })
  await page.route('**/reports/v1/native/fixture-tabs-editable/1/api/save', route => {
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
      "expected=[[{'pos':'2220','val':'left','leader':'dot'},{'pos':'4500','val':'right','leader':'hyphen'},{'pos':'5760','val':'decimal'}],[{'pos':'2880','val':'clear'}]]",
      "for i in range(2):",
      "  tabs=ps1[i].find(w+'pPr/'+w+'tabs');actual=[{E.QName(k).localname:v for k,v in t.attrib.items()} for t in tabs];assert actual==expected[i],actual",
      "  for old,new in zip(ps0[i].findall('.//'+w+'t'),ps1[i].findall('.//'+w+'t')):",
      "    space='{http://www.w3.org/XML/1998/namespace}space'",
      "    if old.get(space)!=new.get(space): assert old.get(space) is None and new.get(space)=='preserve';old.set(space,'preserve')",
      "  for parent in (ps0[i],ps1[i]):",
      "    pr=parent.find(w+'pPr')",
      "    if pr is not None:",
      "      tabs=pr.find(w+'tabs')",
      "      if tabs is not None: pr.remove(tabs)",
      "      if not len(pr) and not pr.attrib: parent.remove(pr)",
      "assert E.tostring(root0,method='c14n')==E.tostring(root1,method='c14n'),'制表位以外正文/未知XML变化'",
      'print(json.dumps({"base64":base64.b64encode(data).decode(),"model":inspect_docx(data),"independentZipXml":True,"unchangedParts":unchanged}))',
    ].join('\n')], { cwd: repo, env: { ...process.env, PYTHONPATH: repo, AGENT_REPORTING_DOC_ENGINE_DIR: runtime }, input: JSON.stringify({ base64: sources.uniform.base64, operations: payload.operations }), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024, timeout: 120000 })
    assert.equal(result.status, 0, result.stderr); saved = JSON.parse(result.stdout)
    assert.equal(payload.operations.length,2)
    const expected=[
      [{pos:2220,val:'left',leader:'dot'},{pos:4500,val:'right',leader:'hyphen'},{pos:5760,val:'decimal'}],
      [{pos:2880,val:'clear'}],
    ]
    for(const [index,op] of payload.operations.entries()) {
      const anchor=sources.uniform.model.blocks[index]
      assert.equal(op.kind,'setParagraphTabStops');assert.equal(op.blockId,anchor.blockId)
      assert.equal(op.expectedObjectSha256,anchor.expectedObjectSha256);assert.deepEqual(op.stops,expected[index])
    }
    return route.fulfill({ json: { documentId: 'fixture-tabs-editable', revision: 2, parentRevision: 1, revisionRegistered: true,
      artifacts: { word: { downloadUrl: '/fixture-tabs-revision-2.docx', size: Buffer.from(saved.base64, 'base64').length, sha256: saved.model.sourceSha256 } },
      editor: { openUrl: '/reports/v1/native/fixture-tabs-editable/2' }, validation: { ok: false, issues: [{ code: 'fixture_review', message: '制表位验收待复核，保留 Word 下载' }] } } })
  })
  await page.route('**/fixture-tabs-revision-2.docx', route => route.fulfill({ body: Buffer.from(saved.base64, 'base64'), contentType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', headers: { 'Content-Disposition': 'attachment; filename="ruler-revision-2.docx"' } }))
  await page.route(/\/reports\/v1\/native\/fixture-tabs-[a-z]+\/[12]$/, async route => route.fulfill({ response: await route.fetch({ url: base + '/reports/v1/editor/assets/native.html' }) }))
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
  const select = async text => { await body().locator('p').filter({hasText:text}).click() }
  const tabValues = () => page.locator('.ruler-tab').evaluateAll(nodes => nodes.map(node=>({pos:Number(node.getAttribute('aria-valuenow')),kind:[...node.classList].find(c=>c.startsWith('ruler-tab-'))?.slice(10)})).sort((a,b)=>a.pos-b.pos))
  const expectTabs = async values => {
    await page.waitForFunction(values=>JSON.stringify([...document.querySelectorAll('.ruler-tab')].map(node=>({pos:Number(node.getAttribute('aria-valuenow')),kind:[...node.classList].find(c=>c.startsWith('ruler-tab-'))?.slice(10)})).sort((a,b)=>a.pos-b.pos))===JSON.stringify(values),values)
    assert.deepEqual(await tabValues(),values)
  }
  const direct=[{pos:2160,kind:'left'},{pos:4320,kind:'right'}]
  const edited=[{pos:2220,kind:'left'},{pos:4500,kind:'right'},{pos:5760,kind:'decimal'}]
  const drags=[]
  const drag = async (selector,target) => {
    const marker=await page.locator(selector).boundingBox(),ruler=await page.locator('.ruler').boundingBox()
    assert.ok(marker && ruler)
    await page.mouse.move(marker.x+marker.width/2,marker.y+marker.height/2);await page.mouse.down()
    const before=await snapshot()
    await page.mouse.move(ruler.x+target/15,marker.y+marker.height/2,{steps:4})
    assert.deepEqual(await snapshot(),before,'移动期间不写入')
    await page.mouse.up();drags.push({selector,target,writeOnlyOnRelease:true})
  }
  const show = async () => {
    await page.locator('[data-tab-id="view"]').click()
    const toggle = page.locator('[data-action="ruler-toggle"]')
    if (await toggle.getAttribute('aria-pressed') !== 'true') await toggle.click()
    await page.locator('.ruler').waitFor()
  }
  const results=[]
  for(const mode of process.env.DOCX_TABS_CASE?[process.env.DOCX_TABS_CASE]:['readonly','editable']) {
    stage=mode
    await page.goto(base+'/reports/v1/native/fixture-tabs-'+mode+'/1')
    await page.locator('.docx-source-home').waitFor({timeout:60000});await select('DIRECT-')
    const before=await snapshot();await show();assert.deepEqual(await snapshot(),before)
    await expectTabs(direct);await assertAligned()
    if(mode==='zoom') {
      await page.waitForFunction(()=>document.querySelector('.ruler-tab-type')?.getAttribute('aria-disabled')==='false')
      await page.locator('[data-action="view-放大"]').click()
      await page.waitForFunction(()=>document.querySelector('.ruler-tab-type')?.getAttribute('aria-disabled')==='true')
      assert.ok((await page.locator('.ruler-tab-type').getAttribute('title')).includes('100%'))
      const locked=await snapshot()
      await page.locator('.ruler-tab-left').dispatchEvent('keydown',{key:'Delete'})
      await drag('.ruler-tab-left',3000);await expectTabs(direct)
      assert.deepEqual(await snapshot(),locked,'110%不能改制表位')
      await page.screenshot({path:join(temporary,'zoom-locked-tabs.png'),fullPage:true})
      await page.locator('[data-action="view-100%"]').click()
      await page.waitForFunction(()=>document.querySelector('.ruler-tab-type')?.getAttribute('aria-disabled')==='false')
      await expectTabs(direct);await assertAligned()
    } else if(mode==='readonly') {
      assert.equal(await page.locator('.ruler-tab-type').getAttribute('aria-disabled'),'true')
      await page.locator('.ruler-tab-left').dispatchEvent('keydown',{key:'Delete'})
      await drag('.ruler-tab-left',3000);await expectTabs(direct)
      const ruler=await page.locator('.ruler').boundingBox();await page.mouse.click(ruler.x+384,ruler.y+15)
      assert.deepEqual(await snapshot(),before,'只读增删拖动均无写入')
    } else {
      await page.waitForFunction(()=>document.querySelector('.ruler-tab-type')?.getAttribute('aria-disabled')==='false')
      const cycle=[]
      for(let i=0;i<5;i++) {cycle.push(await page.locator('.ruler-tab-type').textContent());await page.locator('.ruler-tab-type').click()}
      assert.deepEqual(cycle,['L','⊥','⌐','.','|']);assert.deepEqual(await snapshot(),before,'切换类型不改草稿')
      await page.locator('.ruler-tab-left').press('ArrowRight');await expectTabs([{pos:2220,kind:'left'},{pos:4320,kind:'right'}])
      await body().focus();await page.keyboard.press('Control+z');await expectTabs(direct)
      await body().focus();await page.keyboard.press('Control+Shift+z');await expectTabs([{pos:2220,kind:'left'},{pos:4320,kind:'right'}])
      await drag('.ruler-tab-right',4500);await expectTabs([{pos:2220,kind:'left'},{pos:4500,kind:'right'}])
      for(let i=0;i<3;i++) await page.locator('.ruler-tab-type').click()
      assert.equal(await page.locator('.ruler-tab-type').textContent(),'.')
      const ruler=await page.locator('.ruler').boundingBox();await page.mouse.click(ruler.x+384,ruler.y+15)
      await expectTabs(edited)
      await select('INHERITED-TABS');await expectTabs([{pos:2880,kind:'left'}])
      await drag('.ruler-tab-left',0);await expectTabs([])
      for(const text of ['UNKNOWN-TABS','RTL-TABS']) {
        await select(text)
        await page.waitForFunction(()=>document.querySelector('.ruler-tab-type')?.getAttribute('aria-disabled')==='true')
        const locked=await snapshot();await page.locator('.ruler-tab-type').dispatchEvent('click')
        const r=await page.locator('.ruler').boundingBox();await page.mouse.click(r.x+384,r.y+15)
        assert.deepEqual(await snapshot(),locked,text+'来源只读')
      }
      await page.reload();await page.locator('.docx-source-home').waitFor({timeout:60000});await select('DIRECT-');await show();await expectTabs(edited)
      await select('INHERITED-TABS');await expectTabs([])
      await page.screenshot({path:join(temporary,'restored-tabs.png'),fullPage:true})
      await page.locator('[data-action="save"]').click()
      await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2')
      await page.getByText('制表位验收待复核，保留 Word 下载',{exact:true}).waitFor()
      const event=page.waitForEvent('download');await page.getByRole('link',{name:'下载 Word',exact:true}).click()
      const download=await event,path=join(temporary,'tab-stops-revision-2.docx');await download.saveAs(path)
      assert.equal(hash(await readFile(path)),saved.model.sourceSha256)
      await page.goto(base+'/reports/v1/native/fixture-tabs-editable/2');await page.locator('.docx-source-home').waitFor({timeout:60000})
      await select('DIRECT-');await show();await expectTabs(edited)
      await select('INHERITED-TABS');await expectTabs([])
      await assertAligned();await page.screenshot({path:join(temporary,'reopened-tabs.png'),fullPage:true})
    }
    await page.screenshot({path:join(temporary,mode+'-tabs.png'),fullPage:true})
    results.push({mode,tabEditing:mode==='editable',readonlyWritesBlocked:mode==='readonly',zoomWritesBlocked:mode==='zoom',...(mode==='editable'?{undoRedo:true,draftRestored:true,independentZipXml:saved.independentZipXml,downloadedAndReopened:true}: {})})
    await writeFile(join(temporary,mode+'-result.json'),JSON.stringify(results.at(-1),null,2))
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
