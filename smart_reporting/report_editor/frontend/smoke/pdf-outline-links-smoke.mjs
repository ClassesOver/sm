import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {spawnSync} from 'node:child_process'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright'

const base=process.env.PDF_OUTLINE_SMOKE_BASE??'http://127.0.0.1:5173'
const output=process.env.PDF_OUTLINE_SMOKE_OUTPUT??'/tmp/office-pdf-source-gaps-20261113/browser'
const staticDir=process.env.PDF_OUTLINE_SMOKE_STATIC_DIR
const digest=bytes=>createHash('sha256').update(bytes).digest('hex')
const manifestSha256=staticDir?digest(await readFile(resolve(staticDir,'.vite/manifest.json'))):undefined
if(process.env.PDF_OUTLINE_SMOKE_MANIFEST_SHA256)assert.equal(manifestSha256,process.env.PDF_OUTLINE_SMOKE_MANIFEST_SHA256)
const repo=fileURLToPath(new URL('../../../../',import.meta.url))
const fixture=spawnSync(`${repo}/.venv/bin/python`,[fileURLToPath(new URL('./pdf-outline-links-source.py',import.meta.url))],{encoding:'utf8'})
assert.equal(fixture.status,0,fixture.stderr)
const source=Buffer.from(JSON.parse(fixture.stdout).bytes,'base64'),sha256=createHash('sha256').update(source).digest('hex')
await mkdir(output,{recursive:true});await writeFile(`${output}/outline-source.pdf`,source)
const browser=await chromium.launch({headless:true,...(process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE?{executablePath:process.env.REPORT_EDITOR_CHROMIUM_EXECUTABLE}:{})})
try {
  const context=await browser.newContext({viewport:{width:1440,height:900}}),errors=[],popups=[],assets=[],identityTasks=[]
  context.on('page',page=>{
    page.on('pageerror',error=>errors.push(error.message))
    page.on('console',entry=>{if(entry.type()==='error')errors.push(entry.text())})
    page.on('response',response=>{
      const url=new URL(response.url()),prefix='/reports/v1/editor/assets/'
      if(!staticDir||url.origin!==new URL(base).origin||!url.pathname.startsWith(prefix)||!(/\.(m?js|css)$/.test(url.pathname)))return
      const task=(async()=>{
        const relative=decodeURIComponent(url.pathname.slice(prefix.length))
        assert.equal(response.status(),200,relative)
        const actual=await response.body(),expected=await readFile(resolve(staticDir,relative))
        const sha256=digest(actual);assert.equal(sha256,digest(expected),`构建资源身份不匹配：${relative}`)
        assets.push({path:relative,sha256,size:actual.length})
      })()
      identityTasks.push(task)
      void task.catch(()=>{})
    })
  })
  await context.route(/https?:\/\/example\.com\/.*/,route=>route.fulfill({contentType:'text/html',body:'<!doctype html><title>Bookmark target</title><p>Controlled external bookmark target</p>'}))
  const page=await context.newPage()
  const documentId='outline-links-source'
  await page.route(`**/reports/v1/native/${documentId}/1/api/context`,route=>route.fulfill({json:{
    context:{documentId,revision:1,parentRevision:null,format:'pdf',origin:'upload',scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'outline-links.pdf',size:source.length,sha256,mediaType:'application/pdf'}},
    csrfToken:'fixture',capabilities:{pdf_editor:true},editingEnabled:false,
  }}))
  await page.route(`**/reports/v1/native/${documentId}/1/api/file`,route=>route.fulfill({body:source,contentType:'application/pdf'}))
  await page.route(`**/reports/v1/native/${documentId}/1`,async route=>route.fulfill({response:await route.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
  await page.goto(`${base}/reports/v1/native/${documentId}/1`)
  await page.waitForFunction(()=>document.querySelectorAll('.pdf-page').length===2&&document.querySelector('.pdf-page-content canvas'),null,{timeout:60000})
  await page.locator('[data-pdf-ribbon-tab="view"]').click()
  const toggle=page.locator('[data-source-command-id="genoffice.pdf.view.navigation.outline"]')
  await toggle.click()
  const panel=page.getByRole('navigation',{name:'PDF 目录大纲',exact:true})
  const before=await page.evaluate(()=>Object.entries(localStorage))
  assert.deepEqual(await panel.locator('.pdf-outline-link').allTextContents(),['First page','Website','Contact','HTTP','Second page'])
  assert.equal(await panel.getByRole('link',{name:'Contact',exact:true}).getAttribute('href'),'mailto:review@example.com')
  for(const [name,href,keyboard] of [['Website','https://example.com/report',false],['HTTP','http://example.com/help',true]]) {
    const link=panel.getByRole('link',{name,exact:true})
    assert.equal(await link.getAttribute('target'),'_blank');assert.equal(await link.getAttribute('rel'),'noopener noreferrer')
    const popupPromise=context.waitForEvent('page')
    if(keyboard){await link.focus();await page.keyboard.press('Enter')}else await link.click()
    const popup=await popupPromise;await popup.waitForLoadState()
    assert.equal(popup.url(),href);assert.equal(await popup.evaluate(()=>window.opener===null),true)
    popups.push({name,href:popup.url(),activation:keyboard?'Enter':'click',openerNull:true});await popup.close()
  }
  await panel.getByRole('button',{name:'Second page',exact:true}).click()
  await page.waitForFunction(()=>document.querySelector('.pdf-page.is-active')?.getAttribute('data-page-id')?.endsWith(':page:1'))
  assert.equal(await page.evaluate(()=>document.activeElement?.textContent),'Second page')
  const active=await panel.locator('[aria-current="page"]').allTextContents();assert.deepEqual(active,['Second page'])
  assert.equal(await panel.locator('a[aria-current]').count(),0)
  // 阅读位置偏好可变化；没有编辑操作/新修订写入。
  const operations=await page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.includes('outline-links-source')).map(([,value])=>{try{return JSON.parse(value)?.operations??[]}catch{return []}}))
  assert.ok(operations.every(items=>items.length===0))
  const layouts=[]
  for(const [width,height] of [[1440,900],[390,600]]) {
    await page.setViewportSize({width,height});await page.waitForTimeout(100)
    const bounds=await panel.getByRole('link',{name:'Website',exact:true}).boundingBox();assert.ok(bounds&&bounds.x>=0&&bounds.x+bounds.width<=width+1)
    layouts.push({width,height,bounds});await page.screenshot({path:`${output}/outline-${width}.png`,fullPage:true})
  }
  await Promise.all(identityTasks)
  if(staticDir){assert.ok(assets.some(asset=>asset.path.endsWith('.css')));assert.ok(assets.some(asset=>/\.m?js$/.test(asset.path)))}
  assert.deepEqual(errors,[])
  const receipt={ok:true,source:{sha256,size:source.length},build:{staticDir,manifestSha256},assets:assets.sort((a,b)=>a.path.localeCompare(b.path)),rows:await panel.locator('.pdf-outline-link').allTextContents(),popups,active,operations,layouts,errors,initialStorageEntries:before.length}
  await writeFile(`${output}/evidence.json`,JSON.stringify(receipt,null,2));console.log(JSON.stringify(receipt,null,2))
} finally {await browser.close()}
