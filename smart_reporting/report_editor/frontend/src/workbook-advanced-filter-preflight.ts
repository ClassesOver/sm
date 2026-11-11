import type { WorkbookOperation } from './workbook-draft'
import type { FilterCriteria, FilterRange } from './workbook-filters'

/** 保留草稿已有的顺序操作，仅替换本次实时筛选差分，按公开请求预算预演。 */
export function advancedFilterPreflightOperations(existing: readonly WorkbookOperation[], stagedCount: number,
  sheetName: string, filter: { range: FilterRange; columns: FilterCriteria[] }): WorkbookOperation[] {
  const operations: WorkbookOperation[] = existing.filter((operation, index) => index < stagedCount
    || operation.kind !== 'applySheetFilter' || operation.sheetName !== sheetName)
  operations.push({ kind: 'applySheetFilter', sheetName, filter })
  if (operations.length > 500) throw new Error('高级筛选后的操作超过 500 条，请先保存当前修改并在新修订继续')
  return operations
}
