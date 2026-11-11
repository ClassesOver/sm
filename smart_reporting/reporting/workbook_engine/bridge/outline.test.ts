import {expect,it} from 'vitest'
import {createBlankWorkbook,readWorkbook} from '../packages/xlsx-engine/src/index'
import {applyWorkbookOperations} from './operations'
it('normalizes optional outline fields without dropping explicit false or hidden axis state',async()=>{
 const source=await createBlankWorkbook()
 const first=await applyWorkbookOperations(source,[{kind:'applySheetOutline',sheetName:'Sheet1',summaryBelow:false,rows:[{index:0,level:1,collapsed:false,hidden:true}],columns:[{index:0,level:1,collapsed:false}]}])
 const sheet=(await readWorkbook(first)).sheets[0]!
 expect(sheet.outlineSummaryBelow).toBe(false)
 expect(sheet.rows.find(row=>row.row===1)).toMatchObject({outlineLevel:1,hidden:true})
 const shown=await applyWorkbookOperations(first,[{kind:'applySheetOutline',sheetName:'Sheet1',rows:[{index:0,level:1,collapsed:false,hidden:false}]}])
 const reopened=(await readWorkbook(shown)).sheets[0]!
 expect(reopened.outlineSummaryBelow).toBe(false)
 expect(reopened.rows.find(row=>row.row===1)?.hidden??false).toBe(false)
})
