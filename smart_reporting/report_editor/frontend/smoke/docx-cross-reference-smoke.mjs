// 冻结网页+真实 Python/Node 交叉引用桥；API路由为本地夹具，不冒充生产鉴权整链。
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {readFile,writeFile,mkdir} from 'node:fs/promises'
import {createServer} from 'node:http'
import {spawnSync} from 'node:child_process'
import {dirname,resolve,extname} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright'
const frontend=resolve(dirname(fileURLToPath(import.meta.url)),'..'),repo=resolve(frontend,'../../..'),staticRoot=resolve(process.env.DOCX_TEST_DIST??resolve(frontend,'../static'))
const output=process.env.DOCX_CROSS_REFERENCE_EVIDENCE??'/tmp/word-cross-reference-browser-20261111',port=Number(process.env.DOCX_CROSS_REFERENCE_PORT??4317),sha=b=>createHash('sha256').update(b).digest('hex')
const manifestSha256=sha(await readFile(resolve(staticRoot,'.vite/manifest.json')));assert.equal(manifestSha256,process.env.DOCX_EXPECTED_MANIFEST_SHA256);await mkdir(output,{recursive:true})
const python=`import base64,json,sys
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
from lxml import etree as E
from docx import Document
from smart_reporting.reporting.delivery.docx_native import inspect_docx,patch_docx
p=json.load(sys.stdin);W='http://schemas.openxmlformats.org/wordprocessingml/2006/main';ns={'w':W}
if p['mode']=='create':
 document=Document();document.add_paragraph('Trusted 😀 & cache');paragraph=document.add_paragraph();paragraph.add_run('Insert reference here.').bold=True
 stream=BytesIO();document.save(stream);out=BytesIO()
 with ZipFile(BytesIO(stream.getvalue())) as source,ZipFile(out,'w',ZIP_DEFLATED) as edited:
  for name in source.namelist():
   data=source.read(name)
   if name=='word/document.xml':
    d=E.fromstring(data);first=d.find('w:body/w:p',ns);start=E.Element('{'+W+'}bookmarkStart');start.set('{'+W+'}id','1');start.set('{'+W+'}name','SavedTarget');end=E.Element('{'+W+'}bookmarkEnd');end.set('{'+W+'}id','1');first.insert(0,start);first.append(end);data=E.tostring(d,xml_declaration=True,encoding='UTF-8',standalone=True)
   edited.writestr(name,data)
 data=out.getvalue();Path(p['path']).write_bytes(data);print(json.dumps({'bytes':base64.b64encode(data).decode(),'model':inspect_docx(data)}))
elif p['mode']=='patch':
 data=patch_docx(Path(p['source']).read_bytes(),p['operations']);Path(p['output']).write_bytes(data);print(json.dumps({'bytes':base64.b64encode(data).decode(),'model':inspect_docx(data)}))
else:
 with ZipFile(p['source']) as a,ZipFile(p['output']) as b:
  assert a.namelist()==b.namelist();changed=[n for n in a.namelist() if a.read(n)!=b.read(n)];assert changed==['word/document.xml'],changed
  for n in b.namelist():
   if n.endswith(('.xml','.rels')):E.fromstring(b.read(n))
  d=E.fromstring(b.read('word/document.xml'));paragraphs=d.findall('w:body/w:p',ns);target=paragraphs[1];instruction=target.find('.//w:instrText',ns);assert instruction is not None
  assert instruction.text==' REF SavedTarget '+chr(92)+'h ',repr(instruction.text)
  assert [n.get('{'+W+'}fldCharType') for n in target.findall('.//w:fldChar',ns)]==['begin','separate','end']
  texts=target.xpath('.//w:t/text()',namespaces=ns);assert texts==['Insert ','Trusted 😀 & cache','reference here.'],texts
  assert len(target.findall('w:r/w:rPr/w:b',ns))==2
  assert len(d.findall('.//w:bookmarkStart',ns))==1;assert len(d.findall('.//w:bookmarkEnd',ns))==1
  print(json.dumps({'changedParts':changed,'allXmlValid':True,'instruction':instruction.text,'cachedText':texts[1],'targetText':''.join(texts),'boldRuns':2}))`
