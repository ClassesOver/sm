import {expect,it} from 'vitest'
import {stagePdfFormCreation,replacePdfFormCreation,removePdfFormCreation,validateRestoredPdfFormCreation,type PdfFormCreation} from './pdf-form-create'
const model={sourceSha256:'a'.repeat(64),pages:[{pageId:'p',index:0,cropBox:{x:0,y:0,width:300,height:400}},{pageId:'q',index:1,cropBox:{x:0,y:0,width:300,height:400}}],capabilities:{createFormField:true},formDesignWidgets:[]}
const input:PdfFormCreation={pageId:'p',fieldName:'customer.name',fieldKind:'text',rect:[30,200,150,224],required:true,value:'Alice'}
it('appends multiple fields and updates or deletes only the stable selected name',()=>{
 const first=stagePdfFormCreation(model,[],input),all=stagePdfFormCreation(model,first,{...input,pageId:'q',fieldName:'customer.other',value:'Bob'})
 expect(all).toHaveLength(2);expect(first).toHaveLength(1);expect(()=>validateRestoredPdfFormCreation(model,all)).not.toThrow()
 const updated=replacePdfFormCreation(model,all,'customer.other',{...input,pageId:'q',fieldName:'customer.other',value:'Updated'})
 expect(updated[0]).toEqual(all[0]);expect(updated[1]!.value).toBe('Updated');expect(removePdfFormCreation(model,updated,'customer.name')).toEqual([updated[1]])
})
it('rejects duplicate or prefix names stale sources mixed operations and invalid later geometry',()=>{
 const first=stagePdfFormCreation(model,[],input)
 for(const patch of [{fieldName:input.fieldName},{fieldName:'customer'},{fieldName:input.fieldName+'.child'},{fieldName:'other',rect:[0,0,0,0] as [number,number,number,number]}])expect(()=>stagePdfFormCreation(model,first,{...input,...patch})).toThrow()
 expect(()=>stagePdfFormCreation(model,[{kind:'rotatePage'}],input)).toThrow()
 expect(()=>validateRestoredPdfFormCreation(model,[first[0]!,{...first[0]!,fieldName:'other',sourceSha256:'b'.repeat(64)}])).toThrow()
 expect(()=>replacePdfFormCreation(model,first,'missing',input)).toThrow()
})
