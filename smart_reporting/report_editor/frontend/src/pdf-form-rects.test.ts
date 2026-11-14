import {describe,it,expect} from 'vitest'
import * as creation from './pdf-form-create'
import {NativeDraft} from './native-draft'
const sha='a'.repeat(64),widgets=[0,1].map(i=>({fieldName:'field'+i,widgetId:(7+i)+'R',widgetIdentity:String(i+1).repeat(64),expectedWidgetSha256:'b'.repeat(64),pageIndex:0,rect:[20+i*60,40,60+i*60,60]as [number,number,number,number],designEditable:true,removable:true,removalReason:null,fieldKind:'text'}))
const model=()=>({sourceSha256:sha,pages:[{pageId:'p',index:0,cropBox:{x:0,y:0,width:300,height:400}}],formDesignWidgets:widgets,capabilities:{editFormWidget:true}})
const changes=()=>widgets.map(({fieldName,widgetId,widgetIdentity,expectedWidgetSha256,rect})=>({fieldName,widgetId,widgetIdentity,expectedWidgetSha256,rect:rect.map(v=>v+10)as [number,number,number,number]}))
const stage=(...args:any[])=>{const fn=(creation as any).stagePdfFormWidgetRects;expect(typeof fn).toBe('function');return fn(...args)}
describe('source-bound multi-widget geometry',()=>{
 it('stages and replaces one atomic geometry draft, merges subsequent gestures and removes identity moves',()=>{
  const m=model(),first=stage(m,[],changes());expect(first).toEqual([{kind:'editFormWidgetRects',sourceSha256:sha,changes:changes()}]);const second=stage(m,first,[{...changes()[0],rect:[35,55,75,75]}]);expect(second[0].changes).toHaveLength(2);expect(second[0].changes[0].rect).toEqual([35,55,75,75]);expect(stage(m,second,widgets.map(w=>({...changes().find(c=>c.widgetId===w.widgetId),rect:w.rect})))).toEqual([])
  const draft=new NativeDraft({documentId:'d',revision:1,sourceSha256:sha,scope:{database:'db',companyId:'co',userId:'u',threadId:'t'}},{getItem:()=>null,setItem:()=>{},removeItem:()=>{}});draft.setOperations(first);draft.setOperations(second);draft.undo();expect(draft.operations).toEqual(first);draft.redo();expect(draft.operations).toEqual(second)
 })
 it('rejects mixed, duplicate, stale, out of bounds and malformed restored geometry before staging',()=>{
  const m=model();for(const values of [[],[changes()[0],changes()[0]],[{...changes()[0],widgetIdentity:'f'.repeat(64)}],[{...changes()[0],rect:[0,0,7,10]}],[{...changes()[0],rect:[0,0,400,10]}],[{...changes()[0],required:true}]])expect(()=>stage(m,[],values)).toThrow();expect(()=>stage(m,[{kind:'insertText'}],changes())).toThrow();expect(()=>stage({...m,capabilities:{editFormWidget:false}},[],changes())).toThrow()
  for(const patch of [{changes:[]},{changes:[{...changes()[0],required:true}]},{extra:true}])expect(()=>creation.validatePdfFormCreation([{kind:'editFormWidgetRects',sourceSha256:sha,changes:changes(),...patch}])).toThrow()
 })
})
