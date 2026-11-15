/** Copy only closed auxiliary graphs; structural PDF links are rebound separately. */
import {inspectDesignDateActions} from './form-design-actions'
import {PDFArray,PDFCheckBox,PDFDict,PDFDropdown,PDFName,PDFRawStream,PDFRef,PDFRadioGroup,PDFSignature,PDFTextField,type PDFField} from 'pdf-lib'
const fieldKeys=['FT','T','Ff','V','DV','DA','Q','MaxLen','Kids','Parent','Opt','TU','TM','AA']
const widgetKeys=['Type','Subtype','Rect','Parent','P','F','AP','AS','MK','BS','Border','DA','H','AA']
export function inspectFormCopy(field:PDFField,designEditable:boolean,safeRadio=false,safeSignature=false){try{
 const widgets=field.acroField.getWidgets(),dict=field.acroField.dict,context=dict.context
 if(field instanceof PDFSignature){if(!designEditable||!safeSignature)throw Error('仅安全空签名占位可复制，已签名或扩展字段不可复制');return {copyEditable:true,copyReason:null}}
 const radio=field instanceof PDFRadioGroup
 const supported=radio?safeRadio&&widgets.length>=2&&widgets.length<=64:widgets.length===1&&(field instanceof PDFTextField||field instanceof PDFCheckBox||field instanceof PDFDropdown)&&widgets[0]!.dict!==dict
 if(!designEditable||!supported)throw Error('复制仅支持安全独立控件或完整安全互斥单选组')
 const date=inspectDesignDateActions(dict),widgetDates=widgets.map(w=>inspectDesignDateActions(w.dict))
 if(dict.has(PDFName.of('AA'))&&(!date||!(field instanceof PDFTextField))||widgets.some((w,i)=>w.dict.has(PDFName.of('AA'))&&(!date||!widgetDates[i]||widgetDates[i]!.format!==date.format)))throw Error('日期复制仅支持精确的内建 AFDate 动作')
 const trustedActions=new Set([...(date?.objects??[]),...widgetDates.flatMap(value=>value?.objects??[])])
 const parts=field.getName().split('.'),parents=parts.slice(0,-1);if(parts.length>16||parents.some(name=>!/^[A-Za-z_][A-Za-z0-9_-]{0,63}$/.test(name))||(parents.length?parents.join('.').length+1:0)>255)throw Error('原字段父层级名称不符合当前复制命名范围')
 if(dict.keys().some(k=>!fieldKeys.includes(k.decodeText()))||widgets.some(w=>w.dict.keys().some(k=>!widgetKeys.includes(k.decodeText()))))throw Error('字段含未支持复制的动作或扩展属性')
 if(widgets.some(w=>!w.dict.has(PDFName.of('AP'))))throw Error('原字段没有可保留的外观')
 const stack:unknown[]=[...dict.entries().filter(([k])=>!['Parent','Kids'].includes(k.decodeText())).map(([,v])=>v),...widgets.flatMap(w=>w.dict.entries().filter(([k])=>!['Parent','P'].includes(k.decodeText())).map(([,v])=>v))],seen=new Set<object>();let budget=4096,size=0
 while(stack.length){if(--budget<0)throw Error('字段辅助对象超过复制预算');let value=stack.pop();if(value instanceof PDFRef){value=context.lookup(value);if(!value)throw Error('字段辅助引用缺失')}
  if(value&&typeof value==='object'){if(seen.has(value))continue;seen.add(value)}
  if(value instanceof PDFRawStream){size+=value.contents.length;if(size>16*1024*1024)throw Error('字段外观超过复制预算');value=value.dict}
  if(value instanceof PDFDict){if(['Parent','Kids','P','Annots','Fields','A','AA','OpenAction','StructParent'].some(k=>value.has(PDFName.of(k)))||value.has(PDFName.of('JS'))&&!trustedActions.has(value)||['/Page','/Pages','/Annot','/Catalog'].includes(String(value.get(PDFName.of('Type')))))throw Error('字段辅助图包含结构或动作引用');stack.push(...value.values())}
  else if(value instanceof PDFArray)stack.push(...value.asArray())
 }
 return {copyEditable:true,copyReason:null}
}catch(error){return {copyEditable:false,copyReason:error instanceof Error?error.message:'字段暂不能安全复制'}}}
