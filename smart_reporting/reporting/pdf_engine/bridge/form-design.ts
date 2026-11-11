/** Strict source-bound adapter around pinned Form Design widget removal. */
import { createHash } from 'node:crypto'
import { PDFArray, PDFCheckBox, PDFDict, PDFDocument, PDFDropdown, PDFName, PDFNumber, PDFRef, PDFTextField, PDFRadioGroup, PDFString, PDFHexString, PDFRawStream, PDFStream, type PDFField } from 'pdf-lib'
import { applyFormWidgetEdits } from '../src/main/save-pdf'
import { replyReferences } from './note-replies'
import {receipt} from './form-design-create'
import {inspectDesignDateActions} from './form-design-actions'
import {inspectDesignTextProperties,type DesignTextProperties} from '../src/main/form-text-properties'
export {inspectDesignTextProperties,designTextFontNames,type DesignTextProperties} from '../src/main/form-text-properties'

const hash = (value: Uint8Array | string) => createHash('sha256').update(value).digest('hex')

export interface DesignWidgetIdentity {
  fieldName: string
  widgetId: string
  widgetIdentity: string
  expectedWidgetSha256: string
  pageIndex: number
  rect: [number, number, number, number]
  required?: boolean
  designEditable?: boolean
  designReason?: string | null
  fieldKind?: string
  dateFormat?: string
  radioOptions?: string[]
  radioValue?: string | null
  radioRenameEditable?: boolean
  radioRenameReason?: string | null
  radioRemovalEditable?: boolean
  radioRemovalReason?: string | null
  radioRequiredEditable?: boolean
  radioRequiredReason?: string | null
  textPropertiesEditable?: boolean
  textPropertiesReason?: string | null
  textProperties?: DesignTextProperties
  choiceOptionsEditable?: boolean
  choiceOptionsReason?: string | null
  choiceOptions?: string[]
  choiceValue?: string | null
  choiceDefaultValue?: string | null
  removable: boolean
  removalReason: string | null
}

export function inspectDesignChoiceOptions(field:PDFField):{editable:boolean;reason:string|null;options?:string[];value?:string|null;defaultValue?:string|null}{try{
 if(!(field instanceof PDFDropdown)||field.isReadOnly()||field.isEditable()||field.isMultiselect()||field.isSorted()||field.acroField.getWidgets().length!==1)throw Error('选项编辑仅支持独立单控件、单选、不可自由输入且未排序的下拉字段')
 if(['A','AA'].some(key=>field.acroField.getInheritableAttribute(PDFName.of(key))!==undefined||field.acroField.getWidgets()[0].dict.has(PDFName.of(key))))throw Error('含动作的下拉字段暂不能编辑选项')
 const dict=field.acroField.dict,options=dict.lookupMaybe(PDFName.of('Opt'),PDFArray),text=(v:unknown)=>v instanceof PDFString||v instanceof PDFHexString?v.decodeText():undefined
 if(['I','TI'].some(k=>field.acroField.getInheritableAttribute(PDFName.of(k))!==undefined)||!options||options.size()<1||options.size()>100)throw Error('下拉选项或选择索引超出安全范围')
 const values=options.asArray().map(raw=>{const v=dict.context.lookup(raw);if(v instanceof PDFArray){if(v.size()!==2||text(v.lookup(0))!==text(v.lookup(1)))throw Error('不同导出值与显示值暂不能编辑');return text(v.lookup(0))}return text(v)})
 if(values.some(v=>typeof v!=='string'||!v||v.length>200||!/^[ -~]+$/.test(v))||new Set(values).size!==values.length)throw Error('已有选项须唯一且限200字符以内可打印 ASCII')
 const scalar=(key:string)=>{const raw=field.acroField.getInheritableAttribute(PDFName.of(key));if(raw===undefined)return null;const value=text(dict.context.lookup(raw));if(value===undefined||!values.includes(value))throw Error('当前值或默认值未与简单选项一致');return value},value=scalar('V'),defaultValue=scalar('DV'),ap=field.acroField.getWidgets()[0].dict.lookupMaybe(PDFName.of('AP'),PDFDict),normal=ap?.lookup(PDFName.of('N'))
 if(!ap||ap.keys().some(key=>String(key)!=='/N')||!(normal instanceof PDFRawStream)||!normal.contents.length)throw Error('下拉字段原外观不可完整保留')
 return {editable:true,reason:null,options:values as string[],value,defaultValue}
}catch(error){return {editable:false,reason:error instanceof Error?error.message:'下拉选项来源暂不能安全编辑'}}}

