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
const port = Number(process.env.DOCX_TABLE_ALIGNMENT_SMOKE_PORT ?? 4242)
const baseUrl = `http://127.0.0.1:${port}`
const documentId = 'fixture-table-alignment-built'
const mediaType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex')
const temporary = await mkdtemp(join(tmpdir(), 'docx-table-alignment-built-'))
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
    alignment=p.get('jc','center')
    table=table.replace('<w:tblLayout',('<w:jc w:val="'+alignment+'"></w:jc>' if p.get('paired') else '<w:jc w:val="'+alignment+'"/>')+'<w:tblInd w:w="'+str(p.get('indent',333))+'" w:type="dxa"/><w:tblLayout',1)
    if p.get('pct'): table=table.replace('w:w="7203" w:type="dxa"','w:w="2500" w:type="pct"')
    if p.get('floating') or p.get('suppressed'):
        table=table.replace('<w:tblPr>','<w:tblPr><w:tblpPr w:horzAnchor="margin" w:vertAnchor="margin" w:tblpX="777" w:tblpY="111" w:leftFromText="180" w:rightFromText="180"/>')
    if p.get('suppressed'):
        # 保持仅两行，但声明的最小行高总和超12960，真实converter进入suppressed分支。
        table=table.replace('<w:tr>','<w:tr><w:trPr><w:trHeight w:val="7000" w:hRule="atLeast"/></w:trPr>')
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
        first_left=root.find('w:tr/w:tc/w:tcPr/w:tcMar/w:left',ns)
        details={'margins':margins,'firstCellLeftTwips':int(first_left.get(nsW+'w')) if first_left is not None else margins.get('left',108),'cellXml':[etree.tostring(c).decode() for c in root.findall('w:tr/w:tc',ns)],
          'maskedXml':xml[:a]+re.sub(r'(<w:tblPr>)([\s\S]*?)(</w:tblPr>)',lambda m:m[1]+re.sub(r'<w:jc\b[^>]*?/>|<w:jc\b[^>]*>[\s\S]*?</w:jc>','',m[2])+m[3],table,count=1)+xml[b:],
          'rawJc':re.search(r'<w:jc\b[^>]*?/>|<w:jc\b[^>]*>[\s\S]*?</w:jc>',etree.tostring(root.find('w:tblPr',ns)).decode()).group(0) if root.find('w:tblPr/w:jc',ns) is not None else None,
          'alignment':anchor['tableAlignmentSource']['alignment'],
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
  assert.equal(anchor.tableAlignmentEditable, true)
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
  const select=async kind=>{
    await locate()
    if(kind==='node'){const first=cells().nth(0).locator('p').first();await first.evaluate(node=>node.scrollIntoView({block:'center'}));await first.hover();await page.locator('.doc-table-handle').click();await page.waitForFunction(()=>document.querySelector('table.ProseMirror-selectednode'))}
    if(kind==='rect'){const first=await cells().nth(0).boundingBox(),last=await table().locator('tr').first().locator('td,th').last().boundingBox();assert.ok(first&&last);await page.mouse.move(first.x+8,first.y+8);await page.mouse.down();await page.mouse.move(last.x+last.width-8,last.y+last.height-8,{steps:25});await page.mouse.up();await page.waitForFunction(()=>document.querySelectorAll('.selectedCell').length>1)}
    await page.locator('[data-tab-id="tableLayout"]').click()
  }
  const openAlignment=async()=>{await controls('table-properties').click();const margins=page.getByRole('dialog',{name:'单元格边距',exact:true});if(await margins.count())await margins.locator('[data-action="table-alignment"]').click();else await page.getByRole('dialog',{name:'表格属性选项',exact:true}).locator('[data-action="table-alignment"]').click();return page.getByRole('dialog',{name:'整表对齐',exact:true})}
  const geometry=async()=>table().evaluate(node=>{const a=node.getBoundingClientRect(),pm=node.closest('.ProseMirror'),b=pm.getBoundingClientRect(),css=getComputedStyle(pm),style=getComputedStyle(node);return{left:a.left-b.left-(parseFloat(css.paddingLeft)||0),right:b.right-(parseFloat(css.paddingRight)||0)-a.right,width:a.width,height:a.height,marginLeft:style.marginLeft,marginRight:style.marginRight,float:style.cssFloat,suppressed:node.getAttribute('data-tblp-suppressed')}})
  const set=async alignment=>{const dialog=await openAlignment();await dialog.locator('select').selectOption(alignment);await dialog.getByRole('button',{name:'确定',exact:true}).click();await dialog.waitFor({state:'detached'})}
  const canonicalDom=()=>table().evaluate(node=>{const clone=node.cloneNode(true);for(const el of [clone,...clone.querySelectorAll('[class]')])if(el.hasAttribute('class'))el.setAttribute('class',[...el.classList].sort().join(' '));for(const el of [clone,...clone.querySelectorAll('*')]){const attrs=[...el.attributes].map(attr=>[attr.name,attr.value]).sort(([a],[b])=>a.localeCompare(b));for(const attr of [...el.attributes])el.removeAttribute(attr.name);for(const [name,value]of attrs)el.setAttribute(name,value)}return clone.outerHTML})
  const results=[]
  const sources=[
    {revision:1,name:'ltr-legacy15-positive',options:{legacy:15,indent:333}},
    {revision:10,name:'ltr-legacy14-negative',options:{legacy:14,indent:-109}},
    {revision:20,name:'rtl-start',options:{rtl:true,jc:'start',legacy:15,indent:333}},
    {revision:30,name:'rtl-end-paired',options:{rtl:true,jc:'end',paired:true,legacy:14,indent:-109}},
    {revision:40,name:'pct-width',options:{pct:true,legacy:15,indent:333}},
    {revision:50,name:'merged',options:{merged:true,legacy:15,indent:-109}},
    {revision:60,name:'true-floating',options:{floating:true,legacy:15,indent:333}},
    {revision:70,name:'suppressed-floating',options:{suppressed:true,legacy:15,indent:333}},
  ]
  for(const {revision,name,options} of sources){
    if(revision<Number(process.env.DOCX_TABLE_ALIGNMENT_START_REVISION??1))continue
    let resumed=null
    if(process.env.DOCX_TABLE_ALIGNMENT_RESUME_DIRECTORY){
      try{resumed=JSON.parse(await readFile(join(process.env.DOCX_TABLE_ALIGNMENT_RESUME_DIRECTORY,`${name}-result.json`),'utf8'))}catch(error){if(error.code!=='ENOENT')throw error}
      if(resumed)for(const saved of resumed.caseResults){const bytes=await readFile(join(process.env.DOCX_TABLE_ALIGNMENT_RESUME_DIRECTORY,`revision-${saved.revision}.docx`));assert.equal(sha256(bytes),saved.downloadSha256,'续跑仅复用已核验保存文件');await writeFile(join(temporary,`revision-${saved.revision}.docx`),bytes);await writeFile(join(temporary,`downloaded-revision-${saved.revision}.docx`),bytes)}
      if(resumed?.complete){results.push(resumed);await writeFile(join(temporary,`${name}-result.json`),JSON.stringify(resumed,null,2));continue}
    }
    let before=source
    if(revision!==1){const path=join(temporary,`revision-${revision}.docx`);runPython({mode:'fixture',outputPath:path,...options});const bytes=await readFile(path);before=JSON.parse(runPython({mode:'inspect',path}));revisions.set(revision,bytes);inspections.set(revision,before)}
    const signed=before.model.blocks.find(b=>b.type==='table');assert.equal(signed.tableAlignmentEditable,true);assert.equal(signed.tableAlignmentSource.positioning,options.floating||options.suppressed?'floating':'inline')
    stage=`noop-${name}`;await open(revision);await locate();const initial=await canonicalDom(),sourceBox=await geometry();if(options.floating)assert.equal(sourceBox.float,'left','真实浮动分支');if(options.suppressed)assert.equal(sourceBox.float,'none','抑制浮动分支');let dialog=await openAlignment();assert.equal(await dialog.locator('select').inputValue(),signed.tableAlignmentSource.alignment??'left');if(options.floating||options.suppressed)assert.match(await dialog.locator('[role="note"]').textContent(),/浮动定位优先/);await dialog.getByRole('button',{name:'确定',exact:true}).click();assert.equal(await canonicalDom(),initial,'alias/noop不规范化');assert.deepEqual(await geometry(),sourceBox)
    const byAlignment=resumed?.byAlignment??{},caseResults=resumed?.caseResults??[]
    // 每次由明确修订继续，最终值反复仅一次operation；三种选择分别定位整表。
    let current=revision
    if(resumed){current=caseResults.at(-1).revision;const path=join(temporary,`revision-${current}.docx`);const bytes=await readFile(join(process.env.DOCX_TABLE_ALIGNMENT_RESUME_DIRECTORY,`revision-${current}.docx`));await writeFile(path,bytes);revisions.set(current,bytes);inspections.set(current,JSON.parse(runPython({mode:'inspect',path})));await open(current);await locate()}
    for(const [index,alignment] of (signed.tableAlignmentSource.alignment==='right'?['center','left','right']:['right','left','center']).entries()){
      if(caseResults.some(result=>result.alignment===alignment))continue
      stage=`set-${name}-${alignment}`;await select(['caret','node','rect'][index]);const undoBefore=await canonicalDom();await writeFile(join(temporary,'undo-expected.html'),undoBefore);await set(alignment);const modified=await canonicalDom();await page.keyboard.press('Control+z');await writeFile(join(temporary,'undo-actual.html'),await canonicalDom());assert.equal(await canonicalDom(),undoBefore);await page.keyboard.press('Control+Shift+z');assert.equal(await canonicalDom(),modified)
      // 同次会话往返一次再取最终值，协议只保最后alignment。
      await set(alignment==='center'?'left':'center');await set(alignment);const finalDom=await canonicalDom(),box=await geometry();byAlignment[alignment]=box
      if(options.floating||options.suppressed){assert.equal(box.left,sourceBox.left,'浮动定位优先，jc不改变当前位置');assert.equal(box.width,sourceBox.width)}
      await page.reload();await page.locator('.docx-source-home').waitFor({timeout:60000});await select(['caret','node','rect'][index]);assert.equal(await canonicalDom(),finalDom,'草稿精确恢复');assert.deepEqual(await geometry(),box)
      stage=`save-${name}-${alignment}`;await controls('save').click();await page.waitForFunction(next=>(document.querySelector('.save-state-label')?.textContent??'').includes(`已保存修订 ${next}`),current+1,{timeout:60000}).catch(error=>{throw Error(`${error};route=${routeError}`)});assert.equal(routeError,undefined);assert.deepEqual(savePayloads.at(-1).operations.map(op=>op.kind),['setTableAlignment']);assert.equal(savePayloads.at(-1).operations[0].alignment,alignment)
      const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('link',{name:'下载 Word',exact:true}).click()]);const bytes=await readFile(await download.path());assert.equal(sha256(bytes),sha256(revisions.get(current+1)));const path=join(temporary,`downloaded-revision-${current+1}.docx`);await writeFile(path,bytes);const actual=JSON.parse(runPython({mode:'inspect',path}));assert.equal(actual.details.alignment,alignment==='left'?null:alignment);if(alignment==='left')assert.equal(actual.details.rawJc,null)
      for(const key of ['cellXml','maskedXml','parts'])assert.deepEqual(actual.details[key],before.details[key],`仅直属jc变化:${key}`)
      current++;stage=`reopen-${name}-${alignment}`;await open(current);await locate();assert.deepEqual(await geometry(),box,'明确修订重开实际位置与live相同');await page.screenshot({path:join(temporary,`revision-${current}-${alignment}-reopened.png`),fullPage:true});await writeFile(join(temporary,`revision-${current}-${alignment}-reopened.html`),await page.content());caseResults.push({alignment,revision:current,box,downloadSha256:sha256(bytes)});await writeFile(join(temporary,`${name}-result.json`),JSON.stringify({name,options,sourceBox,byAlignment,caseResults},null,2))
    }
    if(!options.floating&&!options.suppressed){
      if(options.rtl){const displayIndent=options.indent-(options.legacy<15?before.details.firstCellLeftTwips:0);assert.ok(byAlignment.center.left<byAlignment.left.left,'RTL起始侧在右侧');assert.ok(byAlignment.center.left<byAlignment.right.left,'来源right仍为右侧');assert.ok(Math.abs((byAlignment.right.left-byAlignment.left.left)-displayIndent/15)<2,'RTL起始侧缩进从右侧量，legacy保留物理首格左边距hang与signed indent')}
      else assert.ok(byAlignment.left.left<byAlignment.center.left&&byAlignment.center.left<byAlignment.right.left,'LTR起始/居中/右实际位置严格递增')
    }
    const result={name,options,sourceBox,byAlignment,caseResults};results.push(result);await writeFile(join(temporary,`${name}-result.json`),JSON.stringify({...result,complete:true},null,2))
  }
  await Promise.all(checks)
  assert.ok([...chunks.keys()].some(file => /^lazy-docx-main-.*\.js$/.test(file)))
  assert.ok([...chunks.keys()].some(file => /^lazy-native-docx-engine-.*\.js$/.test(file)))
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ok:true,temporary,browserVersion:browser.version(),results,operations:savePayloads.map(p=>p.operations),onlyDirectTableJcChanged:true,actualPositionsAndReopenMatched:true,loadedChunks:Object.fromEntries(chunks),errors}))
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
