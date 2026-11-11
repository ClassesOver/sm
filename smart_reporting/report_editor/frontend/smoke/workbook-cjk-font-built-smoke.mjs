import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'
const frontend=process.cwd(),repo=new URL('../../../',`file://${frontend}/`).pathname,base='http://127.0.0.1:4232'
const families=[['Noto Sans CJK SC','思源黑体（内置）'],['Noto Serif CJK SC','思源宋体（内置）'],['LXGW WenKai','霞鹜文楷（内置）'],['Ma Shan Zheng','马善政毛笔楷书（内置）'],['ZCOOL XiaoWei','站酷小薇（内置）'],['SimSun','宋体（系统字体）'],['SimHei','黑体（系统字体）'],['Microsoft YaHei','微软雅黑（系统字体）'],['KaiTi','楷体（系统字体）'],['FangSong','仿宋（系统字体）']]
function python(payload){const result=spawnSync(`${repo}/.venv/bin/python`,['-c',`
import base64,json,sys
from io import BytesIO
from openpyxl import Workbook,load_workbook
from smart_reporting.report_editor.native_office import patch_office
p=json.load(sys.stdin)
if p['mode']=='create':
 b=Workbook();b.active.title='字体测试'
 for row in range(1,11):b.active.cell(row,1,'中文字体验证')
 f=BytesIO();b.save(f);print(base64.b64encode(f.getvalue()).decode())
elif p['mode']=='patch':print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 b=load_workbook(BytesIO(base64.b64decode(p['bytes'])));print(json.dumps([{'value':b.active.cell(row,1).value,'family':b.active.cell(row,1).font.name} for row in range(1,11)]))
`],{input:JSON.stringify(payload),encoding:'utf8',cwd:repo});assert.equal(result.status,0,result.stderr);return result.stdout.trim()}
const bytes=Buffer.from(python({mode:'create'}),'base64'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',context={documentId:'cjk-font-probe',format:'xlsx',revision:1,parentRevision:null,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:'cjk.xlsx',size:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),mediaType:media},origin:'upload'}
const server=spawn('./node_modules/.bin/vite',['preview','--host','127.0.0.1','--port','4232','--strictPort'],{cwd:frontend,stdio:'ignore'})
let browser,saved,payload
try{
 for(let i=0;i<120;i++){try{if((await fetch(`${base}/reports/v1/editor/assets/native.html`)).ok)break}catch{}await delay(250)}
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1500,height:1100}}),errors=[],assets=[]
 page.on('pageerror',error=>errors.push(error.message))
 page.on('response',response=>{const path=new URL(response.url()).pathname;if(path.startsWith('/reports/v1/editor/assets/')&&/\.(?:js|woff2)$/.test(path))assets.push((async()=>{assert.equal(response.status(),200);const body=await response.body();assert.equal(createHash('sha256').update(body).digest('hex'),createHash('sha256').update(readFileSync(`../static/${path.slice('/reports/v1/editor/assets/'.length)}`)).digest('hex'));return path})())})
 const routeRevision=async(revision,file)=>{
  await page.route(`**/reports/v1/native/cjk-font-probe/${revision}/api/context`,route=>route.fulfill({json:{context:{...context,revision,parentRevision:revision===1?null:1,sourceFile:{...context.sourceFile,size:file.length,sha256:createHash('sha256').update(file).digest('hex')}},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}}))
  await page.route(`**/reports/v1/native/cjk-font-probe/${revision}/api/file`,route=>route.fulfill({body:file,contentType:media}))
 }
 await routeRevision(1,bytes)
 await page.route('**/reports/v1/native/cjk-font-probe/1/api/save',async route=>{payload=route.request().postDataJSON();saved=Buffer.from(python({mode:'patch',bytes:bytes.toString('base64'),operations:payload.operations}),'base64');await route.fulfill({json:{documentId:'cjk-font-probe',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:'/cjk.xlsx'}},editor:{openUrl:'/reports/v1/native/cjk-font-probe/2'},validation:{issues:[]}}})})
 await page.route(/\/reports\/v1\/native\/cjk-font-probe\/[12]$/,async route=>route.fulfill({response:await route.fetch({url:`${base}/reports/v1/editor/assets/native.html`})}))
 await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/cjk-font-probe/1'))
 await page.goto(`${base}/reports/v1/editor/assets/native.html`);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
 const fonts=await page.evaluate(async()=>{await document.fonts.ready;return ['Noto Sans CJK SC','Noto Serif CJK SC','LXGW WenKai','Ma Shan Zheng','ZCOOL XiaoWei'].map(family=>({family,available:document.fonts.check(`12px "${family}"`,'中文'),faces:[...document.fonts].filter(face=>face.family.replaceAll('"','').replaceAll("'",'')===family).map(face=>face.status)}))})
 for(const font of fonts){assert.equal(font.available,true);assert(font.faces.includes('loaded'))}
 const goto=async row=>{await page.locator('[data-ribbon-tab="Home"]').click();await page.locator('[data-ribbon-command="goto-open"]').click();await page.locator('[data-goto-reference]').fill(`A${row}`);await page.locator('.workbook-ribbon-goto-dialog button[type="submit"]').click()}
 for(const [index,[family,label]] of families.entries()){
  await goto(index+1);const menu=page.locator('[data-ribbon-control="font-family"]');assert.equal(await menu.locator(`option[value="${family}"]`).textContent(),label);await menu.selectOption(family);await page.waitForTimeout(100);assert.equal(await menu.inputValue(),family)
 }
 await page.screenshot({path:'/tmp/workbook-cjk-font-built.png',fullPage:true})
 await page.locator('[data-action="save"]').click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent==='已保存修订 2',null,{timeout:60000})
 const actual=JSON.parse(python({mode:'inspect',bytes:saved.toString('base64')}));assert.deepEqual(actual.map(cell=>cell.family),families.map(([family])=>family));assert(actual.every(cell=>cell.value==='中文字体验证'))
 await routeRevision(2,saved);await page.addInitScript(()=>history.replaceState(null,'','/reports/v1/native/cjk-font-probe/2'));await page.goto(`${base}/reports/v1/native/cjk-font-probe/2`);await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000})
 for(const [index,[family]] of families.entries()){await goto(index+1);assert.equal(await page.locator('[data-ribbon-control="font-family"]').inputValue(),family)}
 const paths=await Promise.all(assets),fontPaths=[...new Set(paths.filter(path=>path.endsWith('.woff2')))];assert(fontPaths.some(path=>/NotoSansCJKsc/.test(path)));assert(fontPaths.some(path=>/NotoSerifCJKsc/.test(path)));for(const name of ['LXGWWenKai','MaShanZheng','ZCOOLXiaoWei'])assert(fontPaths.some(path=>path.includes(name)));assert.deepEqual(errors,[])
 console.log(JSON.stringify({ok:true,preview:true,fonts,actual,operations:payload.operations,fontPaths,js200AndHashMatch:paths.filter(path=>path.endsWith('.js')).length,assets:[...new Set(paths.filter(path=>/workbook-(main|engine-|structure|chart-references|xml-parser)/.test(path)))],pageErrors:errors}))
}finally{await browser?.close();server.kill()}