// 改名不重绘；仅接纳状态、外观流及整组引用闭合的互斥单选组。
function inspectRadioRename(document:PDFDocument,field:PDFField,references:Map<string,number>|null):{editable:boolean;reason:string|null}{try{
 if(!(field instanceof PDFRadioGroup)||field.isReadOnly()||!field.isMutuallyExclusive()||!references)throw Error('仅支持未保护的互斥单选组')
 const widgets=field.acroField.getWidgets(),kids=field.acroField.Kids(),options=field.getOptions(),pages=document.getPages()
 if(widgets.length<2||widgets.length>64||kids?.size()!==widgets.length||options.length!==widgets.length||options.some(v=>!v||v.length>128||!/^[ -~]+$/.test(v))||new Set(options).size!==options.length||!safeAncestors(document,field.ref,field.acroField.dict,references,widgets.length)||['A','AA'].some(k=>field.acroField.getInheritableAttribute(PDFName.of(k))!==undefined))throw Error('单选组选项、层级或动作未通过改名复核')
 const onNames=widgets.map(widget=>{const ap=widget.dict.lookupMaybe(PDFName.of('AP'),PDFDict),normal=ap?.lookupMaybe(PDFName.of('N'),PDFDict),names=normal?.keys().filter(k=>String(k)!=='/Off')??[];if(names.length!==1)throw Error('单选外观状态不完整');return String(names[0])})
 if(new Set(onNames).size!==widgets.length)throw Error('单选外观开启状态重复')
 const state=(key:string)=>{const raw=field.acroField.getInheritableAttribute(PDFName.of(key));if(raw===undefined)return '/Off';const value=document.context.lookup(raw);if(!(value instanceof PDFName)||String(value)!=='/Off'&&!onNames.includes(String(value)))throw Error('单选当前值或默认值不匹配');return String(value)},selected=state('V');state('DV')
 const streams=new Set<string>()
 for(const[index,widget]of widgets.entries()){
  const ref=kids!.get(index),flags=widget.dict.lookup(PDFName.of('F')),occurrences=pages.flatMap(page=>page.node.lookupMaybe(PDFName.of('Annots'),PDFArray)?.asArray()??[]).filter(r=>String(r)===String(ref))
  if(!(ref instanceof PDFRef)||String(ref)===String(field.ref)||references.get(String(ref))!==2||occurrences.length!==1||String(widget.dict.get(PDFName.of('Parent')))!==String(field.ref)||String(widget.dict.get(PDFName.of('Subtype')))!=='/Widget'||flags!==undefined&&(!(flags instanceof PDFNumber)||!Number.isInteger(flags.asNumber())||flags.asNumber()<0||(flags.asNumber()&704)!==0)||['A','AA','StructParent','IRT','Popup','OC'].some(k=>widget.dict.has(PDFName.of(k)))||String(widget.dict.get(PDFName.of('AS')))!==(selected===onNames[index]?selected:'/Off'))throw Error('单选控件状态、身份或动作不闭合')
  const ap=widget.dict.lookupMaybe(PDFName.of('AP'),PDFDict)
  if(!ap||!ap.has(PDFName.of('N'))||ap.keys().some(k=>!['/N','/D','/R'].includes(String(k))))throw Error('单选外观类型不支持')
  for(const key of ap.keys()){
   const states=ap.lookupMaybe(key,PDFDict)
   if(!states||states.keys().length!==2||!states.has(PDFName.of('Off'))||!states.has(PDFName.of(onNames[index].slice(1))))throw Error('单选外观状态不完整')
   for(const raw of states.values()){const stream=document.context.lookup(raw);if(!(raw instanceof PDFRef)||!(stream instanceof PDFRawStream)||!stream.contents.length||streams.has(String(raw))||references.get(String(raw))!==1)throw Error('单选外观流共享或不可读取');streams.add(String(raw))}
  }
 }
 return {editable:true,reason:null}
}catch(error){return {editable:false,reason:error instanceof Error?error.message:'单选组暂不能安全改名'}}}

