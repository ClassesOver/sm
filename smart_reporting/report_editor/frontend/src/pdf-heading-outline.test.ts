// @vitest-environment node
import {execFileSync} from 'node:child_process'
import {fileURLToPath} from 'node:url'
import {afterEach,expect,it,vi} from 'vitest'
import {getDocument} from 'pdfjs-dist/legacy/build/pdf.mjs'
import type {PDFDocumentProxy} from 'pdfjs-dist'
import {readPdfNavigationOutline} from './pdf-heading-outline'
import {buildHeadingOutline} from './vendor/genoffice-pdf/renderer/heading-outline'

const repo=fileURLToPath(new URL('../../../../',import.meta.url))
const sources=JSON.parse(execFileSync(`${repo}.venv/bin/python`,[fileURLToPath(new URL('../smoke/pdf-heading-outline-source.py',import.meta.url))],{cwd:repo,env:{...process.env,PYTHONPATH:repo},encoding:'utf8'}))
const tasks:ReturnType<typeof getDocument>[]=[]
afterEach(async()=>{await Promise.all(tasks.splice(0).map(task=>task.destroy()));vi.restoreAllMocks()})
async function load(kind:string){const task=getDocument({data:new Uint8Array(Buffer.from(sources[kind].bytes,'base64')),useSystemFonts:true});tasks.push(task);return task.promise}

it('derives the pinned size-tier tree from actual PDF.js text and keeps page zero',async()=>{
 const document=await load('headings')
 expect(await document.getOutline()).toBeNull()
 expect(await readPdfNavigationOutline(document)).toEqual({generated:true,items:[
  {title:'User Guide',depth:0,pageIndex:0},
  {title:'Chapter Alpha',depth:1,pageIndex:1},
  {title:'Section Details',depth:2,pageIndex:1},
  {title:'Chapter Beta',depth:1,pageIndex:2},
 ]})
})
it('returns no inferred structure for a real PDF with only body-sized text',async()=>{
 expect(await readPdfNavigationOutline(await load('plain'))).toEqual({generated:false,items:[]})
})
it('prefers actual embedded bookmarks without scanning page text',async()=>{
 const document=await load('embedded'),getPage=vi.spyOn(document,'getPage')
 expect(await readPdfNavigationOutline(document)).toEqual({generated:false,items:[{title:'Embedded First',depth:0,pageIndex:0},{title:'Embedded Last',depth:0,pageIndex:2}]})
 expect(getPage).not.toHaveBeenCalled()
})
it('uses the same heading fallback when embedded-outline reading rejects',async()=>{
 const document=await load('headings');vi.spyOn(document,'getOutline').mockRejectedValueOnce(Error('embedded outline unreadable'))
 expect((await readPdfNavigationOutline(document))?.items.map(item=>item.title)).toEqual(['User Guide','Chapter Alpha','Section Details','Chapter Beta'])
})
it('discards a cancelled embedded read before starting a text scan',async()=>{
 let release!:(value:null)=>void,cancelled=false
 const getPage=vi.fn(),document={getOutline:()=>new Promise<null>(done=>{release=done}),getPage} as unknown as PDFDocumentProxy
 const reading=readPdfNavigationOutline(document,()=>cancelled);cancelled=true;release(null)
 expect(await reading).toBeNull();expect(getPage).not.toHaveBeenCalled()
})
it('allows the in-flight page to settle but stops subsequent pages after cancellation',async()=>{
 let release!:(value:{items:[]})=>void,cancelled=false
 const getTextContent=()=>new Promise<{items:[]}>(done=>{release=done})
 const getPage=vi.fn(async()=>({getTextContent}))
 const document={numPages:3,getOutline:async()=>null,getPage} as unknown as PDFDocumentProxy
 const reading=readPdfNavigationOutline(document,()=>cancelled)
 await vi.waitFor(()=>expect(release).toBeTypeOf('function'));cancelled=true;release({items:[]})
 expect(await reading).toBeNull();expect(getPage.mock.calls).toHaveLength(1)
})
it('keeps the pinned 400-page scan bound',async()=>{
 const getPage=vi.fn(async()=>({getTextContent:async()=>({items:[]})}))
 expect(await buildHeadingOutline({numPages:405,getPage} as unknown as PDFDocumentProxy)).toBeNull()
 expect(getPage).toHaveBeenCalledTimes(400);expect(getPage).toHaveBeenLastCalledWith(400)
})
