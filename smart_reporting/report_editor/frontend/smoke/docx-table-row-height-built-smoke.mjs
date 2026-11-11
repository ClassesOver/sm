// 独立 built GUI 探针：真实 DOCX -> Chromium DOM 输入 -> 草稿刷新 -> 公开保存 -> Python patch -> 下载回读。
// 只启动 vite preview，不构建；调用前须由集成人员完成当前源码构建。
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url))
const repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.DOCX_ROW_HEIGHT_SMOKE_PORT ?? 4242)
const baseUrl = `http://127.0.0.1:${port}`
const documentId = 'fixture-row-height-built'
const mediaType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex')
const temporary = await mkdtemp(join(tmpdir(), 'docx-row-height-built-'))
const sourcePath = join(temporary, 'revision-1.docx')
const runPython = input => {
  const result = spawnSync(join(repo, '.venv/bin/python'), ['-c', String.raw`
import base64, json, re, sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
from hashlib import sha256
from lxml import etree
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
p=json.load(sys.stdin)
if p['mode']=='fixture':
    from docx import Document
    doc=Document(); buf=BytesIO();doc.save(buf)
    def para(t,empty=False):
        return '<w:p w:rsidR="00ABCDEF"><w:pPr><w:keepNext/></w:pPr>'+('' if empty else '<w:r><w:rPr><w:b/><w:color w:val="FF0000"/></w:rPr><w:t>'+t+'</w:t></w:r><w:r><w:rPr><w:i/></w:rPr><w:t>混合😀</w:t></w:r>')+'</w:p>'
    widths=[1801,2401,3001]
    def cell(t,c,pr='',body=None,span=1):
        return '<w:tc><w:tcPr>\n <w:tcW w:w="'+str(sum(widths[c:c+span]))+'" w:type="dxa"/>'+pr+'<w:shd w:val="pct20" w:color="AABBCC" w:fill="112233" w:themeFill="accent2" w:themeFillTint="99"/></w:tcPr>\n'+(body if body is not None else para(t)+para(t+'第二段')+para('',True))+'</w:tc>'
    if p.get('merged'):
        rows='<w:tr><w:trPr><w:trHeight w:val="300" w:hRule="exact"/><w:cantSplit/></w:trPr>'+cell('MERGED中文',0,'<w:gridSpan w:val="2"/><w:vMerge w:val="restart"/>',span=2)+cell('C1中文',2)+'</w:tr><w:tr><w:trPr><w:trHeight w:val="400"/><w:cantSplit/></w:trPr>'+cell('隐藏continue中文',0,'<w:gridSpan w:val="2"/><w:vMerge/>',body=para('隐藏continue中文'),span=2)+cell('C2中文',2)+'</w:tr>'
    else: rows=''.join('<w:tr><w:trPr><w:trHeight w:val="'+str(300+r*100)+'"'+(' w:hRule="exact"' if r==0 else '')+'/><w:cantSplit/></w:trPr>'+''.join(cell(chr(65+c)+str(r+1)+'中文',c) for c in range(3))+'</w:tr>' for r in range(2))
    table='<w:tbl><w:tblPr><w:tblW w:w="7203" w:type="dxa"/><w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>'+''.join('<w:gridCol w:w="'+str(w)+'"/>' for w in widths)+'</w:tblGrid>'+rows+'</w:tbl>'
    with ZipFile(BytesIO(buf.getvalue())) as zin, ZipFile(p['outputPath'],'w') as zout:
        for name in zin.namelist():
            data=zin.read(name)
            if name=='word/document.xml':
                xml=data.decode();xml=re.sub(r'(<w:body>)[\s\S]*?(<w:sectPr\b)',lambda m:m[1]+para('外部前')+table+para('外部后')+m[2],xml,count=1);xml=re.sub(r'<w:pgSz[^>]*/>','<w:pgSz w:w="12000" w:h="16800"/>',xml);xml=re.sub(r'<w:pgMar[^>]*/>','<w:pgMar w:top="1000" w:right="1500" w:bottom="1000" w:left="1500" w:header="500" w:footer="500" w:gutter="0"/>',xml);xml=re.sub(r'<w:cols\b[^>]*/>','<w:cols w:num="2"/>',xml) if p.get('multicol') else xml;data=xml.encode()
            zout.writestr(name,data)
    print('ok')
elif p['mode']=='patch':
    data=patch_docx(Path(p['sourcePath']).read_bytes(),p['operations'])
    Path(p['outputPath']).write_bytes(data)
    print(base64.b64encode(data).decode())
else:
    data=Path(p['path']).read_bytes()
    with ZipFile(BytesIO(data)) as package:
        xml=package.read('word/document.xml').decode()
        a=xml.index('<w:tbl>'); b=xml.index('</w:tbl>',a)+len('</w:tbl>');table=xml[a:b]
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        root=etree.fromstring(xml.encode()).find('w:body/w:tbl',ns)
        model=inspect_docx(data);anchor=next(x for x in model['blocks'] if x['type']=='table')
        heights=[];rules=[]
        for row in root.findall('w:tr',ns):
            h=row.find('w:trPr/w:trHeight',ns)
            heights.append(int(h.get('{'+ns['w']+'}val')) if h is not None else None)
            rules.append(h.get('{'+ns['w']+'}hRule','atLeast') if h is not None else None)
        details={'heights':heights,'rules':rules,'maxHeight':anchor.get('rowHeightMaxTwips'),'cells':anchor.get('rowHeightCells'),
          'maskedXml':re.sub(r'<w:trHeight\b[^>]*/>','',xml),
          'parts':{name:sha256(package.read(name)).hexdigest() for name in package.namelist() if name!='word/document.xml' and not name.endswith('/')}}
    print(json.dumps({'model':model,'details':details},ensure_ascii=False))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr || `python exited ${result.status}`)
  return result.stdout.trim()
}
let server, browser, page, stage = 'setup'
const downloadServer=createServer((request,response)=>{const match=/^\/revision-(\d+)\.docx$/.exec(request.url??'');const bytes=match&&downloadRevisions.get(Number(match[1]));if(!bytes){response.writeHead(404);response.end();return}response.writeHead(200,{'Content-Type':mediaType,'Content-Disposition':'attachment; filename=row-height.docx','Content-Length':bytes.length});response.end(bytes)})
const downloadRevisions=new Map()
await new Promise(resolve=>downloadServer.listen(0,'127.0.0.1',resolve))
const downloadBase=`http://127.0.0.1:${downloadServer.address().port}`
try {
  runPython({ mode: 'fixture', outputPath: sourcePath })
  const sourceBytes = await readFile(sourcePath)
  const source = JSON.parse(runPython({ mode: 'inspect', path: sourcePath }))
  const anchor = source.model.blocks.find(block => block.type === 'table')
  assert.equal(anchor.rowHeightEditable, true)
  assert.equal(anchor.rowHeightCells.length, 6)
  const revisions = new Map([[1, sourceBytes]])
  const inspections = new Map([[1, source]])
  const savePayloads = []
  let routeError
  server = spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'pipe' })
  let serverLog = ''
  server.stderr.on('data', chunk => { serverLog += chunk })
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
      const file = path.split('/').at(-1), actual = await response.body(), expected = await readFile(join(frontend, '../static/assets', file))
      assert.equal(sha256(actual), sha256(expected), `浏览器构建文件身份：${file}`)
      chunks.set(file, sha256(actual))
    })())
  })
  const revisionOf = request => Number(new URL(request.url()).pathname.split('/')[5])
  await page.route(`**/reports/v1/native/${documentId}/*/api/context`, route => {
    const revision = revisionOf(route.request()), bytes = revisions.get(revision)
    return route.fulfill({ json: { context: { documentId, format: 'docx', revision, parentRevision: revision === 1 ? null : revision - 1,
      scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' }, sourceFile: { path: `revision-${revision}.docx`, size: bytes.length, sha256: sha256(bytes), mediaType }, origin: 'report' },
      csrfToken: 'csrf', capabilities: { docx_editor: true }, editingEnabled: true } })
  })
  await page.route(`**/reports/v1/native/${documentId}/*/api/file`, route => route.fulfill({ body: revisions.get(revisionOf(route.request())), contentType: mediaType }))
  await page.route(`**/reports/v1/native/${documentId}/*/api/preview`, route => {
    const model = inspections.get(revisionOf(route.request())).model
    return route.fulfill({ json: { sourceSha256: model.sourceSha256, draftSha256: model.sourceSha256, model } })
  })
  await page.route(`**/reports/v1/native/${documentId}/*/api/save`, async route => {
    try {
      const revision = revisionOf(route.request()), next = revision + 1, payload = route.request().postDataJSON()
      savePayloads.push(payload)
      const outputPath = join(temporary, `revision-${next}.docx`)
      const bytes = Buffer.from(runPython({ mode: 'patch', sourcePath: join(temporary, `revision-${revision}.docx`), outputPath, operations: payload.operations }), 'base64')
      revisions.set(next, bytes); downloadRevisions.set(next,bytes); inspections.set(next, JSON.parse(runPython({ mode: 'inspect', path: outputPath })))
      await route.fulfill({ json: { documentId, revision: next, parentRevision: revision, revisionRegistered: true,
        artifacts: { word: { downloadUrl: `${downloadBase}/revision-${next}.docx`, size: bytes.length, sha256: sha256(bytes) } }, editor: { openUrl: `/reports/v1/native/${documentId}/${next}` }, validation: { ok: true, issues: [] } } })
    } catch (error) { routeError = String(error); await route.fulfill({ status: 500, json: { detail: routeError } }) }
  })
  await page.route(new RegExp(`/reports/v1/native/${documentId}/\\d+$`), async route => route.fulfill({ response: await route.fetch({ url: `${baseUrl}/reports/v1/editor/assets/native.html` }) }))
  const open = async revision => { await page.goto(`${baseUrl}/reports/v1/native/${documentId}/${revision}`); await page.locator('.docx-source-home').waitFor({ timeout: 60000 }) }
  const table = () => page.getByRole('textbox', { name: 'Word 文档编辑区' }).locator('table').first()
  const rowStyles = () => table().locator('tr').evaluateAll(rows=>rows.map(row=>[row.getAttribute('style'),row.className]))
  const controls = action => page.locator(`[data-action="${action}"]`)
  const cells = () => table().locator('td,th')
  const locate = async c => { await cells().nth(c).locator('p').first().click();await page.locator('[data-tab-id="tableLayout"]').click() }
  const setHeight = async value => {
    assert.equal(await controls('table-row-height').isEnabled(),true)
    await controls('table-row-height').click();const dialog=page.getByRole('dialog',{name:'行高',exact:true})
    await dialog.getByLabel('行高（twip）',{exact:true}).fill(value===null?'':String(value));await dialog.getByRole('button',{name:'确定',exact:true}).click();await dialog.waitFor({state:'detached'})
  }
  const history = async redo => { await page.keyboard.press(redo ? 'Control+Shift+z' : 'Control+z') }
  const saveAndRead = async(revision,before,expectedHeights)=>{
    await controls('save').click();await page.waitForFunction(next=>(document.querySelector('.save-state-label')?.textContent??'').includes(`已保存修订 ${next}`),revision+1,{timeout:60000}).catch(error=>{throw Error(`${error};route=${routeError}`)})
    assert.equal(routeError,undefined)
    const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('link',{name:'下载 Word',exact:true}).click()]);const downloaded=await readFile(await download.path());assert.equal(sha256(downloaded),sha256(revisions.get(revision+1)))
    const path=join(temporary,`downloaded-revision-${revision+1}.docx`);await writeFile(path,downloaded);const actual=JSON.parse(runPython({mode:'inspect',path}))
    assert.deepEqual(actual.details.heights,expectedHeights);assert.ok(expectedHeights.every(h=>h===null||h<=before.details.maxHeight))
    for(const key of ['parts','maskedXml','cells'])assert.deepEqual(actual.details[key],before.details[key],`除trHeight外全部原XML/parts保留:${key}`)
    return {downloaded,actual}
  }
  stage='open1';await open(1);await locate(0)
  stage='set-single';const originalStyles=await rowStyles();await setHeight(600);const changedStyles=await rowStyles();assert.notDeepEqual(changedStyles,originalStyles)
  stage='undo-redo';await history(false);assert.deepEqual(await rowStyles(),originalStyles);await history(true);assert.deepEqual(await rowStyles(),changedStyles)
  await locate(3);await setHeight(0)
  await page.waitForFunction(()=>Object.keys(localStorage).some(key=>key.startsWith('native-editor-draft:')&&localStorage.getItem(key).includes('setTableRowHeights')))
  const draftStyles=await rowStyles()
  stage='draft-reload';await page.reload();await page.locator('.docx-source-home').waitFor({timeout:60000});assert.deepEqual(await rowStyles(),draftStyles)
  stage='save1';const {downloaded,actual}=await saveAndRead(1,source,[600,null]);assert.equal(savePayloads.length,1)
  assert.deepEqual(actual.details.rules,['exact',null])
  assert.deepEqual(savePayloads[0].operations.map(op=>op.kind),['setTableRowHeights'])
  assert.deepEqual(savePayloads[0].operations[0].steps,[{top:0,bottom:1,heightTwips:600},{top:1,bottom:2,heightTwips:null}])
  stage='reopen2';await open(2);assert.deepEqual(await rowStyles(),draftStyles);await locate(3);await setHeight(750)
  const reset=await saveAndRead(2,actual,[600,750]);assert.deepEqual(reset.actual.details.rules,['exact','atLeast'])
  const mergedPath=join(temporary,'revision-10.docx');runPython({mode:'fixture',outputPath:mergedPath,merged:true});const mergedBytes=await readFile(mergedPath),mergedSource=JSON.parse(runPython({mode:'inspect',path:mergedPath}));revisions.set(10,mergedBytes);inspections.set(10,mergedSource)
  stage='merged-source';await open(10);await locate(0);await setHeight(900)
  stage='merged-save';const mergedSaved=await saveAndRead(10,mergedSource,[900,900]);assert.deepEqual(savePayloads[2].operations[0].steps,[{top:0,bottom:2,heightTwips:900}])
  await open(11);await locate(0);await setHeight(30000)
  stage='section-limit';const clamped=await saveAndRead(11,mergedSaved.actual,[mergedSource.details.maxHeight,mergedSource.details.maxHeight])
  await open(12);assert.deepEqual(clamped.actual.details.rules,['exact','atLeast'])
  await Promise.all(checks)
  assert.ok([...chunks.keys()].some(file => /^lazy-docx-main-.*\.js$/.test(file)))
  assert.ok([...chunks.keys()].some(file => /^lazy-native-docx-engine-.*\.js$/.test(file)))
  assert.deepEqual(errors, [])
  await page.screenshot({ path: join(temporary, 'row-height-reopened.png'), fullPage: true })
  await writeFile(join(temporary, 'row-height-reopened.html'), await page.content())
  console.log(JSON.stringify({ok:true,temporary,browserVersion:browser.version(),sourceSha256:sha256(sourceBytes),downloadedSha256:sha256(downloaded),operations:savePayloads.map(p=>p.operations),draftReload:true,complexMergedContinuationPreserved:true,sectionLimit:true,onlyTrHeightBytesChanged:true,loadedChunks:Object.fromEntries(chunks),errors}))
} catch (error) {
  if (page) {
    await writeFile(join(temporary, 'failure.html'), await page.content()).catch(() => {})
    await page.screenshot({ path: join(temporary, 'failure.png'), fullPage: true }).catch(() => {})
    console.error(JSON.stringify({ stage, temporary, status: await page.locator('.save-state-label').textContent().catch(() => null) }))
  }
  throw error
} finally {
  await browser?.close()
  server?.kill()
  await new Promise(resolve=>downloadServer.close(resolve))
}
