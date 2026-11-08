import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdtemp, readFile, writeFile, mkdir, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const frontend = fileURLToPath(new URL('../', import.meta.url)), repo = fileURLToPath(new URL('../../../../', import.meta.url))
const port = Number(process.env.DOCX_VERTICAL_SMOKE_PORT ?? 4193), baseUrl = `http://127.0.0.1:${port}`
const temporary = await mkdtemp(join(tmpdir(), 'docx-vertical-smoke-')), sha = bytes => createHash('sha256').update(bytes).digest('hex')
const mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const python = input => {
  const result = spawnSync(join(repo, '.venv/bin/python'), ['-c', `
import base64,json,sys
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
from docx import Document
from docx.oxml.ns import qn
from lxml import etree
from smart_reporting.reporting.delivery.docx_native import inspect_docx,patch_docx
from smart_reporting.reporting.tests.test_docx_vertical_align import source,without_vertical
p=json.load(sys.stdin)
if p['mode']=='source': print(base64.b64encode(source()).decode())
elif p['mode']=='inspect': print(json.dumps(inspect_docx(base64.b64decode(p['bytes']))))
elif p['mode']=='patch': print(base64.b64encode(patch_docx(base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 before,after=Document(p['source']),Document(p['output']);a=before.paragraphs[0]._p;b=after.paragraphs[0]._p
 assert etree.tostring(a.find(qn('w:pPr')),method='c14n')==etree.tostring(b.find(qn('w:pPr')),method='c14n')
 old,new=a.findall('.//'+qn('w:r')),b.findall('.//'+qn('w:r'));assert len(old)==len(new)==3
 for x,y in zip(old,new):
  assert x.find(qn('w:t')).text==y.find(qn('w:t')).text
  assert without_vertical(x.find(qn('w:rPr')))==without_vertical(y.find(qn('w:rPr')))
  prop=y.find(qn('w:rPr'));v=prop.find(qn('w:vertAlign')) if prop is not None else None
  assert (v.get(qn('w:val')) if v is not None else None)==p['value']
 link=b.find(qn('w:hyperlink'));assert link.get(qn('w:tooltip'))=='kept tooltip'
 assert after.part.rels[link.get(qn('r:id'))].target_ref=='https://keep.test'
 props=link.find(qn('w:r')).find(qn('w:rPr'));assert props is None or props.find(qn('w:rStyle')) is None
 assert etree.tostring(before.paragraphs[1]._p)==etree.tostring(after.paragraphs[1]._p)
 with ZipFile(p['source']) as x,ZipFile(p['output']) as y:
  names={n for n in x.namelist() if not n.endswith('/')};assert names=={n for n in y.namelist() if not n.endswith('/')}
  for n in names-{'word/document.xml','docProps/core.xml'}:assert x.read(n)==y.read(n),n
 print(json.dumps({'value':p['value'],'texts':[r.find(qn('w:t')).text for r in new],'mixedStylesPreserved':True,'linkTooltipAndPlainStylePreserved':True,'untouchedPartsPreserved':True}))
`], { cwd: repo, env: { ...process.env, PYTHONPATH: repo }, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 })
  if (result.status !== 0) throw new Error(result.stderr || result.stdout)
  return result.stdout.trim()
}
const versions = new Map([[1, Buffer.from(python({ mode: 'source' }), 'base64')]]), models = new Map()
const receipts = [], operations = []
models.set(1, JSON.parse(python({ mode: 'inspect', bytes: versions.get(1).toString('base64') })))
await writeFile(join(temporary, 'source.docx'), versions.get(1))
const server = spawn('./node_modules/.bin/vite', ['--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: frontend, stdio: 'ignore' })
let browser
try {
  for (let i=0;i<120;i++) { try { if ((await fetch(baseUrl+'/reports/v1/editor/assets/native.html')).ok) break } catch {} await delay(250) }
  browser=await chromium.launch({headless:true,executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE??'/usr/bin/chromium'})
  const page=await browser.newPage({viewport:{width:1600,height:1000},acceptDownloads:true}),errors=[]
  page.on('pageerror',error=>errors.push(error.message))
  await page.route('**/favicon.ico',route=>route.fulfill({status:200,body:''}))
  const revision=route=>Number(new URL(route.request().url()).pathname.split('/')[5])
  await page.route('**/reports/v1/native/vertical-fixture/*/api/context',route=>{
    const rev=revision(route),bytes=versions.get(rev)
    return route.fulfill({json:{context:{documentId:'vertical-fixture',revision:rev,parentRevision:rev===1?null:rev-1,format:'docx',sourceFile:{path:'source.docx',size:bytes.length,sha256:sha(bytes),mediaType:mime},scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},origin:'upload'},editingEnabled:true,csrfToken:'fixture',capabilities:{docx_editor:true}}})
  })
  await page.route('**/reports/v1/native/vertical-fixture/*/api/file',route=>route.fulfill({body:versions.get(revision(route)),contentType:mime}))
  await page.route('**/reports/v1/native/vertical-fixture/*/api/preview',route=>{const model=models.get(revision(route));assert.deepEqual(route.request().postDataJSON().operations,[]);return route.fulfill({json:{sourceSha256:model.sourceSha256,draftSha256:model.sourceSha256,model}})})
  await page.route('**/reports/v1/native/vertical-fixture/*/api/save',route=>{
    const rev=revision(route),payload=route.request().postDataJSON();assert.equal(payload.expectedSha256,sha(versions.get(rev)))
    const next=Buffer.from(python({mode:'patch',bytes:versions.get(rev).toString('base64'),operations:payload.operations}),'base64')
    versions.set(rev+1,next);models.set(rev+1,JSON.parse(python({mode:'inspect',bytes:next.toString('base64')})));operations.push({revision:rev+1,operations:payload.operations})
    return route.fulfill({json:{documentId:'vertical-fixture',revision:rev+1,parentRevision:rev,revisionRegistered:true,validation:{ok:false,issues:[{code:'fixture_review',message:'保留下载'}]},artifacts:{word:{downloadUrl:`/vertical-download-${rev+1}.docx`,sha256:sha(next),size:next.length}},editor:{openUrl:`/reports/v1/native/vertical-fixture/${rev+1}`}}})
  })
  await page.route(/\/vertical-download-\d+\.docx$/,route=>{const rev=Number(route.request().url().match(/vertical-download-(\d+)/)[1]);return route.fulfill({body:versions.get(rev),contentType:mime,headers:{'Content-Disposition':`attachment; filename="vertical-${rev}.docx"`}})})
  await page.route(/\/reports\/v1\/native\/vertical-fixture\/[1-4]$/,async route=>route.fulfill({response:await route.fetch({url:baseUrl+'/reports/v1/editor/assets/native.html'})}))
  const open=async rev=>{await page.goto(baseUrl+`/reports/v1/native/vertical-fixture/${rev}`);try{await page.locator('.docx-source-home').waitFor({timeout:60000})}catch{throw new Error(JSON.stringify({errors,body:await page.locator('body').innerText()}))}}
  const clickText=async()=>page.getByRole('textbox',{name:'Word 文档编辑区'}).locator('p').filter({hasText:'A😀BCkeep'}).click()
  const button=kind=>page.locator(`.docx-source-home [data-action="${kind}"]`)
  const active=async kind=>button(kind).getAttribute('aria-pressed')
  await open(1);await clickText();assert.equal(await button('superscript').isEnabled(),true)
  await button('superscript').click();assert.equal(await active('superscript'),'true')
  await page.keyboard.press('Control+z');assert.equal(await active('superscript'),'false')
  await page.keyboard.press('Control+Shift+z');assert.equal(await active('superscript'),'true')
  await page.reload();await page.locator('.docx-source-home').waitFor({timeout:60000});await clickText();assert.equal(await active('superscript'),'true')
  for (const [rev,value,action] of [[1,'superscript',null],[2,'subscript','subscript'],[3,'baseline','subscript']]) {
    if(rev>1){await open(rev);await clickText();assert.equal(await active(rev===2?'superscript':'subscript'),'true')}
    if(action)await button(action).click()
    await page.locator('[data-action="save"]').click();await page.getByRole('link',{name:'下载 Word',exact:true}).waitFor({timeout:60000})
    assert.deepEqual(operations.at(-1).operations,[{kind:'setParagraphVerticalAlign',blockId:models.get(rev).blocks[0].blockId,expectedObjectSha256:models.get(rev).blocks[0].expectedObjectSha256,value}])
    const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('link',{name:'下载 Word',exact:true}).click()])
    const bytes=await readFile(await download.path());assert.equal(sha(bytes),sha(versions.get(rev+1)))
    const path=join(temporary,`revision-${rev+1}.docx`);await writeFile(path,bytes)
    receipts.push({revision:rev+1,sha256:sha(bytes),...JSON.parse(python({mode:'verify',source:join(temporary,'source.docx'),output:path,value}))})
    assert.equal(await button('superscript').isDisabled(),true)
  }
  await open(4);await clickText();assert.equal(await active('superscript'),'false');assert.equal(await active('subscript'),'false')
  assert.equal(sha(await readFile(join(temporary,'source.docx'))),sha(versions.get(1)));assert.deepEqual(errors,[])
  const evidence={ok:true,browserVersion:browser.version(),sourceSha256:sha(versions.get(1)),receipts,operations,desktopVerified:false,provenance:'authorization/revisions use browser route substitutes; actual packed bridge and independent python-docx/lxml readback'}
  if(process.env.DOCX_VERTICAL_SMOKE_EVIDENCE_DIR){const dir=process.env.DOCX_VERTICAL_SMOKE_EVIDENCE_DIR;await mkdir(dir,{recursive:true});for(const[rev,bytes]of versions)await writeFile(join(dir,`revision-${rev}.docx`),bytes);await writeFile(join(dir,'evidence.json'),JSON.stringify(evidence,null,2))}
  console.log(JSON.stringify(evidence))
}finally{if(browser)await browser.close();server.kill();await rm(temporary,{recursive:true,force:true})}
