/** 固定源 pivot-actions 语义适配；布局与缓存/输出计算全部委托现有 XLSX 引擎。 */
import { readWorkbook, parseAddress, parseRange, formatAddress, type PivotAddition } from '@sheets-web/xlsx-engine'
import { buildPivotLayout, pivotOutputArea, type PivotLayoutValue, type PivotLayoutSpec, type PivotLayoutOptions } from '@sheets-web/xlsx-engine/pivot-layout'
import { pivotHostSheet, readPivotState, resolvePivotTarget } from '@sheets-web/xlsx-engine/pivot-add'
import { createPivotEntrySource } from '@sheets-web/xlsx-engine/pivot-source'
import { decodeXmlText, readXmlAttribute, extractElements, sectionInner } from '@sheets-web/xlsx-engine/xml'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import type { WorkbookOperation } from './workbook-draft'
import { supportsOwnedPivotControls } from '../../../reporting/workbook_engine/packages/xlsx-engine/src/pivot-controls'

export type PivotValue = Omit<PivotLayoutValue,'fieldIndex'|'calcName'> & { field: string }
export interface PivotConfig {
  name: string; sourceTableName?: string; sourceSheetName: string; sourceRange: string; targetSheetName: string; targetCell: string
  rowFields: string[]; columnFields: string[]; values: PivotValue[]
  hiddenMemberFields?: {row:readonly string[];column:readonly string[]}; pageFilters?: PivotLayoutSpec['pageFilters']; groupings?: PivotLayoutSpec['groupings']; filters?: PivotLayoutSpec['filters']; hiddenMembers?: PivotLayoutOptions['hiddenMembers']
}
export interface WorkbookPivot extends PivotConfig {
  tablePath: string; cachePath: string; worksheetPath: string; location: PivotAddition['location']; fieldNames: string[]; readonlyReason?: string
}
const areaRef = (area: PivotAddition['location']) => formatAddress(area.startRow,area.startColumn)+':'+formatAddress(area.endRow,area.endColumn)
const attribute = (tag: string, key: string) => decodeXmlText(readXmlAttribute(tag,key) ?? '')
const builtinFormats:Record<string,string>={'1':'0','2':'0.00','3':'#,##0','4':'#,##0.00','9':'0%','10':'0.00%','11':'0.00E+00','12':'# ?/?','13':'# ??/??','14':'mm-dd-yy','15':'d-mmm-yy','18':'h:mm AM/PM','19':'h:mm:ss AM/PM','20':'h:mm','21':'h:mm:ss'}
const aggregates: Record<string,PivotValue['agg']> = { sum:'sum',count:'count',avg:'average',average:'average',max:'max',min:'min' }

