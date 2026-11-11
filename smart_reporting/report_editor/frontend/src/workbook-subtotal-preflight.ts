import type {WorkbookOperation} from './workbook-draft'
import type {SubtotalPlan} from './workbook-subtotal'

/** 与 main 结构 journal 的逐次插行粒度一致，预演也遵守公开保存的操作总数。 */
export function subtotalPreflightOperations(existing:readonly WorkbookOperation[],sheetName:string,plan:SubtotalPlan):WorkbookOperation[]{
 const operations:WorkbookOperation[]=[...existing,
  ...plan.inserts.map(index=>({kind:'applyRowColumnOps' as const,sheetName,ops:[{kind:'insert-rows' as const,index,count:1}]})),
  {kind:'applyCellEdits',edits:plan.cells.map(cell=>({sheetName,row:cell.row,column:cell.column,writeValue:true,
   cell:cell.formula?{value:null,formula:cell.formula}:{value:cell.value!},style:{bold:true}}))},
  {kind:'applySheetOutline',sheetName,summaryBelow:true,rows:plan.outline.rows.map(row=>({index:row.row,level:row.level,collapsed:false}))},
 ]
 if(operations.length>500)throw new Error('分类汇总后的操作超过 500 条，请先保存当前修改并在新修订继续')
 return operations
}
