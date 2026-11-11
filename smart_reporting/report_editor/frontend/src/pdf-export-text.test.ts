import {beforeEach,afterEach,expect,it,vi} from 'vitest'
import {webcrypto,createHash} from 'node:crypto'
import {bindPdfExportTextDialog,verifiedPdfTextDocx,type PdfTextOfficeResult} from './pdf-export-text'
vi.mock('./pdf-export-text-render',()=>({renderPdfTextExport:vi.fn(async()=>({text:'Report',warnings:['人工核对']}))}))
const bytes=new Uint8Array([80,75,3,4,1,2,3,4]),source='a'.repeat(64)
const result=():PdfTextOfficeResult=>({documentId:'child',revision:1,parentRevision:null,revisionRegistered:true,source:{sha256:source},artifacts:{word:{downloadUrl:'/download/report.docx',size:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex')}},validation:{ok:false,issues:[{code:'manual',message:'人工复核'}]}})
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value(this:HTMLDialogElement){this.open=true}});Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value(this:HTMLDialogElement){this.open=false;this.dispatchEvent(new Event('close'))}});Object.defineProperty(URL,'createObjectURL',{configurable:true,value:vi.fn(()=> 'blob:text-export')});Object.defineProperty(URL,'revokeObjectURL',{configurable:true,value:vi.fn()})})
afterEach(()=>{document.body.replaceChildren();vi.restoreAllMocks();vi.unstubAllGlobals()})
it.each(['sha','size','source','origin','signature'])('rejects untrusted intermediate Word %s',async kind=>{
 const value=result();let actual=bytes
 if(kind==='sha')value.artifacts.word!.sha256='f'.repeat(64)
 if(kind==='size')value.artifacts.word!.size!++
 if(kind==='source')value.source!.sha256='f'.repeat(64)
 if(kind==='origin')value.artifacts.word!.downloadUrl='https://foreign.example/report.docx'
 if(kind==='signature')actual=new Uint8Array([0,0,0,0,1,2,3,4])
 const fetchFile=vi.fn(async()=>new Response(actual))
 await expect(verifiedPdfTextDocx(value,source,'http://localhost/',fetchFile)).rejects.toThrow(/身份|地址/)
 if(kind==='source'||kind==='origin')expect(fetchFile).not.toHaveBeenCalled()
})
it.each(['markdown','html'] as const)('downloads %s through verified Word and manual review',async format=>{
 const root=document.createElement('div');document.body.append(root);const convertOffice=vi.fn(async(_payload:unknown)=>result())
 const view=bindPdfExportTextDialog({root,sourceSha256:source,unavailable:()=>null,convertOffice,fetchFile:async()=>new Response(bytes)})
 view.open(format);root.querySelector<HTMLButtonElement>('[data-pdf-export-text-apply]')!.click()
 await vi.waitFor(()=>expect(root.querySelector('a[download]')).not.toBeNull())
 expect(convertOffice.mock.calls[0]![0]).toMatchObject({expectedSha256:source,format:'docx'});expect(root.querySelector('a[download]')!.getAttribute('download')).toBe(format==='html'?'pdf-report.html':'pdf-report.md')
 expect(root.textContent).toContain('验收未通过');expect(root.textContent).toContain('下载已生成的 Word');view.dispose();expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:text-export')
})
it('keeps Word download after browser serialization fails',async()=>{
 const {renderPdfTextExport}=await import('./pdf-export-text-render');vi.mocked(renderPdfTextExport).mockRejectedValueOnce(Error('renderer failed'))
 const root=document.createElement('div');document.body.append(root);const view=bindPdfExportTextDialog({root,sourceSha256:source,unavailable:()=>null,convertOffice:async()=>result(),fetchFile:async()=>new Response(bytes)})
 view.open('html');root.querySelector<HTMLButtonElement>('[data-pdf-export-text-apply]')!.click();await vi.waitFor(()=>expect(root.textContent).toContain('renderer failed'));expect(root.querySelector('a')!.textContent).toContain('Word');expect(root.querySelector('a[download]')).toBeNull();view.dispose()
})
it('ignores completed conversion after closing',async()=>{
 const root=document.createElement('div');document.body.append(root);let done!:(value:PdfTextOfficeResult)=>void
 const view=bindPdfExportTextDialog({root,sourceSha256:source,unavailable:()=>null,convertOffice:()=>new Promise(resolve=>{done=resolve})})
 view.open('markdown');root.querySelector<HTMLButtonElement>('[data-pdf-export-text-apply]')!.click();root.querySelector('dialog')!.close();done(result());await new Promise(resolve=>setTimeout(resolve,0));expect(URL.createObjectURL).not.toHaveBeenCalled();view.dispose()
})
