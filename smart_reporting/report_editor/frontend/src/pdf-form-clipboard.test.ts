import {expect,it} from 'vitest'
import {PdfFormClipboard} from './pdf-form-clipboard'
import {stagePdfFormCreation,type PdfFormCreateModel,type PdfFormCreation} from './pdf-form-create'
const sha='a'.repeat(64),model:PdfFormCreateModel={sourceSha256:sha,pages:[{pageId:'p',cropBox:{x:0,y:0,width:300,height:400}},{pageId:'q',cropBox:{x:20,y:30,width:300,height:400}}],capabilities:{createFormField:true},formDesignWidgets:[]},input:PdfFormCreation={pageId:'p',fieldName:'customer.name',fieldKind:'text',rect:[30,200,150,224],required:true,value:'Alice'}
it('copy snapshots canonical pending properties without changing draft and paste binds target page',()=>{
 const operations=stagePdfFormCreation(model,[],input),original=structuredClone(operations),clipboard=new PdfFormClipboard(sha)
 clipboard.copy(model,operations,'p',['customer.name']);expect(operations).toEqual(original);expect(clipboard.hasContent).toBe(true)
 operations[0]!.value='Changed';const pasted=clipboard.paste(model,operations,'q')
 expect(pasted).toHaveLength(2);expect(pasted[0]!.value).toBe('Changed');expect(pasted[1]).toMatchObject({fieldName:'customer.name_copy1',pageId:'q',value:'Alice',required:true,rect:[60,220,180,244]})
})
it('duplicate does not overwrite copied content and generates unique same-parent names',()=>{
 const operations=stagePdfFormCreation(model,[],input),clipboard=new PdfFormClipboard(sha);clipboard.copy(model,operations,'p',['customer.name'])
 const other=stagePdfFormCreation(model,operations,{...input,fieldName:'other',value:'Other'})
 const duplicated=clipboard.duplicate(model,other,'p',['other']);expect(duplicated.at(-1)).toMatchObject({fieldName:'other_copy1',value:'Other'})
 const pasted=clipboard.paste(model,duplicated,'p');expect(pasted.at(-1)).toMatchObject({fieldName:'customer.name_copy1',value:'Alice'})
 expect(clipboard.paste(model,pasted,'p').at(-1)!.fieldName).toBe('customer.name_copy2')
})
it('preserves relative rectangles and clamps the whole group without resizing',()=>{
 const first=stagePdfFormCreation(model,[],{...input,rect:[170,300,290,324]}),operations=stagePdfFormCreation(model,first,{...input,fieldName:'customer.second',rect:[150,240,270,264]}),clipboard=new PdfFormClipboard(sha)
 clipboard.copy(model,operations,'p',['customer.name','customer.second']);const result=clipboard.paste(model,operations,'p')
 expect(result.slice(2).map(op=>op.rect)).toEqual([[180,290,300,314],[160,230,280,254]])
})
it('rejects source changes unknown fields mixed drafts oversized layouts and operation budgets',()=>{
 const operations=stagePdfFormCreation(model,[],input),clipboard=new PdfFormClipboard(sha)
 expect(()=>clipboard.copy(model,operations,'p',['missing'])).toThrow();clipboard.copy(model,operations,'p',['customer.name'])
 expect(()=>clipboard.paste({...model,sourceSha256:'b'.repeat(64)},operations,'p')).toThrow()
 expect(()=>clipboard.paste(model,[{kind:'rotatePage'}],'p')).toThrow()
 expect(()=>clipboard.paste({...model,pages:[...model.pages,{pageId:'small',cropBox:{x:0,y:0,width:50,height:50}}]},operations,'small')).toThrow()
 const many=Array.from({length:500},(_,i)=>({...operations[0]!,fieldName:'field'+i}));expect(()=>clipboard.paste(model,many,'p')).toThrow()
})
it('copies complete radio groups and refuses a paste without enough destination pages',()=>{
 const radio={...input,fieldName:'answer',fieldKind:'radio' as const,rect:[30,100,50,120] as [number,number,number,number],value:undefined,radioWidgets:[{pageId:'p',rect:[30,100,50,120] as [number,number,number,number],exportValue:'Yes',checked:true},{pageId:'p',rect:[70,100,90,120] as [number,number,number,number],exportValue:'No'}]};delete radio.value
 const operations=stagePdfFormCreation(model,[],radio),clipboard=new PdfFormClipboard(sha);clipboard.copy(model,operations,'p',['answer'])
 const group=clipboard.paste(model,operations,'q').at(-1)!;expect(group).toMatchObject({fieldName:'answer_copy1',pageId:'q'});expect((group.radioWidgets as any[]).map(w=>[w.pageId,w.exportValue,w.checked])).toEqual([['q','Yes',true],['q','No',undefined]])
 const mixed=structuredClone(operations);(mixed[0]!.radioWidgets as any[])[1].pageId='q';clipboard.copy(model,mixed,'p',['answer']);expect(()=>clipboard.paste(model,mixed,'q')).toThrow();expect((clipboard.paste(model,mixed,'p').at(-1)!.radioWidgets as any[]).map(row=>row.pageId)).toEqual(['p','q'])
})
it('truncates long leaves and fits unique names within the full hierarchy name budget',()=>{
 const clipboard=new PdfFormClipboard(sha)
 for(const name of ['A'.repeat(64),'a'.repeat(63)+'.'+'b'.repeat(63)+'.'+'c'.repeat(63)+'.'+'d'.repeat(61)+'.EF']){
  const operations=stagePdfFormCreation(model,[],{...input,fieldName:name});clipboard.copy(model,operations,'p',[name]);const generated=String(clipboard.paste(model,operations,'p').at(-1)!.fieldName)
  expect(generated).not.toBe(name);expect(generated.length).toBeLessThanOrEqual(256);expect(generated.split('.').at(-1)!.length).toBeLessThanOrEqual(64)
 }
})
it('copies existing safe source fields by trusted identity and preserves template through repeated copies',()=>{
 const source={fieldName:'customer.name',widgetId:'7R',widgetIdentity:'b'.repeat(64),expectedWidgetSha256:'c'.repeat(64),copyEditable:true,designEditable:true,fieldKind:'text',required:true,rect:[30,200,150,224] as [number,number,number,number],pageIndex:0,removable:true,removalReason:null},m={...model,formDesignWidgets:[source]},clipboard=new PdfFormClipboard(sha)
 clipboard.copy(m,[],'p',['customer.name']);const result=clipboard.paste(m,[],'q')
 expect(result).toHaveLength(1);expect(result[0]).toMatchObject({fieldName:'customer.name_copy1',fieldKind:'text',required:true,pageId:'q',rect:[60,220,180,244],copyFrom:{fieldName:source.fieldName,widgetId:source.widgetId,widgetIdentity:source.widgetIdentity,expectedWidgetSha256:source.expectedWidgetSha256}});expect(result[0]).not.toHaveProperty('value')
 clipboard.copy(m,result,'q',['customer.name_copy1']);const next=clipboard.paste(m,result,'p');expect(next[1]!.copyFrom).toEqual(result[0]!.copyFrom)
 expect(()=>clipboard.paste({...m,formDesignWidgets:[{...source,widgetIdentity:'d'.repeat(64)}]},result,'p')).toThrow()
})
it('rejects unsupported original fields and forged copy templates before draft mutation',()=>{
 const source={fieldName:'original',widgetId:'7R',widgetIdentity:'b'.repeat(64),expectedWidgetSha256:'c'.repeat(64),copyEditable:true,designEditable:true,fieldKind:'choice',required:false,rect:[30,200,150,224] as [number,number,number,number],pageIndex:0,removable:true,removalReason:null},m={...model,formDesignWidgets:[source]},clipboard=new PdfFormClipboard(sha)
 expect(()=>clipboard.copy({...m,formDesignWidgets:[{...source,copyEditable:false}]},[],'p',['original'])).toThrow()
 const copyFrom={fieldName:source.fieldName,widgetId:source.widgetId,widgetIdentity:source.widgetIdentity,expectedWidgetSha256:source.expectedWidgetSha256},clone={pageId:'p',fieldName:'original_copy1',fieldKind:'choice' as const,required:false,rect:[40,190,160,214] as [number,number,number,number],copyFrom}
 expect(stagePdfFormCreation(m,[],clone)).toHaveLength(1)
 for(const patch of [{required:true},{value:'Forged'},{options:['Forged']},{fieldName:'different.clone'},{rect:[40,190,170,214] as [number,number,number,number]},{copyFrom:{...copyFrom,unexpected:1}}])expect(()=>stagePdfFormCreation(m,[],{...clone,...patch})).toThrow()
})
it('generates a valid new leaf for common source field names containing spaces or starting with a digit',()=>{
 for(const name of ['Contact name','123 Contact']){
  const source={fieldName:name,widgetId:'7R',widgetIdentity:'b'.repeat(64),expectedWidgetSha256:'c'.repeat(64),copyEditable:true,designEditable:true,fieldKind:'text',required:false,rect:[30,200,150,224] as [number,number,number,number],pageIndex:0,removable:true,removalReason:null},m={...model,formDesignWidgets:[source]},clipboard=new PdfFormClipboard(sha)
  clipboard.copy(m,[],'p',[name]);const clone=clipboard.paste(m,[],'p')[0]!;expect(String(clone.fieldName)).toMatch(/^[A-Za-z_][A-Za-z0-9_-]*$/);expect(clone.copyFrom).toMatchObject({fieldName:name})
 }
})
it('copies a source date template across pages without accepting client date format or value overrides',()=>{
 const source={fieldName:'StartDate',widgetId:'7R',widgetIdentity:'b'.repeat(64),expectedWidgetSha256:'c'.repeat(64),copyEditable:true,designEditable:true,fieldKind:'date',dateFormat:'dd/mm/yyyy',required:true,rect:[30,200,150,224] as [number,number,number,number],pageIndex:0,removable:true,removalReason:null},m={...model,formDesignWidgets:[source]},clipboard=new PdfFormClipboard(sha)
 clipboard.copy(m,[],'p',['StartDate']);const operations=clipboard.paste(m,[],'q'),clone=operations[0]!
 expect(clone).toMatchObject({fieldKind:'date',fieldName:'StartDate_copy1',pageId:'q',required:true,copyFrom:{fieldName:'StartDate'}});expect(clone).not.toHaveProperty('dateFormat');expect(clone).not.toHaveProperty('value')
 for(const patch of [{dateFormat:'yyyy-mm-dd' as const},{value:'Forged'}])expect(()=>stagePdfFormCreation(m,[],{...clone,...patch} as unknown as PdfFormCreation)).toThrow()
 clipboard.copy(m,operations,'q',['StartDate_copy1']);expect(clipboard.paste(m,operations,'p')[1]!.copyFrom).toEqual(clone.copyFrom)
})
it('copies an existing single-page radio field as a complete group and validates unchanged member templates',()=>{
 const group=[0,1,2].map(i=>({fieldName:'Answer',widgetId:(7+i)+'R',widgetIdentity:String(i+1).repeat(64),expectedWidgetSha256:'c'.repeat(64),copyEditable:true,designEditable:true,fieldKind:'radio',required:true,radioOptions:['Yes','No','Maybe'],radioValue:'No',radioChecked:i===1,rect:[30+i*50,200,50+i*50,220] as [number,number,number,number],pageIndex:0,removable:false,removalReason:null})),m={...model,formDesignWidgets:group},clipboard=new PdfFormClipboard(sha)
 clipboard.copy(m,[],'p',['Answer']);const operations=clipboard.paste(m,[],'q'),clone=operations[0]!
 expect(clone).toMatchObject({fieldKind:'radio',fieldName:'Answer_copy1',required:true,copyFrom:{widgetId:'7R'}});expect(clone.radioWidgets).toEqual(group.map((w,i)=>({pageId:'q',rect:w.rect.map((v,j)=>v+(j%2===0?30:20)),exportValue:w.radioOptions[i],checked:i===1})))
 clipboard.copy(m,operations,'q',['Answer_copy1']);expect(clipboard.paste(m,operations,'p')[1]!.copyFrom).toEqual(clone.copyFrom)
 for(const rows of [(clone.radioWidgets as any[]).slice(0,2),(clone.radioWidgets as any[]).map((w,i)=>i===1?{...w,checked:false}:w),(clone.radioWidgets as any[]).map((w,i)=>i===1?{...w,rect:[w.rect[0]+1,...w.rect.slice(1)]}:w)])expect(()=>stagePdfFormCreation(m,[],{...clone,radioWidgets:rows} as unknown as PdfFormCreation)).toThrow()
 const cross={...m,formDesignWidgets:group.map((w,i)=>({...w,pageIndex:i===2?1:0}))};clipboard.copy(cross,[],'p',['Answer']);expect(()=>clipboard.paste(cross,[],'q')).toThrow()
 expect(()=>clipboard.paste({...m,formDesignWidgets:group.map((w,i)=>i===1?{...w,copyEditable:false}:w)},operations,'q')).toThrow()
})
it('copies a safe empty signature source as an empty placeholder without value or appearance payloads',()=>{
 const source={fieldName:'Signature1',widgetId:'7R',widgetIdentity:'b'.repeat(64),expectedWidgetSha256:'c'.repeat(64),copyEditable:true,designEditable:true,fieldKind:'signature',required:true,rect:[30,200,190,244] as [number,number,number,number],pageIndex:0,removable:true,removalReason:null},m={...model,formDesignWidgets:[source]},clipboard=new PdfFormClipboard(sha)
 clipboard.copy(m,[],'p',['Signature1']);const operations=clipboard.paste(m,[],'q'),clone=operations[0]!;expect(clone).toMatchObject({fieldKind:'signature',fieldName:'Signature1_copy1',required:true,copyFrom:{widgetId:'7R'},rect:[60,220,220,264]});expect(clone).not.toHaveProperty('value');expect(clone).not.toHaveProperty('image')
 for(const patch of [{value:'signed'},{image:'fake'},{fieldName:'parent.copy'},{required:false}])expect(()=>stagePdfFormCreation(m,[],{...clone,...patch} as unknown as PdfFormCreation)).toThrow()
 expect(()=>clipboard.copy({...m,formDesignWidgets:[{...source,copyEditable:false}]},[],'p',['Signature1'])).toThrow()
})
it('anchors a multipage source group at the clicked member page and preserves page offsets with per-page CropBox translation',()=>{
 const pages=[...model.pages,{pageId:'r',cropBox:{x:40,y:50,width:300,height:400}}],group=[0,1,2].map(i=>({fieldName:'Answer',widgetId:(7+i)+'R',widgetIdentity:String(i+1).repeat(64),expectedWidgetSha256:'c'.repeat(64),copyEditable:true,designEditable:true,fieldKind:'radio',required:true,radioOptions:['Yes','No','Maybe'],radioValue:'No',radioChecked:i===1,rect:[30+(i===2?50:0),200,50+(i===2?50:0),220] as [number,number,number,number],pageIndex:i===0?0:1,removable:false,removalReason:null})),m={...model,pages,formDesignWidgets:group},clipboard=new PdfFormClipboard(sha)
 clipboard.copy(m,[],'q',['Answer']);expect(()=>clipboard.paste(m,[],'p')).toThrow();const next=clipboard.paste(m,[],'r'),clone=next[0]!
 expect(clone).toMatchObject({fieldName:'Answer_copy1',pageId:'q',copyFrom:{widgetId:'7R'}});expect((clone.radioWidgets as any[]).map(row=>[row.pageId,row.rect])).toEqual([['q',[60,220,80,240]],['r',[60,210,80,230]],['r',[110,210,130,230]]])
 clipboard.copy(m,next,'r',['Answer_copy1']);expect((clipboard.paste(m,next,'q')[1]!.radioWidgets as any[]).map(row=>row.pageId)).toEqual(['p','q','q'])
 const original=structuredClone(next),small={...m,pages:pages.map(p=>p.pageId==='r'?{...p,cropBox:{x:40,y:50,width:20,height:20}}:p)};expect(()=>clipboard.paste(small,[],'r')).toThrow();expect(next).toEqual(original)
})
