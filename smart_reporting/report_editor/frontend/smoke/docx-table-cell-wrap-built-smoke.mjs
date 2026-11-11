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
const port = Number(process.env.DOCX_CELL_WRAP_SMOKE_PORT ?? 4267)
const baseUrl = `http://127.0.0.1:${port}`
const documentId = 'fixture-cell-wrap-built'
const mediaType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex')
const temporary = await mkdtemp(join(tmpdir(), 'docx-cell-wrap-built-'))
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
    widths=[2001,1999]
    text='换行测试中文mixed words long content repeated repeated repeated repeated repeated'
    def cell(t,c,pr='',body=None):
        return '<w:tc><w:tcPr><w:tcW w:w="'+str(widths[c])+'" w:type="dxa"/>'+pr+'<w:shd w:fill="E6EDF5"/><w:tcFitText/><w:foo w:val="keep"/></w:tcPr>'+ (body if body is not None else para(t)+para(text))+'</w:tc>'
    row0='<w:tr>'+cell('OWNER',0,('<w:vMerge w:val="restart"/>' if p.get('merged') else '')+('<w:noWrap></w:noWrap>' if p.get('mixed') or p.get('merged') else ''))+cell('RIGHT',1)+'</w:tr>'
    row1='<w:tr>'+cell('HIDDEN-CONTINUATION' if p.get('merged') else 'LOWER',0,('<w:vMerge/><w:noWrap w:val="0"/>' if p.get('merged') else ''))+cell('TAIL',1,'<w:noWrap w:val="off"/>')+'</w:tr>'
    table='<w:tbl><w:tblPr><w:tblW w:w="4000" w:type="dxa"/><w:tblLayout w:type="'+('fixed' if p.get('fixed') else 'autofit')+'"/>'+('<w:bidiVisual/>' if p.get('rtl') else '')+'</w:tblPr><w:tblGrid>'+''.join('<w:gridCol w:w="'+str(w)+'"/>' for w in widths)+'</w:tblGrid>'+row0+row1+'</w:tbl>'
    with ZipFile(BytesIO(buf.getvalue())) as zin, ZipFile(p['outputPath'],'w') as zout:
        for name in zin.namelist():
            data=zin.read(name)
            if name=='word/document.xml':
                xml=data.decode();xml=re.sub(r'(<w:body>)[\s\S]*?(<w:sectPr\b)',lambda m:m[1]+para('外部前')+table+para('外部后')+m[2],xml,count=1);xml=re.sub(r'<w:pgSz[^>]*/>','<w:pgSz w:w="12000" w:h="16800"/>',xml);xml=re.sub(r'<w:pgMar[^>]*/>','<w:pgMar w:top="1000" w:right="1500" w:bottom="1000" w:left="1500" w:header="500" w:footer="500" w:gutter="0"/>',xml);xml=re.sub(r'<w:cols\b[^>]*/>','<w:cols w:num="2"/>',xml) if p.get('multicol') else xml;data=xml.encode()
            if name=='word/settings.xml':
                xml=data.decode();xml=re.sub(r'<w:compat>[\s\S]*?</w:compat>','',xml);xml=xml.replace('</w:settings>','<w:compat><w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="'+str(p.get('legacy',15))+'"/></w:compat></w:settings>');data=xml.encode()
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
        details={'margins':margins,'cellXml':[re.sub(r'<w:noWrap\b[^>]*?/>|<w:noWrap\b[^>]*>[\s\S]*?</w:noWrap>','',etree.tostring(c).decode()) for c in root.findall('w:tr/w:tc',ns)],
          'maskedXml':re.sub(r'<w:noWrap\b[^>]*?/>|<w:noWrap\b[^>]*>[\s\S]*?</w:noWrap>','',xml),
          'noWrap':[e is not None and e.get(nsW+'val','true') not in ['0','false','off'] for e in [c.find('w:tcPr/w:noWrap',ns) for c in root.findall('w:tr/w:tc',ns)]],
          'parts':{name:sha256(package.read(name)).hexdigest() for name in package.namelist() if name!='word/document.xml' and not name.endswith('/')}}
    print(json.dumps({'model':model,'details':details},ensure_ascii=False))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr || `python exited ${result.status}`)
  return result.stdout.trim()
}
let server, browser, page, stage = 'setup'
const downloadServer=createServer((request,response)=>{const match=/^\/revision-(\d+)\.docx$/.exec(request.url??'');const bytes=match&&downloadRevisions.get(Number(match[1]));if(!bytes){response.writeHead(404);response.end();return}response.writeHead(200,{'Content-Type':mediaType,'Content-Disposition':'attachment; filename=table-alignment.docx','Content-Length':bytes.length});response.end(bytes)})
const downloadRevisions=new Map()
await new Promise(resolve=>downloadServer.listen(0,'127.0.0.1',resolve))
const downloadBase=`http://127.0.0.1:${downloadServer.address().port}`
try {
  runPython({ mode: 'fixture', outputPath: sourcePath })
  const sourceBytes = await readFile(sourcePath)
  const source = JSON.parse(runPython({ mode: 'inspect', path: sourcePath }))
  const anchor = source.model.blocks.find(block => block.type === 'table')
  assert.equal(anchor.tableCellWrapEditable, true)
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
  const openWrap=async()=>{await controls('table-properties').click();const props=page.getByRole('dialog',{name:'单元格边距',exact:true});if(await props.count())await props.locator('[data-action="cell-wrap"]').click();else await page.getByRole('dialog',{name:'表格属性选项',exact:true}).locator('[data-action="cell-wrap"]').click();return page.getByRole('dialog',{name:'自动换行',exact:true})}
  const set=async wrap=>{const dialog=await openWrap();await dialog.getByRole('checkbox',{name:'自动换行',exact:true}).setChecked(wrap);await dialog.getByRole('button',{name:'确定',exact:true}).click();await dialog.waitFor({state:'detached'})}
  const geometry=()=>table().evaluate(node=>({width:node.getBoundingClientRect().width,height:node.getBoundingClientRect().height,cells:[...node.querySelectorAll('td,th')].map(cell=>({noWrap:cell.style.whiteSpace,whiteSpace:getComputedStyle(cell).whiteSpace,text:cell.textContent,width:cell.getBoundingClientRect().width,height:cell.getBoundingClientRect().height}))}))
  const canonicalDom=()=>table().evaluate(node=>{const clone=node.cloneNode(true);for(const el of [clone,...clone.querySelectorAll('[class]')])if(el.hasAttribute('class'))el.setAttribute('class',[...el.classList].sort().join(' '));for(const el of [clone,...clone.querySelectorAll('*')]){const attrs=[...el.attributes].map(attr=>[attr.name,attr.value]).sort(([a],[b])=>a.localeCompare(b));for(const attr of [...el.attributes])el.removeAttribute(attr.name);for(const [name,value]of attrs)el.setAttribute(name,value)}return clone.outerHTML})
  const results=[]
  for(const {revision,name,options,selection,wrap,expected}of [
    {revision:1,name:'auto-caret',options:{},selection:'caret',wrap:false,expected:[true,false,false,false]},
    {revision:10,name:'fixed-mixed-rect',options:{fixed:true,mixed:true},selection:'rect',wrap:true,expected:[false,false,false,false]},
    {revision:20,name:'rtl-rect',options:{rtl:true},selection:'rect',wrap:false,expected:[true,true,false,false]},
    {revision:30,name:'merged-lower',options:{merged:true},selection:'lower',wrap:true,expected:[false,false,false,false]},
  ]){
    if(revision<Number(process.env.DOCX_CELL_WRAP_START_REVISION??1))continue
    if(process.env.DOCX_CELL_WRAP_RESUME_DIRECTORY){
      let prior=null
      try{prior=JSON.parse(await readFile(join(process.env.DOCX_CELL_WRAP_RESUME_DIRECTORY,`${name}-result.json`),'utf8'))}catch(error){if(error.code!=='ENOENT')throw error}
      if(prior){const bytes=await readFile(join(process.env.DOCX_CELL_WRAP_RESUME_DIRECTORY,`downloaded-revision-${prior.revision}.docx`));assert.equal(sha256(bytes),prior.downloadSha256,'续跑核验已完成来源下载身份');for(const prefix of ['revision','downloaded-revision'])await writeFile(join(temporary,`${prefix}-${prior.revision}.docx`),bytes);await writeFile(join(temporary,`${name}-result.json`),JSON.stringify(prior,null,2));results.push(prior);continue}
    }
    const path=join(temporary,`revision-${revision}.docx`);if(revision!==1)runPython({mode:'fixture',outputPath:path,...options});const bytesBefore=await readFile(path),before=JSON.parse(runPython({mode:'inspect',path}));revisions.set(revision,bytesBefore);inspections.set(revision,before);assert.equal(before.model.blocks.find(b=>b.type==='table').tableCellWrapEditable,true)
    const choose=async()=>{await locate();if(selection==='rect'){const first=await cells().first().boundingBox(),last=await table().locator('tr').first().locator('td,th').last().boundingBox();assert(first&&last);await page.mouse.move(first.x+8,first.y+8);await page.mouse.down();await page.mouse.move(last.x+last.width-8,last.y+last.height-8,{steps:25});await page.mouse.up();await page.waitForFunction(()=>document.querySelectorAll('.selectedCell').length===2)}if(selection==='lower'){const box=await cells().first().boundingBox();assert(box);await page.mouse.click(box.x+12,box.y+box.height-12)}await page.locator('[data-tab-id="tableLayout"]').click()}
    stage=`noop-${name}`;await open(revision);await choose();const initial=await canonicalDom();let dialog=await openWrap();assert.match(await dialog.textContent(),/固定布局或超宽/);if(options.mixed){assert.equal(await dialog.getByRole('checkbox').evaluate(n=>n.indeterminate),true);assert.equal(await dialog.getByRole('checkbox').getAttribute('aria-checked'),'mixed')}await dialog.getByRole('button',{name:'确定',exact:true}).click();assert.equal(await canonicalDom(),initial,'未触碰/mixed不创建操作')
    stage=`set-${name}`;await set(wrap);const modified=await canonicalDom();await page.keyboard.press('Control+z');assert.equal(await canonicalDom(),initial);await page.keyboard.press('Control+Shift+z');assert.equal(await canonicalDom(),modified)
    // 连续往返只保本功能步骤，最终真实值与目标一致。
    await set(!wrap);await set(wrap);const finalDom=await canonicalDom(),box=await geometry();await page.reload();await page.locator('.docx-source-home').waitFor({timeout:60000});await choose();assert.equal(await canonicalDom(),finalDom,'草稿精确恢复');assert.deepEqual(await geometry(),box)
    stage=`save-${name}`;await controls('save').click();await page.waitForFunction(n=>(document.querySelector('.save-state-label')?.textContent??'').includes(`已保存修订 ${n}`),revision+1,{timeout:60000});assert.equal(routeError,undefined);const operations=savePayloads.at(-1).operations;assert.deepEqual(operations.map(o=>o.kind),['setTableCellWrap']);assert.equal(operations[0].steps.at(-1).wrap,wrap)
    const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('link',{name:'下载 Word',exact:true}).click()]);const bytes=await readFile(await download.path());assert.equal(sha256(bytes),sha256(revisions.get(revision+1)));const downloaded=join(temporary,`downloaded-revision-${revision+1}.docx`);await writeFile(downloaded,bytes);const after=JSON.parse(runPython({mode:'inspect',path:downloaded}));assert.deepEqual(after.details.noWrap,expected);for(const key of ['cellXml','maskedXml','parts'])assert.deepEqual(after.details[key],before.details[key],`只改直属noWrap:${key}`)
    stage=`reopen-${name}`;await open(revision+1);await locate();assert.deepEqual(await geometry(),box,'明确重开与live的实际单元格尺寸/换行CSS/正文一致');const screenshot=join(temporary,`revision-${revision+1}-${name}-reopened.png`);await page.screenshot({path:screenshot,fullPage:true});await writeFile(join(temporary,`revision-${revision+1}-${name}-reopened.html`),await page.content());const result={name,revision:revision+1,options,selection,wrap,operations,box,noWrap:after.details.noWrap,downloadSha256:sha256(bytes),screenshot};results.push(result);await writeFile(join(temporary,`${name}-result.json`),JSON.stringify(result,null,2));console.log(JSON.stringify({case:name,revision:revision+1,downloadSha256:result.downloadSha256}))
  }
  await Promise.all(checks)
  assert.ok([...chunks.keys()].some(file => /^lazy-docx-main-.*\.js$/.test(file)))
  assert.ok([...chunks.keys()].some(file => /^lazy-native-docx-engine-.*\.js$/.test(file)))
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ok:true,temporary,browserVersion:browser.version(),results,operations:savePayloads.map(p=>p.operations),onlyDirectNoWrapChanged:true,actualGeometryAndReopenMatched:true,loadedChunks:Object.fromEntries(chunks),errors}))
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
