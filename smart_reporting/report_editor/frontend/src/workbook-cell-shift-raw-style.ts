/** 官方插入单元格会从getCell复制CF投影样式；仅在同步构造自动空白批次时改用raw样式。 */
export function createCellShiftRawStyleGuard() {
  let active: { command: any; unitId: string; subUnitId: string; range: any; sheet: any } | undefined
  const clear = (command?: any) => { if (!command || active?.command === command) active = undefined }
  return {
    begin(command: any, workbook: any) {
      active = undefined
      if (!/^sheet\.command\.insert-range-move-(?:down|right)$/.test(command.id)) return
      const sheet = workbook?.getActiveSheet()
      if (!sheet?.getSheet) return
      const range = command.params?.range ?? sheet.getSelection?.()?.getActiveRange?.()?.getRange?.()
      if (!range) return
      const token = { command, unitId: workbook.getId(), subUnitId: sheet.getSheetId(), range: { ...range }, sheet: sheet.getSheet() }
      active = token
      // 官方在首次await之前同步构造此批次；失败/取消也不能把身份留给后续用户编辑。
      queueMicrotask(() => { if (active === token) active = undefined })
    },
    normalize(command: any) {
      const token = active, params = command.params
      if (!token || command.id !== 'sheet.command.set-range-values' || params?.unitId !== token.unitId || params.subUnitId !== token.subUnitId || !params.range || !params.cellValue) return
      if (['startRow', 'endRow', 'startColumn', 'endColumn'].some(key => params.range[key] !== token.range[key])) return
      const cells = Object.entries(params.cellValue).flatMap(([row, columns]) => Object.entries(columns as object).map(([column, cell]) => ({ row: Number(row), column: Number(column), cell })))
      if (cells.some(({ row, column, cell }) => !(row >= token.range.startRow && row <= token.range.endRow && column >= token.range.startColumn && column <= token.range.endColumn)
        || cell !== null && (typeof cell !== 'object' || Object.keys(cell).some(key => key !== 's')))) return
      const styles = cells.map(({ row, column }) => {
        const style = token.sheet.getCellRaw(row, column)?.s
        return style == null ? null : { s: structuredClone(style) }
      })
      active = undefined
      cells.forEach(({ row, column }, index) => { params.cellValue[row][column] = styles[index] })
    },
    clear,
  }
}
