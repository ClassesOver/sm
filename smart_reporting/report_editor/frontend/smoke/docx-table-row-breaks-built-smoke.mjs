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
const port = Number(process.env.DOCX_ROW_BREAKS_SMOKE_PORT ?? 4242)
const baseUrl = `http://127.0.0.1:${port}`
const documentId = 'fixture-row-breaks-built'
const mediaType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex')
const temporary = await mkdtemp(join(tmpdir(), 'docx-row-breaks-built-'))
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
        return '<w:p w:rsidR="00ABCDEF"><w:pPr><w:spacing w:before="0" w:after="0" w:line="300" w:lineRule="exact"/></w:pPr>'+('' if empty else '<w:r><w:rPr><w:b/><w:color w:val="AA0000"/></w:rPr><w:t>'+t+'</w:t></w:r><w:r><w:rPr><w:i/></w:rPr><w:t>中文😀</w:t></w:r>')+'</w:p>'
    widths=[3001,4001]
    def cell(t,c,pr='',body=None):
        return '<w:tc><w:tcPr><w:tcW w:w="'+str(widths[c])+'" w:type="dxa"/>'+pr+'<w:shd w:fill="E6EDF5"/></w:tcPr>'+ (body if body is not None else para(t)+para(t+'正文'))+'</w:tc>'
    row0='<w:tr w:rsidR="00112233"><w:trPr><w:cantSplit w:val="0"/><w:trHeight w:val="600" w:hRule="exact"/><w:tblHeader/></w:trPr>'+cell('HEADER-L',0)+cell('HEADER-R',1)+'</w:tr>'
    cant='<w:cantSplit></w:cantSplit>' if p.get('paired') else '<w:cantSplit/>'
    row1='<w:tr w:rsidR="00445566"><w:trPr>'+cant+'<w:trHeight w:val="300" w:hRule="atLeast"/></w:trPr>'+cell('MERGE-OWNER' if p.get('merged') else 'OWNER',0,'<w:vMerge w:val="restart"/>' if p.get('merged') else '')+cell('TARGET',1,body=''.join(para('TARGET-LINE-'+str(i).zfill(2)) for i in range(18)))+'</w:tr>'
    row2='<w:tr><w:trPr><w:trHeight w:val="300" w:hRule="atLeast"/></w:trPr>'+cell('HIDDEN-CONTINUATION',0,'<w:vMerge/>' if p.get('merged') else '')+cell('TAIL',1)+'</w:tr>'
    table='<w:tbl><w:tblPr><w:tblW w:w="7002" w:type="dxa"/><w:tblLayout w:type="fixed"/><w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="108" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="109" w:type="dxa"/></w:tblCellMar>'+('<w:bidiVisual/>' if p.get('rtl') else '')+'</w:tblPr><w:tblGrid>'+''.join('<w:gridCol w:w="'+str(w)+'"/>' for w in widths)+'</w:tblGrid>'+row0+row1+row2+'</w:tbl>'
    with ZipFile(BytesIO(buf.getvalue())) as zin, ZipFile(p['outputPath'],'w') as zout:
        for name in zin.namelist():
            data=zin.read(name)
            if name=='word/document.xml':
                xml=data.decode();xml=re.sub(r'(<w:body>)[\s\S]*?(<w:sectPr\b)',lambda m:m[1]+''.join(para('PREFACE-'+str(i)) for i in range(12))+table+para('外部后')+m[2],xml,count=1);xml=re.sub(r'<w:pgSz[^>]*/>','<w:pgSz w:w="12000" w:h="10000"/>',xml);xml=re.sub(r'<w:pgMar[^>]*/>','<w:pgMar w:top="1000" w:right="1500" w:bottom="1000" w:left="1500" w:header="500" w:footer="500" w:gutter="0"/>',xml);xml=re.sub(r'<w:cols\b[^>]*/>','<w:cols w:num="2"/>',xml) if p.get('multicol') else xml;data=xml.encode()
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
          'maskedXml':re.sub(r'<w:cantSplit\b[^>]*?/>|<w:cantSplit\b[^>]*>[\s\S]*?</w:cantSplit>','',xml),
          'rowFlags':[r.find('w:trPr/w:cantSplit',ns) is not None and r.find('w:trPr/w:cantSplit',ns).get(nsW+'val','true') not in ['0','false','off'] for r in root.findall('w:tr',ns)],
          'rowXml':[etree.tostring(r).decode() for r in root.findall('w:tr',ns)],
          'parts':{name:sha256(package.read(name)).hexdigest() for name in package.namelist() if name!='word/document.xml' and not name.endswith('/')}}
    print(json.dumps({'model':model,'details':details},ensure_ascii=False))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr || `python exited ${result.status}`)
  return result.stdout.trim()
}
let server, browser, page, stage = 'setup'
const downloadServer=createServer((request,response)=>{const match=/^\/revision-(\d+)\.docx$/.exec(request.url??'');const bytes=match&&downloadRevisions.get(Number(match[1]));if(!bytes){response.writeHead(404);response.end();return}response.writeHead(200,{'Content-Type':mediaType,'Content-Disposition':'attachment; filename=row-breaks.docx','Content-Length':bytes.length});response.end(bytes)})
const downloadRevisions=new Map()
await new Promise(resolve=>downloadServer.listen(0,'127.0.0.1',resolve))
const downloadBase=`http://127.0.0.1:${downloadServer.address().port}`
try {
  runPython({ mode: 'fixture', outputPath: sourcePath })
  const sourceBytes = await readFile(sourcePath)
  const source = JSON.parse(runPython({ mode: 'inspect', path: sourcePath }))
  const anchor = source.model.blocks.find(block => block.type === 'table')
  assert.equal(anchor.rowBreakEditable, true)
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
  const dom=()=>table().evaluate(node=>{const clone=node.cloneNode(true);for(const el of [clone,...clone.querySelectorAll('[class]')])if(el.hasAttribute('class'))el.setAttribute('class',[...el.classList].sort().join(' '));return clone.outerHTML})
  const locate=async()=>{await table().locator('tr').nth(1).locator('td,th').last().locator('p').first().click();await page.locator('[data-tab-id="tableLayout"]').click()}
  const openRows=async()=>{await controls('table-properties').click();const props=page.getByRole('dialog',{name:'单元格边距',exact:true});if(await props.count())await props.locator('[data-action="row-breaks"]').click();else await page.getByRole('dialog',{name:'表格属性选项',exact:true}).locator('[data-action="row-breaks"]').click();return page.getByRole('dialog',{name:'行跨页',exact:true})}
  const set=async allow=>{const dialog=await openRows();await dialog.locator('[data-action="allow-break"]').setChecked(allow);await dialog.getByRole('button',{name:'确定',exact:true}).click();await dialog.waitFor({state:'detached'})}
  const preview=async label=>{
    await page.locator('[data-tab-id="view"]').click();await page.locator('[data-action="pagination-preview"]').click();await page.locator('.pv-page').first().waitFor({timeout:60000});await page.waitForFunction(()=>document.querySelectorAll('.pv-page').length>0&&document.querySelector('.pv-content [data-idx]'))
    await page.evaluate(async()=>{await document.fonts.ready;await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))})
    const layout=await page.locator('.pv-page').evaluateAll(pages=>{
      const intersect=(a,b)=>({left:Math.max(a.left,b.left),right:Math.min(a.right,b.right),top:Math.max(a.top,b.top),bottom:Math.min(a.bottom,b.bottom)})
      return pages.map((page,index)=>{const lines=[];for(const paragraph of page.querySelectorAll('[data-pv-body] p')){const text=paragraph.textContent??'';if(!text.includes('TARGET-LINE-'))continue;if(getComputedStyle(paragraph).visibility==='hidden')continue;const range=document.createRange();range.selectNodeContents(paragraph);for(const rect of range.getClientRects()){let clip=intersect(rect,page.getBoundingClientRect());for(let parent=paragraph.parentElement;parent&&parent!==page;parent=parent.parentElement){const css=getComputedStyle(parent);if(['hidden','clip','auto','scroll'].includes(css.overflowY)||parent.classList.contains('pv-clip'))clip=intersect(clip,parent.getBoundingClientRect())}if(clip.right-clip.left>1&&clip.bottom-clip.top>2){lines.push(text.match(/TARGET-LINE-\d+/)[0]);break}}}return{page:index,lines:[...new Set(lines)],window:[...page.querySelectorAll('[data-pv-body]')].map(node=>node.getAttribute('data-pv-win'))}})
    })
    assert.equal(new Set(layout.flatMap(p=>p.lines)).size,18,'实际分页所有目标行文字均可见且不丢')
    await page.screenshot({path:join(temporary,`${label}-preview.png`),fullPage:true});await writeFile(join(temporary,`${label}-preview.html`),await page.content())
    await page.locator('.pv-toolbar .pv-close').last().click();await page.locator('.pagination-preview').waitFor({state:'detached'});return layout
  }
  const results=[]
  for(const [revision,options] of [[1,{}],[10,{merged:true}],[20,{rtl:true}],[30,{paired:true}]]){
    if(revision<Number(process.env.DOCX_ROW_BREAKS_START_REVISION??1))continue
    let before=source
    if(revision!==1){const path=join(temporary,`revision-${revision}.docx`);runPython({mode:'fixture',outputPath:path,...options});const bytes=await readFile(path);before=JSON.parse(runPython({mode:'inspect',path}));revisions.set(revision,bytes);inspections.set(revision,before)}
    assert.equal(before.model.blocks.find(b=>b.type==='table').rowBreakEditable,true)
    stage=`before-${revision}`;await open(revision);await locate();const initial=await dom();let dialog=await openRows();assert.equal(await dialog.locator('[data-action="allow-break"]').isChecked(),false);await dialog.getByRole('button',{name:'确定',exact:true}).click();assert.equal(await dom(),initial,'无操作不dirty')
    const first=await table().locator('tr').nth(0).locator('td,th').first().boundingBox(),last=await table().locator('tr').nth(1).locator('td,th').last().boundingBox();assert.ok(first&&last);await page.mouse.move(first.x+8,first.y+8);await page.mouse.down();await page.mouse.move(last.x+last.width-8,last.y+last.height-8,{steps:25});await page.mouse.up();await page.waitForFunction(()=>document.querySelectorAll('.selectedCell').length>1);const mixedDom=await dom();dialog=await openRows();assert.equal(await dialog.locator('[data-action="allow-break"]').evaluate(node=>node.indeterminate),true);assert.equal(await dialog.locator('[data-action="allow-break"]').getAttribute('aria-checked'),'mixed');await dialog.getByRole('button',{name:'确定',exact:true}).click();assert.equal(await dom(),mixedDom,'混合状态不操作不dirty');await locate()
    const initialPages=await preview(`revision-${revision}-prevent`);const initialStart=initialPages.find(p=>p.lines.includes('TARGET-LINE-00'))?.page;assert.equal(initialStart,1,'来源cantSplit把长行整体推到第二页')
    await locate();const undoBefore=await dom();stage=`allow-${revision}`;await set(true);const allowed=await dom();assert.notEqual(allowed,initial)
    await page.keyboard.press('Control+z');assert.equal(await dom(),undoBefore);await page.keyboard.press('Control+Shift+z');assert.equal(await dom(),allowed)
    const allowPages=await preview(`revision-${revision}-allow`);assert.equal(allowPages.find(p=>p.lines.includes('TARGET-LINE-00'))?.page,0,'允许跨页后目标行实际从第一页起排');assert.ok(allowPages.filter(p=>p.lines.length).length>=2,'目标行真实跨页切分');assert.notDeepEqual(allowPages,initialPages)
    await locate();await set(false);const preventAgain=await preview(`revision-${revision}-prevent-again`);assert.deepEqual(preventAgain,initialPages,'禁止跨页立即恢复原分页');await locate();await set(true);const finalDom=await dom();await page.reload();await page.locator('.docx-source-home').waitFor({timeout:60000});assert.equal(await dom(),finalDom,'草稿回放精确恢复')
    const livePages=await preview(`revision-${revision}-draft-allow`);assert.deepEqual(livePages,allowPages,'草稿恢复实际分页一致')
    stage=`save-${revision}`;await controls('save').click();await page.waitForFunction(next=>(document.querySelector('.save-state-label')?.textContent??'').includes(`已保存修订 ${next}`),revision+1,{timeout:60000}).catch(error=>{throw Error(`${error};route=${routeError}`)})
    assert.equal(routeError,undefined);const operations=savePayloads.at(-1).operations;assert.deepEqual(operations.map(op=>op.kind),['setTableRowBreaks']);assert.deepEqual(operations[0].steps,[{top:1,bottom:2,allowBreak:true},{top:1,bottom:2,allowBreak:false},{top:1,bottom:2,allowBreak:true}])
    const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('link',{name:'下载 Word',exact:true}).click()]);const bytes=await readFile(await download.path());assert.equal(sha256(bytes),sha256(revisions.get(revision+1)));const path=join(temporary,`downloaded-revision-${revision+1}.docx`);await writeFile(path,bytes);const actual=JSON.parse(runPython({mode:'inspect',path}));assert.deepEqual(actual.details.rowFlags,[false,false,false]);for(const key of ['cellXml','maskedXml','parts'])assert.deepEqual(actual.details[key],before.details[key],`只改cantSplit保所有原字节:${key}`);for(const index of [0,2])assert.equal(actual.details.rowXml[index],before.details.rowXml[index],'非目标行全文保留')
    stage=`reopen-${revision}`;await open(revision+1);await locate();const reopenedPages=await preview(`revision-${revision+1}-reopened`);assert.deepEqual(reopenedPages,livePages,'真实保存重开与live分页完全一致')
    results.push({revision,...options,initialPages,allowPages,preventAgain,livePages,reopenedPages,operations});await writeFile(join(temporary,`revision-${revision}-result.json`),JSON.stringify(results.at(-1),null,2))
  }
  await Promise.all(checks)
  assert.ok([...chunks.keys()].some(file => /^lazy-docx-main-.*\.js$/.test(file)))
  assert.ok([...chunks.keys()].some(file => /^lazy-native-docx-engine-.*\.js$/.test(file)))
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ok:true,temporary,browserVersion:browser.version(),results,operations:savePayloads.map(p=>p.operations),onlyCantSplitChanged:true,liveAndReopenedPaginationMatched:true,loadedChunks:Object.fromEntries(chunks),errors}))
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