const engine=p=>{const r=spawnSync(resolve(repo,'.venv/bin/python'),['-c',python],{cwd:repo,env:{...process.env,PYTHONPATH:repo},input:JSON.stringify(p),encoding:'utf8',maxBuffer:20*1024*1024,timeout:120000});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout)}
const revisions={1:engine({mode:'create',path:resolve(output,'revision-1.docx')})},requests=[],errors=[],chunks={},identities=[]
const base='http://127.0.0.1:'+port,pathBase='/reports/v1/native/fixture-cross-reference/',prefix='/reports/v1/editor/assets/'
const server=createServer(async(req,res)=>{try{const p=new URL(req.url,base).pathname;assert.ok(p.startsWith(prefix));const file=resolve(staticRoot,p.slice(prefix.length));assert.ok(file.startsWith(staticRoot+'/'));res.writeHead(200,{'Content-Type':({'.js':'application/javascript','.css':'text/css','.woff2':'font/woff2'})[extname(file)]??'text/html'});res.end(await readFile(file))}catch{res.writeHead(404);res.end('not found')}})
await new Promise((done,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',done)})
let browser,page
try{
 browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1600,height:1100}})
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
 page.on('response',r=>{const p=new URL(r.url()).pathname;if(r.status()>=400)errors.push(r.status()+' '+p);if(r.ok()&&p.startsWith(prefix)&&p.endsWith('.js'))identities.push(r.body().then(async b=>{assert.equal(sha(b),sha(await readFile(resolve(staticRoot,p.slice(prefix.length)))));chunks[p]=sha(b)}))})
 await page.route('**/favicon.ico',r=>r.fulfill({body:'',status:200}))
 const mediaType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
 await page.route('**/reports/v1/native/fixture-cross-reference/*/api/**',async r=>{
  const request=r.request(),path=new URL(request.url()).pathname,revision=Number(path.split('/')[5]),entry=revisions[revision],post=request.method()==='POST'?request.postDataJSON():undefined;requests.push({path,method:request.method(),payload:post});await writeFile(resolve(output,'requests.json'),JSON.stringify(requests,null,2))
  if(path.endsWith('/context'))return r.fulfill({json:{context:{documentId:'fixture-cross-reference',format:'docx',revision,parentRevision:revision>1?revision-1:null,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'revision-'+revision+'.docx',size:Buffer.from(entry.bytes,'base64').length,sha256:entry.model.sourceSha256,mediaType},origin:'upload'},csrfToken:'fixture',capabilities:{docx_editor:true},editingEnabled:true}})
  if(path.endsWith('/file'))return r.fulfill({body:Buffer.from(entry.bytes,'base64'),contentType:mediaType})
  assert.equal(post.expectedSha256,entry.model.sourceSha256)
  if(path.endsWith('/preview')){assert.deepEqual(post.operations,[]);return r.fulfill({json:{sourceSha256:entry.model.sourceSha256,draftSha256:entry.model.sourceSha256,model:entry.model}})}
  assert.ok(path.endsWith('/save'));await writeFile(resolve(output,'last-save-request.json'),JSON.stringify({revision,post},null,2));assert.equal(post.operations.length,1);assert.equal(post.operations[0].kind,'insertCrossReference');assert.equal(revisions[revision+1],undefined)
  revisions[revision+1]=engine({mode:'patch',source:resolve(output,'revision-'+revision+'.docx'),output:resolve(output,'revision-'+(revision+1)+'.docx'),operations:post.operations})
  return r.fulfill({json:{documentId:'fixture-cross-reference',revision:revision+1,parentRevision:revision,revisionRegistered:true,artifacts:{word:{downloadUrl:'/cross-reference-download-'+(revision+1)+'.docx',sha256:revisions[revision+1].model.sourceSha256,size:Buffer.from(revisions[revision+1].bytes,'base64').length}},editor:{openUrl:pathBase+(revision+1)},validation:{ok:false,issues:[{code:'fixture_review',message:'交叉引用版式待复核'}]}}})
 })
 await page.route(/\/cross-reference-download-\d+\.docx$/,r=>{const n=Number(new URL(r.request().url()).pathname.match(/(\d+)\.docx$/)[1]);return r.fulfill({body:Buffer.from(revisions[n].bytes,'base64'),contentType:mediaType})})
 await page.route(/\/reports\/v1\/native\/fixture-cross-reference\/\d+$/,async r=>r.fulfill({body:await readFile(resolve(staticRoot,'native.html')),contentType:'text/html'}))
 const open=async n=>{await page.goto(base+pathBase+n);await page.locator('.docx-source-home').waitFor({timeout:60000})},draft=()=>page.evaluate(()=>{const revision=Number(location.pathname.split('/').at(-1)),k=Object.keys(localStorage).find(k=>k.startsWith('native-editor-draft:v1:')&&JSON.parse(localStorage.getItem(k)).identity.revision===revision);return k?JSON.parse(localStorage.getItem(k)).operations:[]})
 const panel=async()=>{await page.locator('[data-tab-id=references]').click();const entry=page.locator('[data-action=cross-reference]');await entry.click();if(process.env.DOCX_CROSS_REFERENCE_KEYBOARD==='1'){const first=page.locator('[data-cross-reference-insert]:enabled').first(),close=page.locator('[data-cross-reference-close]');assert.equal(await (await first.count()?first:close).evaluate(node=>document.activeElement===node),true);await close.click();assert.equal(await entry.evaluate(node=>document.activeElement===node),true);await entry.click()}}
 await open(1)
 await page.locator('.tiptap').evaluate(el=>{let position;el.editor.state.doc.forEach((node,offset)=>{if(node.attrs.docxIndex===1)position=offset+1+7});if(position==null)throw new Error('missing ordinary second paragraph');el.editor.commands.setTextSelection(position)})
 await panel();if(process.env.DOCX_CROSS_REFERENCE_KEYBOARD==='1'){await page.keyboard.press('Space');assert.equal(await page.locator('[data-cross-reference-insert]').isDisabled(),true)}else await page.locator('[data-cross-reference-insert]').click();assert.equal((await draft()).length,1);assert.equal((await draft())[0].kind,'insertCrossReference');assert.equal((await draft())[0].offset,7)
 await page.locator('.tiptap').evaluate(el=>el.editor.commands.undo());assert.deepEqual(await draft(),[]);await page.locator('.tiptap').evaluate(el=>el.editor.commands.redo());assert.equal((await draft()).length,1)
 await page.reload();await page.locator('.docx-source-home').waitFor({timeout:60000});assert.equal((await draft())[0].kind,'insertCrossReference');assert.equal(await page.locator('[data-native-cross-reference]').textContent(),'Trusted 😀 & cache')
 await page.locator('[data-action=save]:visible').first().click();await page.waitForFunction(()=>document.querySelector('.save-state-label')?.textContent.includes('已保存修订 2'),undefined,{timeout:60000})
 const url='/cross-reference-download-2.docx',downloaded=Buffer.from(await page.evaluate(async url=>Array.from(new Uint8Array(await(await fetch(url)).arrayBuffer())),url));assert.equal(sha(downloaded),revisions[2].model.sourceSha256);await writeFile(resolve(output,'downloaded-2.docx'),downloaded);assert.equal(await page.getByText('交叉引用版式待复核',{exact:true}).count(),1)
 const saved=engine({mode:'verify',source:resolve(output,'revision-1.docx'),output:resolve(output,'downloaded-2.docx')});await open(2);assert.ok((await page.locator('.tiptap').textContent()).includes('Insert Trusted 😀 & cachereference here.'));await panel();assert.equal(await page.locator('[data-cross-reference-insert]').count(),1)
 await page.screenshot({path:resolve(output,'success.png'),fullPage:true});
 await page.waitForLoadState('networkidle');await Promise.all(identities);assert.deepEqual(errors,[]);assert.equal(sha(await readFile(resolve(staticRoot,'.vite/manifest.json'))),manifestSha256)
 const evidence={ok:true,apiRoutesAreFixtures:true,realPythonNodeBridge:true,keyboardChecked:process.env.DOCX_CROSS_REFERENCE_KEYBOARD==='1',successScreenshot:resolve(output,'success.png'),manifestSha256,manifestBeforeSha256:manifestSha256,manifestAfterSha256:sha(await readFile(resolve(staticRoot,'.vite/manifest.json'))),saved,requests,chunks,errors};await writeFile(resolve(output,'evidence.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify({ok:true,output,manifestSha256,saved,errors}))
}catch(e){await page?.screenshot({path:resolve(output,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(resolve(output,'failure.json'),JSON.stringify({error:String(e),errors,requests},null,2));throw e}finally{await browser?.close();await new Promise(done=>server.close(done))}
