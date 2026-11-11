// 真实构建/Chromium/Node保存/openpyxl回读；HTTP身份与修订登记使用本地夹具。
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
import { createServer } from 'node:http'

const frontend = process.cwd(), repo = resolve('../../..'), evidence = process.env.WORKBOOK_SMOKE_EVIDENCE_DIR ?? '/tmp/xlsx-pivot-protection-built'
const port = Number(process.env.WORKBOOK_SMOKE_PORT ?? 4217), base = `http://127.0.0.1:${port}`
const media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', sha = bytes => createHash('sha256').update(bytes).digest('hex')
await mkdir(evidence, { recursive: true })
// 在参数校验和输入读取前移除旧回执，失败时不能沿用上一次成功结果。
if (process.argv.includes('--inspect-only')) await rm(join(evidence, 'inspection-receipt.json'), { force: true })
const python = payload => {
  const result = spawnSync(join(repo, '.venv/bin/python'), ['-c', `
import base64,json,sys
from io import BytesIO
from zipfile import ZipFile
from openpyxl import Workbook,load_workbook
from openpyxl.styles import PatternFill
from datetime import datetime
from xml.etree import ElementTree as ET
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='source':
 b=Workbook();s=b.active;s.title='Data'
 for row in [['Date','Region','Amount','Qty','Delivery'],[datetime(2026,1,1),'East',10,1,datetime(2026,1,5)],[datetime(2026,1,15),'West',20,2,datetime(2026,1,20)],[datetime(2026,2,1),'East',30,3,datetime(2026,2,5)]]:s.append(row)
 b.create_sheet('Pivot');s=b.create_sheet('Inputs');s['A1']='locked';s['B2']='initial';s['B3']='styled';s['B3'].fill=PatternFill('solid',fgColor='FFFFCC');s['Z100']='extent'
 o=BytesIO();b.save(o);print(base64.b64encode(o.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
elif p['mode']=='field-source':
 raw=base64.b64decode(p['bytes']);ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
 with ZipFile(BytesIO(raw)) as z:
  pivot=ET.fromstring(z.read('xl/pivotTables/pivotTable1.xml'))
  state=json.loads(next(n for n in pivot.iter() if n.tag.endswith('aioPivotState')).attrib['v'])
  output=pivot.find('m:location',ns).attrib['ref']
 relayout={k:v for k,v in state.items() if k not in ('name','location','worksheetSheetName','standardGroupings','groupingPersistence')};relayout['sourceTableName']='Sales'
 operations=[{'kind':'applyTableAdditions','additions':[{'worksheetSheetName':'Data','area':state['sourceArea'],'name':'Sales','columnNames':state['fieldNames']}]},{'kind':'applyPivotLayoutExpansions','updates':[{'tablePath':'xl/pivotTables/pivotTable1.xml','cachePath':'xl/pivotCache/pivotCacheDefinition1.xml','worksheetPath':'xl/worksheets/sheet2.xml','newOutputRef':output,'relayout':relayout}]}]
 print(base64.b64encode(patch_office('xlsx',raw,operations)).decode())
else:
 raw=base64.b64decode(p['bytes']);preservation=None
 if p.get('geometryOnly'):
  with ZipFile(BytesIO(base64.b64decode(p['baseline']))) as before,ZipFile(BytesIO(raw)) as after:
   prefixes=('xl/pivotTables/','xl/pivotCache/','xl/slicers/','xl/slicerCaches/','xl/timelines/','xl/timelineCaches/','xl/drawings/','xl/worksheets/_rels/')
   def retained(z):return {n for n in z.namelist() if n.startswith(prefixes) or n in ('xl/styles.xml','[Content_Types].xml','xl/_rels/workbook.xml.rels')}
   assert retained(before)==retained(after),'几何保存保留部件清单发生变化'
   drawing_path='xl/drawings/drawing1.xml';slicer_path='xl/slicers/slicer1.xml'
   unchanged=sorted(retained(before)-{drawing_path,slicer_path})
   for n in unchanged:assert before.read(n)==after.read(n),f'几何保存保留部件被修改: {n}'
   ns={'xdr':'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing'}
   drawings=[];slicers=[]
   for side,z in [('before',before),('after',after)]:
    drawing=ET.fromstring(z.read(drawing_path))
    anchors=[a for a in drawing if any(n.attrib.get('name')=='Slicer_P1_F1' for n in a.iter())]
    assert len(anchors)==1,'几何保存保留目标绘图身份异常'
    for tag in ('xdr:from','xdr:ext'):
     node=anchors[0].find(tag,ns);assert node is not None,'几何保存保留目标绘图结构异常';anchors[0].remove(node)
    drawings.append(ET.tostring(drawing))
    slicer=ET.fromstring(z.read(slicer_path));controls=list(slicer.iter('{urn:smart-reporting:pivot-control:v1}control'))
    assert len(controls)==1,'几何保存保留目标控件身份异常'
    metadata=json.loads(controls[0].attrib['value'])
    if side=='after':assert metadata['request']['anchor']=={'row':4,'column':12,'width':320,'height':180},'几何保存保留目标控件元数据与绘图不一致'
    metadata['request'].pop('anchor',None);controls[0].set('value',json.dumps(metadata,sort_keys=True))
    slicers.append(ET.tostring(slicer))
   assert drawings[0]==drawings[1],'几何保存保留绘图被修改: 兄弟锚点或目标外观/关联'
   assert slicers[0]==slicers[1],'几何保存保留目标切片器非几何属性被修改'
   preservation={'unchangedParts':unchanged,'siblingAnchorsPreserved':True,'targetAppearancePreserved':True,'targetMetadataConsistent':True}
 b=load_workbook(BytesIO(raw));s=b['Inputs'];assert s['A1'].value=='locked';assert s['B2'].value=='allowed';assert s.protection.sheet;assert s['B3'].fill.fgColor.rgb=='00FFFFCC'
 if p.get('expectedEntry'):assert s['B3'].value==p['expectedEntry']
 if p.get('baseline'):
  with ZipFile(BytesIO(base64.b64decode(p['baseline']))) as before,ZipFile(BytesIO(raw)) as after:assert before.read('xl/styles.xml')==after.read('xl/styles.xml')
 if p.get('expectedFreeze'):
  assert b['Pivot'].freeze_panes==p['expectedFreeze']
  assert b['Pivot'].sheet_view.rightToLeft is True
  if not p.get('geometry'):
   with ZipFile(BytesIO(base64.b64decode(p['baseline']))) as before,ZipFile(BytesIO(raw)) as after:assert before.read('xl/drawings/drawing1.xml')==after.read('xl/drawings/drawing1.xml')
 table=b['Pivot']._pivots[0];assert len(table.dataFields)==2;assert len(table.colFields)==2
 rows=list(b['Pivot'].iter_rows(values_only=True));numbers=[v for row in rows for v in row if isinstance(v,(int,float))];assert numbers and set(numbers)=={10,1},rows
 with ZipFile(BytesIO(raw)) as z:
  if p.get('fieldRenameOnly'):
   ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'};fields=['OrderDate','Area','Revenue','Qty','ShippedDate']
   standard=ET.fromstring(z.read('xl/pivotCache/pivotCacheDefinition1.xml'));pivot=ET.fromstring(z.read('xl/pivotTables/pivotTable1.xml'))
   state=json.loads(next(n for n in pivot.iter() if n.tag.endswith('aioPivotState')).attrib['v'])
   assert state['fieldNames']==[n.attrib['name'] for n in standard.find('m:cacheFields',ns)]==fields
   assert state['sourceTableName']==standard.find('m:cacheSource/m:worksheetSource',ns).attrib['name']=='Sales'
   assert [b['Data'].cell(1,i).value for i in range(1,6)]==fields
   assert b['Data']['G1'].value=='manual rename draft'
   assert [c.name for c in b['Data'].tables['Sales'].tableColumns]==fields
   for name,field in [('xl/slicerCaches/slicerCache1.xml','Area'),('xl/timelineCaches/timelineCache1.xml','OrderDate'),('xl/timelineCaches/timelineCache2.xml','ShippedDate')]:assert ET.fromstring(z.read(name)).attrib['sourceName']==field
   with ZipFile(BytesIO(base64.b64decode(p['baseline']))) as old:
    for name in old.namelist():
     if name.endswith('.rels') or name.startswith('xl/pivotCache/pivotCacheRecords') or name in ('xl/drawings/drawing1.xml','[Content_Types].xml','xl/workbook.xml'):assert old.read(name)==z.read(name),f'字段更名保存保留部件被修改: {name}'
  assert 'name="Entry"' in z.read('xl/worksheets/sheet3.xml').decode()
  xml=z.read('xl/pivotTables/pivotTable1.xml').decode();assert 'h="1"' in xml
  assert 'xl/slicers/slicer1.xml' in z.namelist()
  assert ('xl/timelines/timeline1.xml' in z.namelist()) != bool(p.get('deleted'))
  assert len(table.filters)==(1 if p.get('deleted') else 2)
  if p.get('deleted'):
   assert 'xl/timelineCaches/timelineCache1.xml' not in z.namelist()
   assert b'Timeline_P1_F0_Cache' not in z.read('xl/workbook.xml')
   assert b'name="Timeline_P1_F0"' not in z.read('xl/drawings/drawing1.xml')
  if p.get('geometry'):
   ns={'xdr':'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing'}
   drawing=ET.fromstring(z.read('xl/drawings/drawing1.xml'))
   anchors=[anchor for anchor in drawing if any(node.attrib.get('name')=='Slicer_P1_F1' for node in anchor.iter())]
   assert len(anchors)==1
   a=anchors[0];assert a.find('xdr:from/xdr:row',ns).text=='4';assert a.find('xdr:from/xdr:col',ns).text=='12'
   assert a.find('xdr:ext',ns).attrib=={'cx':'3048000','cy':'1714500'}
  for n in ([2] if p.get('deleted') else [1,2]):
   timeline=z.read(f'xl/timelineCaches/timelineCache{n}.xml').decode();assert '2026-01-01T00:00:00' in timeline and '2026-01-31T00:00:00' in timeline
   assert f'xl/timelines/timeline{n}.xml' in z.namelist()
 print(json.dumps({'protected':s.protection.sheet,'allowedValue':s['B2'].value,'pivot':table.name,'values':len(table.dataFields),'columnFields':len(table.colFields),'cells':[[c.value for c in row] for row in b['Pivot'].iter_rows()],**({'preservation':preservation} if preservation else {})},ensure_ascii=False))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(payload), encoding: 'utf8', maxBuffer: 16 * 1024 * 1024, timeout: 60000 })
  if (result.error || result.status !== 0) throw Error(result.error?.message || result.stderr || `python status ${result.status}`)
  return result.stdout.trim()
}
const viewportOnly = process.argv.includes('--viewport-only'), geometryOnly = process.argv.includes('--geometry-only'), fieldRenameOnly = process.argv.includes('--field-rename-only'), reuseSource = viewportOnly || geometryOnly || fieldRenameOnly
if (reuseSource && !process.env.WORKBOOK_SMOKE_SOURCE_XLSX) throw new Error('控件定向验收需要 WORKBOOK_SMOKE_SOURCE_XLSX 指向本脚本先前产出的 revision-2.xlsx')
let source = reuseSource ? await readFile(process.env.WORKBOOK_SMOKE_SOURCE_XLSX) : Buffer.from(python({ mode: 'source' }), 'base64')
if (fieldRenameOnly) source = Buffer.from(python({mode:'field-source',bytes:source.toString('base64')}),'base64')
const revisions = new Map([[1, source]])
let downloadServer, downloadUrl = '/fixture-download.xlsx'
if(fieldRenameOnly){
  // Chromium的download导航不经过page.route，下载夹具必须提供真实HTTP响应。
  downloadServer=createServer((_req,res)=>{const bytes=revisions.get(2);if(!bytes){res.writeHead(404);res.end();return}res.writeHead(200,{'Content-Type':media,'Content-Disposition':'attachment; filename=field-rename.xlsx'});res.end(bytes)})
  await new Promise(resolve=>downloadServer.listen(0,'127.0.0.1',resolve));downloadUrl='http://127.0.0.1:'+downloadServer.address().port+'/fixture-download.xlsx'
}
await writeFile(join(evidence, 'source.xlsx'), source)
// 复用已有浏览器产物单独检查真实文件，不重新启动 Chromium 或创建工作簿。
if (process.argv.includes('--inspect-only')) {
  assert(geometryOnly, '--inspect-only 需要同时指定 --geometry-only')
  assert(process.env.WORKBOOK_SMOKE_SAVED_XLSX, '--inspect-only 需要 WORKBOOK_SMOKE_SAVED_XLSX')
  const saved = await readFile(process.env.WORKBOOK_SMOKE_SAVED_XLSX)
  const independent = JSON.parse(python({ mode: 'inspect', bytes: saved.toString('base64'), baseline: source.toString('base64'), expectedFreeze: 'K3', geometry: true, geometryOnly: true }))
  const receipt = { ok: true, inspectionOnly: true, sourceSha256: sha(source), savedSha256: sha(saved), independent }
  await writeFile(join(evidence, 'inspection-receipt.json'), JSON.stringify(receipt, null, 2))
  console.log(JSON.stringify(receipt))
  process.exit(0)
}
const preview = spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: ['ignore', 'pipe', 'pipe'] })
let previewLog = ''
preview.stdout.on('data', data => { previewLog += data }); preview.stderr.on('data', data => { previewLog += data })
let browser, page, stage = 'start', routeError, saveCount = 0
const errors = []
const assetChecks = [], assets = new Map()
try {
  for (let i = 0; i < 100; i++) {
    if (preview.exitCode !== null) throw Error(`preview exited ${preview.exitCode}: ${previewLog}`)
    try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`, { signal: AbortSignal.timeout(1000) })).ok) break } catch {}
    if (i === 99) throw Error(`preview not ready: ${previewLog}`)
    await delay(250)
  }
  browser = await chromium.launch({ headless: true, args: ['--disable-features=LocalNetworkAccessChecks'], ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  const context = await browser.newContext({ viewport: { width: 1500, height: 1050 }, permissions: ['clipboard-read', 'clipboard-write'] })
  page = await context.newPage(); page.on('pageerror', error => errors.push(error.message))
  if(fieldRenameOnly){
    page.on('response',response=>{const path=new URL(response.url()).pathname;if(!path.startsWith('/reports/v1/editor/assets/')||!path.endsWith('.js'))return;assetChecks.push((async()=>{const bytes=await response.body();assert.equal(response.status(),200);assert.equal(sha(bytes),sha(await readFile(resolve('../static',path.slice('/reports/v1/editor/assets/'.length)))));assets.set(path,sha(bytes))})())})
  }
  if (process.argv.includes('--trace-cancel')) {
    page.on('console', message => { if (message.text().startsWith('CANCEL_TRACE')) console.log(message.text()) })
    await page.route('**/assets/lazy-workbook-main-*.js', async route => {
      const response = await route.fetch(), source = await response.text()
      const body = source.replace(/([A-Za-z_$][\w$]*)\.cancel=!0/g, '(console.warn("CANCEL_TRACE",$1.id,JSON.stringify($1.params)),$1.cancel=!0)')
      await route.fulfill({ response, body })
    })
  }
  await page.route('**/reports/v1/native/pivot-protection/**', async route => {
    const url = new URL(route.request().url()), match = url.pathname.match(/\/pivot-protection\/(\d+)(.*)$/)
    if (!match) return route.continue()
    const revision = Number(match[1]), bytes = revisions.get(revision), suffix = match[2]
    if (!bytes) return route.fulfill({ status: 404 })
    if (suffix === '/api/context') return route.fulfill({ json: { context: { documentId: 'pivot-protection', format: 'xlsx', revision, parentRevision: revision > 1 ? revision - 1 : null, scope: { database: 'f', companyId: 'f', userId: 'f', threadId: 'f' }, sourceFile: { path: 'test.xlsx', size: bytes.length, sha256: sha(bytes), mediaType: media }, origin: 'upload' }, csrfToken: 'fixture', capabilities: { xlsx_editor: true }, editingEnabled: true } })
    if (suffix === '/api/file') return route.fulfill({ body: bytes, contentType: media })
    if (suffix === '/api/save') {
      try {
        const payload = route.request().postDataJSON(), saved = Buffer.from(python({ mode: 'patch', bytes: bytes.toString('base64'), operations: payload.operations }), 'base64')
        revisions.set(revision + 1, saved); saveCount++
        await writeFile(join(evidence, 'saved.xlsx'), saved); await writeFile(join(evidence, 'operations.json'), JSON.stringify(payload.operations, null, 2))
        await writeFile(join(evidence, `revision-${revision + 1}.xlsx`), saved); await writeFile(join(evidence, `operations-${revision}.json`), JSON.stringify(payload.operations, null, 2))
        return route.fulfill({ json: { documentId: 'pivot-protection', revision: revision + 1, parentRevision: revision, revisionRegistered: true, artifacts: { xlsx: { downloadUrl, size: saved.length, sha256: sha(saved) } }, editor: { openUrl: `/reports/v1/native/pivot-protection/${revision + 1}` }, validation: { ok: true, issues: [] } } })
      } catch (error) { routeError = String(error); return route.fulfill({ status: 500, json: { detail: routeError } }) }
    }
    if (!suffix) return route.fulfill({ response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }) })
    return route.continue()
  })
  const ready = () => page.waitForFunction(() => document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false', null, { timeout: 60000 })
  const command = async (tab, id) => { await page.locator(`[data-ribbon-tab="${tab}"]`).click(); await page.locator(`[data-ribbon-command="${id}"]`).click() }
  const goto = async ref => { await command('Home', 'goto-open'); await page.locator('[data-goto-reference]').fill(ref); await page.locator('.workbook-ribbon-goto-dialog [type="submit"]').click(); await page.locator('.workbook-ribbon-goto-dialog').waitFor({ state: 'hidden' }) }
  const draft = () => page.evaluate(() => Object.keys(localStorage).filter(key => key.startsWith('native-editor-draft:')).flatMap(key => JSON.parse(localStorage.getItem(key)).operations ?? []))
  const applied = async kind => page.waitForFunction(kind => Object.keys(localStorage).some(key => key.startsWith('native-editor-draft:') && JSON.parse(localStorage.getItem(key)).operations?.some(op => op.kind === kind)), kind)
  if (reuseSource) {
    stage = fieldRenameOnly ? 'field-rename-controls' : geometryOnly ? 'geometry-controls' : 'viewport-controls'
    const run = fieldRenameOnly ? (await import('./workbook-pivot-controls-field-rename.mjs')).runPivotControlFieldRenameSmoke : geometryOnly ? (await import('./workbook-pivot-controls-geometry.mjs')).runPivotControlGeometrySmoke : (await import('./workbook-pivot-controls-viewport.mjs')).runPivotControlViewportSmoke
    const viewport = await run({ page, base, ready, command, goto, draft, evidence })
    assert.equal(routeError, undefined); assert.equal(saveCount, 1); assert.deepEqual(errors, [])
    const independent = JSON.parse(python({ mode: 'inspect', bytes: revisions.get(2).toString('base64'), baseline: source.toString('base64'), ...(fieldRenameOnly ? {fieldRenameOnly:true} : {expectedFreeze: geometryOnly ? 'K3' : 'B3'}), ...(geometryOnly ? { geometry: true, geometryOnly: true } : {}) }))
    await Promise.all(assetChecks)
    if(fieldRenameOnly){assert.equal(sha(await readFile(join(evidence,'downloaded.xlsx'))),sha(revisions.get(2)));await writeFile(join(evidence,'assets.json'),JSON.stringify(Object.fromEntries(assets),null,2))}
    const receipt = { ok: true, browserVersion: browser.version(), manifestSha256: sha(await readFile(resolve('../static/.vite/manifest.json'))), sourceSha256: sha(source), savedSha256: sha(revisions.get(2)), saveCount, viewport, independent, errors, ...(fieldRenameOnly?{fieldRenameOnly,resourceCount:assets.size}:{}) }
    await writeFile(join(evidence, 'receipt.json'), JSON.stringify(receipt, null, 2)); console.log(JSON.stringify(receipt))
  } else {
  stage = 'open'; await page.goto(`${base}/reports/v1/native/pivot-protection/1`); await ready()
  stage = 'ranges'; await goto('Inputs!B2:B3'); await command('Review', 'allow-edit-ranges-open')
  const ranges = page.locator('[role="dialog"][aria-label="允许用户编辑区域"]')
  await ranges.locator('[data-action="add"]').click(); await ranges.getByLabel('区域名称 1', { exact: true }).fill('Entry')
  await ranges.locator('[type="submit"]').click(); await ranges.waitFor({ state: 'hidden' }); await applied('setSheetEditableRanges')
  stage = 'protect'; await goto('Inputs!B2'); await command('Review', 'sheet-protect'); await goto('Inputs!B2'); await page.keyboard.type('allowed'); await page.keyboard.press('Enter'); await applied('applyCellEdits')
  stage = 'pivot'; await goto('Data!A1:E4'); await command('Insert', 'pivot-open')
  const pivot = page.locator('[role="dialog"][aria-label="数据透视表"]')
  for (const [axis, name] of [['rows', 'Date'], ['rows', 'Delivery'], ['columns', 'Region'], ['values', 'Amount'], ['values', 'Qty']]) { await pivot.locator(`[data-field="${axis}"]`).selectOption(name); await pivot.locator(`[data-add="${axis}"]`).click() }
  await pivot.getByLabel('透视表名称', { exact: true }).fill('Advanced'); await pivot.getByLabel('目标工作表', { exact: true }).selectOption('Pivot'); await pivot.getByLabel('目标起点', { exact: true }).fill('A1')
  await pivot.locator('[type="submit"]').click(); await pivot.waitFor({ state: 'hidden' }); await applied('addPivot')
  stage = 'slicer'; await goto('Pivot!A1'); await command('Insert', 'slicer-open')
  // 事务期间父容器 inert，getByRole会暂时排除子对话框；用稳定DOM身份等待真正关闭。
  const filter = page.locator('[role="dialog"][aria-label="透视表筛选"]')
  await filter.getByLabel('筛选字段', { exact: true }).selectOption('Region'); await filter.locator('[data-members] input[value="West"]').uncheck(); await filter.locator('[data-native-control]').check(); await filter.locator('[type="submit"]').click(); await filter.waitFor({ state: 'hidden' }); await applied('applyPivotLayoutExpansions')
  stage = 'timeline'; await goto('Pivot!A1'); await command('Insert', 'timeline-open'); await filter.getByLabel('筛选字段', { exact: true }).selectOption('Date')
  await filter.getByLabel('开始日期', { exact: true }).fill('2026-01-01'); await filter.getByLabel('结束日期', { exact: true }).fill('2026-01-31'); await filter.locator('[data-native-control]').check(); await filter.getByLabel('控件左上角单元格', { exact: true }).fill('H15'); await page.screenshot({ path: join(evidence, 'timeline.png'), fullPage: true })
  await filter.locator('[type="submit"]').click(); await filter.waitFor({ state: 'hidden' })
  stage = 'second-timeline'; await goto('Pivot!A1'); await command('Insert', 'timeline-open'); await filter.getByLabel('筛选字段', { exact: true }).selectOption('Delivery')
  await filter.getByLabel('开始日期', { exact: true }).fill('2026-01-01'); await filter.getByLabel('结束日期', { exact: true }).fill('2026-01-31'); await filter.locator('[data-native-control]').check(); await filter.getByLabel('控件左上角单元格', { exact: true }).fill('H24'); await filter.locator('[type="submit"]').click(); await filter.waitFor({ state: 'hidden' })
  stage = 'canvas-controls'; await goto('Pivot!A1')
  const slicer = page.locator('[data-pivot-control="Slicer_P1_F1"]'), dateControl = page.locator('[data-pivot-control="Timeline_P1_F0"]')
  await slicer.waitFor({ state: 'visible' }); assert.equal(await page.locator('[data-pivot-control]').count(), 3)
  await command('Review', 'sheet-protect'); await goto('Data!A1'); await goto('Pivot!A1')
  await page.waitForFunction(() => document.querySelector('[data-pivot-control="Slicer_P1_F1"] fieldset')?.disabled === true)
  await command('Review', 'sheet-protect')
  await page.waitForFunction(() => document.querySelector('[data-pivot-control="Slicer_P1_F1"] fieldset')?.disabled === false)
  const normalBounds = await slicer.boundingBox()
  await command('View', 'zoom-in')
  await page.waitForFunction(width => document.querySelector('[data-pivot-control="Slicer_P1_F1"]')?.getBoundingClientRect().width > width * 1.02, normalBounds.width)
  const zoomBounds = await slicer.boundingBox(); assert(zoomBounds.width > normalBounds.width)
  const canvasApply = async control => {
    const count = (await draft()).filter(op => op.kind === 'upsertPivotControl').length
    await control.locator('[type="submit"]').click()
    await page.waitForFunction(count => Object.keys(localStorage).filter(key => key.startsWith('native-editor-draft:')).some(key => (JSON.parse(localStorage.getItem(key)).operations ?? []).filter(op => op.kind === 'upsertPivotControl').length > count), count)
    await page.waitForFunction(() => !document.querySelector('#report-editor')?.inert)
    await slicer.waitFor({ state: 'visible' })
  }
  await slicer.getByLabel('West', { exact: true }).check(); await canvasApply(slicer)
  assert(await slicer.getByLabel('West', { exact: true }).isChecked())
  await slicer.getByLabel('West', { exact: true }).uncheck(); await canvasApply(slicer)
  await dateControl.getByLabel('结束日期', { exact: true }).fill('2026-01-10'); await canvasApply(dateControl)
  assert.equal(await dateControl.getByLabel('结束日期', { exact: true }).inputValue(), '2026-01-10')
  await dateControl.getByLabel('结束日期', { exact: true }).fill('2026-01-31'); await canvasApply(dateControl)
  await command('View', 'zoom-reset')
  const scrollStart = await slicer.boundingBox()
  await page.mouse.move(350, 700); await page.mouse.wheel(0, 400)
  await page.waitForFunction(top => {
    const element = document.querySelector('[data-pivot-control="Slicer_P1_F1"]')
    return !element || element.getBoundingClientRect().top < top - 10 || getComputedStyle(element).display === 'none'
  }, scrollStart.y)
  await page.mouse.wheel(0, -600)
  await page.waitForFunction(top => document.querySelector('[data-pivot-control="Slicer_P1_F1"]')?.getBoundingClientRect().top >= top - 2, scrollStart.y)
  await page.screenshot({ path: join(evidence, 'canvas-controls.png'), fullPage: true })
  await goto('Data!A1'); assert.equal(await page.locator('[data-pivot-control]').count(), 0)
  await goto('Pivot!A1'); await slicer.waitFor({ state: 'visible' }); assert.equal(await page.locator('[data-pivot-control]').count(), 3)
  stage = 'refresh-two-timelines'; await command('Data', 'refresh-all'); await page.waitForFunction(() => document.querySelector('.workbook-feedback')?.textContent?.includes('已刷新 1 个透视表'))
  const beforeHistory = await draft(); await command('File', 'undo'); await page.waitForFunction(() => !document.querySelector('#report-editor')?.inert); await command('File', 'redo'); await page.waitForFunction(() => !document.querySelector('#report-editor')?.inert); assert.deepEqual(await draft(), beforeHistory)
  stage = 'save'; await page.locator('[data-action="save"]').click(); await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent?.includes('已保存修订 2'), null, { timeout: 60000 }); assert.equal(routeError, undefined); assert.equal(saveCount, 1)
  const saved = revisions.get(2), independent = JSON.parse(python({ mode: 'inspect', bytes: saved.toString('base64') }))
  stage = 'reopen'; await page.goto(`${base}/reports/v1/native/pivot-protection/2`); await ready(); await goto('Inputs!B3'); await page.keyboard.type('reopened'); await page.keyboard.press('Enter')
  await page.waitForFunction(() => Object.keys(localStorage).filter(key => key.startsWith('native-editor-draft:')).some(key => {
    const draft = JSON.parse(localStorage.getItem(key)); return draft.identity?.revision === 2 && draft.operations?.some(op => op.kind === 'applyCellEdits' && op.edits.some(edit => edit.sheetName === 'Inputs' && edit.row === 2 && edit.column === 1 && edit.cell.value === 'reopened'))
  }))
  await page.screenshot({ path: join(evidence, 'reopened.png'), fullPage: true })
  stage = 'canvas-after-unrelated-edit'; await goto('Pivot!A1'); await slicer.waitFor({ state: 'visible' }); await canvasApply(slicer)
  stage = 'delete-control'; await goto('Pivot!A1'); await command('Insert', 'timeline-open'); await filter.getByLabel('筛选字段', { exact: true }).selectOption('Date'); await filter.locator('[data-action="delete-control"]').click(); await filter.waitFor({ state: 'hidden' }); await applied('removePivotControl')
  const afterDelete = await draft(); await command('File', 'undo'); await page.waitForFunction(() => !document.querySelector('#report-editor')?.inert); assert(!(await draft()).some(op => op.kind === 'removePivotControl')); await command('File', 'redo'); await page.waitForFunction(() => !document.querySelector('#report-editor')?.inert); assert.deepEqual(await draft(), afterDelete)
  stage = 'control-geometry'; await command('Insert', 'slicer-open'); await filter.getByLabel('筛选字段', { exact: true }).selectOption('Region')
  await filter.getByLabel('控件左上角单元格', { exact: true }).fill('M5'); await filter.getByLabel('控件宽度（像素）', { exact: true }).fill('320'); await filter.getByLabel('控件高度（像素）', { exact: true }).fill('180'); await filter.locator('[type="submit"]').click(); await filter.waitFor({ state: 'hidden' })
  const afterGeometry = await draft(); await command('File', 'undo'); await page.waitForFunction(() => !document.querySelector('#report-editor')?.inert); await command('File', 'redo'); await page.waitForFunction(() => !document.querySelector('#report-editor')?.inert); assert.deepEqual(await draft(), afterGeometry)
  await command('Insert', 'slicer-open'); await filter.getByLabel('筛选字段', { exact: true }).selectOption('Region'); assert.equal(await filter.getByLabel('控件左上角单元格', { exact: true }).inputValue(), 'M5'); assert.equal(await filter.getByLabel('控件宽度（像素）', { exact: true }).inputValue(), '320'); assert.equal(await filter.getByLabel('控件高度（像素）', { exact: true }).inputValue(), '180'); await page.screenshot({ path: join(evidence, 'control-position.png'), fullPage: true }); await filter.locator('[data-action="cancel"]').click()
  stage = 'styled-save'; await page.locator('[data-action="save"]').click(); await page.waitForFunction(() => document.querySelector('.save-state-label')?.textContent?.includes('已保存修订 3'), null, { timeout: 60000 }); assert.equal(routeError, undefined); assert.equal(saveCount, 2)
  const finalSaved = revisions.get(3), finalIndependent = JSON.parse(python({ mode: 'inspect', bytes: finalSaved.toString('base64'), baseline: saved.toString('base64'), expectedEntry: 'reopened', deleted: true, geometry: true }))
  assert.deepEqual(errors, [])
  const receipt = { ok: true, browserVersion: browser.version(), manifestSha256: sha(await readFile(resolve('../static/.vite/manifest.json'))), sourceSha256: sha(source), revision2Sha256: sha(saved), savedSha256: sha(finalSaved), saveCount, independent, finalIndependent, canvas: { controlCount: 3, normalWidth: normalBounds.width, zoomWidth: zoomBounds.width, memberFilter: true, dateInterval: true, scroll: true, sheetSwitch: true, protectionUnlock: true, unrelatedEditPreserved: true }, operations: beforeHistory, errors }
  await writeFile(join(evidence, 'receipt.json'), JSON.stringify(receipt, null, 2)); console.log(JSON.stringify({ ok: true, evidence, saveCount, independent }))
  }
} catch (error) {
  if (page) { await page.screenshot({ path: join(evidence, 'failure.png'), fullPage: true }).catch(() => {}); await writeFile(join(evidence, 'failure.html'), await page.content()).catch(() => {}) }
  console.error(JSON.stringify({ stage, evidence, routeError })); throw error
} finally { await browser?.close(); preview.kill(); if(downloadServer)await new Promise(resolve=>downloadServer.close(resolve)) }
