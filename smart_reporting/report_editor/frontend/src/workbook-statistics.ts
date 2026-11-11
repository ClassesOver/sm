/** 固定源 ribbon-actions.ts workbook-statistics：只统计当前完整 snapshot，不修改工作簿。 */
export function readWorkbookStatistics(runtime: any): {sheets: number; cells: number; formulas: number; message: string} | null {
  const workbook = runtime.univerAPI.getActiveWorkbook()
  if (!workbook) return null
  const snapshot = workbook.getSnapshot()
  let cells = 0, formulas = 0
  for (const sheet of Object.values(snapshot.sheets) as any[]) {
    for (const row of Object.values(sheet.cellData ?? {})) {
      for (const cell of Object.values(row ?? {}) as any[]) {
        if (!cell) continue
        if (cell.v !== undefined && cell.v !== null && cell.v !== '') cells += 1
        if (typeof cell.f === 'string' && cell.f.length > 0) formulas += 1
      }
    }
  }
  const sheets = Object.keys(snapshot.sheets).length
  return {sheets, cells, formulas,
    message: `工作簿统计：${sheets} 个工作表 · ${cells.toLocaleString()} 个有数据的单元格 · ${formulas.toLocaleString()} 个公式。`}
}
