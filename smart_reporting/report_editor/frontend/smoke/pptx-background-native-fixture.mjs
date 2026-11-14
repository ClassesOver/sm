// 显式夹具授权与修订宿主：编辑/播放/保存均使用实际 PPTX bytes，不冒称生产授权验收。
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {readFile,writeFile} from 'node:fs/promises'
import {createServer} from 'node:http'
import {spawnSync} from 'node:child_process'
import {resolve,extname} from 'node:path'

export async function createBackgroundNativeFixture({frontend,directory,engineRoot,sourceOrigin,staticRoot,expectedManifest}){
 const hash=bytes=>createHash('sha256').update(bytes).digest('hex'),repo=resolve(frontend,'../../..'),prefix='/reports/v1/editor/assets/',base='/reports/v1/native/media-native/1/api/'
 const helper=resolve(frontend,'smoke/pptx-background-source-fixture.py')
 const engine=payload=>{
  const result=spawnSync(resolve(repo,'.venv/bin/python'),[helper],{cwd:repo,env:{...process.env,PYTHONPATH:repo,PYTHONDONTWRITEBYTECODE:'1',TMPDIR:'/dev/shm',AGENT_REPORTING_SLIDES_ENGINE_DIR:engineRoot},input:JSON.stringify({directory,...payload}),encoding:'utf8',maxBuffer:60*1024*1024,timeout:120000})
  assert.equal(result.status,0,result.stderr);return JSON.parse(result.stdout)
 }
 const source=await readFile(resolve(directory,'source.pptx')),identity=hash(source),entry=engine({mode:'inspect'}),resources=new Map(),checks=[],errors=[],requests=[]
 assert.equal(entry.sha256,identity)
 if(!sourceOrigin){assert.ok(expectedManifest);assert.equal(hash(await readFile(resolve(staticRoot,'.vite/manifest.json'))),expectedManifest)}
 const html=sourceOrigin?(await readFile(resolve(frontend,'native.html'),'utf8')).replace('/src/unified-main.ts',sourceOrigin+prefix+'src/unified-main.ts'):await readFile(resolve(staticRoot,'native.html'))
 let saved,saveCount=0,downloadCount=0
 const server=createServer(async(request,response)=>{
  try{
   const path=new URL(request.url,'http://localhost').pathname
   if(path==='/favicon.ico'){response.writeHead(204);response.end();return}
   if(path==='/media-download.pptx'){
    assert.ok(saved);downloadCount++;response.writeHead(200,{'Content-Type':'application/vnd.openxmlformats-officedocument.presentationml.presentation','Content-Disposition':'attachment; filename="media-revision-2.pptx"'});response.end(saved);return
   }
   assert.ok(path.startsWith(prefix))
   if(sourceOrigin){response.writeHead(302,{Location:sourceOrigin+path});response.end();return}
   const file=resolve(staticRoot,path.slice(prefix.length));assert.ok(file.startsWith(staticRoot+'/'))
   response.writeHead(200,{'Content-Type':{'.js':'application/javascript','.css':'text/css','.html':'text/html','.woff2':'font/woff2','.wasm':'application/wasm'}[extname(file)]??'application/octet-stream'});response.end(await readFile(file))
  }catch(error){errors.push(String(error));response.writeHead(404);response.end('not found')}
 })
 return {engine,source:entry,requests,errors,
  listen:()=>new Promise(done=>server.listen(0,'127.0.0.1',done)),close:()=>new Promise(done=>server.close(done)),
  async setup(page){
   page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error'&&!message.text().includes('ERR_DEMUXER'))errors.push(message.text())});page.on('dialog',dialog=>dialog.type()==='beforeunload'?dialog.accept():dialog.dismiss())
   page.on('response',response=>{const path=new URL(response.url()).pathname;if(response.status()>=400)errors.push(`${response.status()} ${path}`);if(response.status()===200&&path.startsWith(prefix)&&/\.(js|css|ts|tsx)$/.test(path))checks.push(response.body().then(async bytes=>{if(!sourceOrigin)assert.equal(hash(bytes),hash(await readFile(resolve(staticRoot,path.slice(prefix.length)))));resources.set(path,{sha256:hash(bytes),size:bytes.length})}).catch(error=>errors.push(String(error))))})
   await page.route('**/reports/v1/native/media-native/1',route=>route.fulfill({body:html,contentType:'text/html'}))
   await page.route('**'+base+'**',async route=>{
    try{
     const request=route.request(),endpoint=new URL(request.url()).pathname.slice(base.length);requests.push(endpoint)
     if(endpoint==='context')return route.fulfill({json:{context:{documentId:'media-native',format:'pptx',revision:1,parentRevision:null,scope:{database:'fixture',companyId:'fixture',userId:'fixture',threadId:'fixture'},origin:'upload',sourceFile:{path:'source.pptx',sha256:identity,size:source.length,mediaType:'application/vnd.openxmlformats-officedocument.presentationml.presentation'}},csrfToken:'media-fixture',capabilities:{pptx_editor:true},editingEnabled:true}})
     if(endpoint==='file')return route.fulfill({body:source,contentType:'application/vnd.openxmlformats-officedocument.presentationml.presentation'})
     if(endpoint==='preview.pdf')return route.fulfill({status:204,body:''})
     assert.equal(request.headers()['x-csrf-token'],'media-fixture');const payload=request.postDataJSON();assert.equal(payload.expectedSha256,identity);assert.ok(Array.isArray(payload.operations))
     if(endpoint==='save'){
      assert.equal(++saveCount,1);assert.match(payload.requestId,/^[\w-]+$/);await writeFile(resolve(directory,'saved-journal.json'),JSON.stringify(payload))
      const output=resolve(directory,'revision-2.pptx'),result=engine({mode:'inspect',operations:payload.operations,output});saved=await readFile(output);assert.equal(hash(saved),result.sha256)
      return route.fulfill({json:{documentId:'media-native',revision:2,parentRevision:1,revisionRegistered:true,artifacts:{pptx:{downloadUrl:'/media-download.pptx',path:'revision-2.pptx',size:result.size,sha256:result.sha256}},editor:null,validation:{ok:true,issues:[]}}})
     }
     if(endpoint==='preview'){const result=engine({mode:'inspect',operations:payload.operations});return route.fulfill({json:{sourceSha256:identity,draftSha256:result.sha256,model:result.model}})}
     assert.equal(endpoint,'render-tree');return route.fulfill({json:engine({mode:'render',operations:payload.operations})})
    }catch(error){errors.push(String(error));await route.fulfill({status:500,json:{detail:String(error)}})}
   })
  },
  async open(page){await page.goto(`http://127.0.0.1:${server.address().port}/reports/v1/native/media-native/1`);await page.locator('.slides-canvas canvas').first().waitFor({timeout:90000})},
  draft:page=>page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('native-editor-draft:')).flatMap(([,value])=>JSON.parse(value).operations)),
  async finish(){await Promise.all(checks);assert.deepEqual(errors,[]);assert.equal(saveCount,1);assert.equal(downloadCount,1);assert.equal(hash(await readFile(resolve(directory,'source.pptx'))),identity);return {authorization:'explicit-native-fixture',sourceSha256:identity,saveCount,downloadCount,resources:Object.fromEntries(resources),resourceCount:resources.size,requests,errors}}
 }
}
