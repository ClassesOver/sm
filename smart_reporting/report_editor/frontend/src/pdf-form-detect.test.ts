import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import type {PDFDocumentProxy} from 'pdfjs-dist'
import {NativeDraft} from './native-draft'
import {bindPdfFormDetect,collectPdfFormCandidates,stagePdfDetectedForm,type PdfDetectedFormCandidate} from './pdf-form-detect'
import type {PdfFormCreateModel} from './pdf-form-create'

const sourceSha256='a'.repeat(64)
beforeEach(()=>{
 Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value(this:HTMLDialogElement){this.open=true}})
 Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value(this:HTMLDialogElement){this.open=false;this.dispatchEvent(new Event('close'))}})
})
afterEach(()=>{document.body.replaceChildren()})
function model():PdfFormCreateModel{return {sourceSha256,pages:[{pageId:'p0',index:0,cropBox:{x:0,y:0,width:400,height:500}}],capabilities:{createFormField:true},formDesignWidgets:[]}}
function source(gate?:Promise<void>){return {numPages:1,getPage:async()=>{await gate;return {pageNumber:1,view:[0,0,400,500],rotate:0,userUnit:1,getTextContent:async()=>({items:[{str:'Name: ________',transform:[12,0,0,12,30,440],width:140,height:12}]}),getOperatorList:async()=>({fnArray:[],argsArray:[]})}}} as unknown as PDFDocumentProxy}
function fixture(gate?:Promise<void>,refresh:()=>Promise<void>=async()=>{}){
 const root=document.body.appendChild(document.createElement('div')),draft=new NativeDraft({documentId:'d',revision:1,sourceSha256,scope:{database:'db',companyId:'co',userId:'u',threadId:'t'}},{getItem:()=>null,setItem:()=>{},removeItem:()=>{}})
 let current=model(),page='p0',doc=source(gate),reason:string|null=null
 const panel=bindPdfFormDetect({root,draft,model:()=>current,sourceDocument:()=>doc,activePageId:()=>page,unavailable:()=>reason,refresh})
 return {root,draft,panel,changePage:()=>page='other',changeSource:()=>doc=source(),changeModel:()=>current={...current,sourceSha256:'b'.repeat(64)},changeGeometry:()=>current.pages[0].cropBox.width=399,block:()=>reason='当前只读'}
}
const candidate:PdfDetectedFormCandidate={sourceSha256,pageId:'p0',fieldName:'name',fieldKind:'text',rect:[100,439,260,457],required:false}
it('候选未确认及关闭不改稿，单选确认只加入一个真实字段操作，可撤销重做',async()=>{
 const f=fixture();f.panel.open();await vi.waitFor(()=>expect(f.root.querySelectorAll('input[type=radio]')).toHaveLength(1));expect(f.draft.operations).toEqual([])
 const apply=f.root.querySelector<HTMLButtonElement>('[data-pdf-form-detect-apply]')!;expect(apply.disabled).toBe(true)
 f.root.querySelector<HTMLDialogElement>('dialog')!.close();apply.dispatchEvent(new MouseEvent('click'));expect(f.draft.operations).toEqual([])
 f.panel.open();await vi.waitFor(()=>expect(f.root.querySelectorAll('input[type=radio]')).toHaveLength(1));f.root.querySelector<HTMLInputElement>('input[type=radio]')!.click();f.root.querySelector<HTMLButtonElement>('[data-pdf-form-detect-apply]')!.click()
 await vi.waitFor(()=>expect(f.draft.operations).toHaveLength(1));expect(f.draft.operations[0]).toMatchObject({kind:'createFormField',sourceSha256,pageId:'p0',fieldName:'name',fieldKind:'text',required:false})
 f.draft.undo();expect(f.draft.operations).toEqual([]);f.draft.redo();expect(f.draft.operations).toHaveLength(1);f.panel.dispose()
})
it.each(['page','source','model','geometry','draft','readonly','dispose'] as const)('检测中 %s 变化拒绝迟到候选且不改稿',async change=>{
 let release!:()=>void;const f=fixture(new Promise<void>(resolve=>{release=resolve}));f.panel.open()
 if(change==='page')f.changePage();if(change==='source')f.changeSource();if(change==='model')f.changeModel();if(change==='geometry')f.changeGeometry();if(change==='draft')f.draft.setOperations([{kind:'rotatePage',pageId:'p0',delta:90}]);if(change==='readonly')f.block();if(change==='dispose')f.panel.dispose()
 const before=f.draft.operations;f.panel.update();release();await new Promise(resolve=>setTimeout(resolve,15));expect(f.root.querySelectorAll('input[type=radio]')).toHaveLength(0);expect(f.draft.operations).toEqual(before)
})
it('已有候选在换页或改稿后拒绝保留的确认回调，撤销也不能复活旧结果',async()=>{
 const f=fixture();f.panel.open();await vi.waitFor(()=>expect(f.root.querySelector('input[type=radio]')).not.toBeNull());f.root.querySelector<HTMLInputElement>('input[type=radio]')!.click();const apply=f.root.querySelector<HTMLButtonElement>('[data-pdf-form-detect-apply]')!
 f.draft.setOperations([{kind:'rotatePage',pageId:'p0',delta:90}]);f.panel.update();f.draft.undo();f.panel.update();apply.dispatchEvent(new MouseEvent('click'));expect(f.draft.operations).toEqual([]);expect(f.root.textContent).toContain('重新检测')
})
it('候选必须通过既有类型、坐标、页面与来源契约，不允许其他草稿混入',()=>{
 expect(stagePdfDetectedForm(model(),[],candidate)).toEqual([{kind:'createFormField',...candidate}])
 for(const patch of [{sourceSha256:'b'.repeat(64)},{pageId:'foreign'},{fieldKind:'signature'},{rect:[0,0,900,50]},{rect:[0,0,6,6]},{fieldName:'a..b'}])expect(()=>stagePdfDetectedForm(model(),[],{...candidate,...patch} as PdfDetectedFormCandidate)).toThrow()
 expect(()=>stagePdfDetectedForm(model(),[{kind:'rotatePage'}],candidate)).toThrow(/单独/)
})
it('实际预览刷新失败仍保留已确认草稿并明确展示失败',async()=>{
 const f=fixture(undefined,async()=>{throw Error('preview unavailable')});f.panel.open();await vi.waitFor(()=>expect(f.root.querySelector('input[type=radio]')).not.toBeNull());f.root.querySelector<HTMLInputElement>('input[type=radio]')!.click();f.root.querySelector<HTMLButtonElement>('[data-pdf-form-detect-apply]')!.click()
 await vi.waitFor(()=>expect(f.root.textContent).toContain('草稿已保留'));expect(f.root.textContent).toContain('preview unavailable');expect(f.draft.operations).toHaveLength(1);expect(f.root.querySelector<HTMLButtonElement>('[data-pdf-form-detect-apply]')!.disabled).toBe(true)
})
