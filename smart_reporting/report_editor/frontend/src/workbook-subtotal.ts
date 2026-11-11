import { CommandType, Direction, ICommandService, IUndoRedoService, generateRandomId } from '@univerjs/core'
import { InsertRowMutationUndoFactory, SetRangeValuesUndoMutationFactory } from '@univerjs/sheets'
import { columnLabel } from '@sheets-web/xlsx-engine'
import { readWorkbookOutline } from './workbook-outline'

export interface SubtotalRange { startRow: number; endRow: number; startColumn: number; endColumn: number }
export interface SubtotalInput { groupCol: number; valueCol: number; agg: 'sum' | 'count' | 'average' }
export interface SubtotalPlan {
  range: SubtotalRange
  input: SubtotalInput
  groups: { startRow: number; endRow: number; label: string; subtotalRow: number }[]
  inserts: number[]
  cells: { row: number; column: number; value?: string; formula?: string }[]
  outline: { summaryBelow: true; rows: { row: number; level: number }[] }
  addedRows: number
  grandTotalRow: number
}
export interface SubtotalTarget {
  unitId: string; sheetId: string; workbookCore: any; sheetCore: any
  range: SubtotalRange; snapshotSignature: string; revision: number
  fields: { column: number; label: string }[]
}
export interface SubtotalOptions {
  readonly?: () => boolean
  protectedSheet?: (sheetId: string) => boolean
  preflight: (target: SubtotalTarget, plan: SubtotalPlan) => void | Promise<void>
  captureMetadata: () => unknown
  transaction?: (active: boolean) => void
  restoreMetadata: (snapshot: unknown, phase?: 'rollback' | 'history') => void
}
const KEY = 'genofficeOutline'
function validateInput(range: SubtotalRange, input: SubtotalInput) {
  const { startRow, endRow, startColumn, endColumn } = range
  if (![startRow,endRow,startColumn,endColumn].every(Number.isSafeInteger) || startRow < 0 || endRow <= startRow || endRow >= 1048576 || startColumn < 0 || endColumn <= startColumn || endColumn >= 16384) throw new Error('请选择包含表头和明细的至少两列区域')
  if (![input.groupCol,input.valueCol].every(c => Number.isSafeInteger(c) && c >= startColumn && c <= endColumn) || input.groupCol === input.valueCol) throw new Error('分组列和值列必须是选区内不同的列')
  if (!['sum','count','average'].includes(input.agg)) throw new Error('分类汇总函数无效')
}
export function planSubtotal(range: SubtotalRange, values: unknown[][], input: SubtotalInput): SubtotalPlan {
  validateInput(range,input)
  const {startRow,endRow,startColumn}=range
  if (values.length !== endRow - startRow + 1) throw new Error('分类汇总数据与选区不匹配')
  const raw: {startRow:number;endRow:number;label:string}[] = []
  for (let row = startRow + 1; row <= endRow; row++) {
    const label = String(values[row - startRow]?.[input.groupCol - startColumn] ?? '')
    const previous = raw.at(-1)
    if (previous?.label === label) previous.endRow = row
    else raw.push({startRow:row,endRow:row,label})
  }
  if (raw.length > 200) throw new Error('分类汇总最多支持200个相邻分组，请先排序或缩小选区')
  const addedRows = raw.length + 1, grandTotalRow = endRow + addedRows
  if (grandTotalRow >= 1048576) throw new Error('分类汇总插行后超出工作表边界')
  const groups = raw.map((group,index) => ({...group,startRow:group.startRow + index,endRow:group.endRow + index,subtotalRow:group.endRow + index + 1}))
  const code = {sum:9,count:3,average:1}[input.agg], col = columnLabel(input.valueCol)
  const cells: SubtotalPlan['cells'] = [], rows: SubtotalPlan['outline']['rows'] = []
  for (const group of groups) {
    cells.push({row:group.subtotalRow,column:input.groupCol,value:`${group.label} Total`},{row:group.subtotalRow,column:input.valueCol,formula:`=SUBTOTAL(${code},$${col}$${group.startRow+1}:$${col}$${group.endRow+1})`})
    for (let row = group.startRow; row <= group.endRow; row++) rows.push({row,level:2})
    rows.push({row:group.subtotalRow,level:1})
  }
  cells.push({row:grandTotalRow,column:input.groupCol,value:'Grand Total'},{row:grandTotalRow,column:input.valueCol,formula:`=SUBTOTAL(${code},$${col}$${startRow+2}:$${col}$${grandTotalRow})`})
  return {range:{...range},input:{...input},groups,inserts:[...raw].reverse().map(group=>group.endRow+1).concat(grandTotalRow),cells,outline:{summaryBelow:true,rows},addedRows,grandTotalRow}
}

