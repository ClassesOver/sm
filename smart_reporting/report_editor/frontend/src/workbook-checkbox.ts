/** 固定源 f8c17004 ribbon-actions.ts:813；使用官方可交互 DV checkbox。 */
import type { FUniver } from '@univerjs/core/lib/facade'
import '@univerjs/sheets-data-validation/facade'

export function applyWorkbookCheckbox(runtime: { univerAPI: FUniver }): boolean {
  const range = runtime.univerAPI.getActiveWorkbook()?.getActiveRange()
  if (!range) return false
  range.setDataValidation(runtime.univerAPI.newDataValidation().requireCheckbox().build())
  return true
}
