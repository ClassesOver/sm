/** 受限来源组合：只读检查解析XML，所有修改仅委托固定源引擎。 */
import {XMLParser,XMLValidator} from 'fast-xml-parser'
import {groupChildSlices,groupElements,isConnectorXml,reorderElement,scanSlide,ungroupElement,type GroupElement,type OpenedPptx,type Slide,type SlideElement} from '@genoffice/pptx-engine'
import {COORD_MAX} from '../packages/pptx-engine/src/generate.ts'
export type GroupEdit={slideIndex:number;kind:'group';elementIds:string[]}|{slideIndex:number;kind:'ungroup';elementId:string}
export type GroupCapabilities={groupEditable:boolean;groupReason:string|null;ungroupEditable:boolean;ungroupReason:string|null}
const parser=new XMLParser({ignoreAttributes:false,parseTagValue:false,parseAttributeValue:false,trimValues:false,processEntities:false})
const namespaces={p:'http://schemas.openxmlformats.org/presentationml/2006/main',a:'http://schemas.openxmlformats.org/drawingml/2006/main',r:'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
const validId=(id:unknown):id is string=>typeof id==='string'&&id.length>0&&id.length<=200
const dirty=(e:SlideElement)=>!!(e.dirty||e.dirtyTransform||e.dirtyFill||e.dirtyStroke||e.dirtySrcRect||e.dirtyPPr||e.textMoved)
function root(xml:string,name:string):any{
 if(!xml||/<!DOCTYPE|<!ENTITY|<!--|<!\[CDATA\[|<mc:AlternateContent\b/.test(xml)||XMLValidator.validate(xml)!==true)throw Error('来源XML无法完整识别')
 for(const match of xml.matchAll(/xmlns:(p|a|r)\s*=\s*['"]([^'"]*)['"]/g))if(namespaces[match[1] as keyof typeof namespaces]!==match[2])throw Error('来源XML命名空间无法核验')
 const node=parser.parse(xml)[name]
 if(!node||typeof node!=='object'||Array.isArray(node))throw Error('来源对象结构无法完整识别')
 return node
}
function pageReason(slide:Slide):string|null{
 if(/<p:(?:timing|cxnSp)\b|<a:(?:stCxn|endCxn)\b/.test(slide.originalXml+slide.bodySuffix+slide.elements.map(e=>e.anchor.originalXml).join('')))return '页面含动画或连接线，暂不支持组合操作'
 if(slide.structureDirty||slide.elements.some(dirty))return '页面已有结构或内容编辑，不能与来源组合操作同时提交'
 try{
  if(root(slide.originalXml,'p:sld')['@_xmlns:p']!==namespaces.p)return '页面来源XML命名空间无法核验'
  const scan=scanSlide(slide.originalXml)
  if(scan.elements.length!==slide.elements.length||scan.bodyPrefix!==slide.bodyPrefix||scan.bodySuffix!==slide.bodySuffix||scan.elements.some((part,i)=>slide.originalXml.slice(part.start,part.end)!==slide.elements[i]!.anchor.originalXml||!!part.gapAfter?.trim()))return '页面包含无法完整识别的来源对象或间隔内容'
  const ids=slide.elements.map(e=>e.id)
  if(ids.some(id=>!validId(id))||new Set(ids).size!==ids.length)return '页面来源对象身份无法核验'
 }catch{return '页面来源XML无法完整识别'}
 return null
}
function transformReason(element:SlideElement,xfrm:any):string|null{
 const t=element.transform,o=t.offset
 if(dirty(element)||t.rot!==0||t.flipH||t.flipV)return '对象已有编辑、旋转或翻转，暂仅可读'
 if(![o.x,o.y,o.cx,o.cy].every(n=>Number.isSafeInteger(n)&&Math.abs(n)<=COORD_MAX)||o.cx<=0||o.cy<=0)return '对象来源几何无法可靠保留'
 if(!xfrm||typeof xfrm!=='object'||Array.isArray(xfrm)||Number(xfrm['@_rot']??0)!==0||![undefined,'0','false'].includes(xfrm['@_flipH'])||![undefined,'0','false'].includes(xfrm['@_flipV']))return '对象来源变换无法可靠保留'
 if(['x','y'].some(k=>Number(xfrm['a:off']?.['@_'+k])!==o[k as 'x'|'y'])||['cx','cy'].some(k=>Number(xfrm['a:ext']?.['@_'+k])!==o[k as 'cx'|'cy']))return '对象来源坐标与模型不一致'
 return null
}
function ordinaryReason(opened:OpenedPptx,element:SlideElement,xml=element.anchor.originalXml):string|null{
 if(!['text','shape','picture'].includes(element.type)||element.placeholder||isConnectorXml(xml)||/<p:ph\b|<a:(?:grpFill|scene3d|sp3d|videoFile|audioFile)\b|model3d|svgBlip|<mc:AlternateContent\b/.test(xml))return '仅支持无占位符的普通文字、形状和嵌入图片'
 try{
  const node=root(xml,element.type==='picture'?'p:pic':'p:sp'),reason=transformReason(element,node['p:spPr']?.['a:xfrm'])
  if(reason)return reason
  if(element.type==='picture'&&(element.media||element.model3d||element.scene3d||!/[.](?:png|jpe?g)$/i.test(element.mediaRef)||!opened.archive.readBytes(element.mediaRef)?.length||!node['p:blipFill']?.['a:blip']?.['@_r:embed']||node['p:blipFill']?.['a:blip']?.['@_r:link']))return '仅支持媒体身份可读取的嵌入PNG或JPEG图片'
 }catch{return '对象来源XML无法完整识别'}
 return null
}
function ungroupReason(opened:OpenedPptx,element:SlideElement):string|null{
 if(element.type!=='group')return '仅来源组合对象可取消组合'
 try{
  const node=root(element.anchor.originalXml,'p:grpSp'),properties=node['p:grpSpPr'],xfrm=properties?.['a:xfrm'],reason=transformReason(element,xfrm),offset=element.transform.offset,child=element.childOffset
  if(reason)return reason
  if(!child||['x','y','cx','cy'].some(k=>child[k as keyof typeof child]!==offset[k as keyof typeof offset])||['x','y'].some(k=>Number(xfrm?.['a:chOff']?.['@_'+k])!==child[k as 'x'|'y'])||['cx','cy'].some(k=>Number(xfrm?.['a:chExt']?.['@_'+k])!==child[k as 'cx'|'cy']))return '仅支持完整且1:1的来源子坐标系统'
  if(Object.keys(node).some(k=>!['p:nvGrpSpPr','p:grpSpPr','p:sp','p:pic'].includes(k))||Object.keys(properties).some(k=>k!=='a:xfrm')||node['p:nvGrpSpPr']?.['p:cNvPr']?.['a:hlinkClick']||node['p:nvGrpSpPr']?.['p:cNvPr']?.['a:hlinkHover']||/<p:ph|<a:grpSpLocks/.test(element.anchor.originalXml))return '组合含嵌套、未知孩子或组级样式，暂仅可读'
  const slices=groupChildSlices(element.anchor.originalXml),ids=slices.map(slice=>slice.nvId)
  if(!slices.length||slices.length>500||slices.length!==element.children.length||ids.some(id=>!id)||new Set(ids).size!==ids.length)return '组合孩子来源身份无法完整识别'
  for(const [i,slice] of slices.entries()){
   const childElement=element.children[i]!
   if(slice.nvId!==childElement.nvId||ordinaryReason(opened,childElement,slice.xml))return '组合孩子含不支持内容或来源顺序无法核验'
  }
 }catch{return '来源组合结构无法完整识别'}
 return null
}
export function inspectGroupCapabilities(opened:OpenedPptx,slideIndex:number,elementId:string):GroupCapabilities{
 const slide=Number.isInteger(slideIndex)&&slideIndex>=0?opened.deck.slides[slideIndex]:undefined,element=slide?.elements.find(e=>e.id===elementId)
 const common=!slide||!element?'来源页面或对象不存在':pageReason(slide)
 const groupReason=common??ordinaryReason(opened,element!),ungroupReasonValue=common??ungroupReason(opened,element!)
 return {groupEditable:groupReason===null,groupReason,ungroupEditable:ungroupReasonValue===null,ungroupReason:ungroupReasonValue}
}
export function validateGroupEdits(opened:OpenedPptx,input:unknown,conflicts:{deletedSlides?:readonly number[]}={}):GroupEdit[]{
 if(input===undefined)return []
 if(!Array.isArray(input)||input.length>50)throw Error('group_edits_invalid')
 const seen=new Set<number>(),result:GroupEdit[]=[]
 for(const item of input){
  if(!item||typeof item!=='object'||!Number.isInteger(item.slideIndex)||item.slideIndex<0||item.slideIndex>=opened.deck.slides.length||seen.has(item.slideIndex)||conflicts.deletedSlides?.includes(item.slideIndex))throw Error('group_edit_target_invalid')
  seen.add(item.slideIndex)
  if(item.kind==='group'){
   if(Object.keys(item).sort().join()!=='elementIds,kind,slideIndex'||!Array.isArray(item.elementIds)||item.elementIds.length<2||item.elementIds.length>500||item.elementIds.some((id:unknown)=>!validId(id))||new Set(item.elementIds).size!==item.elementIds.length)throw Error('group_edit_invalid')
   const slide=opened.deck.slides[item.slideIndex]!,indices:number[]=item.elementIds.map((id:string)=>slide.elements.findIndex(e=>e.id===id)).sort((a:number,b:number)=>a-b)
   if(indices.some((index:number,i:number)=>index<0||index!==indices[0]+i))throw Error('group_edit_source_not_contiguous')
   const ids=indices.map((index:number)=>slide.elements[index]!.id)
   const sourceReason=pageReason(slide)
   if(sourceReason)throw Error(sourceReason)
   for(const index of indices){const reason=ordinaryReason(opened,slide.elements[index]!);if(reason)throw Error(reason)}
   const targets=indices.map((index:number)=>slide.elements[index]!.transform.offset),right=Math.max(...targets.map(o=>o.x+o.cx)),bottom=Math.max(...targets.map(o=>o.y+o.cy)),left=Math.min(...targets.map(o=>o.x)),top=Math.min(...targets.map(o=>o.y))
   if(![left,top,right,bottom,right-left,bottom-top].every(n=>Number.isSafeInteger(n)&&Math.abs(n)<=COORD_MAX))throw Error('group_edit_geometry_invalid')
   result.push({slideIndex:item.slideIndex,kind:'group',elementIds:ids})
  }else if(item.kind==='ungroup'){
   if(Object.keys(item).sort().join()!=='elementId,kind,slideIndex'||!validId(item.elementId))throw Error('group_edit_invalid')
   const capability=inspectGroupCapabilities(opened,item.slideIndex,item.elementId)
   if(!capability.ungroupEditable)throw Error(capability.ungroupReason!)
   result.push({slideIndex:item.slideIndex,kind:'ungroup',elementId:item.elementId})
  }else throw Error('group_edit_invalid')
 }
 return result
}
function moveTo(slide:Slide,id:string,index:number):void{
 while(slide.elements[index]!.id!==id)if(!reorderElement(slide,id,'backward'))throw Error('group_edit_reorder_failed')
}
export function applyGroupEdits(opened:OpenedPptx,items:GroupEdit[]):void{
 const validated=validateGroupEdits(opened,items)
 for(const item of validated){
  const slide=opened.deck.slides[item.slideIndex]!
  if(item.kind==='group'){
   const index=slide.elements.findIndex(e=>e.id===item.elementIds[0]),result=groupElements(opened,item.slideIndex,item.elementIds)
   if(!result)throw Error('group_edit_apply_failed')
   moveTo(result.slide,result.groupId,index)
  }else{
   const index=slide.elements.findIndex(e=>e.id===item.elementId),count=(slide.elements[index] as GroupElement).children.length,result=ungroupElement(opened,item.slideIndex,item.elementId)
   if(!result)throw Error('ungroup_edit_apply_failed')
   const children=result.elements.slice(-count).map(e=>e.id)
   for(const [i,id] of children.entries())moveTo(result,id,index+i)
  }
 }
}