// 必填只改字段本地 Ff 的 Required 位，不物化继承标志或间接标量。
function inspectRadioRequired(document:PDFDocument,field:PDFField,group:{editable:boolean;reason:string|null}):{editable:boolean;reason:string|null}{try{
 if(!(field instanceof PDFRadioGroup)||!group.editable)throw Error(group.reason||'单选组来源暂不能安全切换必填')
 const flags=field.acroField.dict.get(PDFName.of('Ff')),widgets=field.acroField.getWidgets(),rawOptions=field.acroField.dict.get(PDFName.of('Opt')),options=document.context.lookup(rawOptions)
 if(!(flags instanceof PDFNumber)||!Number.isInteger(flags.asNumber())||flags.asNumber()<0||flags.asNumber()>0x7fffffff)throw Error('必填仅支持本地直接非负31位整数字段标志')
 if(rawOptions!==undefined&&(!(options instanceof PDFArray)||options.size()!==widgets.length||options.asArray().some(raw=>{const value=document.context.lookup(raw);return !(value instanceof PDFString||value instanceof PDFHexString)})))throw Error('单选组选项数组不完整')
 for(const[index,widget]of widgets.entries()){const ref=field.acroField.Kids()!.get(index),owner=document.getPages().find(page=>page.node.lookupMaybe(PDFName.of('Annots'),PDFArray)?.asArray().some(value=>String(value)===String(ref)));if(!owner||String(widget.dict.get(PDFName.of('P')))!==String(owner.ref))throw Error('单选按钮页面引用与实际归属不一致')}
 return {editable:true,reason:null}
}catch(error){return {editable:false,reason:error instanceof Error?error.message:'单选组暂不能安全切换必填'}}}

// 删除必须同步移除 Opt，且不得修改被共享的数组或当前/默认选项。
function inspectRadioRemoval(document:PDFDocument,field:PDFField,index:number,references:Map<string,number>|null,group:{editable:boolean;reason:string|null}):{editable:boolean;reason:string|null}{try{
 if(!(field instanceof PDFRadioGroup)||!group.editable||!references)throw Error(group.reason||'单选组来源暂不能安全删除按钮')
 const widgets=field.acroField.getWidgets(),widget=widgets[index],on=widget.getOnValue(),uniqueArray=(dict:PDFDict,key:string,optional=false)=>{const raw=dict.get(PDFName.of(key));if(raw===undefined&&optional)return;const value=document.context.lookup(raw);if(!(value instanceof PDFArray)||raw instanceof PDFRef&&references.get(String(raw))!==1)throw Error('单选组数组共享或结构不支持');return value}
 for(const[i,sibling]of widgets.entries()){const ref=field.acroField.Kids()!.get(i),owner=document.getPages().find(page=>page.node.lookupMaybe(PDFName.of('Annots'),PDFArray)?.asArray().some(value=>String(value)===String(ref)));if(!owner||String(sibling.dict.get(PDFName.of('P')))!==String(owner.ref))throw Error('单选按钮页面引用与实际归属不一致')}
 uniqueArray(field.acroField.dict,'Kids');const options=uniqueArray(field.acroField.dict,'Opt',true)
 if(options&&(options.size()!==widgets.length||options.asArray().some(raw=>{const value=document.context.lookup(raw);return !(value instanceof PDFString||value instanceof PDFHexString)})))throw Error('单选组选项数组不完整')
 for(const key of ['V','DV'])if(String(document.context.lookup(field.acroField.getInheritableAttribute(PDFName.of(key))))===String(on))throw Error('不能删除当前选项或默认选项')
 const ref=field.acroField.Kids()!.get(index),page=document.getPages().find(p=>p.node.lookupMaybe(PDFName.of('Annots'),PDFArray)?.asArray().some(v=>String(v)===String(ref)))
 if(!page)throw Error('单选按钮页面身份不完整');uniqueArray(page.node,'Annots')
 return {editable:true,reason:null}
}catch(error){return {editable:false,reason:error instanceof Error?error.message:'单选按钮暂不能安全删除'}}}

