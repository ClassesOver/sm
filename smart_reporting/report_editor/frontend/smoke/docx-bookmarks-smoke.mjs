// 冻结网页+真实 Python/Node 书签桥；API路由为本地夹具，不冒充生产鉴权整链。
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {readFile,writeFile,mkdir} from 'node:fs/promises'
import {createServer} from 'node:http'
import {spawnSync} from 'node:child_process'
import {dirname,resolve,extname} from 'node:path'
import {fileURLToPath} from 'node:url'
import {chromium} from 'playwright'
const frontend=resolve(dirname(fileURLToPath(import.meta.url)),'..'),repo=resolve(frontend,'../../..'),staticRoot=resolve(process.env.DOCX_TEST_DIST??resolve(frontend,'../static'))
const output=process.env.DOCX_BOOKMARK_EVIDENCE??'/tmp/word-bookmarks-browser-20261111',port=Number(process.env.DOCX_BOOKMARK_PORT??4314),sha=b=>createHash('sha256').update(b).digest('hex')
const manifestSha256=sha(await readFile(resolve(staticRoot,'.vite/manifest.json')));assert.equal(manifestSha256,process.env.DOCX_EXPECTED_MANIFEST_SHA256);await mkdir(output,{recursive:true})
const python=`import base64,json,sys
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
from lxml import etree as E
from smart_reporting.reporting.delivery.docx_native import inspect_docx,patch_docx
from smart_reporting.reporting.tests.test_docx_comment_text_host import source
p=json.load(sys.stdin);W='http://schemas.openxmlformats.org/wordprocessingml/2006/main';ns={'w':W}
if p['mode']=='create':
 data=source();Path(p['path']).write_bytes(data);print(json.dumps({'bytes':base64.b64encode(data).decode(),'model':inspect_docx(data)}))
elif p['mode']=='patch':
 data=patch_docx(Path(p['source']).read_bytes(),p['operations']);Path(p['output']).write_bytes(data);print(json.dumps({'bytes':base64.b64encode(data).decode(),'model':inspect_docx(data)}))
else:
 with ZipFile(p['source']) as a,ZipFile(p['output']) as b:
  assert a.namelist()==b.namelist();changed=[n for n in a.namelist() if a.read(n)!=b.read(n)];assert changed==['word/document.xml'],changed
  for n in b.namelist():
   if n.endswith(('.xml','.rels')):E.fromstring(b.read(n))
  d=E.fromstring(b.read('word/document.xml'));starts=d.findall('.//w:bookmarkStart',ns);names=[n.get('{'+W+'}name') for n in starts]
  if p['created']:
   s=next(n for n in starts if n.get('{'+W+'}name')=='ExactBookmark');id=s.get('{'+W+'}id');active=False;text=''
   for n in s.getparent():
    if n is s:active=True
    elif n.tag=='{'+W+'}bookmarkEnd' and n.get('{'+W+'}id')==id:active=False
    elif active:text+=''.join(n.xpath('.//w:t/text()',namespaces=ns))
   assert text=='chor t',repr(text)
  else:assert 'ExactBookmark' not in names
  print(json.dumps({'changedParts':changed,'allXmlValid':True,'names':names}))`
