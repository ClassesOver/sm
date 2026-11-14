import {createServer} from 'vite'
import {chromium} from 'playwright'
import assert from 'node:assert/strict'
import {mkdtemp,readFile,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import JSZip from 'jszip'
const server=await createServer({optimizeDeps:{entries:['src/docx-export.ts'],include:['jszip','@tiptap/core','react/jsx-runtime','zod','@dagrejs/dagre','pathfinding']},server:{host:'127.0.0.1',port:0}})
await server.listen()
const browser=await chromium.launch({headless:true})
const dir=await mkdtemp(join(tmpdir(),'docx-export-'))
try{
 const page=await browser.newPage({acceptDownloads:true})
 await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/reports/v1/editor/assets/`)
 await page.evaluate(async()=>{
  const {Editor,Node}=await import('/reports/v1/editor/assets/node_modules/@tiptap/core/dist/index.js')
  const {createDocxExportControls}=await import('/reports/v1/editor/assets/src/docx-export.ts')
  const doc=Node.create({name:'doc',topNode:true,content:'docParagraph+',renderHTML:()=>['div',0]})
  const p=Node.create({name:'docParagraph',content:'inline*',renderHTML:()=>['p',0]})
  const text=Node.create({name:'text',group:'inline'})
  const img=Node.create({name:'docInlineImage',group:'inline',inline:true,atom:true,addAttributes:()=>({dataUrl:{default:null}}),renderHTML:({node})=>['img',{src:node.attrs.dataUrl}]})
  const element=document.body.appendChild(document.createElement('div'))
  const editor=new Editor({element,extensions:[doc,p,text,img],content:{type:'doc',content:[{type:'docParagraph',content:[{type:'text',text:'导出验收'}, {type:'docInlineImage',attrs:{dataUrl:'data:image/png;base64,iVBORw0KGgo='}}]}]}})
  window.exportsControl=createDocxExportControls({editor,container:document.body,title:'浏览器导出.docx',onError:error=>{throw error}})
 })
 for(const format of ['markdown','html']){
  const [download,result]=await Promise.all([page.waitForEvent('download'),page.evaluate(format=>window.exportsControl.run(format),format)])
  assert.equal(result,true)
  const path=join(dir,download.suggestedFilename());await download.saveAs(path)
  const bytes=await readFile(path)
  if(format==='markdown'){
   assert.equal(download.suggestedFilename(),'浏览器导出.zip')
   const zip=await JSZip.loadAsync(bytes)
   assert.equal(await zip.file('浏览器导出.md').async('string'),'导出验收![](media/image1.png)\n')
   assert.equal((await zip.file('media/image1.png').async('uint8array')).length,8)
  }else{
   assert.match(bytes.toString(),/导出验收/);assert.match(bytes.toString(),/data:image\/png;base64,iVBORw0KGgo=/)
   assert.match(bytes.toString(),/<!DOCTYPE html>/)
  }
 }
 console.log('PASS: browser downloads standalone HTML and Markdown ZIP with exact embedded image bytes')
}finally{await browser.close();await server.close();await rm(dir,{recursive:true,force:true})}
