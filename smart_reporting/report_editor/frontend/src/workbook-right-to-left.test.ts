import { expect, it } from 'vitest'
import { applyPageSetups, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { BooleanNumber, LocaleType, Univer, UniverInstanceType } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { SpreadsheetSkeleton } from '@univerjs/engine-render'
import { buildWorkbookData } from './workbook-vendor/core/univer-data'
import { withWorkbookView } from './workbook-view'
import { installWorkbookRtl } from './workbook-rtl'
import '@univerjs/sheets/facade'

it('persists the right-to-left sheet view through the real XLSX page setup writer and reader', async () => {
  const bytes = await applyPageSetups(await createBlankWorkbook(), [{ sheetName: 'Sheet1', rightToLeft: true }])
  expect((await readWorkbook(bytes)).sheets[0]).toHaveProperty('rightToLeft', true)
})

it('places logical column A to the right of B in the real RTL spreadsheet skeleton', async () => {
  const model = await readWorkbook(await createBlankWorkbook())
  const univer = new Univer({ locale: LocaleType.EN_US })
  let skeleton: SpreadsheetSkeleton | undefined
  let rtl: ReturnType<typeof installWorkbookRtl> | undefined
  try {
    univer.registerPlugin(UniverSheetsPlugin)
    const data = withWorkbookView(buildWorkbookData(model, 'rtl-geometry', 'RTL'), model)
    Object.assign(Object.values(data.sheets)[0]!, { rightToLeft: BooleanNumber.TRUE })
    univer.createUnit(UniverInstanceType.UNIVER_SHEET, data)
    rtl = installWorkbookRtl({ univer, univerAPI: FUniver.newAPI(univer) })
    const workbook = FUniver.newAPI(univer).getActiveWorkbook()!
    skeleton = univer.__getInjector().createInstance(SpreadsheetSkeleton, workbook.getActiveSheet().getSheet(), workbook.getWorkbook().getStyles())
    const a = skeleton.getCellWithCoordByIndex(0, 0), b = skeleton.getCellWithCoordByIndex(0, 1)
    expect(a.startX).toBeGreaterThan(b.startX)
  } finally { skeleton?.dispose(); rtl?.dispose(); univer.dispose() }
})

it('hydrates imported right-to-left view state into the real native worksheet', async () => {
  const model = await readWorkbook(await createBlankWorkbook())
  Object.assign(model.sheets[0]!, { rightToLeft: true })
  const univer = new Univer({ locale: LocaleType.EN_US })
  try {
    univer.registerPlugin(UniverSheetsPlugin)
    univer.createUnit(UniverInstanceType.UNIVER_SHEET, withWorkbookView(buildWorkbookData(model, 'rtl-probe', 'RTL'), model))
    expect(FUniver.newAPI(univer).getActiveWorkbook()!.getActiveSheet().getSheet().getConfig().rightToLeft).toBe(BooleanNumber.TRUE)
  } finally { univer.dispose() }
})
