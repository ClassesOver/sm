import { expect, it, vi } from 'vitest'
import { BooleanNumber, ICommandService, IUniverInstanceService, LocaleType, Univer, UniverInstanceType } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { SpreadsheetSkeleton } from '@univerjs/engine-render'
import { IRenderManagerService } from '@univerjs/engine-render'
import { SheetSkeletonManagerService } from '@univerjs/sheets-ui'
import { SetWorksheetActiveOperation } from '@univerjs/sheets'
import { applyCellEdits, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { buildWorkbookData } from './workbook-vendor/core/univer-data'
import { withWorkbookView } from './workbook-view'
import '@univerjs/sheets/facade'
const implementation = './workbook-rtl'

async function runtime() {
  const model = await readWorkbook(await applyCellEdits(await createBlankWorkbook(), [
    { sheetName: 'Sheet1', row: 0, column: 0, writeValue: true, cell: { value: 'first' } },
    { sheetName: 'Sheet1', row: 0, column: 1, writeValue: true, cell: { value: 'second' } },
  ]))
  const univer = new Univer({ locale: LocaleType.EN_US }); univer.registerPlugin(UniverSheetsPlugin)
  univer.createUnit(UniverInstanceType.UNIVER_SHEET, withWorkbookView(buildWorkbookData(model, 'rtl-module', 'RTL'), model))
  univer.__getInjector().get(IUniverInstanceService).focusUnit('rtl-module')
  return { univer, univerAPI: FUniver.newAPI(univer) }
}

it('uses the official async RTL command with native undo/redo and independent install leases', async () => {
  const { installWorkbookRtl } = await import(/* @vite-ignore */ implementation)
  const current = await runtime(), first = installWorkbookRtl(current), second = installWorkbookRtl(current)
  try {
    first.dispose()
    const sheet = current.univerAPI.getActiveWorkbook()!.getActiveSheet()
    expect(await second.set(true)).toMatchObject({ sheetName: 'Sheet1', rightToLeft: true })
    expect(sheet.getSheet().getConfig().rightToLeft).toBe(BooleanNumber.TRUE)
    expect(await current.univerAPI.undo()).toBe(true)
    expect(sheet.getSheet().getConfig().rightToLeft).toBe(BooleanNumber.FALSE)
    expect(await current.univerAPI.redo()).toBe(true)
    expect(sheet.getSheet().getConfig().rightToLeft).toBe(BooleanNumber.TRUE)
    expect(sheet.getRange('A1:B1').getValues()).toEqual([['first', 'second']])
  } finally { second.dispose(); current.univer.dispose() }
})

it('mirrors real cell geometry and maps a visual A hit back to logical column zero while keeping LTR intact', async () => {
  const { installWorkbookRtl } = await import(/* @vite-ignore */ implementation)
  const current = await runtime(), controller = installWorkbookRtl(current), workbook = current.univerAPI.getActiveWorkbook()!, sheet = workbook.getActiveSheet()
  const skeleton = current.univer.__getInjector().createInstance(SpreadsheetSkeleton, sheet.getSheet(), workbook.getWorkbook().getStyles())
  try {
    const ltrA = skeleton.getCellWithCoordByIndex(0, 0), ltrB = skeleton.getCellWithCoordByIndex(0, 1)
    expect(ltrA.startX).toBeLessThan(ltrB.startX)
    await controller.set(true)
    const a = skeleton.getCellWithCoordByIndex(0, 0), b = skeleton.getCellWithCoordByIndex(0, 1)
    expect(a.startX).toBeGreaterThan(b.startX)
    expect(a.endX - a.startX).toBe(ltrA.endX - ltrA.startX)
    expect(skeleton.getColumnIndexByOffsetX((a.startX + a.endX) / 2, 1, { x: 0, y: 0 })).toBe(0)
    sheet.getRange('B1').activate(); expect(workbook.getActiveRange()!.getColumn()).toBe(1)
    await controller.set(false)
    expect(skeleton.getCellWithCoordByIndex(0, 0)).toMatchObject({ startX: ltrA.startX, endX: ltrA.endX })
  } finally { skeleton.dispose(); controller.dispose(); current.univer.dispose() }
})

it('does not remove a pre-existing official command when releasing its RTL controller', async () => {
  const { installWorkbookRtl } = await import(/* @vite-ignore */ implementation)
  const { SetWorksheetRightToLeftCommand } = await import('@univerjs/sheets')
  const current = await runtime(), commands = current.univer.__getInjector().get(ICommandService)
  const foreign = commands.registerCommand(SetWorksheetRightToLeftCommand)
  const controller = installWorkbookRtl(current)
  try { controller.dispose(); expect(commands.hasCommand(SetWorksheetRightToLeftCommand.id)).toBe(true) }
  finally { foreign.dispose(); current.univer.dispose() }
})

it('rebuilds the official active-sheet viewport anchors after a direction mutation', async () => {
  const { installWorkbookRtl } = await import(/* @vite-ignore */ implementation)
  const current = await runtime(), commands = current.univer.__getInjector().get(ICommandService), setCurrent = vi.fn(), reCalculate = vi.fn()
  const injector = current.univer.__getInjector(), originalHas = injector.has.bind(injector), originalGet = injector.get.bind(injector)
  vi.spyOn(injector, 'has').mockImplementation((...args) => args[0] === IRenderManagerService || originalHas(...args))
  vi.spyOn(injector, 'get').mockImplementation(((token: unknown) => token === IRenderManagerService ? {
    getRenderById: () => ({ with: (service: unknown) => { expect(service).toBe(SheetSkeletonManagerService); return { setCurrent, reCalculate } } }),
  } : originalGet(token as never)) as typeof injector.get)
  const controller = installWorkbookRtl(current)
  try {
    await controller.set(true)
    expect(setCurrent).toHaveBeenLastCalledWith({ sheetId: current.univerAPI.getActiveWorkbook()!.getActiveSheet().getSheetId(), commandId: SetWorksheetActiveOperation.id })
    expect(commands.hasCommand('sheet.command.set-worksheet-right-to-left')).toBe(true)
  } finally { controller.dispose(); vi.restoreAllMocks(); current.univer.dispose() }
})
