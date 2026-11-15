import {formatAddress} from '@sheets-web/xlsx-engine'
import type {NativeWorkbookNavigation} from './native-api'
import type {UniverRuntime} from './workbook-vendor/grid/create-univer'
import type {createWorkbookReveal} from './workbook-goto-reveal'

/** Apply only a verified task target; this never writes cells or native operations. */
export async function navigateWorkbookReadTarget(runtime: UniverRuntime, target: NativeWorkbookNavigation, options: {
  current: () => boolean; closed: () => boolean; cancel: () => void
  reveal: ReturnType<typeof createWorkbookReveal>['reveal']
}): Promise<void> {
  const {startRow:r0,endRow:r1,startColumn:c0,endColumn:c1}=target
  if(!options.current() || options.closed())throw new Error('任务或文档已变化')
  if(typeof target.sheetName!=='string' || !target.sheetName ||
     ![r0,r1,c0,c1].every(Number.isSafeInteger) || r0<0 || r1<r0 || r1>=1048576 || c0<0 || c1<c0 || c1>=16384)
    throw new Error('定位范围无效')
  const first=formatAddress(r0,c0),last=formatAddress(r1,c1)
  if(target.range!==(first===last?first:first+':'+last))throw new Error('定位身份不一致')
  const book=runtime.univerAPI.getActiveWorkbook(),sheet=book?.getSheetByName(target.sheetName)
  if(!book || !sheet || book.isCellEditing?.())throw new Error('工作表不可定位或单元格仍在编辑')
  const range=sheet.getRange(r0,c0,r1-r0+1,c1-c0+1)
  options.cancel()
  if(!options.current() || options.closed())throw new Error('任务或文档已变化')
  book.setActiveSheet(sheet);book.setActiveRange(range)
  const current=()=>{
    const active=runtime.univerAPI.getActiveWorkbook(),selection=active?.getActiveRange()?.getRange()
    return options.current() && !options.closed() && active?.getId()===book.getId() && active.getActiveSheet()?.getSheet()===sheet.getSheet()
      && selection?.startRow===r0 && selection.endRow===r1 && selection.startColumn===c0 && selection.endColumn===c1
  }
  if(!current())throw new Error('当前选区已变化，定位未完成')
  const visible=await options.reveal(sheet,r0,c0,current)
  if(!visible || !current())throw new Error('目标未能显示或当前选区已变化')
}