// 在 pdf-lib 递归 getFields 前校验原始树，拒绝循环、重复孩子及不闭合的 Parent。
export function formDesignTreeSafe(document:PDFDocument){try{
 const acro=document.catalog.lookupMaybe(PDFName.of('AcroForm'),PDFDict);if(!acro)return true
 const roots=acro.lookupMaybe(PDFName.of('Fields'),PDFArray);if(!roots)return false
 const uniqueNames=(refs:unknown[])=>{const names=refs.map(ref=>{const value=document.context.lookupMaybe(ref as PDFRef,PDFDict)?.get(PDFName.of('T'));return value instanceof PDFString||value instanceof PDFHexString?value.decodeText():null});return names.every(name=>typeof name==='string'&&!!name&&!name.includes('.'))&&new Set(names).size===names.length};if(!uniqueNames(roots.asArray()))return false
 const seen=new Set<string>(),stack=roots.asArray().map(ref=>({ref,parent:undefined as PDFRef|undefined,depth:0}));let budget=4096
 while(stack.length){const {ref,parent,depth}=stack.pop()!;if(--budget<0||depth>16||!(ref instanceof PDFRef)||seen.has(String(ref)))return false;seen.add(String(ref));const dict=document.context.lookupMaybe(ref,PDFDict);if(!dict||String(dict.get(PDFName.of('Parent')))!==String(parent))return false
  const kids=dict.lookupMaybe(PDFName.of('Kids'),PDFArray)
  if(dict.has(PDFName.of('FT'))){for(const child of kids?.asArray()??[]){if(!(child instanceof PDFRef)||seen.has(String(child)))return false;seen.add(String(child));const widget=document.context.lookupMaybe(child,PDFDict);if(!widget||String(widget.get(PDFName.of('Subtype')))!=='/Widget'||String(widget.get(PDFName.of('Parent')))!==String(ref)||widget.has(PDFName.of('Kids')))return false}}
  else{if(!kids||!kids.size()||!uniqueNames(kids.asArray()))return false;for(const child of kids.asArray())stack.push({ref:child,parent:ref,depth:depth+1})}
 }return true
}catch{return false}}

// 层级仅在每一段 Parent/Kids/AcroForm 根引用唯一且完整闭合时可设计。
function safeAncestors(document:PDFDocument,ref:PDFRef,dict:PDFDict,references:Map<string,number>,widgetCount:number){
 if(references.get(String(ref))!==widgetCount+1)return false
 const seen=new Set<string>();let currentRef=ref,current=dict
 for(let depth=0;depth<16;depth++){if(seen.has(String(currentRef)))return false;seen.add(String(currentRef));const parent=current.get(PDFName.of('Parent'))
  if(parent===undefined){const roots=document.getForm().acroForm.dict.lookupMaybe(PDFName.of('Fields'),PDFArray);return roots?.asArray().filter(value=>String(value)===String(currentRef)).length===1}
  if(!(parent instanceof PDFRef))return false;const node=document.context.lookupMaybe(parent,PDFDict),kids=node?.lookupMaybe(PDFName.of('Kids'),PDFArray)
  if(!node||!kids||node.has(PDFName.of('FT'))||['A','AA'].some(k=>node.has(PDFName.of(k)))||kids.asArray().some(child=>!(child instanceof PDFRef)||String(document.context.lookupMaybe(child,PDFDict)?.get(PDFName.of('Parent')))!==String(parent))||kids.asArray().filter(child=>String(child)===String(currentRef)).length!==1||references.get(String(parent))!==kids.size()+1)return false
  currentRef=parent;current=node
 }return false
}

