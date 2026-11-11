/** 组合会重建来源对象ID，因此同页组合与其他内容修改互斥。 */
export type GroupEdit={slideIndex:number;kind:'group';elementIds:string[]}|{slideIndex:number;kind:'ungroup';elementId:string}
type GroupSource={id:string;type:string;groupEditable?:boolean;ungroupEditable?:boolean}
function fail(reason:string):never{throw new Error(`组合草稿${reason}；原草稿已保留`)}
export function validateSlidesGroupDraft(changes:object,slides:readonly {elements:readonly GroupSource[]}[]):GroupEdit[]{
 const input=changes as Record<string,unknown>,value=input.groupEdits
 if(value===undefined)return []
 if(!Array.isArray(value)||value.length>50)fail('数量或结构无效')
 const seen=new Set<number>(),result:GroupEdit[]=[]
 for(const item of value){
  if(!item||typeof item!=='object'||!Number.isInteger(item.slideIndex)||item.slideIndex<0||item.slideIndex>=slides.length||seen.has(item.slideIndex))fail('页面无效或重复')
  seen.add(item.slideIndex)
  const elements=slides[item.slideIndex]!.elements
  if(item.kind==='group'){
   if(Object.keys(item).sort().join()!=='elementIds,kind,slideIndex'||!Array.isArray(item.elementIds)||item.elementIds.length<2||item.elementIds.length>500||new Set(item.elementIds).size!==item.elementIds.length)fail('目标无效')
   const ids:string[]=item.elementIds
   const indexes=ids.map(id=>elements.findIndex(element=>typeof id==='string'&&id.length<=200&&element.id===id&&element.groupEditable===true)).sort((a,b)=>a-b)
   if(indexes[0]!<0||indexes.some((index,i)=>i>0&&index!==indexes[i-1]!+1))fail('目标不安全或不连续')
   result.push({slideIndex:item.slideIndex,kind:'group',elementIds:indexes.map(index=>elements[index]!.id)})
  }else if(item.kind==='ungroup'){
   if(Object.keys(item).sort().join()!=='elementId,kind,slideIndex'||typeof item.elementId!=='string'||!elements.some(element=>element.id===item.elementId&&element.type==='group'&&element.ungroupEditable===true))fail('取消组合目标不安全')
   result.push({slideIndex:item.slideIndex,kind:'ungroup',elementId:item.elementId})
  }else fail('操作无效')
 }
 if(!result.length)return result
 if(['theme','slideSize','headerFooter'].some(key=>input[key]!==undefined))fail('不能与全局样式或尺寸修改同时提交')
 for(const [key,records] of Object.entries(input)){
  if(key==='groupEdits'||key==='order'||!Array.isArray(records))continue
  if((key==='deletedSlides'||key==='resetLayouts')&&records.some(index=>seen.has(index)))fail('不能与同页删除或版式重置同时提交')
  if(key==='newSlides'&&records.some(item=>item&&typeof item==='object'&&(seen.has(item.duplicateOf)||seen.has(item.layoutFrom))))fail('请先保存来源组合再复制页面')
  if(records.some(item=>item&&typeof item==='object'&&seen.has(item.slideIndex)))fail('不能与同页其他修改同时提交')
 }
 return result
}