export async function readWorkbookPivots(bytes: Uint8Array): Promise<WorkbookPivot[]> {
  const source=await createPivotEntrySource(bytes),result:WorkbookPivot[]=[],workbook=await readWorkbook(bytes)
  for(const tablePath of (await source.paths()).filter(path=>/^xl\/pivotTables\/[^/]+\.xml$/.test(path))){
    const xml=await source.readText(tablePath), tableTag=xml.match(/<pivotTableDefinition\b[^>]*>/)?.[0] ?? ''
    const host=await pivotHostSheet(source,tablePath), relsPath=tablePath.replace('/pivotTables/','/pivotTables/_rels/')+'.rels'
    const rels=await source.readText(relsPath), cacheRel=extractElements(rels,'Relationship').find(tag=>attribute(tag,'Type').endsWith('/pivotCacheDefinition'))
    if(!cacheRel)throw new Error('透视表缓存关系缺失，不能安全编辑')
    const cachePath=resolvePivotTarget(tablePath,attribute(cacheRel,'Target')), cacheXml=await source.readText(cachePath)
    const state=readPivotState(xml), location=state?.location ?? parseRange(attribute(xml.match(/<location\b[^>]*>/)?.[0] ?? '','ref'))
    const fieldTags=extractElements(sectionInner(cacheXml,'cacheFields') ?? '','cacheField'), fieldNames=state?.fieldNames ?? fieldTags.map(tag=>attribute(tag,'name'))
    const sourceTag=cacheXml.match(/<worksheetSource\b[^>]*>/)?.[0] ?? ''
    const rowFields=state?.rowFieldIndices.map(index=>fieldNames[index]!) ?? extractElements(sectionInner(xml,'rowFields') ?? '','field').map(tag=>Number(attribute(tag,'x'))).filter(index=>index>=0).map(index=>fieldNames[index]!)
    const columnFields=state?.columnFieldIndices?.map(index=>fieldNames[index]!) ?? extractElements(sectionInner(xml,'colFields') ?? '','field').map(tag=>Number(attribute(tag,'x'))).filter(index=>index>=0).map(index=>fieldNames[index]!)
    const values=state?.values.map(value=>({field:value.formula!==undefined?value.calcName!:fieldNames[value.fieldIndex]!,agg:value.agg,...(value.formula!==undefined?{formula:value.formula}:{}),...(value.numFmt?{numFmt:value.numFmt}:{}),...(value.showDataAs?{showDataAs:value.showDataAs}:{})})) ?? extractElements(sectionInner(xml,'dataFields') ?? '','dataField').map(tag=>({field:fieldNames[Number(attribute(tag,'fld'))]!,agg:aggregates[attribute(tag,'subtotal') || 'sum']!,...(builtinFormats[attribute(tag,'numFmtId')]?{numFmt:builtinFormats[attribute(tag,'numFmtId')]}:{}),...(['percentOfTotal','percentOfRow','percentOfCol'].includes(attribute(tag,'showDataAs'))?{showDataAs:attribute(tag,'showDataAs') as PivotValue['showDataAs']}:{})}))
    const unsupported=!state && (Number(attribute(xml.match(/<pageFields\b[^>]*>/)?.[0] ?? '','count'))>0 || /<fieldGroup\b|\bformula=/.test(cacheXml) || /<(?:pivotFilters|filters)\b|<item\b[^>]*\bh="(?:1|true)"/.test(xml) || extractElements(sectionInner(xml,'dataFields') ?? '','dataField').some(tag=>(attribute(tag,'showDataAs')&&!['normal','percentOfTotal','percentOfRow','percentOfCol'].includes(attribute(tag,'showDataAs')))||(attribute(tag,'numFmtId')&&!['0',...Object.keys(builtinFormats)].includes(attribute(tag,'numFmtId')))))
    const pageFilters=state?.pageFilters?.map(({fieldIndex,selected})=>({field:fieldNames[fieldIndex]!,...(selected?{selected:[...selected]}:{})}))
    const groupings=state?.groupings?.map(({fieldIndex,...rule})=>({field:fieldNames[fieldIndex]!,...rule}))
    const filters=state?.filters?.map(filter=>filter.kind==='label'?{...filter,field:fieldNames[filter.field]!}:{...filter,field:fieldNames[filter.field]!,valueIndex:filter.dataField})
    const hiddenMembers=state?{row:state.manualHiddenMembers?state.rowFieldIndices.map(index=>[...(state.manualHiddenMembers!.find(entry=>entry.fieldIndex===index)?.members??[])]):state.rowHiddenItems?.map((items,level)=>items.map(index=>state.rowLevelItems[level]![index]!)),column:state.manualHiddenMembers?(state.columnFieldIndices??[]).map(index=>[...(state.manualHiddenMembers!.find(entry=>entry.fieldIndex===index)?.members??[])]):state.colHiddenItems?.map((items,level)=>items.map(index=>state.colLevelItems![level]![index]!))}:undefined
    const requestedTableName=state?.sourceTableName ?? (attribute(sourceTag,'name')||undefined),tableName=requestedTableName?.toLowerCase()
    const tableSource=tableName?workbook.sheets.flatMap(sheet=>(sheet.tables??[]).filter(table=>table.name.toLowerCase()===tableName||table.displayName.toLowerCase()===tableName).map(table=>({sheet,table})))[0]:undefined
    const sourceTableName=tableSource?.table.name ?? requestedTableName
    const sourceSheetName=tableSource?.sheet.name ?? (attribute(sourceTag,'sheet')||state?.sourceSheetName||''), sourceRange=tableSource?areaRef({...tableSource.table.range,endRow:tableSource.table.range.endRow-tableSource.table.totalsRowCount}):state?areaRef(state.sourceArea):attribute(sourceTag,'ref')
    const readonlyReason=sourceTableName&&!tableSource?'动态透视来源表不存在或无法读取。':unsupported?'该透视表包含报告筛选、分组、计算字段、筛选规则或未支持的显示格式，本次字段编辑不支持保留这些功能。':!sourceSheetName||!sourceRange?'透视表来源不是可解析的本工作簿单元格区域。':values.some(value=>!value.field||!value.agg)?'该透视表使用不支持的值字段或聚合方式。':undefined
    result.push({tablePath,cachePath,worksheetPath:host.path,name:attribute(tableTag,'name'),...(sourceTableName?{sourceTableName}:{}),sourceSheetName,sourceRange,targetSheetName:host.name,targetCell:formatAddress(location.startRow,location.startColumn),location,fieldNames:[...fieldNames],rowFields,columnFields,values,...(pageFilters?.length?{pageFilters}:{}),...(groupings?.length?{groupings}:{}),...(filters?.length?{filters}:{}),...(hiddenMembers?{hiddenMembers,hiddenMemberFields:{row:[...rowFields],column:[...columnFields]}}:{}),...(readonlyReason?{readonlyReason}:{})})
  }
  if((await source.paths()).some(path=>/^xl\/(?:slicerCaches|timelineCaches|slicers|timelines)\//i.test(path)) && !await supportsOwnedPivotControls(bytes))for(const pivot of result)pivot.readonlyReason='工作簿含现有 Excel 切片器/时间线控件，当前入口无法同步其控件状态，请在 Excel 中编辑。'
  return result
}
async function additionFor(bytes:Uint8Array,config:PivotConfig):Promise<PivotAddition>{
  if(!config.name.trim()||!config.rowFields.length||!config.values.length||config.values.length>8)throw new Error('请填写名称，至少选择一个行字段和1至8个值字段')
  if(config.values.some(value=>value.numFmt && !Object.values(builtinFormats).includes(value.numFmt.trim())))throw new Error('值字段数字格式暂仅支持常用Excel内置格式，例如0.00、#,##0.00、0.00%')
  const workbook=await readWorkbook(bytes),sheet=workbook.sheets.find(sheet=>sheet.name===config.sourceSheetName)
  if(!sheet||!workbook.sheets.some(sheet=>sheet.name===config.targetSheetName))throw new Error('透视表来源或目标工作表不存在')
  const tableName=config.sourceTableName?.toLowerCase(),table=tableName?(sheet.tables??[]).find(table=>table.name.toLowerCase()===tableName||table.displayName.toLowerCase()===tableName):undefined
  if(config.sourceTableName&&(!table||table.headerRowCount!==1))throw new Error('动态透视来源表不存在或没有单行表头')
  const sourceArea=table?{...table.range,endRow:table.range.endRow-table.totalsRowCount}:parseRange(config.sourceRange),anchor=parseAddress(config.targetCell)
  if(sourceArea.endRow-sourceArea.startRow>10000||sourceArea.endColumn-sourceArea.startColumn>=200)throw new Error('透视表来源最多10000条数据、200列')
  const grid=[]
  for(let row=sourceArea.startRow;row<=sourceArea.endRow;row++){const values=[];for(let column=sourceArea.startColumn;column<=sourceArea.endColumn;column++)values.push(sheet.cells[formatAddress(row,column)]?.value ?? null);grid.push(values)}
  const hiddenByField=new Map<string,readonly string[]>()
  for(const axis of ['row','column'] as const){const names=config.hiddenMemberFields?.[axis]??(axis==='row'?config.rowFields:config.columnFields);names.forEach((field,index)=>{const hidden=config.hiddenMembers?.[axis]?.[index];if(hidden)hiddenByField.set(field,hidden)})}
  const hiddenMembers=config.hiddenMembers?{row:config.rowFields.map(field=>hiddenByField.get(field)??[]),column:config.columnFields.map(field=>hiddenByField.get(field)??[])}:undefined
  const dimensions=new Set([...config.rowFields,...config.columnFields])
  const date1904=['1','true'].includes(readXmlAttribute((await (await createPivotEntrySource(bytes)).readText('xl/workbook.xml')).match(/<workbookPr\b[^>]*>/)?.[0]??'','date1904')??'')
  const groupings=config.groupings?.filter(rule=>dimensions.has(rule.field)).map(rule=>rule.kind==='date'?{...rule,date1904}:rule),filters=config.filters?.filter(rule=>dimensions.has(rule.field))
  const layout=buildPivotLayout(grid,{rowFields:config.rowFields,columnField:config.columnFields,values:config.values,pageFilters:config.pageFilters,groupings,filters},{subtotal:'小计',grandTotal:'总计'},{hiddenMembers})
  const definition=layout.definition
  return {worksheetSheetName:config.targetSheetName,...(table?{sourceTableName:table.name}:{}),sourceSheetName:config.sourceSheetName,sourceArea,name:config.name.trim(),location:pivotOutputArea(anchor,layout),
    fieldNames:definition.fieldNames,rowFieldIndices:definition.rowFieldIndices,columnFieldIndices:definition.columnFieldIndices ?? [],rowLevelItems:definition.rowLevelItems,rowLines:definition.rowLines,colLevelItems:definition.colLevelItems ?? (definition.columnItems?[definition.columnItems]:[]),colLines:definition.colLines ?? [],values:definition.values,
    ...(definition.manualHiddenMembers?{manualHiddenMembers:definition.manualHiddenMembers}:{}),
    ...(definition.pageFilters?{pageFilters:definition.pageFilters}:{}),
    ...(definition.pageLevelItems?{pageLevelItems:definition.pageLevelItems}:{}),
    ...(definition.pageHiddenItems?{pageHiddenItems:definition.pageHiddenItems}:{}),
    ...(definition.groupings?{groupings:definition.groupings}:{}),
    ...(definition.filters?{filters:definition.filters}:{}),
    ...(definition.rowHiddenItems?{rowHiddenItems:definition.rowHiddenItems}:{}),
    ...(definition.colHiddenItems?{colHiddenItems:definition.colHiddenItems}:{})}
}
export async function createPivotPlan(bytes:Uint8Array,config:PivotConfig){
  const addition=await additionFor(bytes,config),operation:WorkbookOperation={kind:'addPivot',addition}
  // 真实完整文件预演也负责来源/输出重叠、已有内容、包关系和预算校验；失败不返回可提交计划。
  await applyWorkbookOperations(bytes,[operation])
  return {operation,operations:[operation],addition}
}
export async function editPivotPlan(bytes:Uint8Array,tablePath:string,config:PivotConfig){
  const pivot=(await readWorkbookPivots(bytes)).find(pivot=>pivot.tablePath===tablePath)
  if(!pivot||pivot.readonlyReason)throw new Error(pivot?.readonlyReason ?? '所选透视表已经变化')
  if(config.targetSheetName!==pivot.targetSheetName||config.targetCell.toUpperCase()!==pivot.targetCell)throw new Error('编辑现有透视表不能移动目标锚点')
  if(config.name!==pivot.name)throw new Error('编辑现有透视表不能更换名称')
  const addition=await additionFor(bytes,config),{worksheetSheetName:_host,name:_name,location,...relayout}=addition
  const operation:WorkbookOperation={kind:'applyPivotLayoutExpansions',updates:[{tablePath:pivot.tablePath,cachePath:pivot.cachePath,worksheetPath:pivot.worksheetPath,newOutputRef:areaRef(location),relayout}]}
  const operations:WorkbookOperation[]=[operation]
  await applyWorkbookOperations(bytes,operations)
  return {operation,operations,addition}
}

/** 全部预演成功才返回操作；刷新实际输出、缓存和位置，不能仅设置 Excel 打开时刷新。 */
export async function refreshWorkbookPivotsPlan(bytes:Uint8Array){
  const pivots=await readWorkbookPivots(bytes)
  if(!pivots.length)throw new Error('当前工作簿没有可刷新的数据透视表')
  const unsupported=pivots.find(pivot=>pivot.readonlyReason)
  if(unsupported)throw new Error(`无法刷新透视表“${unsupported.name}”：${unsupported.readonlyReason}`)
  const workbook=await readWorkbook(bytes),entries=await createPivotEntrySource(bytes)
  for(const pivot of pivots){
    const source=workbook.sheets.find(sheet=>sheet.name===pivot.sourceSheetName),area=parseRange(pivot.sourceRange)
    if(!source)throw new Error(`透视表来源工作表“${pivot.sourceSheetName}”不存在`)
    for(const [address,cell] of Object.entries(source.cells)){
      if(cell.formula===undefined)continue
      const position=parseAddress(address)
      if(position.row>=area.startRow&&position.row<=area.endRow&&position.column>=area.startColumn&&position.column<=area.endColumn)
        throw new Error(`无法刷新透视表“${pivot.name}”：当前入口无法确认公式结果为最新值，请先将来源计算结果转换为值`)
    }
    // 模型不暴露共享公式的自闭合 follower；原始单元格中的 f 也必须检查。
    for(const cell of (await entries.readText(source.path)).matchAll(/<c\b[^>]*?(?:\/>|>[\s\S]*?<\/c>)/g)){
      if(!/<f(?:\s|>)/.test(cell[0]))continue
      const address=readXmlAttribute(cell[0].match(/^<c\b[^>]*>/)?.[0]??'','r')
      if(!address)continue
      const position=parseAddress(address)
      if(position.row>=area.startRow&&position.row<=area.endRow&&position.column>=area.startColumn&&position.column<=area.endColumn)
        throw new Error(`无法刷新透视表“${pivot.name}”：当前入口无法确认公式结果为最新值，请先将来源计算结果转换为值`)
    }
  }
  const operations:WorkbookOperation[]=[]
  let preview=bytes
  for(const pivot of pivots){
    const latest=(await readWorkbookPivots(preview)).find(item=>item.tablePath===pivot.tablePath)!
    const plan=await editPivotPlan(preview,pivot.tablePath,latest)
    preview=await applyWorkbookOperations(preview,plan.operations)
    operations.push(...plan.operations)
  }
  return {operations,count:pivots.length}
}
