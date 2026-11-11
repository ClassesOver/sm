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
const port = Number(process.env.DOCX_CELL_MARGINS_SMOKE_PORT ?? 4242)
const baseUrl = `http://127.0.0.1:${port}`
const documentId = 'fixture-cell-margins-built'
const mediaType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex')
const temporary = await mkdtemp(join(tmpdir(), 'docx-cell-margins-built-'))
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
        rows='<w:tr>'+cell('MERGED中文',0,'<w:gridSpan w:val="2"/><w:vMerge w:val="restart"/>',span=2)+cell('C1中文',2)+'</w:tr><w:tr>'+cell('隐藏continue中文',0,'<w:gridSpan w:val="2"/><w:vMerge/>',body=para('隐藏continue中文'),span=2)+cell('C2中文',2)+'</w:tr>'
    else: rows=''.join('<w:tr>'+''.join(cell(chr(65+c)+str(r+1)+'中文',c) for c in range(3))+'</w:tr>' for r in range(2))
    table='<w:tbl><w:tblPr><w:tblW w:w="7203" w:type="dxa"/><w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>'+''.join('<w:gridCol w:w="'+str(w)+'"/>' for w in widths)+'</w:tblGrid>'+rows+'</w:tbl>'
    table=table.replace('<w:tblPr>','<w:tblPr><w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="108" w:type="dxa"/><w:bottom w:w="7" w:type="dxa"/><w:right w:w="109" w:type="dxa"/></w:tblCellMar>')
    table=table.replace('<w:tcPr>','<w:tcPr><w:tcMar><w:left w:w="33" w:type="dxa"/><w:top w:w="0" w:type="dxa"/></w:tcMar>',1)
    if p.get('merged'): table=table.replace('<w:vMerge/>','<w:vMerge/><w:tcMar><w:left w:w="71" w:type="dxa"/><w:top w:w="0" w:type="dxa"/></w:tcMar>')
    if p.get('rtl'): table=table.replace('<w:tblPr>','<w:tblPr><w:bidiVisual/>')
    if p.get('vertical'): table=table.replace('<w:shd','<w:textDirection w:val="tbRl"/><w:shd',1)
    if p.get('directions'): table=table.replace('<w:shd', '<w:textDirection w:val="tbRlV"/><w:shd',1)
    if p.get('missingTcPr'): table=re.sub(r'<w:tcPr>[\s\S]*?</w:tcPr>','',table,count=1)
    if p.get('sourceMode')=='contents': table=table.replace('w:w="7203" w:type="dxa"','w:w="0" w:type="auto"').replace('w:type="fixed"','w:type="autofit"')
    if p.get('sourceMode')=='window': table=table.replace('w:w="7203" w:type="dxa"','w:w="3500" w:type="pct"').replace('w:type="fixed"','w:type="autofit"')
    if p.get('fullWindow'): table=table.replace('w:w="3500" w:type="pct"','w:w="5000" w:type="pct"')
    if p.get('missingTcW'): table=re.sub(r'<w:tcW\b[^>]*/>','',table)
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
        widths=[int(e.get('{'+ns['w']+'}w')) for e in root.findall('w:tblGrid/w:gridCol',ns)]
        nsW='{'+ns['w']+'}'
        margins={}
        default=root.find('w:tblPr/w:tblCellMar',ns)
        if default is not None:
            for child in default: margins[etree.QName(child).localname]=int(child.get(nsW+'w'))
        model=inspect_docx(data);anchor=next(x for x in model['blocks'] if x['type']=='table')
        details={'margins':margins,'cellXml':[etree.tostring(c).decode() for c in root.findall('w:tr/w:tc',ns)],
          'maskedXml':re.sub(r'<w:tblCellMar\b[^>]*>[\s\S]*?</w:tblCellMar>','',xml),
          'parts':{name:sha256(package.read(name)).hexdigest() for name in package.namelist() if name!='word/document.xml' and not name.endswith('/')}}
    print(json.dumps({'model':model,'details':details},ensure_ascii=False))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr || `python exited ${result.status}`)
  return result.stdout.trim()
}
let server, browser, page, stage = 'setup'
const downloadServer=createServer((request,response)=>{const match=/^\/revision-(\d+)\.docx$/.exec(request.url??'');const bytes=match&&downloadRevisions.get(Number(match[1]));if(!bytes){response.writeHead(404);response.end();return}response.writeHead(200,{'Content-Type':mediaType,'Content-Disposition':'attachment; filename=autofit.docx','Content-Length':bytes.length});response.end(bytes)})
const downloadRevisions=new Map()
await new Promise(resolve=>downloadServer.listen(0,'127.0.0.1',resolve))
const downloadBase=`http://127.0.0.1:${downloadServer.address().port}`
try {
  runPython({ mode: 'fixture', outputPath: sourcePath })
  const sourceBytes = await readFile(sourcePath)
  const source = JSON.parse(runPython({ mode: 'inspect', path: sourcePath }))
  const anchor = source.model.blocks.find(block => block.type === 'table')
  assert.equal(anchor.tableCellMarginsEditable, true)
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
  const controls = action => page.locator(`[data-action="${action}"]`)
  const cells = () => table().locator('td,th')
  const dom=()=>table().evaluate(node=>node.outerHTML)
  const locate=async()=>{await cells().nth(0).locator('p').first().click();await page.locator('[data-tab-id="tableLayout"]').click()}
  const openMargins=async()=>{assert.equal(await controls('table-cell-margins').isEnabled(),true);await controls('table-cell-margins').click();return page.getByRole('dialog',{name:'默认单元格边距',exact:true})}
  const geometry=async()=>cells().evaluateAll(list=>list.map(cell=>{const p=cell.querySelector('p'),a=cell.getBoundingClientRect(),b=p.getBoundingClientRect();const style=getComputedStyle(cell);return{left:b.left-a.left,right:a.right-b.right,top:b.top-a.top,width:a.width,height:a.height,paddingLeft:style.paddingLeft,paddingRight:style.paddingRight}}))
  const results=[]
  for(const [revision,merged,rtl,vertical] of [[1,false,false,false],[10,true,false,false],[20,false,true,false],[30,false,false,true]]){
    let before=source
    if(revision!==1){const path=join(temporary,`revision-${revision}.docx`);runPython({mode:'fixture',outputPath:path,merged,rtl,vertical});const bytes=await readFile(path);before=JSON.parse(runPython({mode:'inspect',path}));revisions.set(revision,bytes);inspections.set(revision,before)}
    assert.equal(before.model.blocks.find(b=>b.type==='table').tableCellMarginsEditable,true)
    stage=`noop-${revision}`;await open(revision);await locate();const initial=await dom();let dialog=await openMargins();assert.equal(await dialog.locator('[data-margin="right"]').inputValue(),'5.45');await dialog.getByRole('button',{name:'确定',exact:true}).click();assert.equal(await dom(),initial)
    stage=`set-${revision}`;const boxesBefore=await geometry();dialog=await openMargins();await dialog.locator('[data-margin="top"]').fill('0');await dialog.locator('[data-margin="right"]').fill('0.31cm');await dialog.locator('[data-margin="bottom"]').fill('0.17cm');await dialog.locator('[data-margin="left"]').fill('0.23cm');await dialog.getByRole('button',{name:'确定',exact:true}).click();const modified=await dom();assert.notEqual(modified,initial)
    await page.keyboard.press('Control+z');assert.equal(await dom(),initial);await page.keyboard.press('Control+Shift+z');assert.equal(await dom(),modified)
    const boxesAfter=await geometry();assert.notDeepEqual(boxesAfter,boxesBefore,'真实内容盒受默认边距影响');assert.equal(boxesAfter[0].paddingLeft,boxesBefore[0].paddingLeft,'owner显式left33覆盖保持');if(merged)assert.equal(boxesAfter[0].paddingLeft,boxesBefore[0].paddingLeft,'merged owner覆盖保持');results.push({revision,merged,rtl,vertical,boxesBefore,boxesAfter})
    await page.reload();await page.locator('.docx-source-home').waitFor({timeout:60000});assert.equal(await dom(),modified,'边距草稿精确恢复')
    await controls('save').click();await page.waitForFunction(next=>(document.querySelector('.save-state-label')?.textContent??'').includes(`已保存修订 ${next}`),revision+1,{timeout:60000}).catch(error=>{throw Error(`${error};route=${routeError}`)})
    assert.equal(routeError,undefined);assert.deepEqual(savePayloads.at(-1).operations.map(op=>op.kind),['setTableCellMargins']);assert.deepEqual(savePayloads.at(-1).operations[0].margins,{top:0,right:176,bottom:96,left:130})
    const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('link',{name:'下载 Word',exact:true}).click()]);const bytes=await readFile(await download.path());assert.equal(sha256(bytes),sha256(revisions.get(revision+1)))
    const path=join(temporary,`downloaded-revision-${revision+1}.docx`);await writeFile(path,bytes);const actual=JSON.parse(runPython({mode:'inspect',path}));assert.deepEqual(actual.details.margins,{top:0,left:130,bottom:96,right:176})
    for(const key of ['cellXml','maskedXml','parts'])assert.deepEqual(actual.details[key],before.details[key],`默认外所有原字节保留:${key}`)
    await open(revision+1);await locate();assert.deepEqual(await geometry(),boxesAfter,'保存重开布局保持')
    await page.screenshot({path:join(temporary,`revision-${revision+1}-margins-reopened.png`),fullPage:true});await writeFile(join(temporary,`revision-${revision+1}-margins-reopened.html`),await page.content())
  }
  await Promise.all(checks)
  assert.ok([...chunks.keys()].some(file => /^lazy-docx-main-.*\.js$/.test(file)))
  assert.ok([...chunks.keys()].some(file => /^lazy-native-docx-engine-.*\.js$/.test(file)))
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ok:true,temporary,browserVersion:browser.version(),results,operations:savePayloads.map(p=>p.operations),cellOverridesPreserved:true,onlyTableDefaultsChanged:true,loadedChunks:Object.fromEntries(chunks),errors}))
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
