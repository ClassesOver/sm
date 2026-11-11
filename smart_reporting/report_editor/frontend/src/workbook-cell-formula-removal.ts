import { formulaReferencesSheet, worksheetReferencesSheet } from '@sheets-web/xlsx-engine/sheets-edit'
import { extractElements, readXmlAttribute } from '@sheets-web/xlsx-engine/xml'
import { normalizeInternalSheetFormula } from './workbook-internal-formula'

export type CellFormulaRemovalSource = { sourceXml: string; unprojected?: boolean }

export function unprojectedCellFormulaNodes(sourceXml: string): string[] {
  const data = extractElements(sourceXml, 'sheetData').join('')
  if (/<[\w.-]+:sheetData\b/.test(sourceXml) || /<[\w.-]+:f\b/.test(data)) throw new Error('单元格公式来源无法完整核对，请同步后重试删除。')
  return (data.match(/<f\b[^>]*(?:\/>|>[\s\S]*?<\/f>)/g) ?? []).filter(node => {
    const type = readXmlAttribute(node.match(/^<[^>]*>/)?.[0] ?? '', 't')
    return /\/>$/.test(node) || type !== undefined && type !== 'normal'
  })
}

/** 稀疏全表扫描，不依赖可视区域；shared公式通过官方FormulaDataModel facade读取。 */
export function assertCellFormulaSheetRemoval(workbook: any, subUnitId?: string, sourceForSheet?: (sheetId: string) => CellFormulaRemovalSource | undefined): void {
  const target = subUnitId ? workbook?.getSheetBySheetId(subUnitId) : workbook?.getActiveSheet()
  if (!target) return
  const name = target.getSheetName()
  for (const sheet of workbook.getSheets()) {
    if (sheet.getSheetId() === target.getSheetId()) continue
    let found = false
    sheet.getSheet?.().getCellMatrix().forValue((row: number, column: number, cell: any) => {
      if (!cell?.f && !cell?.si) return
      const formula = sheet.getRange(row, column).getFormula() || cell.f
      if (typeof formula !== 'string' || !formula) throw new Error(`工作表 "${sheet.getSheetName()}" 的共享公式无法完整读取，请同步后重试删除。`)
      if (formulaReferencesSheet(normalizeInternalSheetFormula(formula, workbook.getId(), name), name)) found = true
    })
    if (found) throw new Error(`工作表 "${sheet.getSheetName()}" 的单元格公式仍引用 "${name}"，已拒绝删除。`)
    const source = sourceForSheet?.(sheet.getSheetId())
    if (source?.unprojected && worksheetReferencesSheet(unprojectedCellFormulaNodes(source.sourceXml).join(''), name))
      throw new Error(`工作表 "${sheet.getSheetName()}" 存在未完整投影的单元格公式仍引用 "${name}"，已拒绝删除。`)
  }
}
