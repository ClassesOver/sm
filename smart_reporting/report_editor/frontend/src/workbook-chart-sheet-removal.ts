import { formulaReferencesSheet, readChartFormulas } from '@sheets-web/xlsx-engine/sheets-edit'
import { normalizeInternalSheetFormula } from './workbook-internal-formula'

export type ChartRemovalSource = { path: string; xml: string }

/** 只信任调用方从实际包关系图读取的来源；live渲染列表不代表图表完整性。 */
export function assertChartSheetRemoval(workbook: any, subUnitId: string | undefined, sourceForSheet: (sheetId: string) => readonly ChartRemovalSource[]): void {
  const target = subUnitId ? workbook?.getSheetBySheetId(subUnitId) : workbook?.getActiveSheet()
  if (!target) return
  const targetName = target.getSheetName()
  for (const sheet of workbook.getSheets()) {
    if (sheet.getSheetId() === target.getSheetId()) continue
    for (const source of sourceForSheet(sheet.getSheetId())) {
      for (const formula of readChartFormulas(source.xml)) {
        if (formulaReferencesSheet(normalizeInternalSheetFormula(formula, workbook.getId(), targetName), targetName))
          throw new Error(`工作表 "${sheet.getSheetName()}" 的图表 "${source.path}" 仍引用 "${targetName}"，已拒绝删除。`)
      }
    }
  }
}
