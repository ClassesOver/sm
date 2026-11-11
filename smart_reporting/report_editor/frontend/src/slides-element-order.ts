/** 层级按完整来源顺序提交；数组从底层到顶层，规划无变化时不新增历史。 */
export type ElementOrder={slideIndex:number;elementIds:string[]}
export type ElementOrderDirection='front'|'back'|'forward'|'backward'
type SourceElement={id:string;type?:string;orderEditable?:boolean}
function fail():never{throw Error('对象层级来源或顺序无效；原草稿已保留')}
function editable(e:SourceElement):boolean{return e.orderEditable===true&&['text','shape','picture'].includes(e.type??'')}
function permutation(value:unknown,ids:readonly string[]):value is string[]{
 return Array.isArray(value)&&ids.length<=500&&value.length===ids.length&&new Set(value).size===value.length
  &&ids.every(id=>typeof id==='string'&&id.length>0&&id.length<=200)&&new Set(ids).size===ids.length&&value.every(id=>typeof id==='string'&&ids.includes(id))
}
export function validateSlidesElementOrders(value:unknown,slides:readonly {elements:readonly SourceElement[]}[],deletedSlides:readonly number[]=[]):ElementOrder[]{
 if(value===undefined)return []
 if(!Array.isArray(value)||value.length>500)fail()
 const seen=new Set<number>()
 for(const item of value){
  if(!item||typeof item!=='object'||Object.keys(item).sort().join()!=='elementIds,slideIndex'||!Number.isInteger(item.slideIndex)||item.slideIndex<0||item.slideIndex>=slides.length||seen.has(item.slideIndex)||deletedSlides.includes(item.slideIndex)||!permutation(item.elementIds,slides[item.slideIndex]!.elements.map(e=>e.id)))fail()
  const readonlyIds=slides[item.slideIndex]!.elements.filter(e=>!editable(e)).map(e=>e.id)
  if(item.elementIds.filter((id:string)=>readonlyIds.includes(id)).some((id:string,i:number)=>id!==readonlyIds[i]))fail()
  seen.add(item.slideIndex)
 }
 return value.map(item=>({slideIndex:item.slideIndex,elementIds:[...item.elementIds]}))
}
export function planSlidesElementOrder(elements:readonly SourceElement[],selectedIds:readonly string[],currentOrder:readonly string[]|undefined,direction:ElementOrderDirection):{elementIds:string[];changed:boolean}{
 const ids=elements.map(e=>e.id),order=currentOrder===undefined?ids:[...currentOrder]
 if(!['front','back','forward','backward'].includes(direction)||!permutation(order,ids)||!selectedIds.length||selectedIds.length>500||new Set(selectedIds).size!==selectedIds.length)fail()
 if(selectedIds.some(id=>!elements.some(e=>e.id===id&&editable(e))))fail()
 const readonlyIds=elements.filter(e=>!editable(e)).map(e=>e.id)
 if(order.filter(id=>readonlyIds.includes(id)).some((id,i)=>id!==readonlyIds[i]))fail()
 const selected=new Set(selectedIds),next=[...order]
 if(direction==='front'||direction==='back'){
  const chosen=order.filter(id=>selected.has(id)),remaining=order.filter(id=>!selected.has(id))
  next.splice(0,next.length,...(direction==='front'?[...remaining,...chosen]:[...chosen,...remaining]))
 }else if(direction==='forward'){
  for(let i=next.length-2;i>=0;i--)if(selected.has(next[i]!)&&!selected.has(next[i+1]!)){[next[i],next[i+1]]=[next[i+1]!,next[i]!]}
 }else{
  for(let i=1;i<next.length;i++)if(selected.has(next[i]!)&&!selected.has(next[i-1]!)){[next[i-1],next[i]]=[next[i]!,next[i-1]!]}
 }
 return {elementIds:next,changed:next.some((id,i)=>id!==order[i])}
}
