import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.PDF_SHAPE_CANVAS_SMOKE_PORT ?? 4219), base = `http://127.0.0.1:${port}`, sha = bytes => createHash('sha256').update(bytes).digest('hex')
function python(input) {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import json,sys,base64,math
from io import BytesIO
from pypdf import PdfReader
from pypdf.generic import ContentStream
from hashlib import sha256
from PIL import Image
from smart_reporting.reporting.tests.test_pdf_page_size import size_fixture
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf,patch_pdf_with_receipt
p=json.load(sys.stdin)
if p['mode']=='create':
 b=size_fixture();image=Image.new('RGB',(4,4),(40,100,210));png=BytesIO();image.save(png,format='PNG');print(json.dumps({'bytes':base64.b64encode(b).decode(),'model':inspect_pdf(b),'image':base64.b64encode(png.getvalue()).decode(),'imagePixelsSha256':sha256(image.tobytes()).hexdigest()}))
elif p['mode']=='inspect':print(json.dumps(inspect_pdf(base64.b64decode(p['bytes']))))
elif p['mode']=='patch':
 b=base64.b64decode(p['bytes']);r=patch_pdf_with_receipt(b,p['operations']);r['bytes']=base64.b64encode(r.pop('content')).decode();r['model']=inspect_pdf(base64.b64decode(r['bytes']));print(json.dumps(r))
elif p['mode']=='verify':
 a=PdfReader(BytesIO(base64.b64decode(p['source'])));b=PdfReader(BytesIO(base64.b64decode(p['bytes'])))
 assert len(a.pages)==len(b.pages)==3
 assert [page.extract_text() for page in b.pages]==[page.extract_text() for page in reversed(a.pages)]
 fields=lambda r:{name:{key:str(f.get(key)) for key in ['/FT','/T','/V','/DV','/Ff','/Opt']} for name,f in (r.get_fields() or {}).items()}
 assert fields(a)==fields(b)
 source=a.pages[0];saved=b.pages[2];assert saved.get('/Rotate',0)==90
 def ap_hash(annot):
  ap=annot.get('/AP');n=ap.get('/N').get_object() if ap else None
  if n is None:return None
  if hasattr(n,'get_data'):return sha256(n.get_data()).hexdigest()
  return {str(k):sha256(v.get_object().get_data()).hexdigest() for k,v in n.items()}
 def old_identity(raw):
  d=raw.get_object();return {**{k:str(d.get(k)) for k in ['/Subtype','/Rect','/Contents','/T','/C','/F']},'AP':ap_hash(d)}
 old=list(source.get('/Annots',[]));all_saved=list(saved.get('/Annots',[]));assert [old_identity(x) for x in old]==[old_identity(x) for x in all_saved[:len(old)]]
 drawings=[o for o in p['operations'] if o['kind']=='addDrawing'];annots=[r.get_object() for r in all_saved[len(old):]];assert len(drawings)==len(annots)
 def near(actual,want):
  assert len(actual)==len(want),(actual,want)
  assert all(math.isclose(float(x),float(y),abs_tol=.021) for x,y in zip(actual,want)),(actual,want)
 def pairs(flat):return list(zip(flat[::2],flat[1::2]))
 expected_subtypes={'rect':'/Square','ellipse':'/Circle','arrow':'/Line','measure':'/Line','ink':'/Ink','polygon':'/Polygon','caret':'/Caret','image':'/Stamp'}
 coverage=[]
 for d,n in zip(drawings,annots,strict=True):
  shape=d['shape'];assert str(n['/Subtype'])==expected_subtypes[shape]
  ap=n['/AP']['/N'].get_object();ops=ContentStream(ap,b).operations
  if shape=='image':
   near(n['/Rect'],d['rect']);im=ap['/Resources']['/XObject']['/Im0'].get_object();assert im['/Width']==4 and im['/Height']==4
   assert sha256(im.get_data()).hexdigest()==p['imagePixelsSha256']
   coverage.append(shape);continue
  near(n['/C'],d['color'])
  near(ap['/BBox'],n['/Rect'])
  if shape=='caret':
   x,y=d['point'];near(n['/Rect'],[x-10,y-10,x+10,y+10]);ms=[v for v,k in ops if k==b'm'];ls=[v for v,k in ops if k==b'l'];near(ms[0],[x,y]);near(ls[0],[x-8,y-6]);near(ls[1],[x+8,y-6])
  elif shape=='polygon':
   near(n['/Vertices'],sum(d['vertices'],[]));xs,ys=zip(*d['vertices']);near(n['/Rect'],[min(xs),min(ys),max(xs),max(ys)])
   path=[v for v,k in ops if k in [b'm',b'l']];assert len(path)==len(d['vertices'])
   for actual,want in zip(path,d['vertices']):near(actual,want)
  elif shape=='ink':
   assert len(n['/InkList'])==len(d['paths'])==2
   for actual,want in zip(n['/InkList'],d['paths']):near(actual,want)
   points=[v for v,k in ops if k in [b'm',b'l']];expected=[point for path in d['paths'] for point in pairs(path)]
   assert len(points)==len(expected)
   for actual,want in zip(points,expected):near(actual,want)
   assert sum(k==b'm' for _,k in ops)==2
  elif shape in ['arrow','measure']:
   near(n['/L'],d['from']+d['to']);path=[v for v,k in ops if k in [b'm',b'l']];near(path[0],d['from']);near(path[1],d['to'])
   if shape=='arrow':assert len(path)==6
   else:
    assert str(n['/Contents'])==d['label'];assert any(k==b'Tj' and str(v[0])==d['label'] for v,k in ops)
    text_matrix=next(v for v,k in ops if k==b'Tm');near(text_matrix[-2:],[(d['from'][0]+d['to'][0])/2,(d['from'][1]+d['to'][1])/2+6])
  elif shape=='rect':
   x1,y1,x2,y2=d['rect'];near(next(v for v,k in ops if k==b're'),[x1,y1,x2-x1,y2-y1])
  elif shape=='ellipse':
   x1,y1,x2,y2=d['rect'];near(next(v for v,k in ops if k==b'm'),[x2,(y1+y2)/2]);assert sum(k==b'c' for _,k in ops)==4
  coverage.append(shape)
 print(json.dumps({'ok':True,'pages':3,'annotationOrderAndGeometry':coverage,'allInkPathsAndMeasurementLabel':True,'originalAnnotationAPIdentities':True,'textAndFieldsPreserved':True,'rotationAndOrderPreserved':True}))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw Error(result.stderr)
  return JSON.parse(result.stdout)
}
const fixture = python({ mode: 'create' }), source = Buffer.from(fixture.bytes, 'base64'), revisions = new Map([[1, source]]), payloads = []
let browser, readonly = false
const server = spawn('./node_modules/.bin/vite', ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
try {
  for (let n = 0; n < 100; n++) { try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  browser = await chromium.launch({ headless: true, executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ?? '/usr/bin/chromium' })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 2 }), errors = []
  page.on('pageerror', error => errors.push(error.message)); page.on('console', entry => { if (entry.type() === 'error') errors.push(entry.text()) })
  const revision = route => Number(route.request().url().match(/shape-canvas-fixture\/(\d+)\/api/)[1]), active = route => revisions.get(revision(route))
  const inspect = bytes => python({ mode: 'inspect', bytes: bytes.toString('base64') }), patch = (bytes, operations) => python({ mode: 'patch', bytes: bytes.toString('base64'), operations })
  await page.route('**/reports/v1/native/shape-canvas-fixture/*/api/context', route => route.fulfill({ json: {
    context: { documentId: 'shape-canvas-fixture', revision: revision(route), parentRevision: revision(route) === 1 ? null : revision(route) - 1, format: 'pdf', origin: 'upload', scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: 'drawings.pdf', size: active(route).length, sha256: sha(active(route)), mediaType: 'application/pdf' } }, csrfToken: 'fixture', capabilities: { pdf_editor: true }, editingEnabled: !readonly,
  } }))
  await page.route('**/reports/v1/native/shape-canvas-fixture/*/api/file', route => route.fulfill({ body: active(route), contentType: 'application/pdf' }))
  await page.route('**/reports/v1/native/shape-canvas-fixture/*/api/preview', route => {
    const bytes = active(route), ops = route.request().postDataJSON().operations, result = ops.length ? patch(bytes, ops) : null
    return route.fulfill({ json: { sourceSha256: sha(bytes), model: result?.model ?? inspect(bytes), appliedOperationIndices: result?.appliedOperationIndices ?? [], skippedOperations: [], previewDigest: result?.previewDigest } })
  })
  await page.route('**/reports/v1/native/shape-canvas-fixture/*/api/preview.pdf', route => {
    const input = route.request().postDataJSON(), result = patch(active(route), input.operations); assert.equal(input.expectedPreviewDigest, result.previewDigest)
    return route.fulfill({ body: Buffer.from(result.bytes, 'base64'), contentType: 'application/pdf', headers: { 'X-Native-Preview-Digest': result.previewDigest } })
  })
  await page.route('**/reports/v1/native/shape-canvas-fixture/*/api/save', route => {
    const input = route.request().postDataJSON(), result = patch(active(route), input.operations), next = revision(route) + 1, bytes = Buffer.from(result.bytes, 'base64'); payloads.push(input); revisions.set(next, bytes)
    return route.fulfill({ json: { documentId: 'shape-canvas-fixture', revision: next, parentRevision: next - 1, revisionRegistered: true, artifacts: { pdf: { downloadUrl: `/drawing-download-${next}.pdf`, size: bytes.length, sha256: sha(bytes) } }, editor: { openUrl: `/reports/v1/native/shape-canvas-fixture/${next}` }, validation: { ok: false, issues: [{ code: 'manual_review', message: '请核验内容；下载仍可用' }] } } })
  })
  await page.route(/\/drawing-download-\d+\.pdf$/, route => route.fulfill({ body: revisions.get(Number(route.request().url().match(/drawing-download-(\d+)/)[1])), contentType: 'application/pdf' }))
  await page.route(/\/reports\/v1\/native\/shape-canvas-fixture\/[123]$/, async route => route.fulfill({ response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }) }))
  const open = async n => { await page.goto(`${base}/reports/v1/native/shape-canvas-fixture/${n}`); await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 3 && document.querySelector('.pdf-page canvas'), null, { timeout: 60000 }) }
  const ops = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('shape-canvas-fixture'))?.[1] ?? '{"operations":[]}').operations)
  const panel = page.locator('.pdf-pending-drawings-panel'), rows = panel.locator('[data-pdf-pending-drawing]')
  const show = async () => { await page.locator('[data-pdf-ribbon-tab="annotate"]').click(); await page.getByRole('button', { name: '待保存绘图', exact: true }).click() }
  const loaded = () => page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 3 && document.querySelector('.pdf-page canvas'), null, { timeout: 60000 })
  const preview = async () => { await page.locator('[data-pdf-ribbon-tab="edit"]').click(); await page.getByRole('button', { name: '校验当前修改', exact: true }).click(); await page.waitForFunction(() => document.querySelector('.native-pdf-editor')?.dataset.pdfPreview === 'true', null, { timeout: 30000 }); await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(node=>node.textContent?.trim()==='校验当前修改'&&!node.disabled)); await loaded() }
  const save = async n => { await page.locator('[data-action="save"]').click(); await page.waitForFunction(n => document.querySelector('.save-state-label')?.textContent === `已保存修订 ${n}`, n, { timeout: 30000 }); const link = await page.locator('.native-delivery a').filter({ hasText: '下载 PDF' }).getAttribute('href'); const bytes = Buffer.from(await page.evaluate(async url => [...new Uint8Array(await (await fetch(url)).arrayBuffer())], link)); assert.deepEqual(bytes, revisions.get(n)) }
  const evidenceDir=process.env.PDF_SHAPE_CANVAS_EVIDENCE_DIR
  if(evidenceDir)await mkdir(evidenceDir,{recursive:true})
  const phase=label=>console.log(JSON.stringify({phase:label}))
  let sourcePosition=0,rotation=0
  const sourceContent=()=>page.locator('.pdf-page').nth(sourcePosition).locator('.pdf-page-content')
  const group=index=>page.locator(`g[data-pdf-shape-index="${index}"]`)
  const selectMode=async()=>{await page.locator('[data-pdf-ribbon-tab="annotate"]').click();await page.getByRole('button',{name:'选择文字',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.native-pdf-editor')?.dataset.pdfMode==='select')}
  const history=async direction=>{await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.getByRole('button',{name:direction==='undo'?/^(撤销|Undo)$/:/^(重做|Redo)$/}).click();await loaded()}
  const settled=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))
  const toClient=async(x,y)=>{
    const bounds=await sourceContent().boundingBox(),crop=fixture.model.pages[0].cropBox,a=x-crop.x,b=y-crop.y
    const pos=rotation===90?[b,a]:rotation===180?[crop.width-a,b]:rotation===270?[crop.height-b,crop.width-a]:[a,crop.height-b]
    return {x:bounds.x+pos[0]*bounds.width/(rotation%180?crop.height:crop.width),y:bounds.y+pos[1]*bounds.height/(rotation%180?crop.width:crop.height)}
  }
  const selected=async index=>{await page.waitForFunction(index=>document.querySelector(`[data-pdf-drawing-selection="${index}"]`),index);assert.equal(await page.locator('[data-pdf-drawing-selection]').count(),1)}
  const closeNumbers=(a,b,epsilon=1e-3)=>{assert.equal(a.length,b.length);a.forEach((v,i)=>assert.ok(Math.abs(v-b[i])<epsilon,`${a} != ${b}`))}
  const translate=(operation,dx,dy)=>{
    const next=structuredClone(operation),point=p=>[p[0]+dx,p[1]+dy]
    if(next.rect)next.rect=[...point(next.rect),...point(next.rect.slice(2))]
    if(next.from){next.from=point(next.from);next.to=point(next.to)}
    if(next.paths)next.paths=next.paths.map(path=>path.map((v,i)=>v+(i%2?dy:dx)))
    if(next.vertices)next.vertices=next.vertices.map(point)
    if(next.point)next.point=point(next.point)
    return next
  }
  const closeOperation=(actual,want)=>{
    for(const key of Object.keys(want)){
      if(['rect','from','to','point'].includes(key))closeNumbers(actual[key],want[key])
      else if(['paths','vertices'].includes(key)){assert.equal(actual[key].length,want[key].length);actual[key].forEach((v,i)=>closeNumbers(v,want[key][i]))}
      else assert.deepEqual(actual[key],want[key],key)
    }
  }
  const strokePoint=async(index,path=0,offset=4)=>{
    const node=group(index).locator('[data-pdf-drawing]').nth(path);await node.waitFor({state:'visible'});await node.scrollIntoViewIfNeeded();await settled()
    return node.evaluate((element,offset)=>{
      const length=element.getTotalLength(),a=element.getPointAtLength(length*.31),b=element.getPointAtLength(Math.min(length,length*.31+.2)),matrix=element.getScreenCTM(),p=new DOMPoint(a.x,a.y).matrixTransform(matrix),q=new DOMPoint(b.x,b.y).matrixTransform(matrix),distance=Math.hypot(q.x-p.x,q.y-p.y)
      return {x:p.x-(q.y-p.y)*offset/distance,y:p.y+(q.x-p.x)*offset/distance}
    },offset)
  }
  const hitIndex=point=>page.evaluate(({x,y})=>document.elementFromPoint(x,y)?.closest('[data-pdf-shape-index]')?.getAttribute('data-pdf-shape-index')??null,point)
  const startDrag=async(index,dx=10,dy=-6,path=0)=>{
    const start=await strokePoint(index,path),a=await toClient(100,100),b=await toClient(100+dx,100+dy),end={x:start.x+b.x-a.x,y:start.y+b.y-a.y}
    assert.equal(await hitIndex(start),String(index),`fat stroke must target exact operation #${index}`)
    await page.mouse.move(start.x,start.y);await page.mouse.down();await page.mouse.move(end.x,end.y,{steps:5});return {start,end}
  }
  phase('ui-twins-and-restored-mixed-source-ledger')
  await open(1);await page.locator('[data-pdf-ribbon-tab="annotate"]').click();await page.locator('[data-pdf-draw-shape="rect"]').click()
  for(let n=1;n<=2;n++){
    await sourceContent().scrollIntoViewIfNeeded();const b=await sourceContent().boundingBox();await page.mouse.move(b.x+b.width*.2,b.y+b.height*.3);await page.mouse.down();await page.mouse.move(b.x+b.width*.4,b.y+b.height*.45,{steps:4});await page.mouse.up();await loaded();await page.waitForFunction(n=>document.querySelectorAll('[data-pdf-drawing="rect"]').length===n,n)
  }
  const uiTwins=await ops();assert.deepEqual(uiTwins[0],uiTwins[1])
  const common={kind:'addDrawing',pageId:fixture.model.pages[0].pageId,color:[.86,.22,.18],width:2}
  const image=rect=>({...common,shape:'image',rect,image:fixture.image})
  const initial=[{...common,shape:'rect',rect:[20,430,200,465]},image([260,40,330,110]),{...common,shape:'rect',rect:[20,430,200,465]},
    {...common,shape:'ellipse',rect:[230,350,310,410]},
    {...common,shape:'arrow',from:[50,210],to:[140,240]},
    {...common,shape:'measure',from:[210,260],to:[300,285],label:'7.00 m'},
    {...common,shape:'ink',paths:[[50,135,70,160,95,145],[50,105,80,120,115,105]]},
    {...common,shape:'polygon',vertices:[[230,150],[300,150],[265,210]]},
    {...common,shape:'caret',point:[340,120]},
    {...common,shape:'rect',rect:[260,40,330,110]},image([245,60,280,90])]
  await page.evaluate(operations=>{const[key,value]=Object.entries(localStorage).find(([key])=>key.includes('shape-canvas-fixture'));const state=JSON.parse(value);state.operations=operations;localStorage.setItem(key,JSON.stringify(state))},initial)
  await page.reload();await loaded();await page.locator('.pdf-page-label').first().click();await selectMode();await group(10).waitFor({state:'visible'});assert.deepEqual(await ops(),initial)
  phase('empty-interiors-and-interleaved-z-order')
  await sourceContent().scrollIntoViewIfNeeded();await settled()
  for(const point of [[110,447.5],[270,380]])assert.equal(await hitIndex(await toClient(...point)),null,'unfilled shape interiors must not become bbox hit areas')
  const stack=[]
  for(const[point,index]of [[[260,75],10],[[260,100],9],[[300,100],1]]){
    const p=await toClient(...point);await sourceContent().scrollIntoViewIfNeeded();await settled();const current=await toClient(...point)
    assert.equal(await hitIndex(current),String(index));await page.mouse.click(current.x,current.y);await selected(index);stack.push({point,index});assert.deepEqual(await ops(),initial)
  }
  phase('all-seven-geometries-live-release-once-history')
  const kinds=[2,3,4,5,6,7,8],moves=[]
  for(const index of kinds){
    await selectMode();const before=await ops(),path=index===6?1:0
    if(index===6){assert.equal(await group(index).locator('[data-pdf-drawing="ink"]').count(),2);assert.equal(await group(index).locator('[data-pdf-shape-hit]').count(),2)}
    const labelBefore=index===5?await group(index).locator('[data-pdf-measure-label]').evaluate(node=>({x:Number(node.getAttribute('x')),y:Number(node.getAttribute('y'))})):null
    const headsBefore=index===4?await group(index).locator('[data-pdf-arrow-head]').evaluateAll(nodes=>nodes.map(node=>['x1','y1','x2','y2'].map(key=>Number(node.getAttribute(key))))):null
    if(index===4)assert.equal(headsBefore.length,2)
    const result=await startDrag(index,10,-6,path);assert.deepEqual(await ops(),before,'live shape drag must not serialize into draft')
    await selected(index);await page.mouse.up();await loaded();const after=await ops()
    for(let i=0;i<before.length;i++)if(i===index)closeOperation(after[i],translate(before[i],10,-6));else assert.deepEqual(after[i],before[i])
    if(index===5){const labelAfter=await group(index).locator('[data-pdf-measure-label]').evaluate(node=>({x:Number(node.getAttribute('x')),y:Number(node.getAttribute('y'))})),ratio=await group(index).evaluate(node=>{const svg=node.ownerSVGElement,b=svg.getBoundingClientRect();return {x:svg.width.baseVal.value/b.width,y:svg.height.baseVal.value/b.height}}),delta={x:(result.end.x-result.start.x)*ratio.x,y:(result.end.y-result.start.y)*ratio.y};assert.ok(Math.abs(labelAfter.x-labelBefore.x-delta.x)<.01&&Math.abs(labelAfter.y-labelBefore.y-delta.y)<.01);assert.equal(await group(index).locator('[data-pdf-measure-label]').textContent(),'7.00 m')}
    if(index===4){const headsAfter=await group(index).locator('[data-pdf-arrow-head]').evaluateAll(nodes=>nodes.map(node=>['x1','y1','x2','y2'].map(key=>Number(node.getAttribute(key))))),ratio=await group(index).evaluate(node=>{const svg=node.ownerSVGElement,b=svg.getBoundingClientRect();return {x:svg.width.baseVal.value/b.width,y:svg.height.baseVal.value/b.height}}),dx=(result.end.x-result.start.x)*ratio.x,dy=(result.end.y-result.start.y)*ratio.y;assert.equal(headsAfter.length,2);headsAfter.forEach((head,i)=>closeNumbers(head,headsBefore[i].map((v,k)=>v+(k%2?dy:dx))))}
    await history('undo');assert.deepEqual(await ops(),before);await history('redo');assert.deepEqual(await ops(),after);moves.push({index,shape:before[index].shape,delta:[10,-6]})
  }
  phase('threshold-cancellation-stale-dom-and-mode-pass-through')
  await selectMode();const moved=await ops(),p=await strokePoint(2);await page.mouse.move(p.x,p.y);await page.mouse.down();await page.mouse.move(p.x+1,p.y+1);await page.mouse.up();assert.deepEqual(await ops(),moved)
  for(const cause of ['pointercancel','lostcapture','Escape','blur','page-switch']){
    await startDrag(2)
    if(cause==='pointercancel')await group(2).evaluate(node=>node.dispatchEvent(new PointerEvent('pointercancel',{pointerId:1,bubbles:true})))
    else if(cause==='lostcapture'){const released=await page.evaluate(()=>{const owner=[...document.querySelectorAll('*')].find(node=>node.hasPointerCapture?.(1));if(!owner)return false;owner.releasePointerCapture(1);return true});assert.equal(released,true)}
    else if(cause==='Escape')await page.keyboard.press('Escape')
    else if(cause==='blur')await page.evaluate(()=>window.dispatchEvent(new Event('blur')))
    else await page.locator('.pdf-page-label').nth(1).evaluate(node=>node.click())
    await page.mouse.up();assert.deepEqual(await ops(),moved,cause);if(cause==='page-switch')await page.locator('.pdf-page-label').first().evaluate(node=>node.click())
  }
  await startDrag(2);await group(2).evaluate(node=>{window.__oldShapeDrag=node});await page.getByRole('button',{name:'放大页面',exact:true}).evaluate(node=>node.click());await loaded();await page.mouse.up();await page.evaluate(()=>window.__oldShapeDrag.dispatchEvent(new PointerEvent('pointerup',{pointerId:1,bubbles:true})));assert.deepEqual(await ops(),moved)
  await startDrag(2);await group(2).evaluate(node=>{window.__oldShapeDrag=node});await page.locator('[data-pdf-ribbon-tab="home"]').evaluate(node=>node.click());await page.getByRole('button',{name:/^(撤销|Undo)$/}).evaluate(node=>node.click());await loaded();await page.mouse.up();await page.evaluate(()=>window.__oldShapeDrag.dispatchEvent(new PointerEvent('pointerup',{pointerId:1,bubbles:true})));const undone=await ops();assert.deepEqual(undone[8],initial[8]);await history('redo');assert.deepEqual(await ops(),moved)
  await selectMode();await page.locator('[data-pdf-ribbon-tab="annotate"]').click();await page.locator('[data-pdf-draw-shape="rect"]').click()
  const through=await strokePoint(2,0,0);await page.mouse.move(through.x,through.y);await page.mouse.down();await page.mouse.move(through.x+24,through.y+24,{steps:4});await page.mouse.up();await loaded();assert.equal((await ops()).at(-1).shape,'rect');assert.deepEqual((await ops()).slice(0,initial.length),moved);await history('undo');assert.deepEqual(await ops(),moved)
  phase('rotate-reorder-drag-preview-save-reopen')
  await page.locator('[data-pdf-ribbon-tab="page"]').click();await page.locator('[data-source-command-id="genoffice.pdf.page.rotateRight"]').click();await loaded();rotation=90
  await page.locator('[data-source-command-id="genoffice.pdf.page.reverse"]').click();await loaded();sourcePosition=2;await page.locator('.pdf-page-label').last().click();await selectMode()
  const beforeRotateMove=await ops();await startDrag(4,12,8);await page.mouse.up();await loaded();const final=await ops();closeOperation(final[4],translate(beforeRotateMove[4],12,8));for(let i=0;i<final.length;i++)if(i!==4)assert.deepEqual(final[i],beforeRotateMove[i])
  await page.reload();await loaded();await page.locator('.pdf-page-label').last().click();await selectMode();await group(6).waitFor({state:'visible'});assert.deepEqual(await ops(),final)
  const stored=await page.evaluate(()=>Object.entries(localStorage).find(([key])=>key.includes('shape-canvas-fixture')))
  if(evidenceDir){await sourceContent().scrollIntoViewIfNeeded();await page.screenshot({path:`${evidenceDir}/draft-rotated.png`,fullPage:true})}
  await preview();await page.waitForFunction(()=>document.querySelectorAll('[data-pdf-shape-hit]').length===0);await save(2)
  if(evidenceDir){await writeFile(`${evidenceDir}/actual-download.pdf`,revisions.get(2));await writeFile(`${evidenceDir}/source.pdf`,source);await writeFile(`${evidenceDir}/saved-operations.json`,JSON.stringify(payloads[0].operations,null,2))}
  const independent=python({mode:'verify',source:fixture.bytes,bytes:revisions.get(2).toString('base64'),operations:payloads[0].operations,imagePixelsSha256:fixture.imagePixelsSha256})
  await open(2);await page.locator('.pdf-page-label').last().click();assert.equal(await page.locator('[data-pdf-shape-index]').count(),0)
  phase('readonly-restored-draft-cannot-hit-or-drag')
  readonly=true;await page.evaluate(([key,value])=>localStorage.setItem(key,value),stored);await open(1);await page.locator('.pdf-page-label').last().click();await selectMode();await group(2).waitFor({state:'visible'});const readonlyOps=await ops();assert.deepEqual(readonlyOps,final)
  await group(2).evaluate(node=>{node.closest('svg').classList.add('is-interactive');node.querySelectorAll('[data-pdf-shape-hit]').forEach(hit=>{hit.style.pointerEvents='stroke'})})
  const ro=await strokePoint(2);await page.mouse.move(ro.x,ro.y);await page.mouse.down();await page.mouse.move(ro.x+25,ro.y+10,{steps:4});await page.mouse.up();assert.deepEqual(await ops(),readonlyOps)
  assert.equal(await page.locator('[data-pdf-drawing-selection]').count(),0);assert.deepEqual(errors,[])
  const evidence={ok:true,independent,browserVersion:browser.version(),dpr:2,uiCreatedTwins:true,restoredMixedLedger:true,emptyInteriorsPassThrough:true,interleavedStackHitOrder:stack,sevenGeometryMoves:moves,allInkPaths:true,arrowHeadsAndMeasurementLabelFollow:true,releaseOnceHistory:true,clickThresholdNoHistory:true,cancellationsAndStaleDomRefused:true,drawingModePassThrough:true,rotationCropReorder:true,undoRedoReload:true,actualPreviewSaveDownloadReopen:true,readonlyIsolation:true,operations:payloads.map(input=>input.operations),provenance:'production static canvas UI; real pointer strokes and valid restored mixed draft; substituted auth/revision routes; actual packed engine/PDF.js/download and independent pypdf geometry/AP/source-annotation checks; no full desktop/production acceptance'}
  if(evidenceDir){for(const[n,bytes]of revisions)await writeFile(`${evidenceDir}/revision-${n}.pdf`,bytes);await writeFile(`${evidenceDir}/evidence.json`,JSON.stringify(evidence,null,2))}
  console.log(JSON.stringify(evidence))
}finally{await browser?.close();server.kill('SIGTERM')}
