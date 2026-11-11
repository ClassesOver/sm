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
const port = Number(process.env.DOCX_CELL_ALIGNMENT_SMOKE_PORT ?? 4242)
const baseUrl = `http://127.0.0.1:${port}`
const documentId = 'fixture-cell-alignment-built'
const mediaType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex')
const temporary = await mkdtemp(join(tmpdir(), 'docx-cell-alignment-built-'))
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
    def alignment_paras(t):
        def p(text,props=''):
            return '<w:p w:rsidR="00ABCDEF"><w:pPr><w:keepNext/>'+props+'</w:pPr><w:r><w:rPr><w:b/><w:color w:val="FF0000"/></w:rPr><w:t>'+text+'</w:t></w:r></w:p>'
        return p('LTR '+t+'中文😀')+p('שלום explicit','<w:bidi/>')+p('שלום inferred')+p('שלום inherited','<w:pStyle w:val="AlignmentRTL"/>')+p('Heading '+t,'<w:pStyle w:val="Heading1"/>')+p('שלום list','<w:bidi/><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>')+p('')
    widths=[1801,2401,3001]
    def cell(t,c,pr='',body=None,span=1):
        return '<w:tc><w:tcPr>\n <w:tcW w:w="'+str(sum(widths[c:c+span]))+'" w:type="dxa"/>'+pr+'<w:shd w:val="pct20" w:color="AABBCC" w:fill="112233" w:themeFill="accent2" w:themeFillTint="99"/></w:tcPr>\n'+(body if body is not None else alignment_paras(t))+'</w:tc>'
    if p.get('merged'):
        rows='<w:tr><w:trPr><w:trHeight w:val="9000" w:hRule="atLeast"/></w:trPr>'+cell('MERGED中文',0,'<w:gridSpan w:val="2"/><w:vMerge w:val="restart"/>',span=2)+cell('C1中文',2)+'</w:tr><w:tr><w:trPr><w:trHeight w:val="9000" w:hRule="atLeast"/></w:trPr>'+cell('隐藏continue中文',0,'<w:gridSpan w:val="2"/><w:vMerge/>',body=para('隐藏continue中文').replace('<w:keepNext/>','<w:keepNext/><w:jc w:val="right"/>'),span=2)+cell('C2中文',2)+'</w:tr>'
    else: rows=''.join('<w:tr><w:trPr><w:trHeight w:val="9000" w:hRule="atLeast"/></w:trPr>'+''.join(cell(chr(65+c)+str(r+1)+'中文',c) for c in range(3))+'</w:tr>' for r in range(2))
    table='<w:tbl><w:tblPr><w:tblW w:w="7203" w:type="dxa"/><w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>'+''.join('<w:gridCol w:w="'+str(w)+'"/>' for w in widths)+'</w:tblGrid>'+rows+'</w:tbl>'
    if p.get('directions'): table=table.replace('<w:shd', '<w:textDirection w:val="tbRlV"/><w:shd',1)
    if p.get('missingTcPr'): table=re.sub(r'<w:tcPr>[\s\S]*?</w:tcPr>','',table,count=1)
    if p.get('sourceMode')=='contents': table=table.replace('w:w="7203" w:type="dxa"','w:w="0" w:type="auto"').replace('w:type="fixed"','w:type="autofit"')
    if p.get('sourceMode')=='window': table=table.replace('w:w="7203" w:type="dxa"','w:w="3500" w:type="pct"').replace('w:type="fixed"','w:type="autofit"')
    if p.get('fullWindow'): table=table.replace('w:w="3500" w:type="pct"','w:w="5000" w:type="pct"')
    if p.get('missingTcW'): table=re.sub(r'<w:tcW\b[^>]*/>','',table)
    with ZipFile(BytesIO(buf.getvalue())) as zin, ZipFile(p['outputPath'],'w') as zout:
        for name in zin.namelist():
            data=zin.read(name)
            if name=='word/styles.xml': data=data.replace(b'</w:styles>',b'<w:style w:type="paragraph" w:styleId="AlignmentRTL"><w:name w:val="Alignment RTL"/><w:basedOn w:val="Normal"/><w:pPr><w:bidi/></w:pPr></w:style></w:styles>')
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
        vertical=[];paragraphs=[];cellXml=[]
        for row in root.findall('w:tr',ns):
            for cell in row.findall('w:tc',ns):
                node=cell.find('w:tcPr/w:vAlign',ns);vertical.append(node.get(nsW+'val') if node is not None else None)
                ps=[]
                for p in cell.findall('w:p',ns):
                    jc=p.find('w:pPr/w:jc',ns);style=p.find('w:pPr/w:pStyle',ns)
                    ps.append({'text':''.join(p.itertext()),'jc':jc.get(nsW+'val') if jc is not None else None,'style':style.get(nsW+'val') if style is not None else None})
                paragraphs.append(ps);cellXml.append(etree.tostring(cell).decode())
        model=inspect_docx(data);anchor=next(x for x in model['blocks'] if x['type']=='table')
        details={'vertical':vertical,'paragraphs':paragraphs,'cellXml':cellXml,'cells':anchor.get('cellAlignmentCells'),'semantics':anchor.get('cellAlignmentParagraphs'),
          'maskedXml':re.sub(r'<w:(?:vAlign|jc)\b[^>]*/>','',xml),
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
  assert.equal(anchor.cellAlignmentEditable, true)
  assert.equal(anchor.cellAlignmentCells.length, 6)
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
  const align=async(vertical,horizontal)=>{const action=`table-align-${vertical==='center'?'middle':vertical}-${horizontal}`;assert.equal(await controls(action).isEnabled(),true);await controls(action).click();assert.equal(await controls(action).getAttribute('aria-pressed'),'true')}
  const geometry=async()=>cells().nth(0).evaluate(cell=>({cell:{top:cell.getBoundingClientRect().top,bottom:cell.getBoundingClientRect().bottom},paragraphs:[...cell.querySelectorAll(':scope>p,:scope>h1,:scope>h2,:scope>.doc-li')].map(p=>({text:p.textContent,align:getComputedStyle(p).textAlign,direction:getComputedStyle(p).direction,top:p.getBoundingClientRect().top,bottom:p.getBoundingClientRect().bottom}))}))
  const save=async(revision,before,vertical,horizontal,merged)=>{
    const snapshot=await dom();await page.reload();await page.locator('.docx-source-home').waitFor({timeout:60000});assert.equal(await dom(),snapshot,'九宫格草稿精确恢复')
    await controls('save').click();await page.waitForFunction(next=>(document.querySelector('.save-state-label')?.textContent??'').includes(`已保存修订 ${next}`),revision+1,{timeout:60000}).catch(error=>{throw Error(`${error};route=${routeError}`)})
    assert.equal(routeError,undefined);const step={top:0,left:0,bottom:merged?2:1,right:merged?2:1,vertical,horizontal};assert.deepEqual(savePayloads.at(-1).operations.map(op=>op.kind),['setTableCellAlignment']);assert.deepEqual(savePayloads.at(-1).operations[0].steps,[step])
    const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('link',{name:'下载 Word',exact:true}).click()]);const bytes=await readFile(await download.path());assert.equal(sha256(bytes),sha256(revisions.get(revision+1)))
    const path=join(temporary,`downloaded-revision-${revision+1}.docx`);await writeFile(path,bytes);const actual=JSON.parse(runPython({mode:'inspect',path})),expected=[...before.details.vertical],targets=merged?[0,2]:[0]
    for(const target of targets)expected[target]=vertical==='top'?null:vertical;assert.deepEqual(actual.details.vertical,expected)
    for(const [index,p] of actual.details.paragraphs[0].entries()){const explicitRtl=[1,3,5].includes(index),effectiveRtl=explicitRtl||index===2;let expected=horizontal==='center'?'center':horizontal==='left'?(effectiveRtl?'left':null):(effectiveRtl?null:'right');if(explicitRtl&&expected!==null&&expected!=='center')expected=expected==='left'?'right':'left';assert.equal(p.jc,expected,`owner paragraph ${index} visual ${horizontal}`)}
    for(let i=1;i<actual.details.paragraphs.length;i++)assert.deepEqual(actual.details.paragraphs[i],before.details.paragraphs[i],'非owner及hidden continue段落jc不变')
    for(let i=0;i<actual.details.cellXml.length;i++)if(!targets.includes(i))assert.equal(actual.details.cellXml[i],before.details.cellXml[i],'非目标cell全文不变')
    for(const key of ['parts','maskedXml','cells'])assert.deepEqual(actual.details[key],before.details[key],`对齐外全部源字节保持:${key}`)
    await open(revision+1);await locate();await page.screenshot({path:join(temporary,`revision-${revision+1}-alignment-reopened.png`),fullPage:true});await writeFile(join(temporary,`revision-${revision+1}-alignment-reopened.html`),await page.content());return actual
  }
  const positions=[]
  for(const [revision,merged] of [[1,false],[30,true]]){
    let before=source,current=revision
    if(merged){const path=join(temporary,`revision-${revision}.docx`);runPython({mode:'fixture',outputPath:path,merged:true});const bytes=await readFile(path);before=JSON.parse(runPython({mode:'inspect',path}));revisions.set(revision,bytes);inspections.set(revision,before)}
    assert.equal(before.model.blocks.find(b=>b.type==='table').cellAlignmentEditable,true)
    const combinations=merged?[['top','left'],['center','center'],['bottom','right']]:['top','center','bottom'].flatMap(v=>['left','center','right'].map(h=>[v,h]))
    for(const [vertical,horizontal] of combinations){stage=`${current}-${vertical}-${horizontal}`;await open(current);await locate();const initial=await dom();await align(vertical,horizontal);const aligned=await dom();await page.keyboard.press('Control+z');assert.equal(await dom(),initial);await page.keyboard.press('Control+Shift+z');assert.equal(await dom(),aligned)
      const rendered=await geometry();assert.equal(rendered.paragraphs.length,7);for(const paragraph of rendered.paragraphs){const visual=paragraph.align==='start'?(paragraph.direction==='rtl'?'right':'left'):paragraph.align==='end'?(paragraph.direction==='rtl'?'left':'right'):paragraph.align;assert.equal(visual,horizontal,'真实computed方向与水平视觉对齐一致')}positions.push({current,vertical,horizontal,...rendered})
      before=await save(current,before,vertical,horizontal,merged);current++
    }
  }
  for(const horizontal of ['left','center','right']){const same=positions.filter(p=>p.current<30&&p.horizontal===horizontal);assert.equal(same.length,3);const offsets=same.map(p=>p.paragraphs[0].top-p.cell.top);assert.ok(offsets[0]<offsets[1]&&offsets[1]<offsets[2],`真实垂直布局top<center<bottom: ${offsets}`)}
  await Promise.all(checks)
  assert.ok([...chunks.keys()].some(file => /^lazy-docx-main-.*\.js$/.test(file)))
  assert.ok([...chunks.keys()].some(file => /^lazy-native-docx-engine-.*\.js$/.test(file)))
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ok:true,temporary,browserVersion:browser.version(),positions,operations:savePayloads.map(p=>p.operations),nineCombinations:true,mergedHiddenParagraphsPreserved:true,onlyAlignmentBytesChanged:true,loadedChunks:Object.fromEntries(chunks),errors}))
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
