import {projectParagraphs,uniformParagraphValue,type ParagraphFormatting,type ParagraphSourceFormatting,type ParagraphList} from './slides-paragraph'
export type BrushText={fontSizePt?:number;fontFamily?:string;color?:string;bold?:boolean;italic?:boolean;underline?:boolean}
export type BrushShape={fill?:string;stroke?:{color:string;widthPt:number}|null}
export type BrushSource={supported:boolean;text?:BrushText;align?:'left'|'center'|'right'|'justify';shape?:BrushShape;reason?:string}
export type SlidesBrush=Omit<BrushSource,'supported'|'reason'>
export type BrushElement={slideIndex:number;id:string;type:string;editable:boolean;text:string;brushSource?:BrushSource;paragraphFormatting?:ParagraphSourceFormatting[];paragraphLists?:ParagraphList[]}
type Target={slideIndex:number;elementId:string}
export type BrushDraft={edits?:(Target&{text?:string})[];textFormatting?:(Target&BrushText&{strike?:boolean})[];paragraphFormatting?:ParagraphFormatting[];shapeStyles?:(Target&BrushShape)[];deletions?:readonly Target[];deletedSlides?:readonly number[];groupEdits?:readonly {slideIndex:number}[]}
const textFields=['fontSizePt','fontFamily','color','bold','italic','underline'] as const
function reason(element:BrushElement,draft:BrushDraft):string|null{
 if(!Number.isInteger(element.slideIndex)||element.slideIndex<0||!element.id||!element.editable||!['text','shape'].includes(element.type)||!element.brushSource?.supported)return element.brushSource?.reason??'请选择可安全刷格式的来源文字或形状'
 if(draft.deletedSlides?.includes(element.slideIndex)||draft.deletions?.some(item=>item.slideIndex===element.slideIndex&&item.elementId===element.id))return '已删除对象不能使用格式刷'
 if(draft.groupEdits?.some(item=>item.slideIndex===element.slideIndex))return '请先保存或撤销本页组合操作'
 return null
}
const targets=(item:Target,element:BrushElement)=>item.slideIndex===element.slideIndex&&item.elementId===element.id
/** 仅读取明确摘要和当前补丁，不使用界面的显示默认值或首 run。 */
function effective(element:BrushElement,draft:BrushDraft):SlidesBrush{
 const result:SlidesBrush={},text:BrushText={...element.brushSource?.text},shape:BrushShape={...element.brushSource?.shape}
 for(const item of draft.textFormatting??[])if(targets(item,element))for(const key of textFields){const value=item[key];if(value!==undefined)Object.assign(text,{[key]:value})}
 for(const item of draft.shapeStyles??[])if(targets(item,element)){if(item.fill!==undefined)shape.fill=item.fill;if(item.stroke!==undefined)shape.stroke=item.stroke?{...item.stroke}:null}
 if(Object.keys(text).length)result.text=text
 if(Object.keys(shape).length)result.shape=shape
 const patches=(draft.paragraphFormatting??[]).filter(item=>targets(item,element))
 if(element.paragraphFormatting?.length||element.paragraphLists?.length){
  const align=uniformParagraphValue(projectParagraphs(element.paragraphFormatting,element.paragraphLists,patches),'align')
  if(align)result.align=align
 }else{
  const align=patches.findLast(item=>item.align!==undefined)?.align??element.brushSource?.align
  if(align)result.align=align
 }
 return result
}
export function captureSlidesBrush(source:BrushElement,currentDraft:BrushDraft):{brush:SlidesBrush|null;issues:string[]}{
 const issue=reason(source,currentDraft);if(issue)return {brush:null,issues:[issue]}
 const brush=effective(source,currentDraft)
 return Object.keys(brush).length?{brush,issues:[]}:{brush:null,issues:['来源没有可复制的明确且统一格式；混合、继承缺省或复杂样式保持原样']}
}
/** 一次返回完整候选；调用方只在 changed 时提交一次历史。 */
export function planSlidesBrushApply<T extends BrushDraft>(brush:SlidesBrush,target:BrushElement,currentDraft:T):{changes:T&BrushDraft;changed:boolean;issues:string[]}{
 const issue=reason(target,currentDraft);if(issue)return {changes:currentDraft,changed:false,issues:[issue]}
 const current=effective(target,currentDraft),changes={...currentDraft},text:BrushText={},shape:BrushShape={}
 const hasText=!!(currentDraft.edits?.findLast(item=>targets(item,target)&&item.text!==undefined)?.text??target.text).trim()
 if(hasText)for(const field of textFields)if(brush.text?.[field]!==undefined&&brush.text[field]!==current.text?.[field])Object.assign(text,{[field]:brush.text[field]})
 if(brush.shape?.fill!==undefined&&brush.shape.fill!==current.shape?.fill)shape.fill=brush.shape.fill
 if(brush.shape?.stroke!==undefined&&JSON.stringify(brush.shape.stroke)!==JSON.stringify(current.shape?.stroke))shape.stroke=brush.shape.stroke?{...brush.shape.stroke}:null
 const align=hasText&&brush.align&&brush.align!==current.align?brush.align:undefined
 if(Object.keys(text).length){
  const previous=currentDraft.textFormatting?.find(item=>targets(item,target))
  changes.textFormatting=[...(currentDraft.textFormatting??[]).filter(item=>!targets(item,target)),{...previous,slideIndex:target.slideIndex,elementId:target.id,...text}]
 }
 if(Object.keys(shape).length){
  const previous=currentDraft.shapeStyles?.find(item=>targets(item,target))
  changes.shapeStyles=[...(currentDraft.shapeStyles??[]).filter(item=>!targets(item,target)),{...previous,slideIndex:target.slideIndex,elementId:target.id,...shape}]
 }
 if(align){
  if((currentDraft.paragraphFormatting?.length??0)>=500)return {changes:currentDraft,changed:false,issues:['段落格式修改已达到500条，请先保存']}
  changes.paragraphFormatting=[...(currentDraft.paragraphFormatting??[]),{slideIndex:target.slideIndex,elementId:target.id,align}]
 }
 if((changes.textFormatting?.length??0)>500||(changes.shapeStyles?.length??0)>500)return {changes:currentDraft,changed:false,issues:['格式修改已达到500项，请先保存']}
 const changed=Object.keys(text).length>0||Object.keys(shape).length>0||!!align
 return {changes:changed?changes:currentDraft,changed,issues:[]}
}
