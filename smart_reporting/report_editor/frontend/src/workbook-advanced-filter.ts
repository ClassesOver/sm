import {BooleanNumber,CommandType,ICommandService,IUndoRedoService,generateRandomId} from '@univerjs/core'
import {SheetsSelectionsService,expandToContinuousRange,isSingleCellSelection} from '@univerjs/sheets'
import {SheetsFilterService,SetSheetFilterRangeCommand,SetSheetsFilterCriteriaCommand,SetSheetsFilterCriteriaMutation,RemoveSheetsFilterMutation} from '@univerjs/sheets-filter'
import {columnLabel} from '@sheets-web/xlsx-engine'

export interface AdvancedFilterRange {startRow:number;endRow:number;startColumn:number;endColumn:number}
export type AdvancedFilterOperator='equal'|'notEqual'|'greaterThan'|'greaterThanOrEqual'|'lessThan'|'lessThanOrEqual'
export interface AdvancedFilterInput {colId:number;operator1:AdvancedFilterOperator;value1:string;operator2?:AdvancedFilterOperator;value2?:string;and?:boolean}
export interface AdvancedFilterTarget {
 unitId:string;sheetId:string;workbookCore:any;sheetCore:any;range:AdvancedFilterRange;revision:number;snapshotSignature:string;selectionSignature:string;filterSignature:string
 fields:{colId:number;label:string}[]
}
export interface AdvancedFilterPlan {filter:{range:AdvancedFilterRange;columns:{colId:number;values?:string[];blank?:boolean;customs?:{and?:boolean;filters:{operator?:AdvancedFilterOperator;val:string}[]}}[]}}
export interface AdvancedFilterOptions {
 readonly?:()=>boolean;protectedSheet?:(sheetId:string)=>boolean
 preflight:(target:AdvancedFilterTarget,plan:AdvancedFilterPlan)=>void|Promise<void>
 captureMetadata:()=>unknown;restoreMetadata:(snapshot:unknown,phase?:'rollback'|'history')=>void;transaction?:(active:boolean)=>void
}
const operators=['equal','notEqual','greaterThan','greaterThanOrEqual','lessThan','lessThanOrEqual']
const area=(range:any):AdvancedFilterRange=>({startRow:range.startRow,endRow:range.endRow,startColumn:range.startColumn,endColumn:range.endColumn})
export function installAdvancedFilter(runtime:any,options:AdvancedFilterOptions){
 const injector=runtime.univer.__getInjector(),commands=injector.get(ICommandService),history=injector.get(IUndoRedoService),filters=injector.get(SheetsFilterService),selections=injector.get(SheetsSelectionsService)
 const owned=new WeakSet<object>(),stateId=`sheet.mutation.native-advanced-filter-state-${generateRandomId()}`
 let disposed=false,running=false
 const revisions=new Map<string,number>()
 const listener=commands.onCommandExecuted((command:any)=>{if(command.type===CommandType.MUTATION && command.id!=='sheet.mutation.mark-dirty-filter-change' && command.params?.unitId)revisions.set(command.params.unitId,(revisions.get(command.params.unitId)??0)+1)})
 const registration=commands.registerCommand({id:stateId,type:CommandType.MUTATION,handler:(_accessor:unknown,params:any)=>{
  if(!params||!owned.has(params))return false
  const book=runtime.univerAPI.getWorkbook(params.target.unitId),sheet=book?.getSheetBySheetId(params.target.sheetId)
  if(book?.getWorkbook()!==params.target.workbookCore||sheet?.getSheet()!==params.target.sheetCore)return false
  options.restoreMetadata(params.metadata,'history');return true
 }})
 const model=(target:{unitId:string;sheetId:string})=>filters.getFilterModel(target.unitId,target.sheetId)
 const signature=(book:any)=>JSON.stringify(book.save())
 const selectionSignature=()=>JSON.stringify(selections.getCurrentLastSelection()?.range)
 const editable=(id:string)=>{
  if(disposed)throw new Error('高级筛选已关闭')
  if(options.readonly?.())throw new Error('只读工作簿不能筛选')
  if(options.protectedSheet?.(id))throw new Error('工作表受保护，请先撤销保护')
 }
 const sourceRange=(sheet:any,current:any)=>{
  const last=selections.getCurrentLastSelection(),selected=last?.range
  if(current)return area(current.getRange())
  if(!last)throw new Error('请先选择包含表头的数据区域')
  return area(isSingleCellSelection(last)?expandToContinuousRange(selected,{left:true,right:true,up:true,down:true},sheet.getSheet()):selected.startRow===selected.endRow?expandToContinuousRange(selected,{down:true},sheet.getSheet()):selected)
 }
 const validate=(target:AdvancedFilterTarget)=>{
  editable(target.sheetId)
  const book=runtime.univerAPI.getActiveWorkbook(),sheet=book?.getActiveSheet()
  if(book?.getWorkbook()!==target.workbookCore||sheet?.getSheet()!==target.sheetCore||JSON.stringify(sourceRange(sheet,model(target)))!==JSON.stringify(target.range)||(revisions.get(target.unitId)??0)!==target.revision||signature(book)!==target.snapshotSignature||selectionSignature()!==target.selectionSignature||JSON.stringify(model(target)?.serialize()??null)!==target.filterSignature)throw new Error('筛选来源或选区已变化，请重新打开对话框')
  return {book,sheet}
 }
 return {
  isRunning:()=>running,ownsMutation:(params:object)=>owned.has(params),
  capture():AdvancedFilterTarget{
   const book=runtime.univerAPI.getActiveWorkbook(),sheet=book?.getActiveSheet(),last=selections.getCurrentLastSelection()
   if(!book||!sheet)throw new Error('请先选择包含表头的数据区域')
   editable(sheet.getSheetId())
   const current=filters.getFilterModel(book.getId(),sheet.getSheetId())
   if(!current&&!last)throw new Error('请先选择包含表头的数据区域')
   // 与固定Univer smart-toggle完全相同的只读范围推导，打开时不执行create命令。
   const range=sourceRange(sheet,current)
   if(!Object.values(range).every(Number.isSafeInteger)||range.startRow<0||range.endRow<=range.startRow||range.endRow>=1048576||range.startColumn<0||range.endColumn<range.startColumn||range.endColumn>=16384)throw new Error('请选择包含表头和明细的数据区域')
   return {unitId:book.getId(),sheetId:sheet.getSheetId(),workbookCore:book.getWorkbook(),sheetCore:sheet.getSheet(),range,revision:revisions.get(book.getId())??0,snapshotSignature:signature(book),selectionSignature:selectionSignature(),filterSignature:JSON.stringify(current?.serialize()??null),fields:Array.from({length:range.endColumn-range.startColumn+1},(_,colId)=>({colId,label:String(sheet.getRange(range.startRow,range.startColumn+colId).getValue()??columnLabel(range.startColumn+colId))}))}
  },
  async apply(target:AdvancedFilterTarget,input:AdvancedFilterInput):Promise<AdvancedFilterPlan>{
   if(running)throw new Error('高级筛选正在执行')
   validate(target)
   if(!Number.isSafeInteger(input.colId)||input.colId<0||input.colId>target.range.endColumn-target.range.startColumn)throw new Error('筛选字段不在来源区域内')
   if(!operators.includes(input.operator1)||typeof input.value1!=='string'||input.value1==='')throw new Error('请填写第一筛选条件')
   if(input.and!==undefined&&typeof input.and!=='boolean')throw new Error('筛选连接方式无效')
   if(input.value2!==undefined&&typeof input.value2!=='string')throw new Error('第二筛选条件值无效')
   if(input.value1.length>32767||(input.value2?.length??0)>32767)throw new Error('筛选条件值超过长度限制')
   if(input.value2&&(!input.operator2||!operators.includes(input.operator2)))throw new Error('第二筛选运算符无效')
   const custom=(operator:AdvancedFilterOperator,val:string)=>({...operator!=='equal'?{operator}:{},val})
   const customFilters=[custom(input.operator1,input.value1),...(input.value2?[custom(input.operator2!,input.value2)]:[])],col=target.range.startColumn+input.colId
   const criteria={colId:col,customFilters:{...(customFilters.length===2&&input.and?{and:BooleanNumber.TRUE}:{}),customFilters}}
   const existing=model(target)?.serialize(),columns:AdvancedFilterPlan['filter']['columns']=(existing?.filterColumns??[]).filter((entry:any)=>entry.colId!==col).map((entry:any)=>{
    if(entry.colorFilters)throw new Error('来源筛选条件暂不支持编辑回写')
    return {colId:entry.colId-target.range.startColumn,...entry.filters?.filters?{values:[...entry.filters.filters]}:{},...entry.filters?.blank?{blank:true}:{},...entry.customFilters?{customs:{...(entry.customFilters.and?{and:true}:{}),filters:entry.customFilters.customFilters.map((item:any)=>({...item,val:String(item.val)}))}}:{}}
   })
   columns.push({colId:input.colId,customs:{...(customFilters.length===2&&input.and?{and:true}:{}),filters:customFilters}});columns.sort((a,b)=>a.colId-b.colId)
   if(columns.length>1000)throw new Error('筛选条件列数超过保存上限')
   const plan:AdvancedFilterPlan={filter:{range:{...target.range},columns}}
   running=true
   try{
    await options.preflight(target,plan);validate(target);options.transaction?.(true)
    const beforeMetadata=options.captureMetadata(),beforeCriteria=model(target)?.getFilterColumn(col)?.serialize()??null,beforeRows=existing?.cachedFilteredOut
    const stacks=[history._undoStacks,history._redoStacks].map((map:Map<string,any[]>)=>({map,stack:map.get(target.unitId),items:map.get(target.unitId)?.slice()}))
    const descriptor=Object.getOwnPropertyDescriptor(history,'pushUndoRedo'),push=history.pushUndoRedo.bind(history),item={unitID:target.unitId,id:generateRandomId(),undoMutations:[] as any[],redoMutations:[] as any[]}
    const restorePush=()=>{if(descriptor)Object.defineProperty(history,'pushUndoRedo',descriptor);else Reflect.deleteProperty(history,'pushUndoRedo')}
    Object.defineProperty(history,'pushUndoRedo',{configurable:true,value:(part:any)=>{if(part.unitID!==target.unitId){push(part);return}item.undoMutations.unshift(...part.undoMutations);item.redoMutations.push(...part.redoMutations)}})
    const execute=(id:string,params:any)=>{owned.add(params);if(!commands.syncExecuteCommand(id,params))throw new Error('筛选命令未执行，修改已撤销')}
    try{
     if(!existing)execute(SetSheetFilterRangeCommand.id,{unitId:target.unitId,subUnitId:target.sheetId,range:{...target.range}})
     execute(SetSheetsFilterCriteriaCommand.id,{unitId:target.unitId,subUnitId:target.sheetId,col,criteria})
     const hiddenRows=new Set<number>(model(target)?.filteredOutRows??[])
     for(const [row,data] of Object.entries(target.sheetCore.getRowManager().getRowData()) as [string,any][]){const index=Number(row);if(data?.hd&&index>target.range.startRow&&index<=target.range.endRow)hiddenRows.add(index)}
     if(hiddenRows.size>100000)throw new Error('筛选隐藏行超过保存上限，请缩小区域')
     const metadataMutation=(metadata:unknown)=>{const params={target,metadata};owned.add(params);return {id:stateId,params}}
     item.undoMutations.push(metadataMutation(beforeMetadata));item.redoMutations.push(metadataMutation(options.captureMetadata()))
     restorePush();history.pushUndoRedo(item)
    }catch(error){
     // 即使mutation监听器在官方history push之前抛错，也直接以原生mutation恢复旧条件。
     try{
      if(!existing){if(model(target))execute(RemoveSheetsFilterMutation.id,{unitId:target.unitId,subUnitId:target.sheetId})}
      else {execute(SetSheetsFilterCriteriaMutation.id,{unitId:target.unitId,subUnitId:target.sheetId,col,criteria:beforeCriteria});if(beforeRows)model(target).filteredOutRows=new Set(beforeRows)}
     }finally{
      options.restoreMetadata(beforeMetadata,'rollback')
      for(const {map,stack,items} of stacks){if(stack){stack.splice(0,stack.length,...items!);map.set(target.unitId,stack)}else map.delete(target.unitId)}history._updateStatus()
     }
     throw error
    }finally{restorePush()}
    return plan
   }finally{options.transaction?.(false);running=false}
  },
  dispose(){disposed=true;listener.dispose();registration.dispose()},
 }
}
