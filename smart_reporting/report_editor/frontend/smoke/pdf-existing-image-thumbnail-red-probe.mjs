import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { appendFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { createRequire } from 'node:module'
import { chromium } from 'playwright'
import { observePdfBuiltAssets } from './pdf-object-dialog-checks.mjs'

const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.PDF_EXISTING_IMAGE_THUMBNAIL_PORT ?? 4218), base = `http://127.0.0.1:${port}`
const directory = process.env.PDF_EXISTING_IMAGE_THUMBNAIL_EVIDENCE_DIR ?? '/dev/shm/pdf-existing-image-thumbnail-20261113'
const outDir = process.env.PDF_EXISTING_IMAGE_THUMBNAIL_FROZEN_OUTDIR
const manifestSha = process.env.PDF_EXISTING_IMAGE_THUMBNAIL_MANIFEST_SHA256
assert(outDir && manifestSha, 'set frozen outDir and manifest SHA from root')
const sha = bytes => createHash('sha256').update(bytes).digest('hex')

function python(input) {
  const result = spawnSync(`${repo}/.venv/bin/python`, ['-c', `
import base64,hashlib,json,sys
from io import BytesIO
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf,patch_pdf_with_receipt,read_pdf_image_pixels
p=json.load(sys.stdin)
if p['mode']=='pngs':
 im=Image.new('RGB',(9,4)); colors=[(230,35,45),(20,170,75),(30,70,225),(245,205,25),(185,35,195),(20,185,205)]
 for y in range(4):
  for x in range(9): im.putpixel((x,y),colors[(y//2)*3+x//3])
 png=BytesIO();im.save(png,'PNG');base=png.getvalue();variants=[]
 for i in range(4):
  variant=im.copy();variant.putpixel((8,3),colors[i]);out=BytesIO();variant.save(out,'PNG');variants.append(base64.b64encode(out.getvalue()).decode())
 print(json.dumps({'png':base64.b64encode(base).decode(),'variants':variants}))
elif p['mode']=='inspect': print(json.dumps(inspect_pdf(base64.b64decode(p['bytes']))))
elif p['mode']=='pixels': print(json.dumps(read_pdf_image_pixels(base64.b64decode(p['bytes']),p['target'])))
elif p['mode']=='pngPixels':
 raw=base64.b64decode(p['image']); im=Image.open(BytesIO(raw)).convert('RGBA'); data=im.tobytes()
 print(json.dumps({'width':im.width,'height':im.height,'rgbaBase64':base64.b64encode(data).decode()}))
elif p['mode']=='patch':
 b=base64.b64decode(p['bytes']);r=patch_pdf_with_receipt(b,p['operations']);out=r.pop('content');r['bytes']=base64.b64encode(out).decode();r['model']=inspect_pdf(out);print(json.dumps(r))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 30 * 1024 * 1024 })
  if (result.status !== 0) throw Error(result.stderr)
  return JSON.parse(result.stdout)
}

function transformPixels(source,bake) {
  const {width,height,data}=source, copy=(x,y)=>data.slice((y*width+x)*4,(y*width+x)*4+4)
  if (bake.kind==='flip') {
    const output=new Uint8ClampedArray(data.length)
    for(let y=0;y<height;y++)for(let x=0;x<width;x++){const pixel=copy(bake.axis==='h'?width-1-x:x,bake.axis==='v'?height-1-y:y);output.set(pixel,(y*width+x)*4)}
    return {width,height,data:[...output]}
  }
  if (bake.kind==='opacity') {
    const output=[...data];for(let i=3;i<output.length;i+=4)output[i]=Math.round(output[i]*bake.alpha)
    return {width,height,data:output}
  }
  if (bake.kind==='rotate') {
    const outWidth=height,outHeight=width,output=new Uint8ClampedArray(data.length),cw=bake.quarterTurns===1
    for(let y=0;y<height;y++)for(let x=0;x<width;x++){const nx=cw?height-1-y:y,ny=cw?x:width-1-x;output.set(copy(x,y),(ny*outWidth+nx)*4)}
    return {width:outWidth,height:outHeight,data:[...output]}
  }
  const sx=Math.round(bake.crop.l*width),sy=Math.round(bake.crop.t*height),sw=Math.max(1,Math.round((bake.crop.r-bake.crop.l)*width)),sh=Math.max(1,Math.round((bake.crop.b-bake.crop.t)*height)),output=[]
  for(let y=sy;y<sy+sh;y++)for(let x=sx;x<sx+sw;x++)output.push(...copy(x,y))
  return {width:sw,height:sh,data:output}
}
function assertPixelMatch(actualBase64,expectedData,label){
  const actual=Buffer.from(actualBase64,'base64'),expected=Buffer.from(expectedData)
  const differences=[];let differenceCount=0
  if(actual.length===expected.length)for(let i=0;i<actual.length;i++)if(actual[i]!==expected[i]){differenceCount++;if(differences.length<20)differences.push({index:i,actual:actual[i],expected:expected[i]})}
  assert.equal(actual.length,expected.length,`${label} RGBA byte length`)
  assert.equal(differenceCount,0,`${label} RGBA mismatch ${JSON.stringify({differenceCount,differences,actualSha256:sha(actual),expectedSha256:sha(expected)})}`)
  return {matchedBytes:actual.length,actualSha256:sha(actual),expectedSha256:sha(expected),differenceCount}
}
async function canvasPngRoundTrip(page,{width,height,data}){
  return page.evaluate(({width,height,rgbaBase64})=>{
    const binary=atob(rgbaBase64),bytes=Uint8ClampedArray.from(binary,char=>char.charCodeAt(0)),canvas=document.createElement('canvas');canvas.width=width;canvas.height=height
    const context=canvas.getContext('2d');context.putImageData(new ImageData(bytes,width,height),0,0)
    const pngBase64=canvas.toDataURL('image/png').split(',')[1]
    const image=new Image();image.src=`data:image/png;base64,${pngBase64}`
    return image.decode().then(()=>{const decoded=document.createElement('canvas');decoded.width=width;decoded.height=height;const target=decoded.getContext('2d');target.drawImage(image,0,0);const pixels=target.getImageData(0,0,width,height).data;let encoded='';for(let i=0;i<pixels.length;i+=8192)encoded+=String.fromCharCode(...pixels.subarray(i,i+8192));return {rgbaBase64:btoa(encoded),pngBase64}})
  },{width,height,rgbaBase64:Buffer.from(data).toString('base64')})
}

await mkdir(directory, { recursive: true })
const engineRuntimeRoot=process.env.AGENT_REPORTING_PDF_ENGINE_DIR
assert(engineRuntimeRoot,'AGENT_REPORTING_PDF_ENGINE_DIR must point at the isolated bridge runtime')
const engineRequire=createRequire(join(engineRuntimeRoot,'dist/cli.mjs')),wasmPath=engineRequire.resolve('@embedpdf/pdfium/pdfium.wasm')
const engineRuntimeIdentity={root:engineRuntimeRoot,nodeVersion:process.version,bundleSha256:sha(await readFile(join(engineRuntimeRoot,'dist/cli.mjs'))),pdfiumWasm:{path:wasmPath,size:(await readFile(wasmPath)).length,sha256:sha(await readFile(wasmPath))},pythonWrapperSha256:{'pdf_native.py':sha(await readFile(join(repo,'smart_reporting/reporting/delivery/pdf_native.py'))),'office_engine.py':sha(await readFile(join(repo,'smart_reporting/reporting/delivery/office_engine.py')))},sourceSha256:{
  'package.json':sha(await readFile(join(repo,'smart_reporting/reporting/pdf_engine/package.json'))),
  'bridge/cli.ts':sha(await readFile(join(repo,'smart_reporting/reporting/pdf_engine/bridge/cli.ts'))),
  'bridge/operations.ts':sha(await readFile(join(repo,'smart_reporting/reporting/pdf_engine/bridge/operations.ts'))),
  'bridge/existing-image.ts':sha(await readFile(join(repo,'smart_reporting/reporting/pdf_engine/bridge/existing-image.ts'))),
  'bridge/existing-image-engine.ts':sha(await readFile(join(repo,'smart_reporting/reporting/pdf_engine/bridge/existing-image-engine.ts'))),
}}
await writeFile(`${directory}/bridge-runtime.json`,JSON.stringify(engineRuntimeIdentity,null,2))
const pngFixture=python({mode:'pngs'})
const engine=join(repo,'smart_reporting/reporting/pdf_engine')
const generated=spawnSync(process.execPath,['--import','tsx','--input-type=module','-e',`
import {readFileSync} from 'node:fs';import {PDFDocument,degrees} from 'pdf-lib'
const p=JSON.parse(readFileSync(0,'utf8')),pdf=await PDFDocument.create()
for(let i=0;i<4;i++){const page=pdf.addPage([500,650]),image=await pdf.embedPng(Buffer.from(p.variants[i],'base64'));page.drawText('Thumbnail fixture '+i,{x:45,y:590,size:12});page.drawImage(image,{x:125,y:210,width:160,height:120});page.setCropBox(20,30,450,580);page.setRotation(degrees(i*90))}
process.stdout.write(Buffer.from(await pdf.save()).toString('base64'))
`],{cwd:engine,input:JSON.stringify(pngFixture),encoding:'utf8',maxBuffer:20*1024*1024})
assert.equal(generated.status,0,generated.stderr)
const source=process.env.PDF_EXISTING_IMAGE_THUMBNAIL_SOURCE_FILE?await readFile(process.env.PDF_EXISTING_IMAGE_THUMBNAIL_SOURCE_FILE):Buffer.from(generated.stdout.trim(),'base64'),model=python({mode:'inspect',bytes:source.toString('base64')}),fixture={png:pngFixture.png,source:source.toString('base64'),model}
await writeFile(`${directory}/source.pdf`,source)
await writeFile(`${directory}/fixture-model.json`,JSON.stringify(model,null,2))
const documentId = 'existing-image-thumbnail-fixture', revision = 1, contextPath = `/reports/v1/native/${documentId}/${revision}`
let browser, previewCount = 0, pendingPixelRequests = 0, heldPixelResolve
const pageErrors = [], consoleErrors = [], requests = [], operationsLog = []
let stage='fixture-ready',peakRss=0
const mark=value=>{stage=value;const memory=process.memoryUsage();peakRss=Math.max(peakRss,memory.rss);const record={stage,at:new Date().toISOString(),memory,peakRss};writeFileSync(`${directory}/progress.json`,JSON.stringify(record));appendFileSync(`${directory}/stage-memory.jsonl`,JSON.stringify(record)+'\n')}
let watchdog
const server = spawn('./node_modules/.bin/vite', ['preview', '--outDir', outDir, '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
try {
  mark('server-starting')
  for (let n = 0; n < 120; n++) { try { if ((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok) break } catch {} await delay(250) }
  mark('server-ready')
  const diskManifest=await readFile(`${outDir}/.vite/manifest.json`)
  assert.equal(sha(diskManifest),manifestSha,'frozen manifest SHA must match root-provided value')
  await writeFile(`${directory}/build-manifest.json`,diskManifest)
  browser = await chromium.launch({ headless: true, ...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE ? { executablePath: process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE } : {}) })
  mark('browser-launched')
  if(process.env.PDF_EXISTING_IMAGE_THUMBNAIL_DIAGNOSTIC)watchdog=setInterval(()=>{
    const memory=process.memoryUsage()
    peakRss=Math.max(peakRss,memory.rss)
    if(memory.rss>1.5*1024**3){writeFileSync(`${directory}/failure.json`,JSON.stringify({stage,reason:'node-rss-limit',memory,pageErrors,consoleErrors,requests,operationsLog}));process.exit(86)}
  },250)
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
  page.setDefaultTimeout(8000)
  process.env.PDF_STATIC_ROOT=outDir;process.env.PDF_EXPECTED_MANIFEST_SHA256=manifestSha
  const verifyAssets=await observePdfBuiltAssets(page)
  page.on('pageerror', error => {if(pageErrors.length<50)pageErrors.push(error.message.slice(0,1000))}); page.on('console', entry => { if (entry.type() === 'error'&&consoleErrors.length<50) consoleErrors.push(entry.text().slice(0,1000)) })
  const latest = () => source
  const patch = (bytes, ops) => python({ mode: 'patch', bytes: bytes.toString('base64'), operations: ops })
  const inspect = bytes => python({ mode: 'inspect', bytes: bytes.toString('base64') })
  const routeBase = `**/reports/v1/native/${documentId}/${revision}/api`
  await page.route(`${routeBase}/context`, route => route.fulfill({ json: { context: { documentId, revision, parentRevision: null, format: 'pdf', origin: 'upload', scope: { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }, sourceFile: { path: 'thumbnail.pdf', size: source.length, sha256: sha(source), mediaType: 'application/pdf' } }, csrfToken: 'fixture', capabilities: { pdf_editor: true }, editingEnabled: true } }))
  await page.route(`${routeBase}/file`, route => {mark('api-file');return route.fulfill({ body: latest(), contentType: 'application/pdf' })})
  await page.route(`${routeBase}/read-model`, route => {mark('api-read-model-start');const value=inspect(latest());mark('api-read-model-done');return route.fulfill({ json: { sourceSha256: sha(latest()), model: value } })})
  await page.route(`${routeBase}/image-pixels`, async route => {
    mark('api-image-pixels-start')
    pendingPixelRequests++
    const target = route.request().postDataJSON()
    requests.push({ kind: 'image-pixels', target })
    if (heldPixelResolve) await new Promise(resolve => { heldPixelResolve = resolve })
    const value=python({ mode: 'pixels', bytes: latest().toString('base64'), target });mark('api-image-pixels-done');return route.fulfill({ json: value })
  })
  await page.route(`${routeBase}/preview`, route => {
    mark('api-preview-start')
    previewCount++
    const input = route.request().postDataJSON(), result = input.operations.length ? patch(latest(), input.operations) : undefined
    requests.push({ kind: 'preview', operations: input.operations })
    const value={ sourceSha256: sha(latest()), model: result?.model ?? inspect(latest()), appliedOperationIndices: result?.appliedOperationIndices ?? [], skippedOperations: result?.skippedOperations ?? [], previewDigest: result?.previewDigest };mark('api-preview-done');return route.fulfill({ json: value })
  })
  await page.route(`${routeBase}/preview.pdf`, route => {
    const input = route.request().postDataJSON(), result = patch(latest(), input.operations)
    assert.equal(input.expectedPreviewDigest, result.previewDigest)
    return route.fulfill({ body: Buffer.from(result.bytes, 'base64'), contentType: 'application/pdf', headers: { 'X-Native-Preview-Digest': result.previewDigest } })
  })
  await page.route(new RegExp(`/reports/v1/native/${documentId}/${revision}$`), async route => route.fulfill({ response: await route.fetch({ url: `${base}/reports/v1/editor/assets/native.html` }) }))
  const open = async () => { await page.goto(`${base}${contextPath}`); await page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 4 && document.querySelector('.pdf-page canvas'), null, { timeout: 60000 }) }
  const getOperations = () => page.evaluate(() => JSON.parse(Object.entries(localStorage).find(([key]) => key.includes('existing-image-thumbnail-fixture'))?.[1] ?? '{"operations":[]}').operations)
  const waitPages = () => page.waitForFunction(() => document.querySelectorAll('.pdf-page').length === 4 && document.querySelectorAll('.pdf-thumbnail').length === 4, null, { timeout: 30000 })
  const imageCommand = page.locator('[data-source-command-id="genoffice.pdf.edit.objects.editImage"]')
  const openDialog = async () => {mark('dialog-edit-tab-click');await page.locator('[data-pdf-ribbon-tab="edit"]').click();mark('dialog-edit-tab-clicked');await imageCommand.click();mark('dialog-command-clicked');const dialog=page.getByRole('dialog', { name: '编辑已有图像', exact: true });await dialog.waitFor({state:'visible'});mark('dialog-visible');return dialog}
  const selectPage = async (dialog, index) => {mark(`dialog-select-page-${index}`);await dialog.getByLabel('已有图像选择', { exact: true }).selectOption(String(index));mark(`dialog-selected-page-${index}`)}
  const stageGeometry = async (index, rect, replacement = false) => {
    mark(`geometry-stage-${index}-dialog`)
    const dialog = await openDialog(); await selectPage(dialog, index)
    for (const [label, value] of [['X', rect[0]], ['Y', rect[1]], ['宽度', rect[2] - rect[0]], ['高度', rect[3] - rect[1]]]) {mark(`geometry-fill-${index}-${label}`);await dialog.getByLabel(`已有图像${label}`, { exact: true }).fill(String(value));mark(`geometry-filled-${index}-${label}`)}
    if (replacement) await dialog.getByLabel('选择替换图像').setInputFiles({ name: 'asymmetric.png', mimeType: 'image/png', buffer: Buffer.from(fixture.png, 'base64') })
    mark(`geometry-confirm-${index}`);await dialog.locator('[data-pdf-existing-image-confirm]').click();mark(`geometry-confirmed-${index}`);await waitPages();mark(`geometry-rendered-${index}`)
    const staged = await getOperations(); assert.equal(staged.length, 1); operationsLog.push(staged[0]); return staged[0]
  }
  const stageBake = async (index, kind, value) => {
    mark(`bake-${kind}-${index}-dialog`)
    const dialog = await openDialog(); await selectPage(dialog, index)
    mark(`bake-${kind}-${index}-select`);await dialog.getByLabel('已有图像像素编辑', { exact: true }).selectOption(kind);mark(`bake-${kind}-${index}-selected`)
    if (kind === 'crop') for (const [label, number] of [['裁去左侧百分比','10'],['裁去上侧百分比','0'],['裁去右侧百分比','20'],['裁去下侧百分比','15']]) await dialog.getByLabel(label, { exact: true }).fill(number)
    if (kind === 'opacity') await dialog.getByLabel('图像透明度百分比', { exact: true }).fill(process.env.PDF_EXISTING_IMAGE_THUMBNAIL_OPACITY_PERCENT??'55')
    mark(`bake-${kind}-${index}-confirm`);await dialog.locator('[data-pdf-existing-image-confirm]').click();mark(`bake-${kind}-${index}-confirmed`);await waitPages();mark(`bake-${kind}-${index}-rendered`)
    const staged = await getOperations(); assert.equal(staged.length, 1); operationsLog.push(staged[0]); return staged[0]
  }
  const undo = async () => {mark('undo-home-click');await page.locator('[data-pdf-ribbon-tab="home"]').click();mark('undo-button-click');await page.getByRole('button', { name: /^(撤销|Undo)$/ }).click();mark('undo-clicked');await waitPages();mark('undo-rendered');assert.deepEqual(await getOperations(), [])}
  const thumbnailLayer = index => page.locator('.pdf-thumbnail').nth(index).locator('.pdf-existing-image-thumbnail-layer')
  const mountedPixels = async (locator,maxPixels=2_000_000) => locator.evaluate(async (node,limit) => {
    const image=node;await image.decode();if(image.naturalWidth*image.naturalHeight>limit)throw Error(`pixel fixture exceeds ${limit}: ${image.naturalWidth}x${image.naturalHeight}`)
    const canvas=document.createElement('canvas');canvas.width=image.naturalWidth;canvas.height=image.naturalHeight
    const context=canvas.getContext('2d');context.drawImage(image,0,0);const bytes=context.getImageData(0,0,canvas.width,canvas.height).data;let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));return {width:canvas.width,height:canvas.height,rgbaBase64:btoa(binary)}
  },maxPixels)

  mark('opening-editor')
  await open()
  mark('editor-open')
  assert.equal(model.pages.length, 4); assert.deepEqual(model.pages.map(item => item.rotation), [0, 90, 180, 270])
  assert(model.pages.every(item => item.cropBox.x !== 0 || item.cropBox.y !== 0), 'each page has a nonzero CropBox origin')
  const images = model.existingImages.filter(item => item.editable)
  assert.equal(images.length, 4); assert(images.every(item => item.replaceable))

  if(process.env.PDF_EXISTING_IMAGE_THUMBNAIL_RED_ONLY==='1'){
    const target=images[0],thumbnail=page.locator('.pdf-thumbnail').nth(0)
    await thumbnail.screenshot({path:`${directory}/original-thumbnail.png`})
    const operation=await stageBake(0,'opacity')
    const image=thumbnail.locator('.pdf-existing-image-thumbnail-image')
    await image.waitFor({state:'visible'});await image.evaluate(node=>node.decode())
    const mounted=await mountedPixels(image),mountedPng=await image.evaluate(node=>node.currentSrc||node.src)
    const mountedBytes=Buffer.from(mountedPng.slice(mountedPng.indexOf(',')+1),'base64')
    await writeFile(`${directory}/mounted-pending.png`,mountedBytes)
    const alpha=Buffer.from(mounted.rgbaBase64,'base64').filter((_,index)=>index%4===3)
    assert(alpha.length>0&&alpha.every(value=>value===0),'100% opacity must mount fully transparent pixels')
    await thumbnail.screenshot({path:`${directory}/pending-thumbnail.png`})
    const box=await page.locator('.pdf-thumbnail-page canvas').nth(0).evaluate((canvas,rect)=>{
      const page=canvas,ctx=page.getContext('2d'),crop={x:20,y:30,width:450,height:580},cx=(rect[0]+rect[2])/2,cy=(rect[1]+rect[3])/2
      const x=Math.max(0,Math.min(page.width-1,Math.floor((cx-crop.x)/crop.width*page.width))),y=Math.max(0,Math.min(page.height-1,Math.floor((crop.y+crop.height-cy)/crop.height*page.height)))
      const values=[];for(let dy=-2;dy<=2;dy++)for(let dx=-2;dx<=2;dx++){const px=Math.max(0,Math.min(page.width-1,x+dx)),py=Math.max(0,Math.min(page.height-1,y+dy));values.push([...ctx.getImageData(px,py,1,1).data])}
      const colored=values.filter(([r,g,b])=>r<245||g<245||b<245).length
      const r=page.getBoundingClientRect(),im=document.querySelectorAll('.pdf-thumbnail')[0].querySelector('.pdf-existing-image-thumbnail-image').getBoundingClientRect()
      return {pixel:{x,y},samples:values,nonWhiteSamples:colored,canvas:{width:page.width,height:page.height},imageBox:{left:im.left-r.left,top:im.top-r.top,width:im.width,height:im.height}}
    },target.rect)
    assert(box.nonWhiteSamples>0,'expected white under fully transparent thumbnail image; original raster remains visible')
    const alphaMin=alpha.reduce((value,current)=>Math.min(value,current),255),alphaMax=alpha.reduce((value,current)=>Math.max(value,current),0)
    writeFileSync(`${directory}/red-evidence.json`,JSON.stringify({ok:false,result:'expected RED reproduction: original image remains visible beneath fully transparent pending PNG',sourceSha256:sha(source),operation,expectedMountedAlpha:0,mountedPngSha256:sha(mountedBytes),mountedPixelSize:[mounted.width,mounted.height],alphaMin,alphaMax,alphaSamples:alpha.length,originalThumbnail:`${directory}/original-thumbnail.png`,pendingThumbnail:`${directory}/pending-thumbnail.png`,mountedPng:`${directory}/mounted-pending.png`,thumbnailImageBoxSample:box,sourceTarget:target,engineRuntime:engineRuntimeIdentity,frontendManifestSha256:manifestSha,pageErrors,consoleErrors},null,2))
    throw Object.assign(Error('red-probe-stop'),{code:'red-probe-stop'})
  }

  if(process.env.PDF_EXISTING_IMAGE_THUMBNAIL_DIAGNOSTIC==='bake-only'){
    const kind=process.env.PDF_EXISTING_IMAGE_THUMBNAIL_BAKE_KIND??'flip-h',operation=await stageBake(0,kind)
    await page.waitForFunction(()=>{const i=document.querySelector('.pdf-thumbnail .pdf-existing-image-thumbnail-image');return i?.complete&&i.naturalWidth>0})
    const pixels=await mountedPixels(page.locator('.pdf-thumbnail').nth(0).locator('.pdf-existing-image-thumbnail-image')),target=images[0]
    const readback=python({mode:'pixels',bytes:source.toString('base64'),target:{sourceSha256:sha(source),pageId:target.pageId,imageId:target.imageId,expectedImageSha256:target.expectedImageSha256}})
    const original=python({mode:'pngPixels',image:readback.image}),expected=transformPixels({...original,data:Buffer.from(original.rgbaBase64,'base64')},operation.bake)
    assert.deepEqual([pixels.width,pixels.height],[expected.width,expected.height])
    let pixelVerification
    if(operation.bake.kind==='opacity'){
      const rawExpected=Buffer.from(expected.data)
      for(let i=3;i<rawExpected.length;i+=4)assert.equal(rawExpected[i],115,'raw opacity alpha is round(255 * 0.45)')
      const roundTrip=await canvasPngRoundTrip(page,{width:expected.width,height:expected.height,data:rawExpected})
      const mounted=Buffer.from(pixels.rgbaBase64,'base64');for(let i=3;i<mounted.length;i+=4)assert.equal(mounted[i],115,'mounted opacity alpha stays 115')
      pixelVerification=assertPixelMatch(pixels.rgbaBase64,Buffer.from(roundTrip.rgbaBase64,'base64'),'opacity browser PNG roundtrip')
      const expectedPng=Buffer.from(roundTrip.pngBase64,'base64');writeFileSync(`${directory}/expected-opacity.png`,expectedPng)
      pixelVerification={...pixelVerification,mode:'exactAlpha+canvasPngRoundTripRGB',rawExpectedSha256:sha(rawExpected),browserExpectedPngSha256:sha(expectedPng),mountedSha256:sha(mounted),rawAlpha:115,rgbNote:'RGB compared with the browser canvas PNG encode/decode result; alpha remains exactly 115'}
    }else pixelVerification={...assertPixelMatch(pixels.rgbaBase64,expected.data,kind),mode:'exactRGBA',rawExpectedSha256:sha(Buffer.from(expected.data)),mountedSha256:sha(Buffer.from(pixels.rgbaBase64,'base64'))}
    writeFileSync(`${directory}/diagnostic.json`,JSON.stringify({stage,kind,operation,width:pixels.width,height:pixels.height,pixelVerification,memory:process.memoryUsage(),pageErrors,consoleErrors,requests,operationsLog},null,2));throw Object.assign(Error('diagnostic-stop'),{code:'diagnostic-stop'})
  }

  // Verify viewport geometry on all four page rotations with a unique move/resize draft.
  const pageGeometry=[]
  for(let index=0;index<4;index++){
    mark(`geometry-page-${index}-start`)
    const rect=images[index].rect, target=[rect[0]+12,rect[1]+16,rect[2]+32,rect[3]+36],operation=await stageGeometry(index,target)
    mark(`geometry-page-${index}-staged`)
    const layer=page.locator('.pdf-thumbnail').nth(index).locator('.pdf-existing-image-thumbnail-layer'),img=layer.locator('.pdf-existing-image-thumbnail-image')
    await page.waitForFunction(i=>{const node=document.querySelectorAll('.pdf-thumbnail')[i]?.querySelector('.pdf-existing-image-thumbnail-image');return node?.complete&&node.naturalWidth>0},index)
    const geometry=await img.evaluate(node=>{const r=node.getBoundingClientRect(),p=node.parentElement.getBoundingClientRect();return {left:(r.left-p.left)/p.width,top:(r.top-p.top)/p.height,width:r.width/p.width,height:r.height/p.height}})
    const p=model.pages[index],crop=p.cropBox,[x1,y1,x2,y2]=operation.rect,conv=(x,y)=>{const px=x-crop.x,py=y-crop.y,w=crop.width,h=crop.height;if(p.rotation===90)return[py,px];if(p.rotation===180)return[w-px,py];if(p.rotation===270)return[h-py,w-px];return[px,h-py]},points=[[x1,y1],[x1,y2],[x2,y1],[x2,y2]].map(([x,y])=>conv(x,y)),xs=points.map(v=>v[0]),ys=points.map(v=>v[1]),vw=p.rotation%180?crop.height:crop.width,vh=p.rotation%180?crop.width:crop.height
    const expected={left:Math.min(...xs)/vw,top:Math.min(...ys)/vh,width:(Math.max(...xs)-Math.min(...xs))/vw,height:(Math.max(...ys)-Math.min(...ys))/vh}
    for(const key of Object.keys(expected))assert(Math.abs(geometry[key]-expected[key])<.012,`rotation ${p.rotation} ${key}: ${geometry[key]} != ${expected[key]}`)
    pageGeometry.push({index,rotation:p.rotation,cropBox:crop,operation,actual:geometry,expected})
    await page.locator('.pdf-thumbnail').nth(index).screenshot({path:`${directory}/thumbnail-rotation-${p.rotation}.png`})
    mark(`geometry-page-${index}-verified`)
    if(process.env.PDF_EXISTING_IMAGE_THUMBNAIL_DIAGNOSTIC==='first-stage'&&index===0){writeFileSync(`${directory}/diagnostic.json`,JSON.stringify({stage,geometry:pageGeometry[0],memory:process.memoryUsage(),pageErrors,consoleErrors,requests,operationsLog},null,2));throw Object.assign(Error('diagnostic-stop'),{code:'diagnostic-stop'})}
    await undo()
    if((process.env.PDF_EXISTING_IMAGE_THUMBNAIL_DIAGNOSTIC==='after-first-undo'&&index===0)||(process.env.PDF_EXISTING_IMAGE_THUMBNAIL_DIAGNOSTIC==='after-geometries'&&index===3)){writeFileSync(`${directory}/diagnostic.json`,JSON.stringify({stage,pageGeometry,memory:process.memoryUsage(),pageErrors,consoleErrors,requests,operationsLog},null,2));throw Object.assign(Error('diagnostic-stop'),{code:'diagnostic-stop'})}
  }

  // Move/resize and replacement use a different source target on page 1.
  const original = images[0].rect, moved = [original[0] + 24, original[1] + 18, original[2] + 44, original[3] + 38]
  const movedOperation = await stageGeometry(0, moved)
  mark('move-thumbnail-ready-wait')
  assert.deepEqual(movedOperation.rect, moved)
  await thumbnailLayer(0).waitFor({ state: 'visible' }); await page.waitForFunction(()=>{const i=document.querySelector('.pdf-thumbnail .pdf-existing-image-thumbnail-image');return i?.complete&&i.naturalWidth>0})
  const movedBox = await thumbnailLayer(0).locator('.pdf-existing-image-thumbnail-image').boundingBox(); assert(movedBox.width > 0 && movedBox.height > 0)
  await undo()
  const replacedOperation = await stageGeometry(0, original, true)
  mark('replacement-thumbnail-ready-wait')
  const replacementImage=thumbnailLayer(0).locator('.pdf-existing-image-thumbnail-image')
  await page.waitForFunction(()=>{const i=document.querySelector('.pdf-thumbnail .pdf-existing-image-thumbnail-image');return i?.complete&&i.naturalWidth>0})
  assert.equal(await thumbnailLayer(0).locator('.pdf-existing-image-thumbnail-ghost').count(), 0)
  const replacementPixels=await mountedPixels(replacementImage,36);assert.deepEqual([replacementPixels.width,replacementPixels.height],[9,4])
  const sourcePixels=await page.evaluate(async src=>{const i=new Image();i.src=src;await i.decode();if(i.naturalWidth*i.naturalHeight>36)throw Error(`replacement source dimensions invalid: ${i.naturalWidth}x${i.naturalHeight}`);const c=document.createElement('canvas');c.width=i.naturalWidth;c.height=i.naturalHeight;const x=c.getContext('2d');x.drawImage(i,0,0);return [...x.getImageData(0,0,c.width,c.height).data]},`data:image/png;base64,${fixture.png}`)
  assertPixelMatch(replacementPixels.rgbaBase64,sourcePixels,'replacement decoded pixels')
  await undo()
  if(process.env.PDF_EXISTING_IMAGE_THUMBNAIL_DIAGNOSTIC==='after-replacement'){writeFileSync(`${directory}/diagnostic.json`,JSON.stringify({stage,memory:process.memoryUsage(),replacementPixelBytes:Buffer.from(replacementPixels.rgbaBase64,'base64').length,pageErrors,consoleErrors,requests,operationsLog},null,2));throw Object.assign(Error('diagnostic-stop'),{code:'diagnostic-stop'})}

  // Each bake mode must mount real PNG pixels and project the expected footprint.
  const bakeKinds = [['flip-h', 0], ['flip-v', 1], ['crop', 2], ['opacity', 3], ['rotate-cw', 0], ['rotate-ccw', 2]]
  const bakeEvidence = []
  for (const [kind, targetPage] of bakeKinds) {
    const operation = await stageBake(targetPage, kind)
    await page.waitForFunction(index=>{const i=document.querySelectorAll('.pdf-thumbnail')[index]?.querySelector('.pdf-existing-image-thumbnail-image');return i?.complete&&i.naturalWidth>0},targetPage)
    const layer = page.locator('.pdf-thumbnail').nth(targetPage).locator('.pdf-existing-image-thumbnail-layer')
    const geometry = await layer.locator('.pdf-existing-image-thumbnail-image').evaluate(node => { const r=node.getBoundingClientRect(),p=node.parentElement.getBoundingClientRect();return {left:(r.left-p.left)/p.width,top:(r.top-p.top)/p.height,width:r.width/p.width,height:r.height/p.height} })
    const pageModel = model.pages[targetPage], [x1,y1,x2,y2]=operation.rect, crop=pageModel.cropBox, rotation=pageModel.rotation
    const transform=(x,y)=>{const px=x-crop.x,py=y-crop.y,w=crop.width,h=crop.height;if(rotation===90)return [py,px];if(rotation===180)return [w-px,py];if(rotation===270)return [h-py,w-px];return [px,h-py]}
    const corners=[[x1,y1],[x1,y2],[x2,y1],[x2,y2]].map(([x,y])=>transform(x,y)), xs=corners.map(v=>v[0]),ys=corners.map(v=>v[1]),vw=rotation%180?crop.height:crop.width,vh=rotation%180?crop.width:crop.height
    const expected={left:Math.min(...xs)/vw,top:Math.min(...ys)/vh,width:(Math.max(...xs)-Math.min(...xs))/vw,height:(Math.max(...ys)-Math.min(...ys))/vh}
    for (const key of Object.keys(expected)) assert(Math.abs(geometry[key]-expected[key])<.012, `${kind} ${key}: ${geometry[key]} != ${expected[key]}`)
    const imageElement=layer.locator('.pdf-existing-image-thumbnail-image'),pixels=await mountedPixels(imageElement)
    const sourceTarget=images[targetPage],readback=python({mode:'pixels',bytes:source.toString('base64'),target:{sourceSha256:sha(source),pageId:sourceTarget.pageId,imageId:sourceTarget.imageId,expectedImageSha256:sourceTarget.expectedImageSha256}})
    const originalPixels=python({mode:'pngPixels',image:readback.image})
    const bake=operation.bake, expectedPixels=transformPixels({...originalPixels,data:Buffer.from(originalPixels.rgbaBase64,'base64')},bake)
    assert.deepEqual([pixels.width,pixels.height],[expectedPixels.width,expectedPixels.height],`${kind} dimensions`)
    let pixelVerification
    if(bake.kind==='opacity'){
      const rawExpected=Buffer.from(expectedPixels.data)
      for(let i=3;i<rawExpected.length;i+=4)assert.equal(rawExpected[i],Math.round(255*bake.alpha),'raw opacity alpha factor')
      const mounted=Buffer.from(pixels.rgbaBase64,'base64');for(let i=3;i<mounted.length;i+=4)assert.equal(mounted[i],Math.round(255*bake.alpha),'mounted opacity alpha factor')
      const roundTrip=await canvasPngRoundTrip(page,{width:expectedPixels.width,height:expectedPixels.height,data:rawExpected})
      pixelVerification=assertPixelMatch(pixels.rgbaBase64,Buffer.from(roundTrip.rgbaBase64,'base64'),kind)
      pixelVerification={...pixelVerification,mode:'exactAlpha+canvasPngRoundTripRGB',rawExpectedSha256:sha(rawExpected),browserExpectedPngSha256:sha(Buffer.from(roundTrip.pngBase64,'base64')),mountedSha256:sha(mounted),rawAlpha:Math.round(255*bake.alpha),rgbNote:'RGB compared with the browser canvas PNG encode/decode result; alpha is checked exactly'}
    }else pixelVerification={...assertPixelMatch(pixels.rgbaBase64,expectedPixels.data,kind),mode:'exactRGBA',rawExpectedSha256:sha(Buffer.from(expectedPixels.data)),mountedSha256:sha(Buffer.from(pixels.rgbaBase64,'base64'))}
    bakeEvidence.push({kind,operation,geometry,expected,pixelSize:[pixels.width,pixels.height],pixelVerification})
    if(kind==='opacity'||kind==='rotate-cw'||kind==='rotate-ccw')await page.locator('.pdf-thumbnail').nth(targetPage).screenshot({path:`${directory}/thumbnail-${kind}.png`})
    await undo()
    if(process.env.PDF_EXISTING_IMAGE_THUMBNAIL_DIAGNOSTIC==='after-first-bake'&&bakeEvidence.length===1){writeFileSync(`${directory}/diagnostic.json`,JSON.stringify({stage,bakeEvidence,memory:process.memoryUsage(),pageErrors,consoleErrors,requests,operationsLog},null,2));throw Object.assign(Error('diagnostic-stop'),{code:'diagnostic-stop'})}
  }

  // Exercise the cached-ready redraw path by mounting, undoing and restaging the same target.
  const cacheOperation=await stageBake(2,'flip-h');await page.waitForFunction(()=>{const i=document.querySelectorAll('.pdf-thumbnail')[2]?.querySelector('.pdf-existing-image-thumbnail-image');return i?.complete&&i.naturalWidth>0});await undo()
  await page.locator('[data-pdf-ribbon-tab="home"]').click();await page.getByRole('button',{name:/^(重做|Redo)$/}).click();await waitPages()
  await page.waitForFunction(()=>{const i=document.querySelectorAll('.pdf-thumbnail')[2]?.querySelector('.pdf-existing-image-thumbnail-image');return i?.complete&&i.naturalWidth>0});assert.deepEqual(await getOperations(),[cacheOperation])
  await undo()

  // A late read must be cancelled and must not mount into a later draft generation.
  heldPixelResolve=()=>{}
  const readsBefore=pendingPixelRequests,delayed=await stageBake(0,'flip-v');await page.locator('.pdf-thumbnail').nth(0).locator('.pdf-existing-image-thumbnail-ghost').waitFor()
  for(let attempt=0;pendingPixelRequests===readsBefore&&attempt<40;attempt++)await delay(50)
  assert(pendingPixelRequests>readsBefore,'thumbnail starts an image-pixels request')
  await undo();heldPixelResolve?.();heldPixelResolve=undefined;await delay(300)
  assert.equal(await page.locator('.pdf-thumbnail .pdf-existing-image-thumbnail-layer').count(),0)
  assert(delayed.bake)

  // Actual preview consumes the one real bridge operation and replaces pending overlays.
  const previewOp=await stageGeometry(3,images[3].rect.map((value,index)=>value+(index<2?12:24)))
  const beforePreview=previewCount
  await page.locator('[data-pdf-ribbon-tab="edit"]').click();await page.getByRole('button',{name:'校验当前修改',exact:true}).click()
  await page.waitForFunction(()=>document.querySelector('.native-pdf-editor')?.dataset.pdfPreview==='true'&&document.querySelectorAll('.pdf-page').length===4&&document.querySelectorAll('.pdf-thumbnail').length===4&&document.querySelectorAll('.pdf-thumbnail .pdf-existing-image-thumbnail-layer').length===0,null,{timeout:30000})
  await page.locator('.pdf-page').nth(3).scrollIntoViewIfNeeded()
  await page.waitForFunction(()=>{const page=document.querySelectorAll('.pdf-page')[3]?.querySelector('canvas'),thumbnail=document.querySelectorAll('.pdf-thumbnail-page canvas')[3];return page?.width>0&&page?.height>0&&thumbnail?.width>0&&thumbnail?.height>0},null,{timeout:30000})
  await page.waitForFunction(()=>document.querySelectorAll('.pdf-thumbnail .pdf-existing-image-thumbnail-layer').length===0,null,{timeout:30000})
  assert(previewCount>beforePreview);assert.equal(await page.locator('.pdf-thumbnail .pdf-existing-image-thumbnail-layer').count(),0)
  assert.deepEqual((await getOperations()).map(op=>op.kind),['transformExistingImage'])
  const assetEvidence=await verifyAssets()
  const evidence={ok:true,scope:'transformExistingImage thumbnail browser smoke only',sourceSha256:sha(source),sourcePdf:`${directory}/source.pdf`,fixtureModel:`${directory}/fixture-model.json`,engineRuntime:engineRuntimeIdentity,frontendManifestSha256:manifestSha,pages:model.pages.map(({pageId,index,rotation,cropBox})=>({pageId,index,rotation,cropBox})),pageGeometry,imageCount:images.length,moveResize:{operation:movedOperation,geometry:movedBox},replacement:{operation:replacedOperation,pixelBytes:replacedOperation.image.length,pixelsMatch:true},bakes:bakeEvidence,cachedReadyRedraw:true,cancelledLatePixelRead:true,actualPreviewDeduplicatesPendingThumbnail:true,previewRequests:requests.filter(item=>item.kind==='preview').length,imagePixelReads:pendingPixelRequests,assets:assetEvidence,peakNodeRssBytes:peakRss,pageErrors,pageErrorsCount:pageErrors.length,consoleErrors,consoleErrorsCount:consoleErrors.length,browserVersion:browser.version()}
  assert.deepEqual(pageErrors,[]);assert.deepEqual(consoleErrors,[])
  await writeFile(`${directory}/operations.json`,JSON.stringify(operationsLog,null,2))
  await writeFile(`${directory}/evidence.json`,JSON.stringify(evidence,null,2));await page.screenshot({path:`${directory}/preview.png`,fullPage:true});console.log(JSON.stringify(evidence))
} catch(error) {
  await writeFile(`${directory}/operations.json`,JSON.stringify(operationsLog,null,2)).catch(()=>{})
  if(error?.code!=='diagnostic-stop'&&error?.code!=='red-probe-stop'){
    await writeFile(`${directory}/failure.json`,JSON.stringify({stage,error:String(error),pageErrors,consoleErrors,requests,operationsLog},null,2)).catch(()=>{})
    throw error
  }
  console.log(JSON.stringify({diagnosticStoppedAt:stage,directory,redProbe:error?.code==='red-probe-stop'}))
} finally { if(watchdog)clearInterval(watchdog);await browser?.close();server.kill('SIGTERM') }

