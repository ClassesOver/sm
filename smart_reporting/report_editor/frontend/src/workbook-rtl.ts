// 固定源 sheet-rtl-view.ts；几何实现按原样保存在 vendor/genoffice-rtl。
import { BooleanNumber, ICommandService, type IDisposable } from '@univerjs/core'
import { IRenderManagerService } from '@univerjs/engine-render'
import { SetWorksheetActiveOperation, SetWorksheetRightToLeftCommand, SetWorksheetRightToLeftMutation } from '@univerjs/sheets'
import { SheetSkeletonManagerService } from '@univerjs/sheets-ui'
import type { UniverRuntime } from './workbook-vendor/grid/create-univer'
import { installRtlGridMirror } from './vendor/genoffice-rtl/rtl-grid-mirror'

interface SharedRtl { references: number; registrations: IDisposable[] }
const installations = new WeakMap<object, SharedRtl>()

export function installWorkbookRtl(runtime: UniverRuntime) {
  installRtlGridMirror()
  let state = installations.get(runtime.univer)
  if (!state) {
    const commands = runtime.univer.__getInjector().get(ICommandService)
    const registrations: IDisposable[] = []
    for (const command of [SetWorksheetRightToLeftCommand, SetWorksheetRightToLeftMutation])
      if (!commands.hasCommand(command.id)) registrations.push(commands.registerCommand(command))
    registrations.push(commands.onCommandExecuted(command => {
      if (command.id !== SetWorksheetRightToLeftMutation.id) return
      const params = command.params as { unitId?: string; subUnitId?: string } | undefined
      const workbook = runtime.univerAPI.getActiveWorkbook(), sheet = workbook?.getActiveSheet()
      if (params?.unitId !== workbook?.getId() || params?.subUnitId !== sheet?.getSheetId()) return
      const injector = runtime.univer.__getInjector()
      // 无渲染层的导入/公式runtime仍可执行官方状态命令，下一次渲染读取新flag。
      if (!injector.has(IRenderManagerService)) return
      // reCalculate只更新skeleton，官方freeze controller需active事件才重建viewport锚点。
      injector.get(IRenderManagerService).getRenderById(workbook!.getId())?.with(SheetSkeletonManagerService)
        .setCurrent({ sheetId: sheet!.getSheetId(), commandId: SetWorksheetActiveOperation.id })
    }))
    state = { references: 0, registrations }
    installations.set(runtime.univer, state)
  }
  state.references++
  let disposed = false
  return {
    async set(rightToLeft: boolean) {
      if (disposed) throw new Error('从右到左视图已关闭')
      const workbook = runtime.univerAPI.getActiveWorkbook(), sheet = workbook?.getActiveSheet()
      if (!workbook || !sheet) throw new Error('工作簿尚未就绪')
      const core = workbook.getWorkbook(), sheetCore = sheet.getSheet(), sheetId = sheet.getSheetId()
      const applied = await runtime.univerAPI.executeCommand(SetWorksheetRightToLeftCommand.id, {
        unitId: workbook.getId(), subUnitId: sheetId, rightToLeft: rightToLeft ? BooleanNumber.TRUE : BooleanNumber.FALSE,
      })
      const live = runtime.univerAPI.getActiveWorkbook()
      if (disposed || live?.getWorkbook() !== core || live.getSheetBySheetId(sheetId)?.getSheet() !== sheetCore)
        throw new Error('从右到左目标工作簿或工作表已关闭或替换')
      if (!applied || (sheetCore.getConfig().rightToLeft === BooleanNumber.TRUE) !== rightToLeft)
        throw new Error('从右到左视图未应用')
      return { sheetId, sheetName: sheet.getSheetName(), rightToLeft }
    },
    dispose() {
      if (disposed) return
      disposed = true
      if (--state.references === 0) {
        state.registrations.forEach(item => item.dispose())
        installations.delete(runtime.univer)
      }
    },
  }
}
