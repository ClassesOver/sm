import assert from 'node:assert/strict'
import {createServer} from 'node:http'
import {spawn,spawnSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {mkdtemp,mkdir,readFile,writeFile} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {setTimeout as delay} from 'node:timers/promises'
import {chromium} from 'playwright'
const frontend=fileURLToPath(new URL('../',import.meta.url)),repo=fileURLToPath(new URL('../../../../',import.meta.url)),port=Number(process.env.SPARKLINE_SMOKE_PORT??4273),base=`http://127.0.0.1:${port}`
const temporary=await mkdtemp(join(tmpdir(),'sparkline-built-')),sha=b=>createHash('sha256').update(b).digest('hex'),media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',documentId='sparkline-built'
const sheetName="迷你图 O'Brien",externalName="来源 '中文",quote=name=>"'"+name.replaceAll("'","''")+"'"
const python=input=>{const r=spawnSync(join(repo,'.venv/bin/python'),['-c',String.raw`
import base64,json,re,sys
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
from hashlib import sha256
from lxml import etree as E
from openpyxl import Workbook
p=json.load(sys.stdin);ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main','x14':'http://schemas.microsoft.com/office/spreadsheetml/2009/9/main','xm':'http://schemas.microsoft.com/office/excel/2006/main'}
if p['mode']=='fixture':
 b=Workbook();s=b.active;s.title=p['sheetName'];other=b.create_sheet(p['externalName'])
 for row in range(1,9):
  for col,value in enumerate([1,-2,3],2):s.cell(row,col,value)
 for col,value in enumerate([-2,8,1],2):other.cell(2,col,value)
 s['A1']='保真';other['A1']='外表来源';s.column_dimensions['G'].width=20
 f=BytesIO();b.save(f)
 with ZipFile(BytesIO(f.getvalue())) as z:parts={n:z.read(n) for n in z.namelist()}
 ref="'"+p['externalName'].replace("'","''")+"'!$B$2:$D$2"
 group='<x14:sparklineGroup data-unknown="preserve-me" customFlag="77" displayEmptyCellsAs="gap"><x14:colorSeries rgb="FFA1B2C3"/><x14:colorNegative rgb="FF445566"/><x14:sparklines><x14:sparkline><xm:f>'+ref.replace('&','&amp;').replace("'",'&apos;')+'</xm:f><xm:sqref>G2</xm:sqref></x14:sparkline></x14:sparklines></x14:sparklineGroup>'
 ext='<extLst><ext uri="{FOREIGN-KEEP}"><keep:payload xmlns:keep="urn:smoke:keep" value="中文 &amp; opaque"/></ext><ext uri="{05C60535-1F16-4fd2-B633-F4F36F0B64E0}"><x14:sparklineGroups xmlns:x14="'+ns['x14']+'" xmlns:xm="'+ns['xm']+'">'+group+'</x14:sparklineGroups></ext></extLst>'
 parts['xl/worksheets/sheet1.xml']=parts['xl/worksheets/sheet1.xml'].replace(b'</worksheet>',ext.encode()+b'</worksheet>')
 parts['customXml/keep.xml']=b'<keep value="opaque"/>'
 out=BytesIO()
 with ZipFile(out,'w',ZIP_DEFLATED) as z:
  for n,v in parts.items():z.writestr(n,v)
 print(base64.b64encode(out.getvalue()).decode())
elif p['mode']=='patch':
 from smart_reporting.report_editor.native_office import patch_office
 print(base64.b64encode(patch_office('xlsx',base64.b64decode(p['bytes']),p['operations'])).decode())
else:
 data=base64.b64decode(p['bytes'])
 with ZipFile(BytesIO(data)) as z:
  assert z.testzip() is None
  for n in z.namelist():
   if n.endswith(('.xml','.rels')):E.fromstring(z.read(n))
  xml=z.read('xl/worksheets/sheet1.xml').decode();root=E.fromstring(xml.encode());groups=root.xpath('./m:extLst/m:ext/x14:sparklineGroups/x14:sparklineGroup',namespaces=ns)
  foreign=root.xpath('./m:extLst/m:ext[@uri="{FOREIGN-KEEP}"]',namespaces=ns)
  print(json.dumps({'groups':[{'type':g.get('type','line'),'attrs':dict(g.attrib),'color':g.find('x14:colorSeries',ns).get('rgb'),'cells':[{'cell':c.find('xm:sqref',ns).text,'sourceRef':c.find('xm:f',ns).text} for c in g.findall('x14:sparklines/x14:sparkline',ns)]} for g in groups],'existingRaw':re.search(r'<x14:sparklineGroup\s[^>]*data-unknown="preserve-me"[\s\S]*?</x14:sparklineGroup>',xml).group(0),'foreign':re.search(r'<ext uri="\{FOREIGN-KEEP\}">[\s\S]*?</ext>',xml).group(0),'rootExtLists':len(root.findall('m:extLst',ns)),'misplacedExt':len(root.findall('m:ext',ns)),'parts':{n:sha256(z.read(n)).hexdigest() for n in z.namelist() if n!='xl/worksheets/sheet1.xml'}}))
`],{cwd:repo,env:{...process.env,PYTHONPATH:repo},input:JSON.stringify(input),encoding:'utf8',maxBuffer:30*1024*1024});assert.equal(r.status,0,r.stderr);return r.stdout.trim()}
const revisions=new Map(),payloads=[],downloads=new Map(),assets=new Map(),checks=[],errors=[],results=[]
const checkpoint=process.env.SPARKLINE_RESUME_DIRECTORY??temporary,savedSources=new Set();await mkdir(checkpoint,{recursive:true});await writeFile(join(temporary,'checkpoint-directory.txt'),checkpoint)
let fixture;try{fixture=await readFile(join(checkpoint,'source-fixture.xlsx'))}catch(e){if(e.code!=='ENOENT')throw e;fixture=Buffer.from(python({mode:'fixture',sheetName,externalName}),'base64');await writeFile(join(checkpoint,'source-fixture.xlsx'),fixture)}
for(const revision of [1,10,20])revisions.set(revision,fixture)
let server,browser,page,stage='setup',routeError
const http=createServer(async(req,res)=>{try{
 const file=/^\/reports\/v1\/native\/sparkline-built\/(\d+)\/api\/file$/.exec(req.url??''),context=/^\/reports\/v1\/native\/sparkline-built\/(\d+)\/api\/context$/.exec(req.url??''),download=/^\/download\/(\d+)\.xlsx$/.exec(req.url??'')
 if(file||download){const bytes=(file?revisions:downloads).get(Number((file??download)[1]));assert(bytes);res.writeHead(200,{'Content-Type':media,'Content-Disposition':'attachment; filename=sparkline.xlsx','Content-Length':bytes.length});res.end(bytes);return}
 if(context){const revision=Number(context[1]),bytes=revisions.get(revision);res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({context:{documentId,format:'xlsx',revision,parentRevision:revision-1,scope:{database:'f',companyId:'f',userId:'f',threadId:'f'},sourceFile:{path:`revision-${revision}.xlsx`,size:bytes.length,sha256:sha(bytes),mediaType:media},origin:'upload'},csrfToken:'csrf',capabilities:{xlsx_editor:true},editingEnabled:true}));return}
 const path=/^\/reports\/v1\/native\/sparkline-built\/\d+$/.test(req.url??'')?'/reports/v1/editor/assets/native.html':req.url,r=await fetch(base+path);res.writeHead(r.status,Object.fromEntries([...r.headers].filter(([k])=>!['content-encoding','content-length','transfer-encoding'].includes(k))));res.end(Buffer.from(await r.arrayBuffer()))
 }catch(e){res.writeHead(500);res.end(String(e))}})
