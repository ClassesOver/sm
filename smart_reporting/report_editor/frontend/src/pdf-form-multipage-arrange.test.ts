import {afterEach,expect,it,vi} from 'vitest'
import {NativeDraft} from './native-draft'
import {bindPdfFormCreatePanel,stagePdfFormWidgetArrangement,type PdfFormCreateModel,type PdfFormWidgetTarget} from './pdf-form-create'
afterEach(()=>document.body.replaceChildren())
const sourceSha256='a'.repeat(64),pageId=(i:number)=>'sha256:'+sourceSha256+':page:'+i
const widgets=Array.from({length:7},(_,i)=>({fieldName:'f'+i,widgetId:(i+7)+'R',widgetIdentity:String(i+1).repeat(64),expectedWidgetSha256:String(i+1).repeat(64),pageIndex:i<3?0:i<6?1:2,rect:[30+(i%3)*70,80+(i%3)*80,70+(i%3)*80,100+(i%3)*85]as[number,number,number,number],required:false,removable:true,removalReason:null,designEditable:true}))
const target=(w:typeof widgets[number]):PdfFormWidgetTarget=>({fieldName:w.fieldName,widgetId:w.widgetId,widgetIdentity:w.widgetIdentity,expectedWidgetSha256:w.expectedWidgetSha256})
function model():PdfFormCreateModel{return {sourceSha256,pages:[0,1,2].map(i=>({pageId:pageId(i),index:i,rotation:i*90,cropBox:{x:10,y:10,width:380+i*30,height:480+i*30}})),formDesignWidgets:widgets,capabilities:{createFormField:true,arrangeFormWidgets:true}}}
it('stages all page identities once while checking page-local geometry and incomplete groups',()=>{
 const m=model(),targets=widgets.map(target);expect(stagePdfFormWidgetArrangement(m,[],targets,'sameSize')).toEqual([{kind:'arrangeFormWidgets',sourceSha256,targets,alignment:'sameSize'}]);expect(stagePdfFormWidgetArrangement(m,[],widgets.filter(w=>w.fieldName!=='f5').map(target),'distributeV')).toHaveLength(1)
 expect(()=>stagePdfFormWidgetArrangement(m,[],widgets.filter(w=>['f0','f3','f6'].includes(w.fieldName)).map(target),'left')).toThrow(/每页/);expect(()=>stagePdfFormWidgetArrangement(m,[],widgets.filter(w=>!['f2','f5'].includes(w.fieldName)).map(target),'distributeH')).toThrow(/每页/)
 for(const key of ['fieldName','widgetId','widgetIdentity','expectedWidgetSha256']as const){const forged=targets.map(t=>({...t}));forged.at(-1)![key]=key==='widgetId'?'999R':key==='fieldName'?'forged':'f'.repeat(64);expect(()=>stagePdfFormWidgetArrangement(m,[],forged,'left')).toThrow(/身份/)}
 const missing=model();missing.pages=missing.pages.slice(0,1);expect(()=>stagePdfFormWidgetArrangement(missing,[],targets,'left')).toThrow(/页面/)
 expect(()=>stagePdfFormWidgetArrangement(m,[{kind:'unknown'}],targets,'left')).toThrow()
})
it('real arrangement panel names each page and stages a multi-page selection through the draft',async()=>{
 const root=document.createElement('div');document.body.append(root);const draft=new NativeDraft({documentId:'multipage-arrange',revision:1,sourceSha256,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem:vi.fn(),removeItem:vi.fn()}),panel=bindPdfFormCreatePanel({root,draft,model,activePageId:()=>pageId(0),unavailable:()=>null,refresh:async()=>{}})
 panel.open('arrange');expect(root.textContent).toContain('按页独立排列');expect(root.querySelector('[aria-label="f3 控件 10R（第2页）"]')).not.toBeNull();for(const input of root.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'))input.checked=true;root.querySelector<HTMLButtonElement>('[data-pdf-form-arrange-apply]')!.click();await vi.waitFor(()=>expect(draft.operations).toHaveLength(1));expect(draft.operations[0]).toMatchObject({kind:'arrangeFormWidgets',targets:widgets.map(target)});draft.undo();expect(draft.operations).toEqual([]);draft.redo();expect(draft.operations).toHaveLength(1);panel.dispose()
})
it('rejects a missing source page even when its selected widget group would be skipped',()=>{
 const m=model();m.pages=m.pages.filter(p=>p.index!==2);expect(()=>stagePdfFormWidgetArrangement(m,[],widgets.map(target),'left')).toThrow(/页面/)
})