const engine=p=>{const r=spawnSync(resolve(repo,'.venv/bin/python'),['-c',python],{cwd:repo,env:{...process.env,PYTHONPATH:repo},input:JSON.stringify(p),encoding:'utf8',maxBuffer:20*1024*1024,timeout:120000});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout)}
const revisions={1:engine({mode:'create',path:resolve(output,'revision-1.docx')})},requests=[],errors=[],chunks={},identities=[]
const base='http://127.0.0.1:'+port,pathBase='/reports/v1/native/fixture-bookmarks/',prefix='/reports/v1/editor/assets/'
const server=createServer(async(req,res)=>{try{const p=new URL(req.url,base).pathname;assert.ok(p.startsWith(prefix));const file=resolve(staticRoot,p.slice(prefix.length));assert.ok(file.startsWith(staticRoot+'/'));res.writeHead(200,{'Content-Type':({'.js':'application/javascript','.css':'text/css','.woff2':'font/woff2'})[extname(file)]??'text/html'});res.end(await readFile(file))}catch{res.writeHead(404);res.end('not found')}})
await new Promise((done,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',done)})
let browser,page
try{
 browser=await chromium.launch({headless:true});page=await browser.newPage({viewport:{width:1600,height:1100}})
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())})
 page.on('response',r=>{const p=new URL(r.url()).pathname;if(r.status()>=400)errors.push(r.status()+' '+p);if(r.ok()&&p.startsWith(prefix)&&p.endsWith('.js'))identities.push(r.body().then(async b=>{assert.equal(sha(b),sha(await readFile(resolve(staticRoot,p.slice(prefix.length)))));chunks[p]=sha(b)}))})
 await page.route('**/favicon.ico',r=>r.fulfill({body:'',status:200}))
 const mediaType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
 await page.route('**/reports/v1/native/fixture-bookmarks/*/api/**',async r=>{
  const request=r.request(),path=new URL(request.url()).pathname,revision=Number(path.split('/')[5]),entry=revisions[revision],post=request.method()==='POST'?request.postDataJSON():undefined;requests.push({path,method:request.method(),payload:post});await writeFile(resolve(output,'requests.json'),JSON.stringify(requests,null,2))
  if(path.endsWith('/context'))return r.fulfill({json:{context:{documentId:'fixture-bookmarks',format:'docx',revision,parentRevision:revision>1?revision-1:null,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},sourceFile:{path:'revision-'+revision+'.docx',size:Buffer.from(entry.bytes,'base64').length,sha256:entry.model.sourceSha256,mediaType},origin:'upload'},csrfToken:'fixture',capabilities:{docx_editor:true},editingEnabled:true}})
  if(path.endsWith('/file'))return r.fulfill({body:Buffer.from(entry.bytes,'base64'),contentType:mediaType})
  assert.equal(post.expectedSha256,entry.model.sourceSha256)
  if(path.endsWith('/preview')){assert.deepEqual(post.operations,[]);return r.fulfill({json:{sourceSha256:entry.model.sourceSha256,draftSha256:entry.model.sourceSha256,model:entry.model}})}
  assert.ok(path.endsWith('/save'));await writeFile(resolve(output,'last-save-request.json'),JSON.stringify({revision,post},null,2));assert.equal(post.operations.length,1);assert.equal(post.operations[0].kind,revision===1?'createBookmark':'deleteBookmark');assert.equal(revisions[revision+1],undefined)
  revisions[revision+1]=engine({mode:'patch',source:resolve(output,'revision-'+revision+'.docx'),output:resolve(output,'revision-'+(revision+1)+'.docx'),operations:post.operations})
  return r.fulfill({json:{documentId:'fixture-bookmarks',revision:revision+1,parentRevision:revision,revisionRegistered:true,artifacts:{word:{downloadUrl:'/bookmark-download-'+(revision+1)+'.docx',sha256:revisions[revision+1].model.sourceSha256,size:Buffer.from(revisions[revision+1].bytes,'base64').length}},editor:{openUrl:pathBase+(revision+1)},validation:{ok:false,issues:[{code:'fixture_review',message:'书签版式待复核'}]}}})
 })
 await page.route(/\/bookmark-download-\d+\.docx$/,r=>{const n=Number(new URL(r.request().url()).pathname.match(/(\d+)\.docx$/)[1]);return r.fulfill({body:Buffer.from(revisions[n].bytes,'base64'),contentType:mediaType})})
 await page.route(/\/reports\/v1\/native\/fixture-bookmarks\/\d+$/,async r=>r.fulfill({body:await readFile(resolve(staticRoot,'native.html')),contentType:'text/html'}))
 const open=async n=>{await page.goto(base+pathBase+n);await page.locator('.docx-source-home').waitFor({timeout:60000})},draft=()=>page.evaluate(()=>{const revision=Number(location.pathname.split('/').at(-1)),k=Object.keys(localStorage).find(k=>k.startsWith('native-editor-draft:v1:')&&JSON.parse(localStorage.getItem(k)).identity.revision===revision);return k?JSON.parse(localStorage.getItem(k)).operations:[]})
 const panel=async()=>{await page.locator('[data-tab-id=references]').click();await page.locator('[data-action=bookmarks]').click()}
 await open(1);await page.locator('.tiptap').evaluate(el=>el.editor.commands.setTextSelection({from:3,to:9}));await panel()
 await page.getByRole('textbox',{name:'书签名称',exact:true}).fill('ExactBookmark');await page.locator('[data-bookmark-add]').click();assert.deepEqual((await draft())[0].ranges.map(r=>({from:r.from,to:r.to,text:r.text})),[{from:2,to:8,text:'chor t'}])
 await page.locator('.tiptap').evaluate(el=>el.editor.commands.undo());assert.deepEqual(await draft(),[]);await page.locator('.tiptap').evaluate(el=>el.editor.commands.redo());assert.equal((await draft()).length,1)
 await page.reload();await page.locator('.docx-source-home').waitFor({timeout:60000});assert.equal((await draft())[0].name,'ExactBookmark');await panel()
 await page.locator('[data-bookmark-go]').filter({hasText:'ExactBookmark'}).click();assert.deepEqual(await page.locator('.tiptap').evaluate(el=>({from:el.editor.state.selection.from,to:el.editor.state.selection.to})),{from:3,to:9})
 const save=async n=>{await writeFile(resolve(output,'before-save-'+n+'.json'),JSON.stringify({draft:await draft(),pm:await page.locator('.tiptap').evaluate(el=>el.editor.getJSON()),status:await page.locator('.docx-bookmarks [role=status]').textContent()},null,2));await page.locator('[data-action=save]').dispatchEvent('click');await page.waitForFunction(n=>document.querySelector('.save-state-label')?.textContent.includes('已保存修订 '+n),n,{timeout:60000});const url='/bookmark-download-'+n+'.docx',b=Buffer.from(await page.evaluate(async url=>Array.from(new Uint8Array(await(await fetch(url)).arrayBuffer())),url));assert.equal(sha(b),revisions[n].model.sourceSha256);await writeFile(resolve(output,'downloaded-'+n+'.docx'),b);assert.equal(await page.getByText('书签版式待复核',{exact:true}).count(),1)}
 await save(2);const created=engine({mode:'verify',source:resolve(output,'revision-1.docx'),output:resolve(output,'downloaded-2.docx'),created:true});await open(2);await panel()
 const entry=revisions[2].model.bookmarks.bookmarks.find(b=>b.name==='ExactBookmark');assert.ok(entry);await page.locator('[data-bookmark-go]').filter({hasText:'ExactBookmark'}).click()
 await page.evaluate(()=>{window.__bookmarkEvents=[];for(const type of ['mousedown','mouseup','click','focusin','focusout'])document.addEventListener(type,e=>window.__bookmarkEvents.push({type,target:e.target.outerHTML?.slice(0,300)}),true)})
 const diagnostic=()=>page.locator('.tiptap').evaluate(el=>({editable:el.editor.isEditable,attrs:el.editor.getJSON().attrs,status:document.querySelector('.docx-bookmarks [role=status]')?.textContent,buttons:[...document.querySelectorAll('[data-bookmark-delete]')].map(b=>({disabled:b.disabled,text:b.textContent})),events:window.__bookmarkEvents}))
 await writeFile(resolve(output,'before-delete.json'),JSON.stringify(await diagnostic(),null,2));await page.locator('[data-bookmark-delete="'+entry.bookmarkId+'"]').click();await writeFile(resolve(output,'after-delete.json'),JSON.stringify(await diagnostic(),null,2));await save(3)
 const deleted=engine({mode:'verify',source:resolve(output,'revision-2.docx'),output:resolve(output,'downloaded-3.docx'),created:false});await open(3);await panel();assert.equal(await page.locator('[data-bookmark-go]').filter({hasText:'ExactBookmark'}).count(),0)
 await page.waitForLoadState('networkidle');await Promise.all(identities);assert.deepEqual(errors,[]);assert.equal(sha(await readFile(resolve(staticRoot,'.vite/manifest.json'))),manifestSha256)
 const evidence={ok:true,apiRoutesAreFixtures:true,realPythonNodeBridge:true,manifestSha256,created,deleted,requests,chunks,errors};await writeFile(resolve(output,'evidence.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify({ok:true,output,manifestSha256,created,deleted,errors}))
}catch(e){await page?.screenshot({path:resolve(output,'failure.png'),fullPage:true}).catch(()=>{});await writeFile(resolve(output,'failure.json'),JSON.stringify({error:String(e),errors,requests},null,2));throw e}finally{await browser?.close();await new Promise(done=>server.close(done))}
