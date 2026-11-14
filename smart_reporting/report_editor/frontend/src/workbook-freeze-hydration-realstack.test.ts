import { afterEach, expect, it } from 'vitest'
import { Univer, LocaleType } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import '@univerjs/sheets/facade'
import { applyPageSetups, createBlankWorkbook, readWorkbook } from '@sheets-web/xlsx-engine'
import { buildWorkbookData } from './workbook-vendor/core/univer-data'
import { loadWorkbookData } from './workbook-vendor/grid/sync'

const runtimes: Univer[] = []
afterEach(() => { runtimes.splice(0).forEach(runtime => runtime.dispose()) })

it('hydrates both frozen axes together without losing source B2 through repeated workbook loads', async () => {
  const model = await readWorkbook(await applyPageSetups(await createBlankWorkbook(), [{ sheetName:'Sheet1', frozenRows:1, frozenColumns:1 }]))
  const univer = new Univer({locale:LocaleType.ZH_CN});runtimes.push(univer);univer.registerPlugin(UniverSheetsPlugin)
  const runtime = {univer,univerAPI:FUniver.newAPI(univer)}
  for (let i=0;i<3;i++) {
    loadWorkbookData(runtime,buildWorkbookData(model,'freeze-probe','freeze-probe'))
    expect(runtime.univerAPI.getActiveWorkbook()!.getActiveSheet().getFreeze()).toMatchObject({xSplit:1,ySplit:1,startRow:1,startColumn:1})
    await new Promise(resolve => setTimeout(resolve,0))
    expect(runtime.univerAPI.getActiveWorkbook()!.getActiveSheet().getFreeze()).toMatchObject({xSplit:1,ySplit:1})
  }
})
