/** 剪贴板buffer仅驻内存并绑定来源SHA；草稿只保存可校验的来源引用。 */
export type ClipboardPaste={sourceSlideIndex:number;elementIds:string[];slideIndex:number;dx:number;dy:number}
export type SlidesClipboardBuffer={sourceSha256:string;sourceSlideIndex:number;elementIds:string[]}
type Source={id:string;type:string;clipboardEditable?:boolean}
type Slide={elements:readonly Source[];masterPath?:string;themePath?:string}
const validId=(id:unknown):id is string=>typeof id==='string'&&id.length>0&&id.length<=200
const pixel=(value:unknown):value is number=>typeof value==='number'&&Number.isFinite(value)&&Math.abs(value)<=100000
function fail():never{throw Error('剪贴板来源、草稿或作用域已变化；请重新复制，原草稿已保留')}
function canonical(slides:readonly Slide[],slideIndex:number,value:unknown):string[]{
 if(!Number.isInteger(slideIndex)||slideIndex<0||slideIndex>=slides.length||!Array.isArray(value)||!value.length||value.length>500||value.some(id=>!validId(id))||new Set(value).size!==value.length)fail()
 const source=slides[slideIndex]!.elements,selected=new Set(value),matched=source.filter(e=>selected.has(e.id))
 if(new Set(source.map(e=>e.id)).size!==source.length||matched.length!==value.length||matched.some(e=>e.clipboardEditable!==true||!['text','shape','picture'].includes(e.type)))fail()
 return matched.map(e=>e.id)
}
export function validateSlidesClipboardDraft(changes:object,slides:readonly Slide[]):ClipboardPaste[]{
 const input=changes as Record<string,unknown>,value=input.clipboardPastes
 if(value===undefined)return []
 if(!Array.isArray(value)||value.length>50||value.reduce((sum,item)=>sum+(Array.isArray(item?.elementIds)?item.elementIds.length:0),0)>500)fail()
 const involved=new Set<number>(),result:ClipboardPaste[]=[]
 for(const item of value){
  if(!item||typeof item!=='object'||Object.keys(item).sort().join()!=='dx,dy,elementIds,slideIndex,sourceSlideIndex'||!Number.isInteger(item.slideIndex)||item.slideIndex<0||item.slideIndex>=slides.length||!pixel(item.dx)||!pixel(item.dy))fail()
  const elementIds=canonical(slides,item.sourceSlideIndex,item.elementIds),source=slides[item.sourceSlideIndex]!,target=slides[item.slideIndex]!
  if(['masterPath','themePath'].some(key=>{const a=source[key as 'masterPath'|'themePath'],b=target[key as 'masterPath'|'themePath'];return a!==undefined&&b!==undefined&&a!==b}))fail()
  involved.add(item.sourceSlideIndex);involved.add(item.slideIndex)
  result.push({sourceSlideIndex:item.sourceSlideIndex,elementIds,slideIndex:item.slideIndex,dx:item.dx,dy:item.dy})
 }
 if(!result.length)return result
 if(['theme','slideSize','headerFooter'].some(key=>input[key]!==undefined&&input[key]!==null))fail()
 for(const [key,records] of Object.entries(input)){
  if(!Array.isArray(records))continue
  if((key==='deletedSlides'||key==='resetLayouts')&&records.some(index=>involved.has(index)))fail()
  if(['groupEdits','slideLayouts'].includes(key)&&records.some(item=>item&&involved.has(item.slideIndex)))fail()
  if(key==='newSlides'&&records.some(item=>item&&(involved.has(item.duplicateOf)||involved.has(item.layoutFrom))))fail()
 }
 return result
}
/** copy时不复制未保存内容；cut可在capture完成后再提交deletions。 */
export function captureSlidesClipboard(sourceSha256:string,sourceSlideIndex:number,elementIds:readonly string[],changes:object,slides:readonly Slide[]):SlidesClipboardBuffer{
 if(!/^[a-f0-9]{64}$/.test(sourceSha256))fail()
 const input=changes as Record<string,unknown>,ids=canonical(slides,sourceSlideIndex,elementIds)
 if(['theme','slideSize','headerFooter'].some(key=>input[key]!==undefined&&input[key]!==null))fail()
 for(const [key,records] of Object.entries(input)){
  if(key==='order'||!Array.isArray(records))continue
  if((key==='deletedSlides'||key==='resetLayouts')&&records.includes(sourceSlideIndex))fail()
  if(records.some(item=>item&&typeof item==='object'&&item.slideIndex===sourceSlideIndex))fail()
  if(key==='newSlides'&&records.some(item=>item&&(item.duplicateOf===sourceSlideIndex||item.layoutFrom===sourceSlideIndex)))fail()
 }
 return {sourceSha256,sourceSlideIndex,elementIds:ids}
}
/** 调用方管理每次20px偏移；这里只返回新数组，不持久化buffer、不改原草稿。 */
export function planSlidesClipboardPaste(buffer:SlidesClipboardBuffer,sourceSha256:string,slideIndex:number,dx:number,dy:number,changes:object,slides:readonly Slide[]):ClipboardPaste[]{
 if(!buffer||buffer.sourceSha256!==sourceSha256||!/^[a-f0-9]{64}$/.test(sourceSha256))fail()
 const input=changes as Record<string,unknown>,existing=validateSlidesClipboardDraft(changes,slides)
 return validateSlidesClipboardDraft({...input,clipboardPastes:[...existing,{sourceSlideIndex:buffer.sourceSlideIndex,elementIds:[...buffer.elementIds],slideIndex,dx,dy}]},slides)
}
