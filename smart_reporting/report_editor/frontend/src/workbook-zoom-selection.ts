// 固定源 f8c17004 ribbon-actions.ts zoom-to-selection；尺寸均为未缩放的累积边界。
import { IRenderManagerService } from '@univerjs/engine-render'
import { SheetSkeletonManagerService } from '@univerjs/sheets-ui'

type Selection = { startRow: number; endRow: number; startColumn: number; endColumn: number }
type Skeleton = {
  rowHeightAccumulation: readonly number[]
  columnWidthAccumulation: readonly number[]
  rowHeaderWidthAndMarginLeft: number
  columnHeaderHeightAndMarginTop: number
}
export function selectionZoomRatio(selection: Selection, skeleton: Skeleton,
  viewport: { width: number; height: number }): number | undefined {
  const rows = skeleton.rowHeightAccumulation, columns = skeleton.columnWidthAccumulation
  const top = selection.startRow > 0 ? (rows[selection.startRow - 1] ?? 0) : 0
  const bottom = rows[Math.min(selection.endRow, rows.length - 1)] ?? 0
  const left = selection.startColumn > 0 ? (columns[selection.startColumn - 1] ?? 0) : 0
  const right = columns[Math.min(selection.endColumn, columns.length - 1)] ?? 0
  const width = viewport.width - skeleton.rowHeaderWidthAndMarginLeft
  const height = viewport.height - skeleton.columnHeaderHeightAndMarginTop
  if (right <= left || bottom <= top || width <= 0 || height <= 0) return undefined
  const percent = Math.round(Math.min(width / (right - left), height / (bottom - top)) * 100)
  return Math.min(400, Math.max(10, percent)) / 100
}

export async function zoomWorkbookToSelection(runtime: any): Promise<{ changed: boolean; percent?: number; message: string }> {
  const workbook = runtime.univerAPI.getActiveWorkbook(), worksheet = workbook?.getActiveSheet()
  const selection = workbook?.getActiveRange()?.getRange()
  if (!workbook || !worksheet || !selection) return { changed: false, message: '请先选择单元格或区域' }
  const injector = runtime.univer.__getInjector()
  if (typeof injector.has === 'function' && !injector.has(IRenderManagerService)) return { changed: false, message: '工作表视图尚未就绪' }
  const render = injector.get(IRenderManagerService).getRenderById(workbook.getId())
  const skeleton = render?.with(SheetSkeletonManagerService).getCurrentSkeleton()
  if (!render || !skeleton) return { changed: false, message: '工作表视图尚未就绪' }
  const ratio = selectionZoomRatio(selection, skeleton, render.engine)
  if (ratio === undefined) return { changed: false, message: '所选区域没有可缩放的可见尺寸' }
  const core = workbook.getWorkbook?.() ?? workbook, sheetCore = worksheet.getSheet?.() ?? worksheet
  const percent = Math.round(ratio * 100)
  const result = (message = `缩放已调整为 ${percent}%，修改尚未保存。`) => ({ changed: true, percent, message })
  const sameWorkbook = () => {
    const active = runtime.univerAPI.getActiveWorkbook()
    return active && (active.getWorkbook?.() ?? active) === core ? active : null
  }
  let applied: unknown
  try {
    applied = await runtime.univerAPI.executeCommand('sheet.command.set-zoom-ratio', {
      unitId: workbook.getId(), subUnitId: worksheet.getSheetId(), zoomRatio: ratio,
    })
  } catch (error) {
    if (sameWorkbook() && typeof worksheet.getZoom === 'function' && Math.round(worksheet.getZoom() * 100) === percent)
      return result(`缩放已调整为 ${percent}%；未执行选区滚动：${(error as Error).message}`)
    throw error
  }
  const observed = typeof worksheet.getZoom === 'function' ? Math.round(worksheet.getZoom() * 100) : undefined
  if (observed !== undefined ? observed !== percent : applied === false) return { changed: false, message: '缩放未应用' }
  const active = sameWorkbook(), activeSheet = active?.getActiveSheet()
  if (!active) return { changed: false, message: '工作簿已关闭或替换，已取消选区滚动' }
  if ((activeSheet?.getSheet?.() ?? activeSheet) !== sheetCore)
    return result(`缩放已调整为 ${percent}%；工作表已切换，已取消选区滚动。`)
  // 先完成缩放再滚动；旧缩放下的滚动钳制会让靠近表边缘的选区留在视口外。
  // Univer在目标已可见时合法返回false；缩放的真实修改仍需保存。
  try {
    await runtime.univerAPI.executeCommand('sheet.command.scroll-to-cell', {
      range: selection, forceTop: true, forceLeft: true,
    })
  } catch (error) {
    if (!sameWorkbook()) return { changed: false, message: '工作簿已关闭或替换' }
    return result(`缩放已调整为 ${percent}%；选区滚动未完成：${(error as Error).message}`)
  }
  if (!sameWorkbook()) return { changed: false, message: '工作簿已关闭或替换' }
  return result()
}
