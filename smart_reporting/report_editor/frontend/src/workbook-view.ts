import type { WorkbookModel } from '@sheets-web/xlsx-engine'

/** 加载时把源视图状态灌入 Univer 工作表快照：sheetView zoomScale → zoomRatio，
 *  showGridLines → showGridlines（BooleanNumber）。保存差分以 getZoom()/
 *  hasHiddenGridLines() 对比文件值；未灌入时网格停在默认 100%/显示网格线，
 *  保存无关修改会把文件中的非默认缩放与隐藏网格线覆盖为默认值。 */
export function withWorkbookView<T extends { sheets: Record<string, { id: string; name: string }> }>(data: T, model: WorkbookModel): T {
  for (const sheet of Object.values(data.sheets)) {
    const source = model.sheets.find(item => item.name === sheet.name)
    if (!source) continue
    Object.assign(sheet, {
      zoomRatio: (source.zoomScale ?? 100) / 100,
      showGridlines: source.showGridlines === false ? 0 : 1,
    })
  }
  return data
}
