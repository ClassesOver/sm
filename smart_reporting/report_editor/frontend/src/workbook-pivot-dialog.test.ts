import { expect, it, vi } from 'vitest'
import { createBlankWorkbook, applyCellEdits } from '@sheets-web/xlsx-engine'
import { createPivotDialog } from './workbook-pivot-dialog'
it('cancels without applying and submits ordered row fields with aggregation',async()=>{
 const bytes=await applyCellEdits(await createBlankWorkbook(),['区域','收入'].map((value,column)=>({sheetName:'Sheet1',row:0,column,writeValue:true,cell:{value}})))
 const apply=vi.fn(async(_config:import('./workbook-pivot').PivotConfig,_tablePath?:string)=>{}),root=document.createElement('div');document.body.append(root)
 const dialog=createPivotDialog(root,apply)
 await dialog.open({bytes,sourceSheetName:'Sheet1',sourceRange:'A1:B2',targetCell:'E1'})
 root.querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click();expect(apply).not.toHaveBeenCalled()
 await dialog.open({bytes,sourceSheetName:'Sheet1',sourceRange:'A1:B2',targetCell:'E1'})
 root.querySelector<HTMLButtonElement>('[data-add="rows"]')!.click()
 root.querySelector<HTMLSelectElement>('[data-field="values"]')!.value='收入'
 root.querySelector<HTMLButtonElement>('[data-add="values"]')!.click()
 root.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))
 await vi.waitFor(()=>expect(apply).toHaveBeenCalledOnce())
 expect(apply.mock.calls[0]![0]).toMatchObject({rowFields:['区域'],values:[{field:'收入',agg:'sum'}],targetCell:'E1'})
 dialog.dispose();root.remove()
})
it('selects an existing Excel table as the explicit current source range',async()=>{
 const {applyWorkbookOperations}=await import('../../../reporting/workbook_engine/bridge/operations')
 const data=await applyCellEdits(await createBlankWorkbook(),['区域','收入'].map((value,column)=>({sheetName:'Sheet1',row:0,column,writeValue:true,cell:{value}})))
 const bytes=await applyWorkbookOperations(data,[{kind:'applyTableAdditions',additions:[{worksheetSheetName:'Sheet1',area:{startRow:0,startColumn:0,endRow:2,endColumn:1},name:'Sales',columnNames:['区域','收入'],style:'TableStyleMedium4',bandedRows:true}]}])
 const root=document.createElement('div');document.body.append(root);const dialog=createPivotDialog(root,async()=>{})
 await dialog.open({bytes,sourceSheetName:'Sheet1',sourceRange:'D1:E2',targetCell:'H1'})
 const select=root.querySelector<HTMLSelectElement>('[aria-label="来源表"]')!
 expect(select.options[1]!.text).toContain('Sales');select.value='0';select.dispatchEvent(new Event('change'))
 await vi.waitFor(()=>expect(root.querySelector('[data-fields]')!.textContent).toContain('区域'))
 expect(root.querySelector<HTMLInputElement>('[aria-label="来源区域"]')!.value).toBe('A1:B3')
 dialog.dispose();root.remove()
})
it('submits calculated fields, grouping and report filter selection from local controls',async()=>{
 const rows=[['区域','年份','收入','数量'],['东',2025,10,2]],bytes=await applyCellEdits(await createBlankWorkbook(),rows.flatMap((row,r)=>row.map((value,column)=>({sheetName:'Sheet1',row:r,column,writeValue:true,cell:{value}}))))
 const apply=vi.fn(async(_config:import('./workbook-pivot').PivotConfig)=>{}),root=document.createElement('div');document.body.append(root);const dialog=createPivotDialog(root,apply)
 await dialog.open({bytes,sourceSheetName:'Sheet1',sourceRange:'A1:D2',targetCell:'H1'})
 root.querySelector<HTMLSelectElement>('[data-field="rows"]')!.value='年份';root.querySelector<HTMLButtonElement>('[data-add="rows"]')!.click()
 const group=root.querySelector<HTMLSelectElement>('[aria-label="年份 分组"]')!;group.value='range';group.dispatchEvent(new Event('change'))
 root.querySelector<HTMLInputElement>('[aria-label="计算字段名称"]')!.value='单价';root.querySelector<HTMLInputElement>('[aria-label="计算字段公式"]')!.value='收入/数量';root.querySelector<HTMLButtonElement>('[data-add="calculated"]')!.click()
 root.querySelector<HTMLSelectElement>('[data-field="pages"]')!.value='区域';root.querySelector<HTMLButtonElement>('[data-add="pages"]')!.click()
 root.querySelector('form')!.dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}))
 await vi.waitFor(()=>expect(apply).toHaveBeenCalledOnce())
 expect(apply.mock.calls[0]![0]).toMatchObject({values:[{field:'单价',formula:'收入/数量'}],groupings:[{field:'年份',kind:'range',rangeStep:10}],pageFilters:[{field:'区域'}]})
 dialog.dispose();root.remove()
})
