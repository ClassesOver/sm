/** 外部只收来源引用；XML与依赖仅从已核验的同文档基线内存捕获。 */
import {copyElementData,pasteElements,type ElementClipboardItem,type OpenedPptx} from '@genoffice/pptx-engine'
import {XMLParser,XMLValidator} from 'fast-xml-parser'
import {COORD_MAX} from '../packages/pptx-engine/src/generate.ts'
import {relsPathFor} from '../packages/pptx-engine/src/zip.ts'
import {inspectGroupCapabilities} from './pptx-groups.ts'
export type ClipboardPaste={sourceSlideIndex:number;elementIds:string[];slideIndex:number;dx:number;dy:number}
export type PreparedClipboardPaste={sourcePartPath:string;targetPartPath:string;items:ElementClipboardItem[];dx:number;dy:number}
export type ClipboardConflicts={deletedSlides?:readonly number[];deletions?:readonly unknown[];groupEdits?:readonly {slideIndex:number}[];newSlides?:readonly {duplicateOf?:number;layoutFrom?:number;withLayout?:string}[];resetLayouts?:readonly number[];slideLayouts?:readonly {slideIndex:number}[];slideSize?:unknown;theme?:unknown;headerFooter?:unknown}
function fail(reason:string):never{throw Error('clipboard_paste_'+reason)}
const idValid=(id:unknown):id is string=>typeof id==='string'&&id.length>0&&id.length<=200
const pixelValid=(value:unknown):value is number=>typeof value==='number'&&Number.isFinite(value)&&Math.abs(value)<=100000
const parser=new XMLParser({ignoreAttributes:false,parseTagValue:false,parseAttributeValue:false,trimValues:false})
const record=(value:unknown):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value)
/** 原生粘贴按精确闭标签追加关系；只读拒绝不能无损追加的目标，不修写来源XML。 */
function validateTargetRelationships(opened:OpenedPptx,path:string):void{
 const xml=opened.archive.readText(relsPathFor(path)),ns='http://schemas.openxmlformats.org/package/2006/relationships'
 if(!xml||/<!DOCTYPE|<!ENTITY|<!--|<!\[CDATA\[/.test(xml)||XMLValidator.validate(xml)!==true||!xml.includes('</Relationships>'))fail('target_relationships_invalid')
 const node=parser.parse(xml).Relationships
 if(!record(node)||node['@_xmlns']!==ns||[...xml.matchAll(/xmlns\s*=\s*['"]([^'"]*)['"]/g)].some(match=>match[1]!==ns)||Object.keys(node).some(key=>!['@_xmlns','Relationship'].includes(key)))fail('target_relationships_invalid')
 const rows=node.Relationship===undefined?[]:Array.isArray(node.Relationship)?node.Relationship:[node.Relationship],seen=new Set<string>(),engine=opened.archive.readRels(path)
 for(const row of rows){
  if(!record(row)||typeof row['@_Id']!=='string'||!row['@_Id']||seen.has(row['@_Id'])||typeof row['@_Type']!=='string'||!row['@_Type']||typeof row['@_Target']!=='string'||!row['@_Target']||Object.keys(row).some(key=>!['@_Id','@_Type','@_Target','@_TargetMode'].includes(key)))fail('target_relationships_invalid')
  const parsed=engine.get(row['@_Id']);if(!parsed||parsed.type!==row['@_Type']||parsed.target!==row['@_Target']||parsed.targetMode!==row['@_TargetMode'])fail('target_relationships_invalid')
  seen.add(row['@_Id'])
 }
 if(engine.size!==seen.size)fail('target_relationships_invalid')
}
export function inspectClipboardCapabilities(opened:OpenedPptx,slideIndex:number,elementId:string):{clipboardEditable:boolean;clipboardReason:string|null}{
 const source=opened.deck.slides[slideIndex],element=source?.elements.find(e=>e.id===elementId)
 let reason=inspectGroupCapabilities(opened,slideIndex,elementId).groupReason
 if(!reason&&source&&element){
  const xml=element.anchor.originalXml,item=copyElementData(opened,source,element)
  if(/<a:hlink(?:Click|Hover)\b|\br:(?:link|id)\s*=/.test(xml))reason='暂不复制超链接或外部关系对象'
  else if(element.type==='picture'){
   const bytes=opened.archive.readBytes(element.mediaRef),png=bytes&&Buffer.from(bytes.subarray(0,8)).toString('hex')==='89504e470d0a1a0a',jpeg=bytes&&bytes[0]===255&&bytes[1]===216&&bytes[2]===255
   const refs=[...xml.matchAll(/\br:embed\s*=\s*(["'])(.*?)\1/g)]
   if(!bytes||(!png&&!jpeg)||refs.length!==1||refs[0]![1]!=='"'||!/^rId\d+$/.test(refs[0]![2]!)||item.rels.length!==1||item.rels[0]!.external||!item.rels[0]!.type.endsWith('/image')||item.rels[0]!.target!==element.mediaRef||Object.keys(item.parts??{}).length!==1||!item.parts?.[element.mediaRef])reason='图片媒体或嵌入关系无法完整核验'
  }else if(item.rels.length||/\br:embed\s*=/.test(xml))reason='文字或形状包含不支持的依赖关系'
 }
 if(!source||!element)reason='来源页面或对象不存在'
 return {clipboardEditable:reason===null,clipboardReason:reason}
}
export function prepareClipboardPastes(opened:OpenedPptx,input:unknown,conflicts:ClipboardConflicts={}):PreparedClipboardPaste[]{
 if(input===undefined)return []
 if(!Array.isArray(input)||input.length>50)fail('invalid')
 if(input.reduce((sum,item)=>sum+(Array.isArray(item?.elementIds)?item.elementIds.length:0),0)>500)fail('limit')
 const involved=new Set<number>(),prepared:PreparedClipboardPaste[]=[]
 for(const item of input){
  if(!item||typeof item!=='object'||Object.keys(item).sort().join()!=='dx,dy,elementIds,slideIndex,sourceSlideIndex'||!Number.isInteger(item.sourceSlideIndex)||!Number.isInteger(item.slideIndex)||item.sourceSlideIndex<0||item.slideIndex<0||item.sourceSlideIndex>=opened.deck.slides.length||item.slideIndex>=opened.deck.slides.length||!pixelValid(item.dx)||!pixelValid(item.dy)||!Array.isArray(item.elementIds)||!item.elementIds.length||item.elementIds.some((id:unknown)=>!idValid(id))||new Set(item.elementIds).size!==item.elementIds.length)fail('invalid')
  const source=opened.deck.slides[item.sourceSlideIndex]!,target=opened.deck.slides[item.slideIndex]!,ids:string[]=item.elementIds
  if(source.path!==target.path){
   const from=opened.archive.resolveSlideChain(source.path),to=opened.archive.resolveSlideChain(target.path)
   if(!from.masterPath||!from.themePath||from.masterPath!==to.masterPath||from.themePath!==to.themePath)fail('theme_chain_conflict')
  }
  if(opened.deck.slides.filter(s=>s.path===source.path).length!==1||opened.deck.slides.filter(s=>s.path===target.path).length!==1)fail('part_identity')
  validateTargetRelationships(opened,target.path)
  const selected=new Set(ids),elements=source.elements.filter(e=>selected.has(e.id)),dx=Math.round(item.dx*9525),dy=Math.round(item.dy*9525)
  if(elements.length!==ids.length)fail('source_missing')
  for(const element of elements){
   const capability=inspectClipboardCapabilities(opened,item.sourceSlideIndex,element.id)
   if(!capability.clipboardEditable)throw Error(capability.clipboardReason!)
   const o=element.transform.offset
   if(![o.x+dx,o.y+dy,o.x+dx+o.cx,o.y+dy+o.cy].every(n=>Number.isSafeInteger(n)&&Math.abs(n)<=COORD_MAX))fail('geometry')
  }
  involved.add(item.sourceSlideIndex);involved.add(item.slideIndex)
  prepared.push({sourcePartPath:source.path,targetPartPath:target.path,items:elements.map(e=>copyElementData(opened,source,e)),dx,dy})
 }
 if(!prepared.length)return prepared
 if([conflicts.theme,conflicts.slideSize,conflicts.headerFooter].some(value=>value!==undefined&&value!==null))fail('global_conflict')
 if(conflicts.deletedSlides?.some(index=>involved.has(index))||conflicts.resetLayouts?.some(index=>involved.has(index))||conflicts.groupEdits?.some(item=>involved.has(item.slideIndex))||conflicts.slideLayouts?.some(item=>involved.has(item.slideIndex))||conflicts.newSlides?.some(item=>involved.has(item.duplicateOf!)||involved.has(item.layoutFrom!)))fail('structure_conflict')
 return prepared
}
/** 所有target先定位，正常来源修改/删除/页面重排完成后才调用；不再使用旧对象ID。 */
export function applyClipboardPastes(opened:OpenedPptx,prepared:readonly PreparedClipboardPaste[]):void{
 const targets=prepared.map(item=>{
  const indexes=opened.deck.slides.flatMap((slide,index)=>slide.path===item.targetPartPath?[index]:[])
  if(indexes.length!==1)fail('target_missing')
  validateTargetRelationships(opened,item.targetPartPath)
  return indexes[0]!
 })
 for(const [i,item] of prepared.entries())if(!pasteElements(opened,targets[i]!,item.items,{dx:item.dx,dy:item.dy}))fail('apply_failed')
}
