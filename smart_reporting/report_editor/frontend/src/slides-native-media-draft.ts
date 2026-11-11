/** 恢复媒体草稿前整批校验；此函数不修改输入或编辑器状态。 */
import { imageSizeFromBytes } from '../../../reporting/slides_engine/packages/pptx-render/src/image-dpi'
import { NATIVE_CHART_TYPES, CHART_STYLE_FIELDS, validChartStyle } from './slides-native-chart-edit'
import { transposeChartData, validChartPointColors } from '../../../reporting/slides_engine/bridge/pptx-chart-data'
export type NativeMediaSourceElement = {
 id:string;type:string;pictureCropEditable?:boolean;pictureCropReason?:string|null;srcRect?:{l:number;t:number;r:number;b:number}|null;pictureReplaceable?:boolean;pictureSha256?:string|null;pictureSize?:number|null
 chartEditSafe?:boolean;chartKind?:string|null;chartCategories?:string[]|null;chartSeries?:{name:string;values:number[]}[]|null
 chartColorSchemes?:readonly {key:string}[]|null
}
export type NativeMediaSourceSlide = { elements: readonly NativeMediaSourceElement[] }
type Target = {slideIndex:number;elementId:string}
type RecordValue = Record<string, unknown>
function fail(reason:string):never {throw Error(`媒体草稿${reason}；原草稿已保留`)}
function record(value:unknown):value is RecordValue{return !!value&&typeof value==='object'&&!Array.isArray(value)}
function fields(value:unknown,keys:string[]):asserts value is RecordValue {
 if(!record(value)||Object.keys(value).some(key=>!keys.includes(key)))fail('包含不支持的字段')
}
function batch(value:unknown,limit:number):RecordValue[]{
 if(value===undefined)return []
 if(!Array.isArray(value)||value.length>limit||value.some(item=>!record(item)))fail('批次数量或结构无效')
 return value as RecordValue[]
}
const label=(value:unknown):value is string=>typeof value==='string'&&Array.from(value).length<=100&&!/[\u0000-\u001f\u007f]/.test(value)
function imageBytes(item:RecordValue):number {
 const value=item.bytesBase64
 if(typeof value!=='string'||!value.length||value.length>8*1024*1024||value.length%4!==0||/[^A-Za-z0-9+/=]/.test(value))fail('图片编码无效')
 let decoded:string
 try{decoded=atob(value)}catch{return fail('图片编码无效')}
 if(btoa(decoded)!==value||decoded.length>6*1024*1024)fail('图片超过单图预算或编码无效')
 const bytes=Uint8Array.from(decoded,c=>c.charCodeAt(0))
 const png=item.extension==='png'&&[137,80,78,71,13,10,26,10].every((n,i)=>bytes[i]===n)&&[0,0,0,0,73,69,78,68,174,66,96,130].every((n,i)=>bytes[bytes.length-12+i]===n)
 const jpg=item.extension==='jpg'&&bytes[0]===255&&bytes[1]===216&&bytes[2]===255&&bytes.at(-2)===255&&bytes.at(-1)===217
 const size=imageSizeFromBytes(bytes)
 if((!png&&!jpg)||!size||size.w*size.h>100_000_000)fail('图片格式或尺寸无效')
 return bytes.length
}
function chartData(categories:unknown,series:unknown,kind:unknown){
 if(!Array.isArray(categories)||categories.length<1||categories.length>100||!categories.every(label)||!Array.isArray(series)||series.length<1||series.length>20)fail('图表数据无效')
 for(const row of series){
  fields(row,['name','values'])
  if(!label(row.name)||!Array.isArray(row.values)||row.values.length!==categories.length||row.values.some(value=>typeof value!=='number'||!Number.isFinite(value)))fail('图表系列无效')
 }
 if(!NATIVE_CHART_TYPES.some(([value])=>value===kind)||(kind==='comboBarLine'&&series.length<2)||(kind==='scatter'&&categories.some(value=>!value.trim()||!Number.isFinite(Number(value)))))fail('图表类型与数据不兼容')
}
export function validateNativeMediaDraft(changes:unknown,slides:readonly NativeMediaSourceSlide[],deletedSlides:readonly number[]=[],deletions:readonly Target[]=[]):void {
 if(!record(changes))fail('结构无效')
 const images=batch(changes.images,50),pictures=batch(changes.pictureReplacements,50),charts=batch(changes.chartEdits,50),crops=batch(changes.pictureCrops,50)
 const seen=new Set<string>();let bytes=0
 const slide=(item:RecordValue)=>{
  if(typeof item.slideIndex!=='number'||!Number.isInteger(item.slideIndex)||item.slideIndex<0||item.slideIndex>=slides.length||deletedSlides.includes(item.slideIndex))fail('引用了无效或已删除的来源页')
  return slides[item.slideIndex]!
 }
 const target=(item:RecordValue)=>{
  const source=slide(item)
  if(typeof item.elementId!=='string'||!item.elementId.length)fail('目标身份无效')
  const key=`${item.slideIndex}:${item.elementId}`
  if(seen.has(key)||deletions.some(d=>d.slideIndex===item.slideIndex&&d.elementId===item.elementId))fail('目标重复或已删除')
  seen.add(key)
  const elements=source.elements.filter(element=>element.id===item.elementId)
  if(elements.length!==1)fail('目标来源不唯一')
  return elements[0]!
 }
 for(const item of images){
  fields(item,['slideIndex','bytesBase64','extension','geometry','descr']);slide(item)
  fields(item.geometry,['x','y','width','height'])
  const g=item.geometry
  if(['x','y','width','height'].some(key=>typeof g[key]!=='number'||!Number.isFinite(g[key])||(g[key] as number)<0||(g[key] as number)>100000)||(g.width as number)<=0||(g.height as number)<=0)fail('图片位置无效')
  if(item.descr!==undefined&&(typeof item.descr!=='string'||item.descr.length>10000))fail('图片描述无效')
  bytes+=imageBytes(item)
 }
 for(const item of pictures){
  fields(item,['slideIndex','elementId','expectedSha256','expectedSize','bytesBase64','extension'])
  const source=target(item)
  if(source.type!=='picture'||source.pictureReplaceable!==true||typeof item.expectedSha256!=='string'||!/^[a-f0-9]{64}$/.test(item.expectedSha256)||!Number.isSafeInteger(item.expectedSize)||(item.expectedSize as number)<=0||item.expectedSha256!==source.pictureSha256||item.expectedSize!==source.pictureSize)fail('图片来源身份已变化或暂不支持替换')
  bytes+=imageBytes(item)
 }
 for(const item of crops){
  fields(item,['slideIndex','elementId','expectedSha256','expectedSize','srcRect','geometry'])
  const source=target(item)
  if(source.type!=='picture'||source.pictureCropEditable!==true||typeof item.expectedSha256!=='string'||!/^[a-f0-9]{64}$/.test(item.expectedSha256)||!Number.isSafeInteger(item.expectedSize)||(item.expectedSize as number)<=0||item.expectedSha256!==source.pictureSha256||item.expectedSize!==source.pictureSize)fail('裁切来源身份已变化或暂不支持')
  if(item.srcRect!==null){
   fields(item.srcRect,['l','t','r','b'])
   const rect=item.srcRect
   if(['l','t','r','b'].some(key=>typeof rect[key]!=='number'||!Number.isFinite(rect[key])||(rect[key] as number)<0||(rect[key] as number)>=1)||(rect.l as number)+(rect.r as number)>=1||(rect.t as number)+(rect.b as number)>=1)fail('裁切比例无效')
  }
  fields(item.geometry,['x','y','width','height'])
  const g=item.geometry
  if(['x','y','width','height'].some(key=>typeof g[key]!=='number'||!Number.isFinite(g[key])||Math.abs(g[key] as number)>100000)||(g.width as number)<=0||(g.height as number)<=0)fail('裁切框位置无效')
 }
 if(bytes>8*1024*1024)fail('图片总量超过 8 MiB 预算')
 for(const item of charts){
  fields(item,['slideIndex','elementId','kind','categories','series','switchRowCol',...CHART_STYLE_FIELDS])
  const source=target(item)
  if(source.type!=='chart'||source.chartEditSafe!==true||(item.kind===undefined&&item.categories===undefined&&!Object.hasOwn(item,'switchRowCol')&&!CHART_STYLE_FIELDS.some(key=>Object.hasOwn(item,key)))||(item.categories===undefined)!==(item.series===undefined))fail('图表来源或修改结构无效')
  if(Object.hasOwn(item,'switchRowCol')&&typeof item.switchRowCol!=='boolean')fail('图表行列交换无效')
  if(!validChartStyle(item))fail('图表格式无效')
  if(item.colorScheme!==undefined&&source.chartColorSchemes&&!source.chartColorSchemes.some(scheme=>scheme.key===item.colorScheme))fail('图表配色来源不可用')
  if(item.kind!==undefined&&!NATIVE_CHART_TYPES.some(([kind])=>kind===item.kind))fail('图表类型无效')
  let data
  if(item.categories===undefined&&item.switchRowCol){
   chartData(source.chartCategories,source.chartSeries,source.chartKind)
   data=transposeChartData({categories:source.chartCategories!,series:source.chartSeries!})
   chartData(data.categories,data.series,item.kind??source.chartKind)
  }else{
   const categories=item.categories===undefined?source.chartCategories:item.categories,series=item.series===undefined?source.chartSeries:item.series
   chartData(categories,series,item.kind??source.chartKind)
   data={categories:categories as string[],series:series as {name:string;values:number[]}[]}
  }
  if(Object.hasOwn(item,'pointColors')&&((item.kind??source.chartKind)==='scatter'||!validChartPointColors(item.pointColors,data.series.length,data.categories.length)))fail('图表单点配色无效或超出数据范围')
 }
}
