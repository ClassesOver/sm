/** 完整来源层级请求；只调用固定源 reorderElement，不改写OOXML。 */
import {isConnectorXml,reorderElement,type OpenedPptx,type SlideElement} from '@genoffice/pptx-engine'
export type ElementOrder={slideIndex:number;elementIds:string[]}
/** 只开放来源顶层普通文字、形状和图片，其他对象仍进入全排列但不主动移动。 */
export function elementOrderEditable(element:SlideElement):boolean{
 return ['text','shape','picture'].includes(element.type)&&!isConnectorXml(element.anchor.originalXml)
}
export function validateElementOrders(opened:OpenedPptx,input:unknown,conflicts:{deletedSlides?:readonly number[]}={}):ElementOrder[]{
 if(input===undefined)return []
 if(!Array.isArray(input)||input.length>500)throw Error('element_orders_invalid')
 const seen=new Set<number>()
 for(const item of input){
  if(!item||typeof item!=='object'||Object.keys(item).sort().join()!=='elementIds,slideIndex'||!Number.isInteger(item.slideIndex)||item.slideIndex<0||item.slideIndex>=opened.deck.slides.length||!Array.isArray(item.elementIds))throw Error('element_order_invalid')
  if(seen.has(item.slideIndex)||conflicts.deletedSlides?.includes(item.slideIndex))throw Error('element_order_target_conflict')
  seen.add(item.slideIndex)
  const elements=opened.deck.slides[item.slideIndex]!.elements,ids=elements.map(e=>e.id)
  if(ids.length>500||ids.some(id=>typeof id!=='string'||id.length===0||id.length>200)||new Set(ids).size!==ids.length||item.elementIds.length!==ids.length||new Set(item.elementIds).size!==ids.length||item.elementIds.some((id:unknown)=>typeof id!=='string'||!ids.includes(id)))throw Error('element_order_permutation_invalid')
  const readonlyIds=elements.filter(e=>!elementOrderEditable(e)).map(e=>e.id)
  if(item.elementIds.filter((id:string)=>readonlyIds.includes(id)).some((id:string,i:number)=>id!==readonlyIds[i]))throw Error('element_order_readonly_changed')
 }
 return input.map(item=>({slideIndex:item.slideIndex,elementIds:[...item.elementIds]}))
}
export function applyElementOrders(opened:OpenedPptx,items:ElementOrder[]):void{
 const validated=validateElementOrders(opened,items)
 for(const item of validated){
  const slide=opened.deck.slides[item.slideIndex]!
  for(let index=0;index<item.elementIds.length;index++){
   const wanted=item.elementIds[index]!
   while(slide.elements[index]!.id!==wanted){
    const target=slide.elements.find(e=>e.id===wanted)!
    const moving=elementOrderEditable(target)?target:slide.elements[index]!
    // 只读目标前的安全对象移至末尾，确保每轮目标都向当前位置靠近。
    const direction=moving===target?'backward':'front'
    if(!elementOrderEditable(moving)||!reorderElement(slide,moving.id,direction))throw Error('element_order_apply_failed')
   }
  }
 }
}
