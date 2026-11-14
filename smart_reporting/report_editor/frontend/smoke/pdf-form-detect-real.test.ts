// @vitest-environment node
import {afterEach,expect,it} from 'vitest'
import {readFile} from 'node:fs/promises'
import {createRequire} from 'node:module'
import {getDocument,type PDFDocumentLoadingTask} from 'pdfjs-dist/legacy/build/pdf.mjs'
import {collectPdfFormCandidates,stagePdfDetectedForm} from '../src/pdf-form-detect'
import {createDesignField} from '../../../reporting/pdf_engine/bridge/form-design-create'
import type {PdfFormCreateModel} from '../src/pdf-form-create'
const require=createRequire(new URL('../../../reporting/pdf_engine/package.json',import.meta.url)),{PDFDocument}=require('pdf-lib')
const tasks:PDFDocumentLoadingTask[]=[]
afterEach(async()=>{await Promise.all(tasks.splice(0).map(task=>task.destroy()))})
it('真实 PDF 使用固定源文字及图形检测，排除签名并沿现有 writer 独立回读',async()=>{
 const bytes=new Uint8Array(await readFile(new URL('../../../reporting/pdf_engine/bridge/fixtures/form-auto-detect-reportlab.pdf',import.meta.url))),hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('')
 const task=getDocument({data:bytes.slice(),useSystemFonts:true});tasks.push(task);const doc=await task.promise
 const m:PdfFormCreateModel={sourceSha256:hash,pages:[0,1].map(index=>({pageId:`sha256:${hash}:page:${index}`,index,cropBox:{x:0,y:0,width:400,height:500}})),capabilities:{createFormField:true},formDesignWidgets:[]}
 const found=await collectPdfFormCandidates(m,doc,()=>{})
 expect(found.candidates.map(c=>[c.fieldName,c.fieldKind,c.pageId.endsWith(':1')?1:0,c.rect])).toEqual([['name','text',0,[100,439,260,457]],['date','date',0,[100,379,260,397]],['agree','checkbox',0,[100,320,114,334]],['name_1','text',1,[101,401,239,421]]])
 expect(found.skipped.some(reason=>reason.includes('签名'))).toBe(true)
 for(const c of found.candidates){const [op]=stagePdfDetectedForm(m,[],c),result=await createDesignField(bytes,hash,op as any);expect(result.skippedOperations).toEqual([]);expect(result.appliedOperationIndices).toEqual([0]);const actual=await PDFDocument.load(result.bytes),field=actual.getForm().getField(c.fieldName),r=field.acroField.getWidgets()[0].getRectangle();expect([r.x,r.y,r.x+r.width,r.y+r.height]).toEqual(c.rect);expect(actual.getPageCount()).toBe(2);expect(actual.getForm().getFields()).toHaveLength(1)}
 const occupied={...m,formDesignWidgets:[{fieldName:'agree',widgetId:'7R',widgetIdentity:'b'.repeat(64),expectedWidgetSha256:'c'.repeat(64),pageIndex:0,rect:[100,320,114,334] as [number,number,number,number],removable:true,removalReason:null}]}
 expect((await collectPdfFormCandidates(occupied,doc,()=>{})).candidates.some(c=>c.fieldKind==='checkbox')).toBe(false)
})