await new Promise(resolve=>http.listen(0,'127.0.0.1',resolve));const app=`http://127.0.0.1:${http.address().port}`
try{
 server=spawn('./node_modules/.bin/vite',['preview','--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:frontend,stdio:'pipe'})
 for(let i=0;;i++){assert.equal(server.exitCode,null);try{if((await fetch(base+'/reports/v1/editor/assets/native.html')).ok)break}catch{}assert(i<120);await delay(250)}
 browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1500,height:1100},acceptDownloads:true})
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});page.on('dialog',d=>d.type()==='beforeunload'?d.accept():d.dismiss())
 page.on('response',r=>{const path=new URL(r.url()).pathname;if(!path.startsWith('/reports/v1/editor/assets/')||!path.endsWith('.js'))return;checks.push((async()=>{assert.equal(r.status(),200);const body=await r.body();assert.equal(sha(body),sha(await readFile(join(frontend,'../static',path.slice('/reports/v1/editor/assets/'.length)))));assets.set(path,sha(body));await writeFile(join(temporary,'assets.json'),JSON.stringify(Object.fromEntries(assets),null,2))})())})
 await page.route('**/reports/v1/native/sparkline-built/*/api/save',async route=>{try{const revision=Number(new URL(route.request().url()).pathname.split('/')[5]),payload=route.request().postDataJSON();assert(!savedSources.has(revision),'禁止重复已成功保存的源修订');payloads.push(payload);const bytes=Buffer.from(python({mode:'patch',bytes:revisions.get(revision).toString('base64'),operations:payload.operations}),'base64');revisions.set(revision+1,bytes);downloads.set(revision+1,bytes);await writeFile(join(temporary,`revision-${revision+1}.xlsx`),bytes);savedSources.add(revision);await writeFile(join(checkpoint,`revision-${revision+1}.xlsx`),bytes);await writeFile(join(checkpoint,`saved-source-${revision}.json`),JSON.stringify({sourceRevision:revision,revision:revision+1,operations:payload.operations,sha256:sha(bytes)},null,2));await route.fulfill({json:{documentId,revision:revision+1,parentRevision:revision,revisionRegistered:true,artifacts:{xlsx:{downloadUrl:`${app}/download/${revision+1}.xlsx`,size:bytes.length,sha256:sha(bytes)}},editor:{openUrl:`/reports/v1/native/${documentId}/${revision+1}`},validation:{ok:true,issues:[]}}})}catch(e){routeError=String(e);await route.fulfill({status:500,json:{detail:routeError}})}})
 await page.addInitScript(()=>{
  const records=[];window.__sparklineCanvasCalls=records
  const proto=CanvasRenderingContext2D.prototype,paths=new WeakMap()
  for(const method of ['beginPath','moveTo','lineTo','stroke','fillRect']){const original=proto[method];proto[method]=function(...args){if(method==='beginPath')paths.set(this,[]);if(method==='moveTo'||method==='lineTo')paths.get(this)?.push([method,...args]);const color=String(method==='stroke'?this.strokeStyle:this.fillStyle).toLowerCase();if((method==='stroke'||method==='fillRect')&&['#376092','#a1b2c3'].includes(color)){records.push({method,color,args,path:paths.get(this)?.map(p=>[...p])??[]});if(records.length>5000)records.shift()}return original.apply(this,args)}}
 })
 const ready=async()=>{await page.waitForFunction(()=>document.querySelector('#report-editor')?.getAttribute('aria-busy')==='false',null,{timeout:60000});await page.locator('[data-ribbon-tab="Home"]').waitFor()}
 const open=async revision=>{await page.goto(`${app}/reports/v1/native/${documentId}/${revision}`);await ready()}
 const tab=name=>page.locator('[data-u-comp="slide-tab-item"]').filter({hasText:name})
 const command=async(group,id)=>{await page.locator(`[data-ribbon-tab="${group}"]`).click();await page.locator(`[data-ribbon-command="${id}"]`).click()}
 const goto=async reference=>{await command('Home','goto-open');await page.locator('[data-goto-reference]').fill(reference);await page.locator('.workbook-ribbon-goto-dialog button[type="submit"]').click();await page.locator('.workbook-ribbon-goto-dialog').waitFor({state:'hidden'})}
 const storage=()=>page.evaluate(()=>Object.fromEntries(Object.keys(localStorage).filter(k=>k.startsWith('native-editor-draft:')).sort().map(k=>[k,localStorage.getItem(k)])))
 const inspect=bytes=>JSON.parse(python({mode:'inspect',bytes:bytes.toString('base64')})),before=inspect(fixture)
 const canvas=()=>page.evaluate(()=>({entries:[...window.__sheetsWebSparklines.store.entries()],draws:window.__sheetsWebSparklines.draws,lastSkip:window.__sheetsWebSparklines.lastSkip,targetBounds:[...window.__sheetsWebSparklines.targetBounds.entries()],calls:window.__sparklineCanvasCalls}))
 const specs=async()=>{const d=await canvas();return d.entries.flatMap(([key,items])=>items.map(item=>({key,...item})))}
 const assertStore=async(type,present)=>{
  await page.waitForFunction(({kind,present})=>{const entries=[...window.__sheetsWebSparklines.store.values()].flat();return ['E4','E5'].every(target=>entries.some(s=>s.target===target&&s.kind===kind)===present)},{kind:type==='stacked'?'winLoss':type,present})
  const existing=(await specs()).find(s=>s.target==='G2');assert(existing,'已有原生组必须在store');assert.equal(existing.source,'$B$2:$D$2');assert.equal(existing.sourceSheet,externalName,'已有跨表source身份必须保留')
 }
 const assertDrawing=async(type)=>{
  await page.waitForFunction(type=>{const c=window.__sparklineCanvasCalls;return c.some(x=>x.color==='#a1b2c3'&&x.method==='stroke')&&c.some(x=>x.color==='#376092'&&x.method===(type==='line'?'stroke':'fillRect'))},type)
  const d=await canvas();assert(d.draws>0);assert(!d.lastSkip,`不得跳过正确来源:${d.lastSkip}`)
  // 外表[-2,8,1]折线：第2点最高，第3点介于第1/2点间；主表[1,-2,3]不满足。
  assert(d.calls.some(c=>c.color==='#a1b2c3'&&c.method==='stroke'&&c.path.length===3&&c.path[1][2]<c.path[2][2]&&c.path[2][2]<c.path[0][2]),'已有跨表折线必须实际使用外表数值绘制')
  const bounds=['E4','E5'].map(target=>{const matches=d.targetBounds.filter(([key])=>key.endsWith(`::${target}`));assert.equal(matches.length,1,`实际目标格坐标必须唯一:${target}`);return {target,...matches[0][1]}})
  const contained=(c,b)=>{const [x,y,w,h]=c.args;return x>=b.startX+2-0.01&&x+w<=b.endX-2+0.01&&y>=b.startY+2-0.01&&y+h<=b.endY-2+0.01&&w>0&&h>0}
  if(type==='line'){
   for(const b of bounds)assert(d.calls.some(c=>c.color==='#376092'&&c.method==='stroke'&&c.path.length===3&&c.path.every(([,x,y])=>x>=b.startX+2-0.01&&x<=b.endX-2+0.01&&y>=b.startY+2-0.01&&y<=b.endY-2+0.01)),`${b.target}折线路径必须位于实际宿主格`)
  }else{
   const bars=d.calls.filter(c=>c.color==='#376092'&&c.method==='fillRect');assert(bars.length>=6)
   for(const c of bars)assert(bounds.some(b=>contained(c,b)),`柱体越出实际宿主格:${JSON.stringify(c.args)}`)
   for(const b of bounds){
    const inside=bars.filter(c=>contained(c,b));assert(inside.length>=3,`${b.target}必须实际画三个柱`)
    if(type==='stacked'){
     const mid=(b.startY+b.endY)/2,columnWidth=(b.endX-b.startX-4)/3
     for(const index of [0,1,2]){const x=b.startX+2+columnWidth*index+0.5;assert(inside.some(c=>Math.abs(c.args[0]-x)<0.01&&(index===1?c.args[1]>=mid-0.01:c.args[1]+c.args[3]<=mid+0.01)),`${b.target}第${index+1}柱必须按正负处于基线正确侧`)}
    }
   }
  }
  return d
 }
 const verifyFile=(bytes,type)=>{const after=inspect(bytes);assert.equal(after.rootExtLists,1);assert.equal(after.misplacedExt,0);for(const key of ['existingRaw','foreign','parts'])assert.deepEqual(after[key],before[key],`保留已有raw/foreign/非目标parts:${key}`);assert.equal(after.groups.length,2);const added=after.groups.find(g=>!g.attrs['data-unknown']);assert.equal(added.type,type);assert.deepEqual(added.cells,[4,5].map(row=>({cell:`E${row}`,sourceRef:`${quote(sheetName)}!$B$${row}:$D$${row}`})));return after}
 for(const [revision,type] of [[1,'line'],[10,'column'],[20,'stacked']]){
  stage=`${type}-source`;let saved;try{saved=JSON.parse(await readFile(join(checkpoint,`saved-source-${revision}.json`),'utf8'))}catch(e){if(e.code!=='ENOENT')throw e}
  let operations,bytes
  if(!saved){let orphan=false;try{await readFile(join(checkpoint,`revision-${revision+1}.xlsx`));orphan=true}catch(e){if(e.code!=='ENOENT')throw e}assert(!orphan,'发现已写出产物但缺少保存回执，禁止重试保存；请先核验并补齐checkpoint')}
  if(saved){
   assert.equal(saved.sourceRevision,revision);assert.equal(saved.revision,revision+1);savedSources.add(revision);bytes=await readFile(join(checkpoint,`revision-${saved.revision}.xlsx`));assert.equal(sha(bytes),saved.sha256);operations=saved.operations;revisions.set(saved.revision,bytes);downloads.set(saved.revision,bytes);verifyFile(bytes,type)
  }else{
   await open(revision);await tab(sheetName).click();await goto(`${quote(sheetName)}!B4:D5`)
   const initial=await storage();await command('Insert',`sparkline:${type}`);await assertStore(type,true);const created=await storage();assert.notDeepEqual(created,initial,'创建必须写草稿');await assertDrawing(type)
   stage=`${type}-undo`;await command('File','undo');await assertStore(type,false);stage=`${type}-redo`;await command('File','redo');await assertStore(type,true)
   stage=`${type}-draft`;await page.reload();await ready();await tab(sheetName).click();await assertStore(type,true);await assertDrawing(type)
   stage=`${type}-save`;await page.locator('[data-action="save"]').click();await page.waitForFunction(n=>(document.querySelector('.save-state-label')?.textContent??'').includes(`已保存修订 ${n}`),revision+1,{timeout:60000});assert.equal(routeError,undefined)
   operations=payloads.at(-1).operations;assert.deepEqual(operations.map(o=>o.kind),['appendSheetSparklines']);assert.equal(operations[0].sheetName,sheetName);assert.equal(operations[0].groups.length,1);assert.equal(operations[0].groups[0].type,type);assert.equal(operations[0].groups[0].cells.length,2)
   const [download]=await Promise.all([page.waitForEvent('download'),page.locator('[data-action="xlsx-download"]').click()]);bytes=await readFile(await download.path());assert.equal(sha(bytes),sha(revisions.get(revision+1)));verifyFile(bytes,type)
   await writeFile(join(checkpoint,`downloaded-revision-${revision+1}.xlsx`),bytes)
  }
  stage=`${type}-explicit-reopen`;await open(revision+1);await tab(sheetName).click();await assertStore(type,true);const drawing=await assertDrawing(type)
  // Resume同样从正式HTTP下载再次核对，但绝不点击保存。
  const response=await page.request.get(`${app}/download/${revision+1}.xlsx`);assert.equal(response.status(),200);assert.equal(sha(await response.body()),sha(bytes));await writeFile(join(checkpoint,`downloaded-revision-${revision+1}.xlsx`),bytes)
  const result={type,sourceRevision:revision,revision:revision+1,downloadSha256:sha(bytes),operations,independent:verifyFile(bytes,type),store:await specs(),draws:drawing.draws,canvasCalls:drawing.calls,targetBounds:drawing.targetBounds,resumed:!!saved}
  await page.screenshot({path:join(checkpoint,`${type}-reopened.png`),fullPage:true});await writeFile(join(checkpoint,`${type}-result.json`),JSON.stringify(result,null,2));results.push(result);console.log(JSON.stringify({type,revision:revision+1,downloadSha256:sha(bytes),resumed:!!saved}))
 }
 await Promise.all(checks);assert.deepEqual(errors,[]);const summary={ok:true,temporary,checkpoint,browserVersion:browser.version(),results:results.map(({canvasCalls,...r})=>r),saveCount:payloads.length,assets:Object.fromEntries(assets),errors};await writeFile(join(checkpoint,'summary.json'),JSON.stringify(summary,null,2));console.log(JSON.stringify(summary))
}catch(e){if(page){await writeFile(join(temporary,'failure.html'),await page.content()).catch(()=>{});await page.screenshot({path:join(temporary,'failure.png'),fullPage:true}).catch(()=>{})}console.error(JSON.stringify({stage,temporary,checkpoint}));throw e}finally{await browser?.close();server?.kill();await new Promise(resolve=>http.close(resolve))}
