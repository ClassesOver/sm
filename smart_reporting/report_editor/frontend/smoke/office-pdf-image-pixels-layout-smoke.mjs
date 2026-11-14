// 真实产品窗口/样式和浏览器图像解码；显式来源与refresh回调不代表PDF保存链或生产授权。
import assert from 'node:assert/strict'
import {mkdir,writeFile,readFile} from 'node:fs/promises'
import {resolve,dirname} from 'node:path'
import {fileURLToPath} from 'node:url'
import {createHash} from 'node:crypto'
import {createServer} from 'vite'
import {chromium} from 'playwright'
import AxeBuilder from '@axe-core/playwright'
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..'),output=resolve(process.env.PDF_PIXEL_LAYOUT_OUTPUT??'/tmp/office-pdf-image-pixels-layout-20261112')
await mkdir(output,{recursive:true})
const html=`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PDF 图像像素窗口</title></head><body><main><h1>PDF 图像</h1><button id="open">编辑图像</button><div id="host"></div></main><script type="module">
import '/src/style.css';import '/src/office-theme.css';import '/src/pdf.css';
import {bindPdfExistingImagePanel} from '/src/pdf-existing-image.ts';import {NativeDraft} from '/src/native-draft.ts';
const sha='a'.repeat(64),pageId='sha256:'+sha+':page:0';
const images=[0,1].map(index=>({pageId,pageIndex:0,rect:[60,90,160,170],imageId:(index?'d':'b').repeat(64),expectedImageSha256:'c'.repeat(64),aboveText:true,editable:true,replaceable:true,bakeable:true}));
const draft=new NativeDraft({documentId:'pixel-ui',revision:1,sourceSha256:sha,scope:{database:'fixture',companyId:'c',userId:'u',threadId:'t'}},localStorage);
const panel=bindPdfExistingImagePanel({root:document.querySelector('#host'),draft,pages:()=>[{pageId,index:0,rotation:0,cropBox:{x:0,y:0,width:400,height:500},mediaBox:{x:0,y:0,width:400,height:500}}],images:()=>images,unavailable:()=>null,refresh:async()=>{if(window.fixture?.failRefresh)throw Error('预览服务暂不可用')},status:message=>window.fixtureStatus=message});
document.querySelector('#open').onclick=()=>panel.open();window.fixture={panel,draft,images};
</script></body></html>`
const server=await createServer({root,configFile:false,optimizeDeps:{noDiscovery:true,include:[]},server:{host:'127.0.0.1',port:0},plugins:[{name:'pixel-ui-fixture',configureServer(server){server.middlewares.use(async(req,res,next)=>{if(req.url!=='/pixel-ui')return next();res.setHeader('Content-Type','text/html');res.end(await server.transformIndexHtml('/pixel-ui',html))})}}]})
await server.listen();const base=`http://127.0.0.1:${server.httpServer.address().port}`
const browser=await chromium.launch({headless:true}),evidence={scope:'product component fixture; no PDF save',cases:[],errors:[],sources:{}}
try{
 for(const viewport of [{width:1440,height:900},{width:640,height:360},{width:390,height:320},{width:320,height:640}]){
  const context=await browser.newContext({viewport}),page=await context.newPage();page.on('pageerror',e=>evidence.errors.push(e.message))
  await page.goto(base+'/pixel-ui');await page.waitForFunction(()=>window.fixture);await page.locator('#open').click()
  const dialog=page.getByRole('dialog',{name:'编辑已有图像',exact:true}),kind=page.getByRole('combobox',{name:'已有图像像素编辑',exact:true})
  await kind.selectOption('crop')
  const fields=[]
  for(const name of ['左','上','右','下']){
   const field=page.getByRole('spinbutton',{name:'裁去'+name+'侧百分比',exact:true});await field.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab')
   const rect=await field.evaluate(node=>{const r=node.getBoundingClientRect(),s=getComputedStyle(node),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return {x:r.x,y:r.y,width:r.width,height:r.height,hit:hit===node,focused:document.activeElement===node,outline:s.outlineWidth}})
   assert.ok(rect.width>=48&&rect.height>=28&&rect.hit&&rect.focused,JSON.stringify({viewport,name,rect}));fields.push({name,...rect})
  }
  if(process.env.PDF_PIXEL_LAYOUT_GEOMETRY_ONLY==='1'){evidence.cases.push({viewport,fields});await context.close();continue}
  await page.getByRole('spinbutton',{name:'裁去左侧百分比',exact:true}).fill('25')
  await page.getByRole('spinbutton',{name:'裁去右侧百分比',exact:true}).fill('')
  await dialog.getByRole('button',{name:'应用',exact:true}).click()
  assert.equal(await dialog.isVisible(),true);assert.deepEqual(await page.evaluate(()=>window.fixture.draft.operations),[])
  assert.equal(await page.getByRole('alert').evaluate(node=>document.activeElement===node),true)
  await page.getByRole('spinbutton',{name:'裁去右侧百分比',exact:true}).fill('0')
  const axe=await new AxeBuilder({page}).include('dialog').analyze();assert.deepEqual(axe.violations,[])
  await page.screenshot({path:resolve(output,`crop-error-${viewport.width}x${viewport.height}.png`)})
  await page.keyboard.press('Escape');assert.equal(await page.locator('#open').evaluate(node=>document.activeElement===node),true)
  assert.deepEqual(await page.evaluate(()=>window.fixture.draft.operations),[])
  const applied=[]
  for(const mode of ['flip-h','flip-v','crop','opacity']){
   await page.locator('#open').click();await kind.selectOption(mode)
   assert.equal(await page.getByRole('spinbutton',{name:'已有图像宽度',exact:true}).isDisabled(),true)
   assert.equal(await page.getByRole('button',{name:'替换为新图像…',exact:true}).isDisabled(),true)
   assert.equal(await page.getByRole('spinbutton',{name:'裁去左侧百分比',exact:true}).isVisible(),mode==='crop')
   assert.equal(await page.getByRole('spinbutton',{name:'图像透明度百分比',exact:true}).isVisible(),mode==='opacity')
   if(mode==='crop')await page.getByRole('spinbutton',{name:'裁去左侧百分比',exact:true}).fill('25')
   if(mode==='opacity')await page.getByRole('spinbutton',{name:'图像透明度百分比',exact:true}).fill('25')
   await dialog.getByRole('button',{name:'应用',exact:true}).click();assert.equal(await dialog.isVisible(),false)
   const operations=await page.evaluate(()=>window.fixture.draft.operations);assert.equal(operations.length,1)
   assert.deepEqual(operations[0].rect,mode==='crop'?[85,90,160,170]:[60,90,160,170])
   assert.deepEqual(operations[0].bake,mode==='crop'?{kind:'crop',crop:{l:.25,t:0,r:1,b:1}}:mode==='opacity'?{kind:'opacity',alpha:.75}:{kind:'flip',axis:mode==='flip-h'?'h':'v'})
   applied.push({mode,operation:operations[0]});await page.evaluate(()=>window.fixture.draft.undo())
  }
  // 延迟的是回执时机；PNG解码、绘制和编码仍由浏览器原生API实际执行。
  await page.locator('#open').click()
  await page.evaluate(()=>{const native=window.createImageBitmap.bind(window);window.createImageBitmap=async(...args)=>{const bitmap=await native(...args);await new Promise(resolve=>window.releaseDecode=resolve);return bitmap}})
  const png=Buffer.from(await page.evaluate(()=>{const canvas=document.createElement('canvas');canvas.width=8;canvas.height=4;const ctx=canvas.getContext('2d');ctx.fillStyle='#C00000';ctx.fillRect(0,0,8,4);return canvas.toDataURL('image/png').split(',')[1]}),'base64')
  const chooser=page.waitForEvent('filechooser');await page.getByRole('button',{name:'替换为新图像…',exact:true}).click();await(await chooser).setFiles({name:'真实解码.png',mimeType:'image/png',buffer:png})
  await page.waitForFunction(()=>window.releaseDecode&&document.querySelector('dialog').getAttribute('aria-busy')==='true')
  assert.equal(await dialog.getByRole('button',{name:'应用',exact:true}).isDisabled(),true)
  const busyAxe=await new AxeBuilder({page}).include('dialog').analyze();assert.deepEqual(busyAxe.violations,[])
  await page.screenshot({path:resolve(output,`busy-${viewport.width}x${viewport.height}.png`)})
  await page.getByRole('combobox',{name:'已有图像选择',exact:true}).selectOption('1');await page.evaluate(()=>window.releaseDecode())
  await page.waitForTimeout(100)
  assert.equal(await page.getByRole('status',{name:'图像替换状态',exact:true}).textContent(),'不替换像素')
  assert.equal(await dialog.getByRole('button',{name:'应用',exact:true}).isDisabled(),false)
  await page.keyboard.press('Escape');assert.deepEqual(await page.evaluate(()=>window.fixture.draft.operations),[])
  await page.locator('#open').click();await kind.selectOption('flip-h');await page.evaluate(()=>window.fixture.failRefresh=true)
  await dialog.getByRole('button',{name:'应用',exact:true}).click();assert.equal(await dialog.isVisible(),false)
  assert.ok(await page.evaluate(()=>window.fixtureStatus.includes('已暂存')&&window.fixtureStatus.includes('预览服务暂不可用')))
  assert.equal((await page.evaluate(()=>window.fixture.draft.operations)).length,1)
  evidence.cases.push({viewport,fields,axeViolations:axe.violations.length,busyAxeViolations:busyAxe.violations.length,cancelFocus:true,blankRejected:true,applied,realDecodeStaleResultDiscarded:true,refreshErrorVisibleViaStatus:true})
  await context.close()
 }
 assert.deepEqual(evidence.errors,[])
 for(const file of ['src/pdf-existing-image.ts','src/pdf.css'])evidence.sources[file]=createHash('sha256').update(await readFile(resolve(root,file))).digest('hex')
 evidence.ok=true
}finally{await writeFile(resolve(output,'evidence.json'),JSON.stringify(evidence,null,2));await browser.close();await server.close()}
console.log(JSON.stringify(evidence))