function census(document: PDFDocument, sourceSha256: string) {
  // getForm() strips XFA; inspect the immutable source graph before calling it.
  const acroForm = document.catalog.lookupMaybe(PDFName.of('AcroForm'), PDFDict)
  const references = replyReferences(document, document.catalog.has(PDFName.of('Perms')) || acroForm?.has(PDFName.of('XFA')) === true)
  if(!formDesignTreeSafe(document))return []
  const fields = document.getForm().getFields()
  const pages = document.getPages()
  return fields.flatMap(field => {
    const widgets = field.acroField.getWidgets()
    const kids = field.acroField.Kids()
    const radioRename=inspectRadioRename(document,field,references),radioRequired=inspectRadioRequired(document,field,radioRename)
    return widgets.map((widget, index): DesignWidgetIdentity => {
      const raw = kids?.get(index)
      const ref = raw instanceof PDFRef ? raw : field.ref
      const fieldName = field.getName()
      const occurrences = pages.flatMap((page, pageIndex) => {
        const annots = page.node.lookupMaybe(PDFName.of('Annots'), PDFArray)
        return (annots?.asArray() ?? []).flatMap(entry => String(entry) === String(ref) ? [pageIndex] : [])
      })
      const rect = widget.getRectangle()
      const flags = widget.dict.lookup(PDFName.of('F'))
      const supported = field instanceof PDFTextField || field instanceof PDFCheckBox || field instanceof PDFDropdown
      const safe = references !== null && supported && !field.isReadOnly() && widgets.length === 1
        && kids?.size() === 1 && raw instanceof PDFRef && String(ref) !== String(field.ref)
        && references.get(String(ref)) === 2 && references.get(String(field.ref)) === 2
        && occurrences.length === 1 && !fieldName.includes('.')
        && String(widget.dict.get(PDFName.of('Parent'))) === String(field.ref)
        && String(widget.dict.get(PDFName.of('Subtype'))) === '/Widget'
        && (flags === undefined || flags instanceof PDFNumber && Number.isInteger(flags.asNumber()) && flags.asNumber() >= 0 && (flags.asNumber() & 704) === 0)
        && !['AA', 'A', 'StructParent', 'IRT', 'Popup', 'OC'].some(key => widget.dict.has(PDFName.of(key)))
        && !['AA', 'A', 'Parent'].some(key => field.acroField.dict.has(PDFName.of(key)))
      const date=inspectDesignDateActions(field.acroField.dict),widgetDate=inspectDesignDateActions(widget.dict)
      const actionsSafe=(!field.acroField.dict.has(PDFName.of('AA'))||!!date)&&(!widget.dict.has(PDFName.of('AA'))||!!widgetDate)&&(!date||!widgetDate||date.format===widgetDate.format)
      const designSupported=supported||field instanceof PDFRadioGroup
      const designEditable=references!==null&&designSupported&&!field.isReadOnly()&&widgets.length>=1&&widgets.length<=64&&kids?.size()===widgets.length&&raw instanceof PDFRef&&String(ref)!==String(field.ref)&&references.get(String(ref))===2&&occurrences.length===1&&safeAncestors(document,field.ref,field.acroField.dict,references,widgets.length)&&String(widget.dict.get(PDFName.of('Parent')))===String(field.ref)&&String(widget.dict.get(PDFName.of('Subtype')))==='/Widget'&&(flags===undefined||flags instanceof PDFNumber&&Number.isInteger(flags.asNumber())&&flags.asNumber()>=0&&(flags.asNumber()&704)===0)&&actionsSafe&&!['A','StructParent','IRT','Popup','OC'].some(key=>widget.dict.has(PDFName.of(key)))&&!field.acroField.dict.has(PDFName.of('A'))&&(!(field instanceof PDFTextField)||!field.isPassword()&&!field.isRichFormatted())
      const radioRemoval=inspectRadioRemoval(document,field,index,references,radioRename)
      const textProperties=inspectDesignTextProperties(field)
      const choiceOptions=inspectDesignChoiceOptions(field),choiceOptionsEditable=designEditable&&choiceOptions.editable
      const expectedWidgetSha256 = hash(widget.dict.toString())
      return {
        fieldName,
        widgetId: `${ref.objectNumber}R${ref.generationNumber || ''}`,
        widgetIdentity: hash(JSON.stringify([sourceSha256, String(field.ref), field.acroField.dict.toString(), String(ref), expectedWidgetSha256, occurrences])),
        expectedWidgetSha256,
        pageIndex: occurrences[0] ?? -1,
        rect: [rect.x, rect.y, rect.x + rect.width, rect.y + rect.height],
        required: field.isRequired(),
        textPropertiesEditable:designEditable&&textProperties.editable,
        textPropertiesReason:designEditable?textProperties.reason:'控件身份或来源保护未通过设计复核',
        ...(textProperties.properties?{textProperties:textProperties.properties}:{}),
        choiceOptionsEditable,
        choiceOptionsReason:choiceOptionsEditable?null:choiceOptions.reason||'控件身份或来源保护未通过设计复核',
        ...(choiceOptionsEditable?{choiceOptions:choiceOptions.options,choiceValue:choiceOptions.value,choiceDefaultValue:choiceOptions.defaultValue}:{}),
        designEditable,
        designReason:designEditable?null:'控件层级、共享引用、保护或动作未通过安全复核；仅支持未签名 AcroForm 的精确控件设计',
        fieldKind:field instanceof PDFRadioGroup?'radio':field instanceof PDFDropdown?'choice':field instanceof PDFCheckBox?'checkbox':date?'date':field instanceof PDFTextField?'text':'unsupported',
        ...(date?{dateFormat:date.format}:{}),
        ...(field instanceof PDFRadioGroup?{radioOptions:field.getOptions(),radioValue:field.getSelected()??null,radioRenameEditable:radioRename.editable,radioRenameReason:radioRename.reason,radioRemovalEditable:radioRemoval.editable,radioRemovalReason:radioRemoval.reason,radioRequiredEditable:radioRequired.editable,radioRequiredReason:radioRequired.reason}:{}),
        removable: safe,
        removalReason: safe ? null : '仅支持未保护、无动作、无共享引用的独立单控件字段删除',
      }
    })
  })
}