// 原生公开batch会在首次push清空redo；先收集官方历史，成功后一次push才能保留失败前的redo。
export function installSubtotal(runtime: any, options: SubtotalOptions) {
  const injector = runtime.univer.__getInjector(), commands = injector.get(ICommandService), history = injector.get(IUndoRedoService)
  const stateId = `sheet.mutation.native-subtotal-state-${generateRandomId()}`, owned = new WeakSet<object>()
  let revision = 0, disposed = false, running = false
  const listener = commands.onCommandExecuted((command: any) => { if (command.type === CommandType.MUTATION) revision++ })
  const registration = commands.registerCommand({id:stateId,type:CommandType.MUTATION,handler:(_accessor:unknown,params:any)=>{
    if (!params || !owned.has(params)) return false
    const book = runtime.univerAPI.getActiveWorkbook(), sheet = book?.getSheetBySheetId(params.target.sheetId)
    if (book?.getWorkbook() !== params.target.workbookCore || sheet?.getSheet() !== params.target.sheetCore) return false
    restoreOutline(sheet,params.outline)
    options.restoreMetadata(params.metadata,'history')
    return true
  }})
  const signature = (book: any) => JSON.stringify(book.save())
  const selection = (book: any) => book?.getActiveRange()?.getRange()
  const editable = (id:string) => {
    if (disposed) throw new Error('分类汇总已关闭')
    if (options.readonly?.()) throw new Error('只读工作簿不能分类汇总')
    if (options.protectedSheet?.(id)) throw new Error('工作表受保护，请先撤销保护')
  }
  const validate = (target:SubtotalTarget) => {
    editable(target.sheetId)
    const book = runtime.univerAPI.getActiveWorkbook(), sheet = book?.getActiveSheet(), current = selection(book)
    if (book?.getWorkbook() !== target.workbookCore || sheet?.getSheet() !== target.sheetCore || revision !== target.revision || signature(book) !== target.snapshotSignature || !current || ['startRow','endRow','startColumn','endColumn'].some(key=>current[key] !== target.range[key as keyof SubtotalRange])) throw new Error('分类汇总来源或选区已变化，请重新打开对话框')
    return {book,sheet}
  }
  return {
    isRunning:()=>running,
    ownsMutation:(params:object)=>owned.has(params),
    capture():SubtotalTarget {
      const book = runtime.univerAPI.getActiveWorkbook(), sheet = book?.getActiveSheet(), range = selection(book)
      if (!sheet || !range) throw new Error('请先选择包含表头的数据区域')
      editable(sheet.getSheetId())
      const area:SubtotalRange = {startRow:range.startRow,endRow:range.endRow,startColumn:range.startColumn,endColumn:range.endColumn}
      if (area.endRow <= area.startRow || area.endColumn <= area.startColumn) throw new Error('请选择包含表头和明细的至少两列区域')
      return {unitId:book.getId(),sheetId:sheet.getSheetId(),workbookCore:book.getWorkbook(),sheetCore:sheet.getSheet(),range:area,snapshotSignature:signature(book),revision,
        fields:Array.from({length:area.endColumn-area.startColumn+1},(_,index)=>({column:area.startColumn+index,label:String(sheet.getRange(area.startRow,area.startColumn+index).getValue()??columnLabel(area.startColumn+index))}))}
    },
    async apply(target:SubtotalTarget,input:SubtotalInput):Promise<SubtotalPlan> {
      if (running) throw new Error('分类汇总正在执行')
      let {book,sheet} = validate(target)
      validateInput(target.range,input)
      const values:unknown[][]=[]
      let groupCount=0, previousLabel:string|undefined
      for(let sourceRow=target.range.startRow;sourceRow<=target.range.endRow;sourceRow++){
        const row:unknown[]=[],value=sheet.getSheet().getCell(sourceRow,input.groupCol)?.v
        if(sourceRow>target.range.startRow){const label=String(value??'');if(label!==previousLabel && ++groupCount>200)throw new Error('分类汇总最多支持200个相邻分组，请先排序或缩小选区');previousLabel=label}
        row[input.groupCol-target.range.startColumn]=value;values.push(row)
      }
      const plan = planSubtotal(target.range,values,input)
      if (sheet.getMaxRows() + plan.addedRows > 1048576) throw new Error('分类汇总插行后超出工作表行数上限')
      const outline = readWorkbookOutline(sheet)
      if ([...outline.rows].some(([row])=>row>=target.range.startRow && row<=target.range.endRow)) throw new Error('所选区域已有行分组，请先清除分组')
      sheet.getSheet().getCellMatrix().forValue((row:number,column:number,cell:any)=>{if(row>=target.range.startRow&&row<=target.range.endRow&&column>=target.range.startColumn&&column<=target.range.endColumn&&/\bSUBTOTAL\s*\(/i.test(cell?.f??''))throw new Error('所选区域已包含分类汇总公式')})
      if (sheet.getSheet().getMergeData().some((merge:SubtotalRange)=>merge.startRow<=target.range.endRow && merge.endRow>=target.range.startRow)) throw new Error('所选行包含合并单元格，请先取消合并')
      running = true
      try {
        await options.preflight(target,plan)
        ;({book,sheet}=validate(target))
        options.transaction?.(true)
        const before = {outline:captureOutline(sheet),metadata:options.captureMetadata()}, item = {unitID:target.unitId,id:generateRandomId(),undoMutations:[] as any[],redoMutations:[] as any[]}
        // 固定Univer 0.25.1公开API没有恢复redo的能力；仅备份当前unit的官方stack元素身份。
        const undoStack=history._undoStacks.get(target.unitId), redoStack=history._redoStacks.get(target.unitId)
        const previousUndo=undoStack?.slice(), previousRedo=redoStack?.slice()
        const restoreHistory=()=>{
          const restore=(map:Map<string,any[]>,original:any[]|undefined,contents:any[]|undefined)=>{
            if(original){original.splice(0,original.length,...contents!);map.set(target.unitId,original)}else map.delete(target.unitId)
          }
          restore(history._undoStacks,undoStack,previousUndo);restore(history._redoStacks,redoStack,previousRedo)
          history._updateStatus()
        }
        let partial: any[] = []
        const pushDescriptor = Object.getOwnPropertyDescriptor(history,'pushUndoRedo'), originalPush = history.pushUndoRedo.bind(history), execute = commands.syncExecuteCommand.bind(commands)
        Object.defineProperty(history,'pushUndoRedo',{configurable:true,value:(part:any) => {
          // 文档编辑器等其它unit共用本服务，其历史必须由官方服务独立保存。
          if (part.unitID !== target.unitId) { originalPush(part); return }
          item.undoMutations.unshift(...part.undoMutations);item.redoMutations.push(...part.redoMutations)
        }})
        // mutation回调可在底层已修改、官方history尚未push时抛错。
        let attempted: { inverse:any; signature:string }[] = []
        const mutationSignature=()=>signature(book)
        const beforeMutation=commands.beforeCommandExecuted((command:any)=>{
          const {id,params}=command
          if (params?.unitId !== target.unitId) return
          const inverse=id==='sheet.mutation.insert-row'
            ? {id:'sheet.mutation.remove-rows',params:injector.invoke(InsertRowMutationUndoFactory,params)}
            : id==='sheet.mutation.set-range-values' ? {id,params:injector.invoke(SetRangeValuesUndoMutationFactory,params)} : undefined
          if(inverse){attempted.push({inverse,signature:mutationSignature()})}
        })
        const run = (id:string,params:any) => {
          partial=[];attempted=[]
          const beforeLength=item.undoMutations.length
          try {if(!commands.syncExecuteCommand(id,params))throw new Error('分类汇总命令未执行，修改已撤销')}
          catch(error) {if(item.undoMutations.length===beforeLength){partial=attempted.filter(entry=>entry.signature!==mutationSignature()).map(entry=>entry.inverse).reverse();item.undoMutations.unshift(...partial)}throw error}
        }
        try {
          for (const row of plan.inserts) run('sheet.command.insert-row-by-range',{unitId:target.unitId,subUnitId:target.sheetId,range:{startRow:row,endRow:row,startColumn:0,endColumn:sheet.getMaxColumns()-1},direction:Direction.UP})
          const value:Record<number,Record<number,any>> = {}
          for(const cell of plan.cells)(value[cell.row]??={})[cell.column]={v:cell.value??null,f:cell.formula??null,p:null,s:{bl:1}}
          run('sheet.command.set-range-values',{unitId:target.unitId,subUnitId:target.sheetId,range:{...target.range,endRow:plan.grandTotalRow},value})
          const manager = sheet.getSheet().getRowManager()
          for(const {row,level} of plan.outline.rows){manager.getRowOrCreate(row);manager.setCustomMetadata(row,{...manager.getCustomMetadata(row),[KEY]:{level,collapsed:false}})}
          const custom = sheet.getSheet().getCustomMetadata()
          sheet.getSheet().setCustomMetadata({...custom,[KEY]:{...custom?.[KEY],summaryBelow:true}})
          const after = {outline:captureOutline(sheet),metadata:options.captureMetadata()}
          const mutation = (state:typeof before) => {const params={target,...state};owned.add(params);return {id:stateId,params}}
          item.undoMutations.push(mutation(before));item.redoMutations.push(mutation(after))
          if(pushDescriptor)Object.defineProperty(history,'pushUndoRedo',pushDescriptor);else Reflect.deleteProperty(history,'pushUndoRedo')
          history.pushUndoRedo(item)
        } catch(error) {
          beforeMutation.dispose()
          for(const mutation of item.undoMutations)execute(mutation.id,mutation.params,{fromCollab:false})
          restoreOutline(sheet,before.outline);options.restoreMetadata(before.metadata,'rollback');restoreHistory()
          throw error
        } finally {beforeMutation.dispose();if(pushDescriptor)Object.defineProperty(history,'pushUndoRedo',pushDescriptor);else Reflect.deleteProperty(history,'pushUndoRedo')}
        return plan
      } finally {options.transaction?.(false);running=false}
    },
    dispose(){disposed=true;listener.dispose();registration.dispose()},
  }
}
function captureOutline(sheet:any) {
  const manager=sheet.getSheet().getRowManager()
  return {custom:structuredClone(sheet.getSheet().getCustomMetadata()?.[KEY]),rows:Object.fromEntries(Object.entries(manager.getRowData()).filter(([,value]:any)=>value?.custom?.[KEY]).map(([row,value]:any)=>[row,structuredClone(value.custom[KEY])]))}
}
function restoreOutline(sheet:any,snapshot:ReturnType<typeof captureOutline>) {
  const manager=sheet.getSheet().getRowManager()
  for(const [row,value] of Object.entries(manager.getRowData()) as [string,any][]){if(value?.custom?.[KEY]){const custom={...manager.getCustomMetadata(Number(row))};delete custom[KEY];manager.setCustomMetadata(Number(row),custom)}}
  for(const [row,entry] of Object.entries(snapshot.rows)){manager.getRowOrCreate(Number(row));manager.setCustomMetadata(Number(row),{...manager.getCustomMetadata(Number(row)),[KEY]:structuredClone(entry)})}
  const custom={...sheet.getSheet().getCustomMetadata()}; if(snapshot.custom===undefined)delete custom[KEY];else custom[KEY]=structuredClone(snapshot.custom);sheet.getSheet().setCustomMetadata(custom)
}
