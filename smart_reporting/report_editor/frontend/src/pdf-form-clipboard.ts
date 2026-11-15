/** Document-local clipboard for pending definitions and trusted source field identities; never writes OS clipboard. */
import {stagePdfFormCreation,validateRestoredPdfFormCreation,type PdfFormCreateModel,type PdfFormCreation} from './pdf-form-create'
import type {NativeOperation} from './native-draft'
export class PdfFormClipboard{
 private entries:PdfFormCreation[]=[]
 private originPage=''
 private serial=0
 constructor(private readonly sourceSha256:string){}
 get hasContent(){return this.entries.length>0}
 private current(model:PdfFormCreateModel,operations:NativeOperation[]){
  if(model.sourceSha256!==this.sourceSha256||model.capabilities?.createFormField!==true)throw Error('字段剪贴板来源或创建能力已变化')
  if(operations.some(op=>op.kind!=='createFormField'))throw Error('粘贴字段与其他类型修改请分别保存')
  validateRestoredPdfFormCreation(model,operations)
 }
 private selected(model:PdfFormCreateModel,operations:NativeOperation[],pageId:string,names:string[]){
  this.current(model,operations)
  if(!names.length||new Set(names).size!==names.length||!model.pages.some(page=>page.pageId===pageId))throw Error('请选择字段')
  const entries=names.map(name=>{
   const matches=operations.filter(op=>op.kind==='createFormField'&&op.fieldName===name)
   if(!matches.length){
    const source=model.formDesignWidgets?.filter(w=>w.fieldName===name)??[],w=source[0],page=model.pages.find((p,i)=>(p.index??i)===w?.pageIndex)
    const identity=w?{fieldName:w.fieldName,widgetId:w.widgetId,widgetIdentity:w.widgetIdentity,expectedWidgetSha256:w.expectedWidgetSha256}:undefined
    if(w?.fieldKind==='radio'){
     if(source.length<2||source.length>64||!page||!source.some(member=>model.pages.find((p,i)=>(p.index??i)===member.pageIndex)?.pageId===pageId)||source.some(member=>!member.copyEditable||member.fieldKind!=='radio'||!model.pages.some((p,i)=>(p.index??i)===member.pageIndex)))throw Error(w.copyReason||'复制单选字段须包含完整安全互斥组及全部页面')
     return {pageId:page.pageId,fieldName:w.fieldName,fieldKind:'radio' as const,rect:structuredClone(w.rect),required:w.required??false,copyFrom:identity!,radioWidgets:source.map((member,i)=>({pageId:model.pages.find((p,n)=>(p.index??n)===member.pageIndex)!.pageId,rect:structuredClone(member.rect),exportValue:member.radioOptions?.[i]??'',checked:member.radioChecked===true}))}
    }
    if(source.length!==1||!w?.copyEditable||!['text','checkbox','choice','date','signature'].includes(w.fieldKind??'')||page?.pageId!==pageId)throw Error(w?.copyReason||'该来源字段暂不能安全复制')
    return {pageId,fieldName:w.fieldName,fieldKind:w.fieldKind as PdfFormCreation['fieldKind'],rect:structuredClone(w.rect),required:w.required??false,copyFrom:identity!}
   }
   if(matches.length!==1)throw Error('字段身份不唯一')
   const {kind,sourceSha256,...value}=matches[0]!,input=value as unknown as PdfFormCreation
   if(input.radioWidgets?!input.radioWidgets.some(row=>row.pageId===pageId):input.pageId!==pageId)throw Error('请选择该字段的实际成员页面，不能只复制部分选项')
   return structuredClone(input)
  })
  return entries
 }
 copy(model:PdfFormCreateModel,operations:NativeOperation[],pageId:string,names:string[]){
  const entries=this.selected(model,operations,pageId,names)
  this.entries=entries;this.originPage=pageId;this.serial=0
 }
 duplicate(model:PdfFormCreateModel,operations:NativeOperation[],pageId:string,names:string[]){
  return this.place(model,operations,this.selected(model,operations,pageId,names),pageId,pageId,1)
 }
 paste(model:PdfFormCreateModel,operations:NativeOperation[],pageId:string){
  if(!this.entries.length)throw Error('请先复制字段')
  const result=this.place(model,operations,this.entries,this.originPage,pageId,this.serial+1);this.serial++;return result
 }
 private place(model:PdfFormCreateModel,operations:NativeOperation[],entries:PdfFormCreation[],from:string,to:string,serial:number){
  if(operations.length+entries.length>500)throw Error('粘贴字段超过500项操作预算')
  this.current(model,operations)
  const originIndex=model.pages.findIndex(page=>page.pageId===from),targetIndex=model.pages.findIndex(page=>page.pageId===to)
  if(originIndex<0||targetIndex<0)throw Error('剪贴板页面身份已变化')
  const byPage=new Map<string,PdfFormCreation['rect'][]>(),placements=new Map<string,{pageId:string;dx:number;dy:number}>()
  for(const entry of entries)for(const row of entry.radioWidgets??[{pageId:entry.pageId,rect:entry.rect}])byPage.set(row.pageId,[...(byPage.get(row.pageId)??[]),row.rect])
  for(const [sourcePageId,rects]of byPage){
   const index=model.pages.findIndex(page=>page.pageId===sourcePageId),origin=model.pages[index]?.cropBox,destination=model.pages[index+targetIndex-originIndex],target=destination?.cropBox
   if(index<0||!origin||!target||!destination)throw Error('目标页范围不足，无法放下整个跨页字段，未修改草稿')
   const minX=Math.min(...rects.map(r=>r[0])),minY=Math.min(...rects.map(r=>r[1])),maxX=Math.max(...rects.map(r=>r[2])),maxY=Math.max(...rects.map(r=>r[3]))
   if(maxX-minX>target.width||maxY-minY>target.height)throw Error('目标页放不下选中字段，未修改草稿')
   const dx=Math.min(Math.max(target.x-origin.x+10*serial,target.x-minX),target.x+target.width-maxX),dy=Math.min(Math.max(target.y-origin.y-10*serial,target.y-minY),target.y+target.height-maxY)
   placements.set(sourcePageId,{pageId:destination.pageId,dx,dy})
  }
  const move=(pageId:string,rect:PdfFormCreation['rect'])=>{const plan=placements.get(pageId)!;return {pageId:plan.pageId,rect:[rect[0]+plan.dx,rect[1]+plan.dy,rect[2]+plan.dx,rect[3]+plan.dy] as PdfFormCreation['rect']}}
  let result=structuredClone(operations)
  const names=[...(model.formDesignWidgets??[]).map(widget=>widget.fieldName),...operations.map(op=>String(op.fieldName))]
  for(const original of entries){
   const entry=structuredClone(original),parts=entry.fieldName.split('.'),originalLeaf=parts.pop()!,cleanLeaf=originalLeaf.replace(/[^A-Za-z0-9_-]/g,'_'),leaf=/^[A-Za-z_]/.test(cleanLeaf)?cleanLeaf:'_'+cleanLeaf,prefix=parts.length?parts.join('.')+'.':'',limit=Math.min(64,256-prefix.length)
   let name=''
   for(let n=1;n<=names.length+54;n++){
    const suffix='_copy'+n,alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_'
    const candidate=limit>suffix.length?prefix+leaf.slice(0,limit-suffix.length)+suffix:limit===1?prefix+(alphabet[n-1]??''):prefix+alphabet[(n-1)%alphabet.length]+Math.floor((n-1)/alphabet.length).toString(36)
    if(candidate.length>256||candidate===prefix||candidate.slice(prefix.length).length>limit)continue
    if(!names.some(other=>other===candidate||other.startsWith(candidate+'.')||candidate.startsWith(other+'.'))){name=candidate;break}
   }
   if(!name)throw Error('无法生成安全且唯一的副本字段名称')
   const clone:PdfFormCreation={...entry,fieldName:name,...move(entry.pageId,entry.rect),...(entry.radioWidgets?{radioWidgets:entry.radioWidgets.map(row=>({...row,...move(row.pageId,row.rect)}))}:{})}
   result=stagePdfFormCreation(model,result,clone);names.push(name)
  }
  return result
 }
}
