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
const port = Number(process.env.DOCX_CELL_MARGIN_OVERRIDES_SMOKE_PORT ?? 4242)
const baseUrl = `http://127.0.0.1:${port}`
const documentId = 'fixture-cell-margin-overrides-built'
const mediaType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex')
const temporary = await mkdtemp(join(tmpdir(), 'docx-cell-margin-overrides-built-'))
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
        rows+='<w:tr>'+''.join(cell(chr(65+c)+'3中文',c) for c in range(3))+'</w:tr>'
    else: rows=''.join('<w:tr>'+''.join(cell(chr(65+c)+str(r+1)+'中文',c) for c in range(3))+'</w:tr>' for r in range(3))
    table='<w:tbl><w:tblPr><w:tblW w:w="7203" w:type="dxa"/><w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>'+''.join('<w:gridCol w:w="'+str(w)+'"/>' for w in widths)+'</w:tblGrid>'+rows+'</w:tbl>'
    table=table.replace('<w:tblPr>','<w:tblPr><w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="108" w:type="dxa"/><w:bottom w:w="7" w:type="dxa"/><w:right w:w="109" w:type="dxa"/></w:tblCellMar>')
    table=table.replace('<w:tcPr>','<w:tcPr><w:tcMar><w:left w:w="33" w:type="dxa"/><w:top w:w="0" w:type="dxa"/></w:tcMar>',1)
    # 第二个owner保持不同显式覆盖，保证普通/合并来源都能真实选择混合矩形。
    needle='</w:tc><w:tc><w:tcPr>'
    table=table.replace(needle,'</w:tc><w:tc><w:tcPr><w:tcMar><w:left w:w="55" w:type="dxa"/></w:tcMar>',1)
    if p.get('merged'):
        # owner无tcMar而hidden continue有覆盖，初始reset必须不能被当作no-op。
        table=re.sub(r'<w:tcMar\b[^>]*>[\s\S]*?</w:tcMar>','',table,count=1)
        table=table.replace('<w:vMerge/>','<w:vMerge/><w:tcMar><w:left w:w="71" w:type="dxa"/><w:top w:w="0" w:type="dxa"/></w:tcMar>')
    if p.get('inherited'):
        table=table.replace('<w:tblPr>','<w:tblPr><w:tblStyle w:val="OverrideInheritance"/><w:tblLook w:firstRow="1" w:noHBand="1" w:noVBand="1"/>')
        table=table.replace('<w:tr>','<w:tr><w:tblPrEx><w:tblCellMar><w:top w:w="23" w:type="dxa"/><w:left w:w="41" w:type="dxa"/><w:bottom w:w="17" w:type="dxa"/></w:tblCellMar></w:tblPrEx>',1)
    if p.get('rtl'): table=table.replace('<w:tblPr>','<w:tblPr><w:bidiVisual/>')
    if p.get('vertical'): table=table.replace('<w:shd','<w:textDirection w:val="tbRl"/><w:shd',1)
    with ZipFile(BytesIO(buf.getvalue())) as zin, ZipFile(p['outputPath'],'w') as zout:
        for name in zin.namelist():
            data=zin.read(name)
            if name=='word/document.xml':
                xml=data.decode();xml=re.sub(r'(<w:body>)[\s\S]*?(<w:sectPr\b)',lambda m:m[1]+para('外部前')+table+para('外部后')+m[2],xml,count=1);xml=re.sub(r'<w:pgSz[^>]*/>','<w:pgSz w:w="12000" w:h="16800"/>',xml);xml=re.sub(r'<w:pgMar[^>]*/>','<w:pgMar w:top="1000" w:right="1500" w:bottom="1000" w:left="1500" w:header="500" w:footer="500" w:gutter="0"/>',xml);data=xml.encode()
            if name=='word/styles.xml' and p.get('inherited'):
                style='<w:style w:type="table" w:styleId="OverrideInheritance"><w:name w:val="Override Inheritance"/><w:tblStylePr w:type="firstRow"><w:tcPr><w:tcMar><w:right w:w="151" w:type="dxa"/></w:tcMar></w:tcPr></w:tblStylePr></w:style>'
                data=data.decode().replace('</w:styles>',style+'</w:styles>').encode()
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
          'maskedXml':re.sub(r'<w:tcMar\b[^>]*(?:/>|>[\s\S]*?</w:tcMar>)','',xml),
          'cellNoMargins':[re.sub(r'<w:tcMar\b[^>]*(?:/>|>[\s\S]*?</w:tcMar>)','',etree.tostring(c).decode()) for c in root.findall('w:tr/w:tc',ns)],
          'paragraphXml':[etree.tostring(c).decode() for c in root.findall('.//w:p',ns)],
          'parts':{name:sha256(package.read(name)).hexdigest() for name in package.namelist() if name!='word/document.xml' and not name.endswith('/')}}
    print(json.dumps({'model':model,'details':details},ensure_ascii=False))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr || `python exited ${result.status}`)
  return result.stdout.trim()
}
let server, browser, page, stage = 'setup'
const downloadServer=createServer((request,response)=>{const match=/^\/revision-(\d+)\.docx$/.exec(request.url??'');const bytes=match&&downloadRevisions.get(Number(match[1]));if(!bytes){response.writeHead(404);response.end();return}response.writeHead(200,{'Content-Type':mediaType,'Content-Disposition':'attachment; filename=cell-margin-overrides.docx','Content-Length':bytes.length});response.end(bytes)})
const downloadRevisions=new Map()
await new Promise(resolve=>downloadServer.listen(0,'127.0.0.1',resolve))
const downloadBase=`http://127.0.0.1:${downloadServer.address().port}`
try {
  runPython({ mode: 'fixture', outputPath: sourcePath })
  const sourceBytes = await readFile(sourcePath)
  const source = JSON.parse(runPython({ mode: 'inspect', path: sourcePath }))
  const anchor = source.model.blocks.find(block => block.type === 'table')
  assert.equal(anchor.tableCellMarginOverridesEditable, true)
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
  const openMargins=async()=>{assert.equal(await controls('table-properties').isEnabled(),true);await controls('table-properties').click();return page.getByRole('dialog',{name:'单元格边距',exact:true})}
  const geometry=async()=>cells().evaluateAll(list=>list.map(cell=>{const p=cell.querySelector('p'),a=cell.getBoundingClientRect(),b=p.getBoundingClientRect();const style=getComputedStyle(cell);return{left:b.left-a.left,right:a.right-b.right,top:b.top-a.top,width:a.width,height:a.height,paddingLeft:style.paddingLeft,paddingRight:style.paddingRight}}))
  const selectFirst = async () => { await locate(); await page.waitForFunction(()=>document.querySelectorAll('.selectedCell').length===0) }
  const selectMixed = async merged => {
    await locate()
    const first=await cells().nth(0).boundingBox(),last=await cells().nth(merged?1:2).boundingBox()
    assert.ok(first&&last)
    await page.mouse.move(first.x+8,first.y+8);await page.mouse.down();await page.mouse.move(last.x+last.width-8,last.y+last.height-8,{steps:25});await page.mouse.up()
    await page.locator('[data-tab-id="tableLayout"]').click()
    await page.waitForFunction(()=>document.querySelectorAll('.selectedCell').length===3)
  }
  const set = async value => {
    const dialog=await openMargins()
    for(const [side,twips] of Object.entries(value))await dialog.locator(`[data-margin="${side}"]`).fill(`${twips}twip`)
    await dialog.getByRole('button',{name:'确定',exact:true}).click()
    await dialog.waitFor({state:'detached'})
  }
  const reset = async () => {const dialog=await openMargins();await dialog.getByRole('button',{name:'恢复继承',exact:true}).click();await dialog.waitFor({state:'detached'})}
  const marginA={top:0,right:176,bottom:96,left:130},marginB={top:20,right:180,bottom:100,left:145}
  const results=[]
  for(const [revision,options] of [[1,{}],[10,{inherited:true}],[20,{merged:true}],[30,{rtl:true,vertical:true}]]){
    if(revision<Number(process.env.DOCX_CELL_MARGIN_OVERRIDES_START_REVISION??1))continue
    let before=source
    if(revision!==1){const path=join(temporary,`revision-${revision}.docx`);runPython({mode:'fixture',outputPath:path,...options});const bytes=await readFile(path);before=JSON.parse(runPython({mode:'inspect',path}));revisions.set(revision,bytes);inspections.set(revision,before)}
    const signed=before.model.blocks.find(b=>b.type==='table'),snapshots=signed.tableCellMarginOverridesSource.cells,owner=snapshots[0]
    assert.equal(signed.tableCellMarginOverridesEditable,true)
    if(options.inherited){assert.equal(owner.resetEffective.left,41);assert.equal(owner.resetEffective.top,23);assert.equal(owner.resetEffective.bottom,17);assert.equal(owner.resetEffective.right,151)}
    if(options.merged){assert.equal(owner.rawPresent,false);assert.equal(owner.hasPhysicalOverrides,true)}
    stage=`noop-${revision}`;await open(revision);await locate();const initial=await dom(),boxesBefore=await geometry();let dialog=await openMargins()
    const initialRight=(owner.effective?.right??before.details.margins.right??108)/20
    assert.equal(await dialog.locator('[data-margin="right"]').inputValue(),String(initialRight));await dialog.getByRole('button',{name:'确定',exact:true}).click();assert.equal(await dom(),initial)
    await selectMixed(options.merged);const mixedInitial=await dom();dialog=await openMargins();assert.equal(await dialog.locator('[data-margin="left"]').inputValue(),'');assert.equal(await dialog.locator('[data-margin="left"]').getAttribute('placeholder'),'多个值');await dialog.getByRole('button',{name:'确定',exact:true}).click();assert.equal(await dom(),mixedInitial,'混合矩形不填不dirty')
    const expectedSteps=[]
    if(options.merged){stage=`hidden-only-reset-${revision}`;await selectFirst();await reset();expectedSteps.push({top:0,left:0,bottom:2,right:2,margins:null})}
    stage=`set-rect-${revision}`;await selectMixed(options.merged);await set(marginA);expectedSteps.push({top:0,left:0,bottom:options.merged?2:1,right:3,margins:marginA});const boxesSet=await geometry();assert.notDeepEqual(boxesSet,boxesBefore,'默认值未改时所选格内容盒实际变化');assert.ok(Math.abs(Number.parseFloat(boxesSet[0].paddingLeft)-marginA.left/15)<0.02)
    stage=`reset-owner-${revision}`;await selectFirst();await reset();expectedSteps.push({top:owner.top,left:owner.left,bottom:owner.bottom,right:owner.right,margins:null});const boxesReset=await geometry()
    assert.ok(Math.abs(Number.parseFloat(boxesReset[0].paddingLeft)-(owner.resetEffective?.left??before.details.margins.left??108)/15)<0.02,'恢复行/样式继承的真实padding')
    await set(marginB);expectedSteps.push({top:owner.top,left:owner.left,bottom:owner.bottom,right:owner.right,margins:marginB});const beforeReset=await dom();await reset();expectedSteps.push({top:owner.top,left:owner.left,bottom:owner.bottom,right:owner.right,margins:null});const modified=await dom();assert.notEqual(modified,beforeReset)
    await page.keyboard.press('Control+z');assert.equal(await dom(),beforeReset);await page.keyboard.press('Control+Shift+z');assert.equal(await dom(),modified)
    const boxesAfter=await geometry();assert.deepEqual(boxesAfter,boxesReset,'连续set/reset恢复同一实际继承布局')
    // 再次reset没有任何物理覆盖时不能追加步骤；保存时以完整steps断言无操作。
    await reset();assert.equal(await dom(),modified)
    await page.reload();await page.locator('.docx-source-home').waitFor({timeout:60000});assert.equal(await dom(),modified,'边距覆盖草稿精确恢复')
    stage=`save-${revision}`;await controls('save').click();await page.waitForFunction(next=>(document.querySelector('.save-state-label')?.textContent??'').includes(`已保存修订 ${next}`),revision+1,{timeout:60000}).catch(error=>{throw Error(`${error};route=${routeError}`)})
    assert.equal(routeError,undefined);assert.deepEqual(savePayloads.at(-1).operations.map(op=>op.kind),['setTableCellMarginOverrides']);assert.deepEqual(savePayloads.at(-1).operations[0].steps,expectedSteps)
    const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('link',{name:'下载 Word',exact:true}).click()]);const bytes=await readFile(await download.path());assert.equal(sha256(bytes),sha256(revisions.get(revision+1)))
    const path=join(temporary,`downloaded-revision-${revision+1}.docx`);await writeFile(path,bytes);const actual=JSON.parse(runPython({mode:'inspect',path})),actualCells=actual.model.blocks.find(b=>b.type==='table').tableCellMarginOverridesSource.cells
    assert.deepEqual(actual.details.margins,before.details.margins,'整表默认完全不动')
    for(const key of ['cellNoMargins','maskedXml','paragraphXml','parts'])assert.deepEqual(actual.details[key],before.details[key],`tcMar之外所有原字节保留:${key}`)
    assert.deepEqual(actual.details.cellXml.slice(-3),before.details.cellXml.slice(-3),'非目标末行cell全文保持')
    for(const [index,cell] of snapshots.entries()){
      const last=[...expectedSteps].reverse().find(step=>step.top<cell.bottom&&step.bottom>cell.top&&step.left<cell.right&&step.right>cell.left)
      assert.deepEqual(actualCells[index].effective,last?(last.margins??cell.resetEffective):cell.effective,'重开有效值等于签发继承回放')
      assert.equal(actualCells[index].rawPresent,last?last.margins!==null:cell.rawPresent)
      assert.equal(actualCells[index].hasPhysicalOverrides,last?last.margins!==null:cell.hasPhysicalOverrides)
    }
    stage=`reopen-${revision}`;await open(revision+1);await locate();assert.deepEqual(await geometry(),boxesAfter,'保存重开布局保持')
    await page.screenshot({path:join(temporary,`revision-${revision+1}-overrides-reopened.png`),fullPage:true});await writeFile(join(temporary,`revision-${revision+1}-overrides-reopened.html`),await page.content())
    results.push({revision,...options,boxesBefore,boxesSet,boxesReset,boxesAfter,expectedSteps,sourceSnapshots:snapshots,reopenedSnapshots:actualCells})
  }
  await Promise.all(checks)
  assert.ok([...chunks.keys()].some(file => /^lazy-docx-main-.*\.js$/.test(file)))
  assert.ok([...chunks.keys()].some(file => /^lazy-native-docx-engine-.*\.js$/.test(file)))
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ok:true,temporary,browserVersion:browser.version(),results,operations:savePayloads.map(p=>p.operations),onlySelectedPhysicalMarginsChanged:true,tableDefaultsPreserved:true,loadedChunks:Object.fromEntries(chunks),errors}))
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
