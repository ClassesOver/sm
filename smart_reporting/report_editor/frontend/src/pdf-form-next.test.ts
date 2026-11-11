import {afterEach,expect,it,vi} from 'vitest'
import {NativeDraft} from './native-draft'
import * as creation from './pdf-form-create'
afterEach(()=>document.body.replaceChildren())
const sourceSha256='a'.repeat(64),pageId='sha256:'+sourceSha256+':page:0'
const widgets=[{fieldName:'party.consent',fieldKind:'radio',widgetId:'7R',widgetIdentity:'b'.repeat(64),expectedWidgetSha256:'c'.repeat(64),pageIndex:0,rect:[30,180,50,200] as [number,number,number,number],required:true,radioOptions:['Yes','No'],radioValue:'Yes',removable:false,removalReason:'multi',designEditable:true},{fieldName:'party.consent',fieldKind:'radio',widgetId:'8R',widgetIdentity:'d'.repeat(64),expectedWidgetSha256:'e'.repeat(64),pageIndex:0,rect:[80,180,100,200] as [number,number,number,number],required:true,radioOptions:['Yes','No'],radioValue:'Yes',removable:false,removalReason:'multi',designEditable:true}]
const target=()=>Object.fromEntries(['fieldName','widgetId','widgetIdentity','expectedWidgetSha256'].map(k=>[k,widgets[0][k as keyof typeof widgets[0]]])) as any
const model=()=>({sourceSha256,pages:[{pageId,index:0,cropBox:{x:0,y:0,width:300,height:400}}],formDesignWidgets:widgets,capabilities:{createFormField:true,appendRadioWidget:true}})
const input=()=>({pageId,rect:[130,180,150,200] as [number,number,number,number],exportValue:'Maybe'})
const create=()=>({pageId,fieldName:'party.customer.name',fieldKind:'text' as const,rect:[30,180,150,204] as [number,number,number,number],required:true})
async function api(){const path='./pdf-form-radio-extension';const module=await import(/* @vite-ignore */ path).catch(()=>null);expect(module,'radio extension frontend exists').not.toBeNull();return module!}
it('creates safe hierarchical names and checks current prefixes when restoring drafts',()=>{
 const m=model(),ops=creation.stagePdfFormCreation(m,[],create());expect(ops[0].fieldName).toBe('party.customer.name')
 for(const name of ['party','party.consent','party.consent.detail','party..name','party.','a.'.repeat(16)+'b'])expect(()=>creation.stagePdfFormCreation(m,[],{...create(),fieldName:name})).toThrow()
 const restore=(creation as any).validateRestoredPdfFormCreation;expect(typeof restore).toBe('function');expect(()=>restore(m,ops)).not.toThrow();expect(()=>restore({...m,sourceSha256:'f'.repeat(64)},ops)).toThrow();expect(()=>restore({...m,formDesignWidgets:[...widgets,{...widgets[0],fieldName:'party.customer.name'}]},ops)).toThrow()
})
it('appends strict radio draft and restores all source identities capabilities options and page bounds',async()=>{
 const m=await api(),source=model(),ops=m.stagePdfRadioExtension(source,[],target(),input());expect(ops[0]).toMatchObject({kind:'appendRadioWidget',sourceSha256,...input()});expect(()=>m.validateRestoredPdfRadioExtension(source,ops)).not.toThrow()
 for(const key of ['fieldName','widgetId','widgetIdentity','expectedWidgetSha256'])expect(()=>m.stagePdfRadioExtension(source,[],{...target(),[key]:'forged'},input())).toThrow()
 for(const patch of [{exportValue:'Yes'},{exportValue:'中文'},{rect:[0,0,1,1]},{pageId:'stale'},{checked:true}])expect(()=>m.stagePdfRadioExtension(source,[],target(),{...input(),...patch} as any)).toThrow()
 expect(()=>m.stagePdfRadioExtension(source,ops,target(),input())).toThrow(/单独/);expect(()=>m.validateRestoredPdfRadioExtension({...source,sourceSha256:'f'.repeat(64)},ops)).toThrow();expect(()=>m.validateRestoredPdfRadioExtension({...source,capabilities:{appendRadioWidget:false}},ops)).toThrow()
 expect(()=>m.validatePdfRadioExtension([{...ops[0],checked:true}])).toThrow()
})
it('real append panel deduplicates radio groups and retains staged draft after refresh failure',async()=>{
 const m=await api(),root=document.createElement('div');document.body.append(root);const draft=new NativeDraft({documentId:'radio',revision:1,sourceSha256,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem:vi.fn(),removeItem:vi.fn()}),panel=m.bindPdfRadioExtensionPanel({root,draft,model,activePageId:()=>pageId,unavailable:()=>null,refresh:async()=>{throw Error('preview failed')}})
 panel.open();expect(root.querySelectorAll('select[aria-label="单选组"] option')).toHaveLength(1);root.querySelector<HTMLInputElement>('input[aria-label="新增选项值"]')!.value='Maybe';root.querySelector<HTMLButtonElement>('[data-pdf-radio-extension-apply]')!.click();await vi.waitFor(()=>expect(draft.operations).toHaveLength(1));expect(draft.operations[0].kind).toBe('appendRadioWidget');await vi.waitFor(()=>expect(root.textContent).toContain('草稿已保留'));draft.undo();expect(draft.operations).toEqual([]);draft.redo();expect(draft.operations[0].exportValue).toBe('Maybe');panel.dispose()
})
it('blocked disposed stale source and mixed drafts never stage radio append',async()=>{
 const m=await api()
 for(const state of ['blocked','disposed','stale','mixed']){const root=document.createElement('div');document.body.append(root);const draft=new NativeDraft({documentId:state,revision:1,sourceSha256,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem:vi.fn(),removeItem:vi.fn()}),panel=m.bindPdfRadioExtensionPanel({root,draft,model:()=>state==='stale'?{...model(),sourceSha256:'f'.repeat(64)}:model(),activePageId:()=>pageId,unavailable:()=>state==='blocked'?'只读':null,refresh:async()=>{}});panel.open();const button=root.querySelector<HTMLButtonElement>('[data-pdf-radio-extension-apply]')!;root.querySelector<HTMLInputElement>('input[aria-label="新增选项值"]')!.value='Maybe';if(state==='disposed')panel.dispose();if(state==='mixed')draft.setOperations([{kind:'setFormValue',name:'x',value:'y'}]);button.dispatchEvent(new MouseEvent('click'));await Promise.resolve();expect(draft.operations).toEqual(state==='mixed'?[{kind:'setFormValue',name:'x',value:'y'}]:[]);panel.dispose()}
})
