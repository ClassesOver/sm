// 固定源 ribbon-actions.ts:965–1020：原生标题尺寸命令与零宽 viewport 修正。
import { BooleanNumber } from '@univerjs/core'
import { IRenderManagerService, SHEET_VIEWPORT_KEY } from '@univerjs/engine-render'
import { SheetSkeletonManagerService } from '@univerjs/sheets-ui'
import type { UniverRuntime } from './workbook-vendor/grid/create-univer'

export async function toggleWorkbookHeadings(runtime: UniverRuntime, isActive: () => boolean = () => true): Promise<{
  sheetId: string; sheetName: string; showHeadings: boolean
}> {
  const workbook = runtime.univerAPI.getActiveWorkbook(), worksheet = workbook?.getActiveSheet()
  if (!workbook || !worksheet) throw new Error('工作簿尚未就绪')
  const workbookCore = workbook.getWorkbook(), sheetCore = worksheet.getSheet(), sheetId = worksheet.getSheetId()
  const current = () => {
    const live = runtime.univerAPI.getActiveWorkbook()
    if (!isActive() || !live || live.getWorkbook() !== workbookCore
      || live.getSheetBySheetId(sheetId)?.getSheet() !== sheetCore || live.getActiveSheet()?.getSheet() !== sheetCore)
      throw new Error('标题目标工作簿或工作表已关闭或替换')
  }
  current()
  const config = sheetCore.getConfig(), nextHidden = config.rowHeader.hidden !== BooleanNumber.TRUE
  config.rowHeader.hidden = nextHidden ? BooleanNumber.TRUE : BooleanNumber.FALSE
  config.columnHeader.hidden = nextHidden ? BooleanNumber.TRUE : BooleanNumber.FALSE
  const unitId = workbook.getId(), render = runtime.univer.__getInjector().get(IRenderManagerService).getRenderById(unitId), scene = render?.scene
  const skeleton = render?.with(SheetSkeletonManagerService).getCurrentSkeleton()
  const viewMain = scene?.getViewport(SHEET_VIEWPORT_KEY.VIEW_MAIN), viewColumnRight = scene?.getViewport(SHEET_VIEWPORT_KEY.VIEW_COLUMN_RIGHT)
  const nextWidth = nextHidden ? 0 : 46, shift = skeleton ? nextWidth - skeleton.rowHeaderWidth : 0
  const mainLeft = (viewMain?.left ?? 0) + shift, columnRightLeft = (viewColumnRight?.left ?? 0) + shift
  const result = await Promise.all([
    runtime.univerAPI.executeCommand('sheet.command.set-row-header-width', { unitId, subUnitId: sheetId, size: nextWidth }),
    runtime.univerAPI.executeCommand('sheet.command.set-col-header-height', { unitId, subUnitId: sheetId, size: nextHidden ? 0 : 20 }),
  ])
  current()
  if (result.some(value => value === false)) throw new Error('标题显示未应用')
  if (viewMain && viewMain.left !== mainLeft) {
    viewMain.left = mainLeft
    viewColumnRight?.setViewportSize({ left: columnRightLeft })
    scene?.makeDirty(true)
  }
  return { sheetId, sheetName: worksheet.getSheetName(), showHeadings: !nextHidden }
}