export async function inspectDesignWidgets(content: Uint8Array) {
  const sourceSha256 = hash(content)
  const document = await PDFDocument.load(content, {updateMetadata: false})
  return {sourceSha256, widgets: census(document, sourceSha256)}
}

// 全间接对象与原始流字节快照，既验证幸存 AP，也验证正文和字段树。
function removalObjects(document:PDFDocument){document.getPages();return document.context.enumerateIndirectObjects().map(([ref,obj])=>{if(obj instanceof PDFStream){obj.updateDict();return [String(ref),obj.dict.toString()+Buffer.from(obj.getContents()).toString('hex')]}return [String(ref),String(obj)]})}
export async function removeDesignWidgetWithReceipt(content:Uint8Array,sourceSha256:string,target:Pick<DesignWidgetIdentity,'fieldName'|'widgetId'|'widgetIdentity'|'expectedWidgetSha256'>){
 if(hash(content)!==sourceSha256)throw Error('pdf_form_design_source_changed')
 const document=await PDFDocument.load(content,{updateMetadata:false}),widgets=census(document,sourceSha256),matches=widgets.filter(widget=>['fieldName','widgetId','widgetIdentity','expectedWidgetSha256'].every(key=>widget[key as keyof DesignWidgetIdentity]===target?.[key as keyof typeof target]))
 if(matches.length!==1||!matches[0].removable&&!matches[0].radioRemovalEditable)throw Error('pdf_form_design_widget_invalid_or_readonly')
 const match=matches[0],field=document.getForm().getField(match.fieldName),radio=match.radioRemovalEditable===true
 const[,objectNumber,generationNumber]=/^(\d+)R(\d*)$/.exec(match.widgetId)!,removedRef=PDFRef.of(Number(objectNumber),Number(generationNumber||0)),op={kind:'removeFormWidget',sourceSha256,fieldName:match.fieldName,widgetId:match.widgetId,widgetIdentity:match.widgetIdentity,expectedWidgetSha256:match.expectedWidgetSha256}
 let selected:string|undefined,options:string[]|undefined,remainingIds:string[]|undefined
 if(radio){
  if(!(field instanceof PDFRadioGroup))throw Error('pdf_form_design_widget_invalid_or_readonly')
  const index=field.acroField.Kids()!.asArray().findIndex(ref=>String(ref)===String(removedRef));if(index<0||field.acroField.getWidgets().length<2)throw Error('pdf_form_design_widget_invalid_or_readonly')
  selected=field.getSelected();options=field.getOptions().filter((_,i)=>i!==index);remainingIds=widgets.filter(w=>w.fieldName===match.fieldName&&w.widgetId!==match.widgetId).map(w=>w.widgetId).sort()
  field.acroField.removeWidget(index);field.acroField.removeExportValue(index)
  // PageLeaf.removeAnnot 会 normalize Contents/Resources；这里只改已核验的原生 Annots 数组。
  const annots=document.getPage(match.pageIndex).node.lookup(PDFName.of('Annots'),PDFArray),annotIndex=annots.asArray().findIndex(ref=>String(ref)===String(removedRef));annots.remove(annotIndex);document.context.delete(removedRef)
 }else{
  applyFormWidgetEdits(document,[{fieldName:match.fieldName,widgetId:match.widgetId,remove:true}])
  // pdf-lib 1.17.1 removeField 使用外观 ref；补移已核验的真正 Widget ref。
  document.getPage(match.pageIndex).node.removeAnnot(removedRef)
 }
 const expected=removalObjects(document),bytes=await document.save({useObjectStreams:false,updateFieldAppearances:false});let reason:string|null=null
 try{
  const output=await PDFDocument.load(bytes,{updateMetadata:false});if(JSON.stringify(removalObjects(output))!==JSON.stringify(expected)||!formDesignTreeSafe(output))throw Error('original objects, appearances or field tree changed')
  const after=(await inspectDesignWidgets(bytes)).widgets
  if(after.some(w=>w.widgetId===match.widgetId))throw Error('removed widget remains in active tree')
  if(radio){const surviving=output.getForm().getRadioGroup(match.fieldName),group=after.filter(w=>w.fieldName===match.fieldName);if(surviving.getSelected()!==selected||JSON.stringify(surviving.getOptions())!==JSON.stringify(options)||JSON.stringify(group.filter(w=>w.designEditable).map(w=>w.widgetId).sort())!==JSON.stringify(remainingIds))throw Error('radio selection, options or surviving widget identities changed')}
  else if(output.getForm().getFieldMaybe(match.fieldName))throw Error('removed field remains in active tree')
 }catch(error){reason='pdf_form_widget_removal_output_review_failed: '+String(error)}
 return receipt(content,bytes,op,reason)
}

// 兼容既有 bytes 调用；公开预览/保存路径使用 WithReceipt 保留失败原因。
export async function removeDesignWidget(content:Uint8Array,sourceSha256:string,target:Pick<DesignWidgetIdentity,'fieldName'|'widgetId'|'widgetIdentity'|'expectedWidgetSha256'>){return (await removeDesignWidgetWithReceipt(content,sourceSha256,target)).bytes}
