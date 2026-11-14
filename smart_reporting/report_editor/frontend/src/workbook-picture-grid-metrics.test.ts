import {expect,it} from 'vitest'
import {createBlankWorkbook,readWorkbook} from '@sheets-web/xlsx-engine'
import {buildWorkbookData,columnWidthToPixels,rowHeightToPixels} from './workbook-vendor/core/univer-data'
it('projects source defaults and explicit dimensions into one native drawing grid coordinate system',async()=>{
 const model=await readWorkbook(await createBlankWorkbook())
 Object.assign(model.sheets[0]!,{defaultColumnWidthPx:75,defaultRowHeightPx:22,
  columns:[{start:1,end:1,width:10.1}],rows:[{row:1,height:16.1}]})
 const sheet=buildWorkbookData(model,'metrics','metrics').sheets['sheet-0']!
 expect(sheet).toMatchObject({defaultColumnWidth:75,defaultRowHeight:22})
 expect(sheet.columnData?.[0]?.w).toBe(columnWidthToPixels(10.1))
 expect(sheet.rowData?.[0]?.h).toBe(rowHeightToPixels(16.1))
})
it('gives legacy in-memory models the same OOXML defaults as the picture reader',async()=>{
 const model=await readWorkbook(await createBlankWorkbook())
 delete model.sheets[0]!.defaultColumnWidthPx;delete model.sheets[0]!.defaultRowHeightPx
 expect(buildWorkbookData(model,'metrics','metrics').sheets['sheet-0']).toMatchObject({defaultColumnWidth:64,defaultRowHeight:20})
})
