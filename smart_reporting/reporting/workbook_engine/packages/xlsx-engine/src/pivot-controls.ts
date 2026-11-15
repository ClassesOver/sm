/** Office 2010/2013 原生非 OLAP 控件；控制列表、缓存和 DrawingML 一起提交。 */
import { z } from 'zod'
import { createBufferEntrySource, assemblePackage, type EntrySource } from './zip'
import { readPivotState, pivotHostSheet, resolvePivotTarget, rebuildPivotOutput, pivotLayoutSpecOf } from './pivot-add'
import { pivotSourceColumnValues, readPivotSourcePatterns } from './pivot-source-format'
import { readWorkbook, parseSheetElements } from './workbook-read'
import { readXmlAttribute, decodeXmlText, escapeXmlText } from './xml'
import { formatAddress } from './cell-address'
import { relationships } from './sheet-removal-parts'

const R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
const X='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
const X14='http://schemas.microsoft.com/office/spreadsheetml/2009/9/main'
const X15='http://schemas.microsoft.com/office/spreadsheetml/2010/11/main'
const XDR='http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing'
const A='http://schemas.openxmlformats.org/drawingml/2006/main'
const MC='http://schemas.openxmlformats.org/markup-compatibility/2006'
const OWN='urn:smart-reporting:pivot-control:v1'
const nativePath=/^xl\/(?:slicerCaches|timelineCaches|slicers|timelines)\/[^/]+\.xml$/i
export const pivotControlPartPath=/^xl\/(?:slicerCaches|timelineCaches|slicers|timelines)\//i
const attr=(xml:string,name:string)=>decodeXmlText(readXmlAttribute(xml,name)??'')
const esc=(v:string|number)=>escapeXmlText(String(v)).replace(/"/g,'&quot;')
const relsPath=(path:string)=>path.replace(/([^/]+)$/,'_rels/$1.rels')
const relative=(path:string)=>'/'+path
const EMPTY_RELS='<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>'
const modes={
 slicer:{ns:X14,prefix:'x14',folder:'slicers',cacheFolder:'slicerCaches',tag:'slicer',cacheTag:'slicerCacheDefinition',root:'slicers',rel:'http://schemas.microsoft.com/office/2007/relationships/slicer',cacheRel:'http://schemas.microsoft.com/office/2007/relationships/slicerCache',content:'application/vnd.ms-excel.slicer+xml',cacheContent:'application/vnd.ms-excel.slicerCache+xml',workbookUri:'{BBE1A952-AA13-448e-AADC-164F8A28A991}',sheetUri:'{A8765BA9-456A-4dab-B4F3-ACF838C121DE}',list:'slicerList',ref:'slicer',cacheList:'slicerCaches',cacheRef:'slicerCache',drawing:'http://schemas.microsoft.com/office/drawing/2010/slicer',drawingTag:'slicer'},
 timeline:{ns:X15,prefix:'x15',folder:'timelines',cacheFolder:'timelineCaches',tag:'timeline',cacheTag:'timelineCacheDefinition',root:'timelines',rel:'http://schemas.microsoft.com/office/2011/relationships/timeline',cacheRel:'http://schemas.microsoft.com/office/2011/relationships/timelineCache',content:'application/vnd.ms-excel.timeline+xml',cacheContent:'application/vnd.ms-excel.timelineCache+xml',workbookUri:'{D0CA8CA8-9F24-4464-BF8E-62219DCF47F9}',sheetUri:'{7E03D99C-DC04-49d9-9315-930204A7B6E9}',list:'timelineRefs',ref:'timelineRef',cacheList:'timelineCacheRefs',cacheRef:'timelineCacheRef',drawing:'http://schemas.microsoft.com/office/drawing/2012/timeslicer',drawingTag:'timeslicer'},
} as const
export const upsertPivotControlRequestSchema=z.object({kind:z.enum(['slicer','timeline']),tablePath:z.string().regex(/^xl\/pivotTables\/[^/]+\.xml$/),field:z.string().min(1).max(255),name:z.string().regex(/^[A-Za-z_][A-Za-z0-9_]{0,199}$/),caption:z.string().max(255).optional(),from:z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(),to:z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional(),anchor:z.object({row:z.number().int().min(0).max(1048575),column:z.number().int().min(0).max(16383),width:z.number().int().min(96).max(2000).optional(),height:z.number().int().min(80).max(2000).optional()}).strict().optional()}).strict()
export type PivotControlRequest=z.infer<typeof upsertPivotControlRequestSchema>
interface Metadata {request:PivotControlRequest;partPath:string;cachePath:string;drawingPath:string;worksheetPath:string;workbookRel:string;sheetRel:string;drawingId:number}
export interface PivotControl extends PivotControlRequest {partPath:string;cachePath:string}
function fail(message:string):never {throw new Error('原生透视控件：'+message)}
function date(value:string):string|undefined {if(!/^\d{4}-\d{2}-\d{2}$/.test(value))return;const d=new Date(value+'T00:00:00Z');if(Number.isFinite(d.getTime())&&d.toISOString().slice(0,10)===value)return value}
function appendExtension(xml:string,root:string,uri:string,body:string):string {
 const block=`<ext uri="${uri}">${body}</ext>`
 const existing=xml.match(new RegExp(`<ext\\b[^>]*uri="${uri.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')}"[^>]*>[\\s\\S]*?<\\/ext>`))
 if(existing)return xml.replace(existing[0],()=>block)
 if(/<extLst\b[^>]*>/.test(xml))return xml.replace('</extLst>',()=>block+'</extLst>')
 if(/<extLst\b[^>]*\/>/.test(xml))return xml.replace(/<extLst\b[^>]*\/>/,()=>'<extLst>'+block+'</extLst>')
 return xml.replace(`</${root}>`,()=>'<extLst>'+block+`</extLst></${root}>`)
}
function appendReference(xml:string,root:string,uri:string,ns:string,prefix:string,list:string,ref:string,id:string):string {
 const found=xml.match(new RegExp(`<${prefix}:${list}\\b[^>]*>[\\s\\S]*?<\\/${prefix}:${list}>`))?.[0]
 const child=`<${prefix}:${ref} r:id="${id}"/>`
 if(found){if(found.includes(child))return xml;return xml.replace(found,()=>found.replace(`</${prefix}:${list}>`,()=>child+`</${prefix}:${list}>`))}
 return appendExtension(xml,root,uri,`<${prefix}:${list} xmlns:${prefix}="${ns}" xmlns:r="${R}">${child}</${prefix}:${list}>`)
}
function addRelationship(xml:string,type:string,target:string){
 const ids=[...xml.matchAll(/\bId="rId(\d+)"/g)].map(match=>Number(match[1])),id='rId'+(Math.max(0,...ids)+1)
 return {id,xml:xml.replace('</Relationships>',()=>`<Relationship Id="${id}" Type="${type}" Target="${target}"/></Relationships>`)}
}
async function optionalText(source:EntrySource,path:string,fallback=EMPTY_RELS){return await source.has(path)?source.readText(path):fallback}
async function nextPath(source:EntrySource,folder:string,stem:string){for(let n=1;n<10000;n++){const path=`xl/${folder}/${stem}${n}.xml`;if(!await source.has(path))return path}return fail('没有可用部件名称')}
function contentType(xml:string,path:string,type:string){const value=`<Override PartName="/${path}" ContentType="${type}"/>`;return xml.includes(`PartName="/${path}"`)?xml:xml.replace('</Types>',()=>value+'</Types>')}
async function context(bytes:Uint8Array,request:PivotControlRequest){
 const source=await createBufferEntrySource(bytes),xml=await source.readText(request.tablePath),state=readPivotState(xml)
 if(!state)fail('仅支持本编辑器可完整读取的透视表')
 const field=state.fieldNames.indexOf(request.field),pageLevel=(state.pageFilters??[]).findIndex(filter=>filter.fieldIndex===field)
 const axis=state.rowFieldIndices.includes(field)?'row':(state.columnFieldIndices??[]).includes(field)?'column':pageLevel>=0?'page':undefined
 if(field<0||!axis||state.groupings?.some(rule=>rule.fieldIndex===field))fail('控件字段必须是未分组的现有行、列或报表筛选字段')
 const cacheId=Number(attr(xml.match(/<pivotTableDefinition\b[^>]*>/)?.[0]??'','cacheId'))
 const rels=await source.readText(relsPath(request.tablePath)),cacheRelationship=[...rels.matchAll(/<Relationship\b[^>]*\/>/g)].find(r=>attr(r[0],'Type')===R+'/pivotCacheDefinition')?.[0]
 const cachePath=resolvePivotTarget(request.tablePath,attr(cacheRelationship??'','Target'))
 const host=await pivotHostSheet(source,request.tablePath),workbookXml=await source.readText('xl/workbook.xml')
 const sheetTag=parseSheetElements(workbookXml).find(sheet=>sheet.name===host.name)?.xml??'',sheetId=Number(attr(sheetTag,'sheetId'))
 if(!Number.isInteger(cacheId)||!Number.isInteger(sheetId)||sheetId<1)fail('透视表身份不可读取')
 for(const path of await source.paths())if(/^xl\/pivotTables\/[^/]+\.xml$/.test(path)&&path!==request.tablePath){const other=await source.readText(path);if(attr(other.match(/<pivotTableDefinition\b[^>]*>/)?.[0]??'','cacheId')===String(cacheId))fail('共享透视缓存需要先拆分，不能孤立更新控件')}
 const cacheXml=await source.readText(cachePath),fieldBlocks=[...cacheXml.matchAll(/<cacheField\b[^>]*>[\s\S]*?<\/cacheField>/g)],fieldXml=fieldBlocks[field]?.[0]
 if(!fieldXml||/<fieldGroup\b/.test(fieldXml))fail('控件不支持分组缓存字段')
 const level=axis==='row'?state.rowFieldIndices.indexOf(field):axis==='column'?(state.columnFieldIndices??[]).indexOf(field):pageLevel
 const members=[...(axis==='row'?state.rowLevelItems[level]:axis==='column'?state.colLevelItems?.[level]:state.pageLevelItems?.[level])??[]]
 const hidden=new Set((axis==='row'?state.rowHiddenItems?.[level]:axis==='column'?state.colHiddenItems?.[level]:state.pageHiddenItems?.[level])??[])
 const selected=members.map((_,index)=>!hidden.has(index))
 if(!members.length||!selected.some(Boolean))fail('至少保留一个可见成员')
 return {source,xml,state,field,axis,cacheId,cachePath,host,sheetId,cacheXml,fieldXml,members,selected,workbookXml}
}
type Context=Awaited<ReturnType<typeof context>>
async function timelineDates(bytes:Uint8Array,ctx:Context){
 const wb=await readWorkbook(bytes),sheet=wb.sheets.find(sheet=>sheet.name===ctx.state.sourceSheetName)
 if(!sheet)fail('日期来源不存在')
 let numericDateField=false
 const area=ctx.state.sourceArea,values=new Map<string,string|undefined>(),epoch1904=['1','true'].includes(attr(ctx.workbookXml.match(/<workbookPr\b[^>]*>/)?.[0]??'','date1904'))
 const cells=Array.from({length:area.endRow-area.startRow},(_,index)=>sheet.cells[formatAddress(area.startRow+index+1,area.startColumn+ctx.field)])
 const patterns=await readPivotSourcePatterns(ctx.source,await ctx.source.readText(sheet.path),area)
 const labels=pivotSourceColumnValues(cells.map(cell=>cell?.value??null),cells.map((_,index)=>patterns[index+1]?.[ctx.field]??'General'),ctx.state.fieldNames[ctx.field]!,{...pivotLayoutSpecOf(ctx.state),dimensionFormatProjection:ctx.state.dimensionFormatProjection===true},epoch1904)
 for(let row=area.startRow+1;row<=area.endRow;row++){
  const cell=sheet.cells[formatAddress(row,area.startColumn+ctx.field)],value=cell?.value,key=String(labels[row-area.startRow-1]??'');let parsed: string|undefined
  if(typeof value==='string')fail('原生时间线需要带日期格式的数值日期，ISO 日期文本仅支持成员筛选')
  else if(typeof value==='number'&&Number.isFinite(value)&&value>=0){
   const format=(patterns[row-area.startRow]?.[ctx.field]??'').replace(/"[^"]*"|\[[^\]]*\]|\\./g,'')
   if(/[dy]/i.test(format))numericDateField=true
   if(/[dy]/i.test(format)&&!(!epoch1904&&Math.floor(value)===60)){
    const serial=Math.floor(value),epoch=epoch1904?Date.UTC(1904,0,1):Date.UTC(1899,11,31),d=new Date(epoch+(serial-(!epoch1904&&serial>60?1:0))*86400000)
    if(Number.isFinite(d.getTime()))parsed=date(d.toISOString().slice(0,10))
   }
  }
  values.set(key,values.has(key)&&values.get(key)!==parsed?undefined:parsed)
 }
 const cachedDates=[...ctx.fieldXml.matchAll(/<d\b[^>]*\bv="([^"]+)"/g)].map(match=>date(match[1]!.slice(0,10)))
 const result=ctx.members.map((member,index)=>{
  if(values.has(member))return values.get(member)
  if(cachedDates[index])return cachedDates[index]
  if(numericDateField&&/^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(member)){
   const serial=Math.floor(Number(member));if(!epoch1904&&serial===60)return
   const d=new Date((epoch1904?Date.UTC(1904,0,1):Date.UTC(1899,11,31))+(serial-(!epoch1904&&serial>60?1:0))*86400000)
   if(Number.isFinite(d.getTime()))return date(d.toISOString().slice(0,10))
  }
 })
 if(result.some(value=>!value))fail('时间线需要全部成员均为有效日期（空白、普通数值和无效日期不支持原生控件）')
 return result as string[]
}
function controlXml(meta:Metadata){const r=meta.request,m=modes[r.kind],p=m.prefix,cacheName=r.name+'_Cache';return `<?xml version="1.0" encoding="UTF-8"?><${p}:${m.root} xmlns:${p}="${m.ns}" xmlns:x="${X}"><${p}:${m.tag} name="${esc(r.name)}" cache="${esc(cacheName)}" caption="${esc(r.caption??r.field)}" ${r.kind==='slicer'?'rowHeight="254000" columnCount="1" showCaption="1"':'level="3" selectionLevel="3" showHeader="1" showSelectionLabel="1" showTimeLevel="1" showHorizontalScrollbar="1"'}><${p}:extLst><x:ext uri="${OWN}"><sr:control xmlns:sr="${OWN}" value="${esc(JSON.stringify(meta))}"/></x:ext></${p}:extLst></${p}:${m.tag}></${p}:${m.root}>`}
function drawingAnchor(meta:Metadata){
 const r=meta.request,m=modes[r.kind],anchor=r.anchor??{row:0,column:0},cx=(anchor.width??(r.kind==='slicer'?192:480))*9525,cy=(anchor.height??(r.kind==='slicer'?260:160))*9525,name=esc(r.name)
 return `<xdr:oneCellAnchor><xdr:from><xdr:col>${anchor.column}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>${anchor.row}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from><xdr:ext cx="${cx}" cy="${cy}"/><mc:AlternateContent xmlns:mc="${MC}" xmlns:a14="http://schemas.microsoft.com/office/drawing/2010/main" xmlns:a15="http://schemas.microsoft.com/office/drawing/2012/main"><mc:Choice Requires="${r.kind==='slicer'?'a14':'a15'}"><xdr:graphicFrame macro=""><xdr:nvGraphicFramePr><xdr:cNvPr id="${meta.drawingId}" name="${name}"/><xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr><xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></xdr:xfrm><a:graphic><a:graphicData uri="${m.drawing}"><ctl:${m.drawingTag} xmlns:ctl="${m.drawing}" name="${name}"/></a:graphicData></a:graphic></xdr:graphicFrame></mc:Choice><mc:Fallback><xdr:sp><xdr:nvSpPr><xdr:cNvPr id="${meta.drawingId}" name="${name}"/><xdr:cNvSpPr/></xdr:nvSpPr><xdr:spPr><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr><xdr:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>${esc(r.caption??r.field)}（需要支持原生控件的 Excel）</a:t></a:r></a:p></xdr:txBody></xdr:sp></mc:Fallback></mc:AlternateContent><xdr:clientData/></xdr:oneCellAnchor>`
}
async function cacheXml(bytes:Uint8Array,meta:Metadata,ctx:Context){
 const r=meta.request,m=modes[r.kind],p=m.prefix,base=`<${p}:pivotTables><${p}:pivotTable tabId="${ctx.sheetId}" name="${esc(ctx.state.name)}"/></${p}:pivotTables>`
 let body:string
 if(r.kind==='slicer')body=base+`<x14:data><x14:tabular pivotCacheId="${ctx.cacheId}" sortOrder="ascending" customListSort="0" showMissing="1" crossFilter="showItemsWithDataAtTop"><x14:items count="${ctx.members.length}">${ctx.members.map((_,i)=>`<x14:i x="${i}" s="${ctx.selected[i]?'1':'0'}" nd="0"/>`).join('')}</x14:items></x14:tabular></x14:data>`
 else {
  const dates=await timelineDates(bytes,ctx),sorted=[...dates].sort(),from=r.from,to=r.to
  if(!from||!to||!date(from)||!date(to)||from>to)fail('时间线开始/结束日期无效')
  if(ctx.selected.some((selected,i)=>selected!==(dates[i]!>=from&&dates[i]!<=to)))fail('时间线区间与透视成员选择不一致，请先按同一区间筛选')
  body=base+`<x15:state singleRangeFilterState="1" minimalRefreshVersion="0" lastRefreshVersion="0" pivotCacheId="${ctx.cacheId}" filterType="dateBetween" filterId="${100000+ctx.field}" filterTabId="${ctx.sheetId}" filterPivotName="${esc(ctx.state.name)}"><x15:selection startDate="${from}T00:00:00" endDate="${to}T00:00:00"/><x15:bounds startDate="${sorted[0]}T00:00:00" endDate="${sorted.at(-1)}T00:00:00"/></x15:state>`
 }
 return `<?xml version="1.0" encoding="UTF-8"?><${p}:${m.cacheTag} xmlns:${p}="${m.ns}" name="${esc(r.name+'_Cache')}" sourceName="${esc(r.field)}">${body}</${p}:${m.cacheTag}>`
}
function metadata(xml:string):Metadata|undefined {const tag=xml.match(/<sr:control\b[^>]*\/>/)?.[0];if(!tag)return;try {const meta=JSON.parse(attr(tag,'value')) as Metadata;meta.request=upsertPivotControlRequestSchema.parse(meta.request);if(!/^xl\/(?:slicers|timelines)\/[^/]+\.xml$/.test(meta.partPath)||!/^xl\/(?:slicerCaches|timelineCaches)\/[^/]+\.xml$/.test(meta.cachePath)||!/^xl\/drawings\/[^/]+\.xml$/.test(meta.drawingPath)||!/^xl\/worksheets\/[^/]+\.xml$/.test(meta.worksheetPath)||!/^rId\d+$/.test(meta.workbookRel)||!/^rId\d+$/.test(meta.sheetRel)||!Number.isSafeInteger(meta.drawingId)||meta.drawingId<1)return;return meta}catch{return}}
function hasRelationship(xml:string,id:string,type:string,path:string,base:string){return [...xml.matchAll(/<Relationship\b[^>]*\/>/g)].some(match=>attr(match[0],'Id')===id&&attr(match[0],'Type')===type&&attr(match[0],'TargetMode')!=='External'&&resolvePivotTarget(base,attr(match[0],'Target'))===path)}
async function assertExclusiveControlReferences(source:EntrySource,meta:Metadata){
 const found=new Set<string>(),m=modes[meta.request.kind]
 for(const path of (await source.paths()).filter(path=>path.endsWith('.rels'))){
  const base=path==='_rels/.rels'?'':path.replace('/_rels/','/').replace(/\.rels$/,'')
  for(const entry of relationships(await source.readText(path),path)){
   if(entry.external)continue
   const target=resolvePivotTarget(base,decodeURIComponent(entry.target.split('#',1)[0]!))
   if(![meta.partPath,meta.cachePath].includes(target))continue
   const expected=target===meta.partPath?{path:relsPath(meta.worksheetPath),id:meta.sheetRel,type:m.rel}:{path:'xl/_rels/workbook.xml.rels',id:meta.workbookRel,type:m.cacheRel}
   if(found.has(target)||path!==expected.path||entry.id!==expected.id||entry.type!==expected.type||entry.external)fail('控件部件仍有其他关系引用，不能安全修改')
   found.add(target)
  }
 }
}
async function metas(bytes:Uint8Array,validate=true):Promise<Metadata[]>{
 const source=await createBufferEntrySource(bytes),paths=(await source.paths()).filter(path=>nativePath.test(path)),result:Metadata[]=[]
 for(const path of paths.filter(path=>/^xl\/(?:slicers|timelines)\//i.test(path))){const xml=await source.readText(path),meta=metadata(xml);if(!meta||meta.partPath!==path||controlXml(meta)!==xml)fail('现有控件不属于可完整保真的结构，保留原文件并拒绝编辑');result.push(meta)}
 if(paths.length!==result.length*2||new Set(result.map(meta=>meta.cachePath)).size!==result.length||result.some(meta=>!paths.includes(meta.cachePath)))fail('存在未知或重复控件缓存')
 if(validate)for(const meta of result){
  const ctx=await context(bytes,meta.request),m=modes[meta.request.kind]
  if(ctx.host.path!==meta.worksheetPath||await source.readText(meta.cachePath)!==await cacheXml(bytes,meta,ctx))fail('缓存选择或透视关联已经变化')
  const wb=await source.readText('xl/workbook.xml'),ws=await source.readText(meta.worksheetPath),wr=await source.readText('xl/_rels/workbook.xml.rels'),sr=await source.readText(relsPath(meta.worksheetPath)),drawing=await source.readText(meta.drawingPath),types=await source.readText('[Content_Types].xml')
  if(!hasRelationship(wr,meta.workbookRel,m.cacheRel,meta.cachePath,'xl/workbook.xml')||!hasRelationship(sr,meta.sheetRel,m.rel,meta.partPath,meta.worksheetPath))fail('控件关系身份不一致')
  if(meta.request.kind==='timeline'){
   const expected=new Map<string,string>();await applyTimelineNative(bytes,meta,ctx,expected)
   if(expected.get(ctx.cachePath)!==ctx.cacheXml||expected.get(meta.request.tablePath)!==ctx.xml)fail('时间线日期缓存或原生区间筛选不一致')
  }
  const wbRef=`<${m.prefix}:${m.cacheList} xmlns:${m.prefix}="${m.ns}" xmlns:r="${R}">`,sheetRef=`<${m.prefix}:${m.list} xmlns:${m.prefix}="${m.ns}" xmlns:r="${R}">`
  if(!wb.includes(`<ext uri="${m.workbookUri}">${wbRef}`)||!ws.includes(`<ext uri="${m.sheetUri}">${sheetRef}`))fail('控件扩展类型或命名空间不一致')
  if(!wb.includes(`<definedName name="${esc(meta.request.name+'_Cache')}">#N/A</definedName>`))fail('控件缓存命名项缺失')
  if(!wb.includes(`<${m.prefix}:${m.cacheRef} r:id="${meta.workbookRel}"/>`)||!ws.includes(`<${m.prefix}:${m.ref} r:id="${meta.sheetRel}"/>`)||!drawing.includes(drawingAnchor(meta)))fail('控件扩展或可见绘图不完整')
  const drawingRel=attr(ws.match(/<drawing\b[^>]*\/>/)?.[0]??'','r:id')
  if(!hasRelationship(sr,drawingRel,R+'/drawing',meta.drawingPath,meta.worksheetPath))fail('控件绘图关系缺失')
  for(const [path,type] of [[meta.partPath,m.content],[meta.cachePath,m.cacheContent],[meta.drawingPath,'application/vnd.openxmlformats-officedocument.drawing+xml']])if(!types.includes(`PartName="/${path}" ContentType="${type}"`))fail('控件部件类型缺失')
 }
 return result
}
export async function readPivotControls(bytes:Uint8Array):Promise<PivotControl[]>{return (await metas(bytes)).map(meta=>({...meta.request,partPath:meta.partPath,cachePath:meta.cachePath}))}
export async function supportsOwnedPivotControls(bytes:Uint8Array):Promise<boolean>{try{return (await metas(bytes)).length>0}catch{return false}}
/** 字段身份迁移不重建输出、成员或时间区间，只规划已验证控件的名称引用。 */
export async function planPivotControlFieldRenames(bytes:Uint8Array,pivotReplacements:ReadonlyMap<string,string>,renames:ReadonlyMap<string,ReadonlyMap<string,string>>):Promise<Map<string,string>>{
 const before=await metas(bytes),source=await createBufferEntrySource(bytes),replaced=new Map(pivotReplacements)
 const assemble=async()=> (await assemblePackage(bytes,{replaced,added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[...replaced.keys()]})).buffer
 const migrated=await assemble()
 for(const meta of before){
  const field=renames.get(meta.request.tablePath)?.get(meta.request.field)
  if(field===undefined)continue
  await assertExclusiveControlReferences(source,meta)
  if(field===meta.request.field)continue
  const current={...meta,request:upsertPivotControlRequestSchema.parse({...meta.request,field})},ctx=await context(migrated,current.request)
  replaced.set(meta.partPath,controlXml(current));replaced.set(meta.cachePath,await cacheXml(migrated,current,ctx))
  const drawing=replaced.get(meta.drawingPath)??await ctx.source.readText(meta.drawingPath)
  replaced.set(meta.drawingPath,drawing.replace(drawingAnchor(meta),()=>drawingAnchor(current)))
 }
 await metas(await assemble())
 return replaced
}
export async function upsertPivotControl(bytes:Uint8Array,input:PivotControlRequest):Promise<Uint8Array>{
 const request=upsertPivotControlRequestSchema.parse(input),existing=await metas(bytes),old=existing.find(meta=>meta.request.name===request.name)
 if(existing.some(meta=>meta.request.name!==request.name&&meta.request.tablePath===request.tablePath&&meta.request.field===request.field))fail('同一字段已有原生控件，请编辑该控件')
 if(old&&(old.request.tablePath!==request.tablePath||old.request.field!==request.field||old.request.kind!==request.kind))fail('不能把现有控件换绑到不同字段或透视表')
 const ctx=await context(bytes,request),source=ctx.source,m=modes[request.kind],replaced=new Map<string,string>(),added=new Map<string,string>()
 let meta:Metadata
 if(old)meta={...old,request:upsertPivotControlRequestSchema.parse({...old.request,...request,anchor:request.anchor??old.request.anchor})}
 else {
  let wr=await source.readText('xl/_rels/workbook.xml.rels'),sr=await optionalText(source,relsPath(ctx.host.path))
  const partPath=await nextPath(source,m.folder,m.tag),cachePath=await nextPath(source,m.cacheFolder,m.tag+'Cache')
  const cacheRel=addRelationship(wr,m.cacheRel,relative(cachePath));wr=cacheRel.xml
  const controlRel=addRelationship(sr,m.rel,relative(partPath));sr=controlRel.xml
  const ws=await source.readText(ctx.host.path),drawingId=attr(ws.match(/<drawing\b[^>]*\/>/)?.[0]??'','r:id')
  let drawingPath:string
  if(drawingId){const rel=[...sr.matchAll(/<Relationship\b[^>]*\/>/g)].find(match=>attr(match[0],'Id')===drawingId)?.[0];if(!rel||attr(rel,'Type')!==R+'/drawing')fail('现有绘图关系无法保真');drawingPath=resolvePivotTarget(ctx.host.path,attr(rel,'Target'))}
  else {drawingPath=await nextPath(source,'drawings','drawing');const drawingRel=addRelationship(sr,R+'/drawing',relative(drawingPath));sr=drawingRel.xml;let modified=ws;if(!/xmlns:r=/.test(modified.match(/<worksheet\b[^>]*>/)?.[0]??''))modified=modified.replace('<worksheet',`<worksheet xmlns:r="${R}"`);const element=`<drawing r:id="${drawingRel.id}"/>`;modified=modified.replace(/<(?:legacyDrawing|legacyDrawingHF|picture|oleObjects|controls|webPublishItems|tableParts|extLst)\b|<\/worksheet>/,match=>element+match);replaced.set(ctx.host.path,modified)}
  const drawing=await optionalText(source,drawingPath,`<xdr:wsDr xmlns:xdr="${XDR}" xmlns:a="${A}"></xdr:wsDr>`),ids=[...drawing.matchAll(/<xdr:cNvPr\b[^>]*\bid="(\d+)"/g)].map(match=>Number(match[1]))
  meta={request,partPath,cachePath,drawingPath,worksheetPath:ctx.host.path,workbookRel:cacheRel.id,sheetRel:controlRel.id,drawingId:Math.max(0,...ids)+1}
  const cacheName=request.name+'_Cache'
  if([...ctx.workbookXml.matchAll(/<definedName\b[^>]*>/g)].some(match=>attr(match[0],'name').toLowerCase()===cacheName.toLowerCase()))fail('控件缓存名称与工作簿已有名称冲突')
  let namedWorkbook=ctx.workbookXml
  const defined=`<definedName name="${esc(cacheName)}">#N/A</definedName>`
  if(/<definedNames\b[^>]*[^/]>/.test(namedWorkbook)||namedWorkbook.includes('<definedNames>'))namedWorkbook=namedWorkbook.replace('</definedNames>',()=>defined+'</definedNames>')
  else if(/<definedNames\b[^>]*\/>/.test(namedWorkbook))namedWorkbook=namedWorkbook.replace(/<definedNames\b[^>]*\/>/,()=>'<definedNames>'+defined+'</definedNames>')
  else namedWorkbook=namedWorkbook.replace(/<(?:calcPr|oleSize|customWorkbookViews|pivotCaches|smartTagPr|smartTagTypes|webPublishing|fileRecoveryPr|webPublishObjects|extLst)\b|<\/workbook>/,match=>'<definedNames>'+defined+'</definedNames>'+match)
  const wb=appendReference(namedWorkbook,'workbook',m.workbookUri,m.ns,m.prefix,m.cacheList,m.cacheRef,meta.workbookRel)
  const sheet=appendReference(replaced.get(ctx.host.path)??ws,'worksheet',m.sheetUri,m.ns,m.prefix,m.list,m.ref,meta.sheetRel)
  replaced.set('xl/workbook.xml',wb);replaced.set('xl/_rels/workbook.xml.rels',wr);replaced.set(ctx.host.path,sheet)
  ;(await source.has(relsPath(ctx.host.path))?replaced:added).set(relsPath(ctx.host.path),sr)
 }
 const put=async(path:string,value:string)=>{(await source.has(path)?replaced:added).set(path,value)}
 await put(meta.partPath,controlXml(meta));await put(meta.cachePath,await cacheXml(bytes,meta,ctx))
 let drawing=await optionalText(source,meta.drawingPath,`<xdr:wsDr xmlns:xdr="${XDR}" xmlns:a="${A}"></xdr:wsDr>`)
 drawing=old?drawing.replace(drawingAnchor(old),()=>drawingAnchor(meta)):drawing.replace('</xdr:wsDr>',()=>drawingAnchor(meta)+'</xdr:wsDr>')
 await put(meta.drawingPath,drawing)
 let types=await source.readText('[Content_Types].xml');for(const [path,type] of [[meta.partPath,m.content],[meta.cachePath,m.cacheContent],[meta.drawingPath,'application/vnd.openxmlformats-officedocument.drawing+xml']])types=contentType(types,path!,type!)
 replaced.set('[Content_Types].xml',types)
 if(request.kind==='timeline')await applyTimelineNative(bytes,meta,ctx,replaced)
 const result=(await assemblePackage(bytes,{replaced,added,addedBinary:new Map(),removedEntries:[],addedEntries:[...added.keys()],touchedEntries:[...replaced.keys()]})).buffer
 await metas(result)
 return result
}
async function applyTimelineNative(bytes:Uint8Array,meta:Metadata,ctx:Context,replaced:Map<string,string>){
 const dates=await timelineDates(bytes,ctx),shared=`<sharedItems containsSemiMixedTypes="0" containsNonDate="0" containsDate="1" containsString="0" containsBlank="0" count="${dates.length}">${dates.map(value=>`<d v="${value}T00:00:00"/>`).join('')}</sharedItems>`
 let cache=replaced.get(ctx.cachePath)??ctx.cacheXml,field=ctx.fieldXml.replace(/<sharedItems\b[^>]*(?:\/>|>[\s\S]*?<\/sharedItems>)/,()=>shared)
 cache=cache.replace(ctx.fieldXml,()=>field)
 cache=appendExtension(cache,'pivotCacheDefinition','{5DA0FC9A-693D-419c-AD59-312A39285967}',`<x15:timelinePivotCacheDefinition xmlns:x15="${X15}" timelineData="1"/>`)
 replaced.set(ctx.cachePath,cache)
 const id=100000+ctx.field,filter=`<filter fld="${ctx.field}" type="dateBetween" id="${id}" evalOrder="-1"><autoFilter ref="A1"><filterColumn colId="0"><customFilters and="1"><customFilter operator="greaterThanOrEqual" val="${meta.request.from}T00:00:00"/><customFilter operator="lessThanOrEqual" val="${meta.request.to}T00:00:00"/></customFilters></filterColumn></autoFilter></filter>`
 let xml=replaced.get(meta.request.tablePath)??ctx.xml
 const existing=xml.match(/<filters\b[^>]*>[\s\S]*?<\/filters>/)?.[0]
 if(existing){
  const previous=existing.match(new RegExp(`<filter\\b[^>]*\\bid="${id}"[^>]*>[\\s\\S]*?<\\/filter>`))?.[0]
  if(previous)xml=xml.replace(previous,()=>filter)
  else {const count=[...existing.matchAll(/<filter\b/g)].length+1;xml=xml.replace(existing,()=>existing.replace(/count="\d+"/,`count="${count}"`).replace('</filters>',()=>filter+'</filters>'))}
 }
 else xml=xml.replace(/<extLst\b|<\/pivotTableDefinition>/,match=>`<filters count="1">${filter}</filters>`+match)
 replaced.set(meta.request.tablePath,xml)
}
export async function syncOwnedPivotControls(beforeBytes:Uint8Array,afterBytes:Uint8Array,tablePath?:string,controlRequest?:PivotControlRequest):Promise<Uint8Array>{
 const before=await metas(beforeBytes)
 if(!before.length)return afterBytes
 const after=await metas(afterBytes,false)
 if(after.length!==before.length||before.some(meta=>!after.some(candidate=>JSON.stringify(candidate)===JSON.stringify(meta))))fail('透视重建改变了控件身份')
 let bytes=afterBytes
 const updates: {previous:Metadata;current:Metadata}[]=[]
 for(const meta of before.filter(meta=>!tablePath||meta.request.tablePath===tablePath)){
  const ctx=await context(bytes,meta.request)
  let current=meta
  if(meta.request.kind==='timeline'){
   const candidate=controlRequest?.name===meta.request.name?upsertPivotControlRequestSchema.parse(controlRequest):undefined
   if(candidate&&(candidate.kind!==meta.request.kind||candidate.tablePath!==meta.request.tablePath||candidate.field!==meta.request.field))fail('时间线更新不能换绑身份')
   if(candidate)current={...meta,request:upsertPivotControlRequestSchema.parse({...meta.request,...candidate,anchor:candidate.anchor??meta.request.anchor})}
   const dates=await timelineDates(bytes,ctx),from=current.request.from!,to=current.request.to!
   const members=ctx.members.filter((_,i)=>dates[i]!<from||dates[i]!>to)
   if(ctx.axis==='page'){
    const hidden=new Set(members),selected=ctx.members.filter(member=>!hidden.has(member))
    const pageFilters=ctx.state.pageFilters?.map(filter=>filter.fieldIndex===ctx.field?{fieldIndex:ctx.field,selected}:filter)
    bytes=await rebuildPivotOutput(bytes,meta.request.tablePath,ctx.cachePath,{...ctx.state,pageFilters})
   }else{
    const manual=[...(ctx.state.manualHiddenMembers??[])].filter(entry=>entry.fieldIndex!==ctx.field)
    manual.push({fieldIndex:ctx.field,members})
    bytes=await rebuildPivotOutput(bytes,meta.request.tablePath,ctx.cachePath,{...ctx.state,manualHiddenMembers:manual})
   }
  }
  updates.push({previous:meta,current})
 }
 // 全部透视重建完成后再恢复原生部件，避免后一个时间线抹掉前一个日期缓存。
 for(const {previous:meta,current} of updates){
  const ctx=await context(bytes,current.request)
  const replaced=new Map<string,string>([[meta.cachePath,await cacheXml(bytes,current,ctx)],[meta.partPath,controlXml(current)]])
  if(drawingAnchor(meta)!==drawingAnchor(current)){const drawing=await ctx.source.readText(meta.drawingPath);replaced.set(meta.drawingPath,drawing.replace(drawingAnchor(meta),()=>drawingAnchor(current)))}
  if(current.request.kind==='timeline')await applyTimelineNative(bytes,current,ctx,replaced)
  bytes=(await assemblePackage(bytes,{replaced,added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[...replaced.keys()]})).buffer
 }
 await metas(bytes)
 return bytes
}

export const removePivotControlRequestSchema=z.object({tablePath:z.string().regex(/^xl\/pivotTables\/[^/]+\.xml$/),name:z.string().regex(/^[A-Za-z_][A-Za-z0-9_]{0,199}$/)}).strict()
export type RemovePivotControlRequest=z.infer<typeof removePivotControlRequestSchema>

/** 删除控件而保留成员选择；同一绘图和透视缓存的其他所有者继续保留。 */
export async function removePivotControl(bytes:Uint8Array,input:RemovePivotControlRequest):Promise<Uint8Array>{
 const request=removePivotControlRequestSchema.parse(input),all=await metas(bytes)
 const meta=all.find(item=>item.request.name===request.name&&item.request.tablePath===request.tablePath)
 if(!meta)fail('要删除的控件不存在或身份已变化')
 const ctx=await context(bytes,meta.request),source=ctx.source,m=modes[meta.request.kind],replaced=new Map<string,string>()
 // 专属部件若被其他关系引用，不能按单一控件所有权删除。
 await assertExclusiveControlReferences(source,meta)
 const removeRel=(xml:string,id:string)=>xml.replace(/<Relationship\b[^>]*\/>/g,tag=>attr(tag,'Id')===id?'':tag)
 const removeRef=(xml:string,id:string)=>xml.replace(`<${m.prefix}:${m.ref} r:id="${id}"/>`,'')
 const cleanList=(xml:string,list:string,uri:string)=>{
  const empty=new RegExp(`<${m.prefix}:${list}\\b[^>]*>\\s*</${m.prefix}:${list}>`)
  const block=xml.match(/<ext\b[^>]*>[\s\S]*?<\/ext>/g)?.find(tag=>attr(tag.match(/^<ext\b[^>]*>/)?.[0]??'','uri')===uri&&empty.test(tag))
  return block?xml.replace(block,''):xml
 }
 let wb=await source.readText('xl/workbook.xml')
 wb=wb.replace(`<${m.prefix}:${m.cacheRef} r:id="${meta.workbookRel}"/>`,'').replace(`<definedName name="${esc(meta.request.name+'_Cache')}">#N/A</definedName>`,'')
 wb=cleanList(wb,m.cacheList,m.workbookUri)
 replaced.set('xl/workbook.xml',wb)
 replaced.set('xl/_rels/workbook.xml.rels',removeRel(await source.readText('xl/_rels/workbook.xml.rels'),meta.workbookRel))
 replaced.set(meta.worksheetPath,cleanList(removeRef(await source.readText(meta.worksheetPath),meta.sheetRel),m.list,m.sheetUri))
 replaced.set(relsPath(meta.worksheetPath),removeRel(await source.readText(relsPath(meta.worksheetPath)),meta.sheetRel))
 replaced.set(meta.drawingPath,(await source.readText(meta.drawingPath)).replace(drawingAnchor(meta),''))
 let types=await source.readText('[Content_Types].xml')
 for(const path of [meta.partPath,meta.cachePath])types=types.replace(/<Override\b[^>]*\/>/g,tag=>attr(tag,'PartName')==='/'+path?'':tag)
 replaced.set('[Content_Types].xml',types)
 if(meta.request.kind==='timeline'){
  const id=100000+ctx.field
  const table=ctx.xml.replace(/<filters\b[^>]*>[\s\S]*?<\/filters>/,block=>{
   const filters=[...block.matchAll(/<filter\b[^>]*>[\s\S]*?<\/filter>/g)].map(match=>match[0]).filter(tag=>attr(tag.match(/^<filter\b[^>]*>/)?.[0]??'','id')!==String(id))
   return filters.length?`<filters count="${filters.length}">${filters.join('')}</filters>`:''
  })
  replaced.set(meta.request.tablePath,table)
  if(!all.some(item=>item!==meta&&item.request.kind==='timeline'&&item.request.tablePath===meta.request.tablePath)){
   replaced.set(ctx.cachePath,ctx.cacheXml.replace(/<ext\b[^>]*>[\s\S]*?<\/ext>/g,block=>block.includes('<x15:timelinePivotCacheDefinition ')?'':block))
  }
 }
 const result=(await assemblePackage(bytes,{replaced,added:new Map(),addedBinary:new Map(),removedEntries:[meta.partPath,meta.cachePath],addedEntries:[],touchedEntries:[...replaced.keys()]})).buffer
 await metas(result)
 return result
}
