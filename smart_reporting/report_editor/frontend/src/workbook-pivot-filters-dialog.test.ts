import { expect, it, vi } from 'vitest'
import { createBlankWorkbook, applyCellEdits } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createPivotPlan, readWorkbookPivots, type PivotConfig } from './workbook-pivot'
import { createPivotFilterDialog } from './workbook-pivot-filters-dialog'

it('labels control persistence honestly, cancels without applying, and submits member selection', async () => {
  const rows = [['地区', '收入'], ['东', 10], ['西', 20]], source = await applyCellEdits(await createBlankWorkbook(), rows.flatMap((row, r) => row.map((value, c) => ({ sheetName: 'Sheet1', row: r, column: c, writeValue: true, cell: { value } }))))
  const config = { name: '收入分析', sourceSheetName: 'Sheet1', sourceRange: 'A1:B3', targetSheetName: 'Sheet1', targetCell: 'E1', rowFields: ['地区'], columnFields: [], values: [{ field: '收入', agg: 'sum' as const }] }
  const bytes = await applyWorkbookOperations(source, (await createPivotPlan(source, config)).operations), pivots = await readWorkbookPivots(bytes)
  const root = document.createElement('div'); document.body.append(root)
  const apply = vi.fn(async (_config: PivotConfig, _path: string) => {}), dialog = createPivotFilterDialog(root, apply)
  await dialog.open({ bytes, pivots, mode: 'slicer' })
  expect(root.textContent).toContain('勾选原生控件后同时保存 Excel 控件、缓存和位置')
  expect(root.querySelector<HTMLInputElement>('[aria-label="控件宽度（像素）"]')!.disabled).toBe(true)
  root.querySelector<HTMLButtonElement>('[data-action="cancel"]')!.click()
  expect(apply).not.toHaveBeenCalled()
  await dialog.open({ bytes, pivots, mode: 'slicer' })
  root.querySelectorAll<HTMLInputElement>('[data-members] input')[1]!.click()
  root.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  await vi.waitFor(() => expect(apply).toHaveBeenCalledOnce())
  expect(apply.mock.calls[0]![0].hiddenMembers?.row).toEqual([['西']])
  expect(apply.mock.calls[0]![1]).toBe(pivots[0]!.tablePath)
  dialog.dispose(); root.remove()
})

it('validates timeline dates before submitting and can clear the current field selection', async () => {
  const rows = [['日期', '收入'], ['2024-01-01', 10], ['2024-01-02', 20]], source = await applyCellEdits(await createBlankWorkbook(), rows.flatMap((row, r) => row.map((value, c) => ({ sheetName: 'Sheet1', row: r, column: c, writeValue: true, cell: { value } }))))
  const config = { name: '日收入', sourceSheetName: 'Sheet1', sourceRange: 'A1:B3', targetSheetName: 'Sheet1', targetCell: 'E1', rowFields: ['日期'], columnFields: [], values: [{ field: '收入', agg: 'sum' as const }] }
  const bytes = await applyWorkbookOperations(source, (await createPivotPlan(source, config)).operations), pivots = await readWorkbookPivots(bytes)
  const root = document.createElement('div'); document.body.append(root)
  const apply = vi.fn(async (_config: PivotConfig, _path: string) => {}), dialog = createPivotFilterDialog(root, apply)
  await dialog.open({ bytes, pivots, mode: 'timeline' })
  const from = root.querySelector<HTMLInputElement>('[aria-label="开始日期"]')!, to = root.querySelector<HTMLInputElement>('[aria-label="结束日期"]')!
  from.value = '2024-01-02'; to.value = '2024-01-01'
  root.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  expect(apply).not.toHaveBeenCalled(); expect(root.querySelector('[role="alert"]')!.textContent).toContain('开始日期')
  to.value = '2024-01-02'
  root.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  await vi.waitFor(() => expect(apply).toHaveBeenCalledOnce())
  expect(apply.mock.calls[0]![0].hiddenMembers?.row).toEqual([['2024-01-01']])
  await dialog.open({ bytes, pivots: [{ ...pivots[0]!, hiddenMembers: { row: [['2024-01-01']] } }], mode: 'timeline' })
  root.querySelector<HTMLButtonElement>('[data-action="reset"]')!.click()
  await vi.waitFor(() => expect(apply).toHaveBeenCalledTimes(2))
  expect(apply.mock.calls[1]![0].hiddenMembers?.row).toEqual([[]])
  dialog.dispose(); root.remove()
})

it('creates and reopens an actual native slicer through the dialog apply contract',async()=>{
 const rows=[['地区','收入'],['东',10],['西',20]],source=await applyCellEdits(await createBlankWorkbook(),rows.flatMap((row,r)=>row.map((value,c)=>({sheetName:'Sheet1',row:r,column:c,writeValue:true,cell:{value}}))))
 const config={name:'收入分析',sourceSheetName:'Sheet1',sourceRange:'A1:B3',targetSheetName:'Sheet1',targetCell:'E1',rowFields:['地区'],columnFields:[],values:[{field:'收入',agg:'sum' as const}]}
 let bytes=await applyWorkbookOperations(source,(await createPivotPlan(source,config)).operations)
 const {editPivotPlan}=await import('./workbook-pivot'),{readPivotControls}=await import('@sheets-web/xlsx-engine/pivot-controls')
 const apply=vi.fn(async(next:PivotConfig,path:string,control?:import('@sheets-web/xlsx-engine/pivot-controls').PivotControlRequest)=>{const operations=(await editPivotPlan(bytes,path,next)).operations;if(control)operations.push({kind:'upsertPivotControl',request:control});bytes=await applyWorkbookOperations(bytes,operations)})
 const remove=vi.fn(async(control:import('@sheets-web/xlsx-engine/pivot-controls').PivotControl)=>{bytes=await applyWorkbookOperations(bytes,[{kind:'removePivotControl',request:{tablePath:control.tablePath,name:control.name}}])})
 const root=document.createElement('div');document.body.append(root);const dialog=createPivotFilterDialog(root,apply,remove)
 await dialog.open({bytes,pivots:await readWorkbookPivots(bytes),mode:'slicer'})
 root.querySelector<HTMLInputElement>('[data-native-control]')!.click()
 root.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))
 await vi.waitFor(()=>expect(root.querySelector<HTMLElement>('[role=dialog]')!.hidden).toBe(true))
 expect(await readPivotControls(bytes)).toEqual([expect.objectContaining({name:'Slicer_P1_F0',field:'地区'})])
 await dialog.open({bytes,pivots:await readWorkbookPivots(bytes),mode:'slicer'})
 expect(root.querySelector<HTMLInputElement>('[data-native-control]')!.checked).toBe(true)
 expect(root.querySelector<HTMLInputElement>('[aria-label="控件名称"]')!.value).toBe('Slicer_P1_F0')
 const position=root.querySelector<HTMLInputElement>('[aria-label="控件左上角单元格"]')!,width=root.querySelector<HTMLInputElement>('[aria-label="控件宽度（像素）"]')!,height=root.querySelector<HTMLInputElement>('[aria-label="控件高度（像素）"]')!
 expect(position).not.toBeNull()
 expect(position.value).toBe('H1');expect(width.value).toBe('192');expect(height.value).toBe('260')
 const previous=bytes.slice(),calls=apply.mock.calls.length
 position.value='XFE1';root.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))
 expect(root.querySelector('[role="alert"]')!.textContent).toContain('控件位置')
 expect(apply).toHaveBeenCalledTimes(calls);expect(bytes).toEqual(previous)
 position.value='m5';width.value='320';height.value='180'
 root.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))
 await vi.waitFor(()=>expect(root.querySelector<HTMLElement>('[role=dialog]')!.hidden).toBe(true))
 expect(await readPivotControls(bytes)).toEqual([expect.objectContaining({anchor:{row:4,column:12,width:320,height:180}})])
 await dialog.open({bytes,pivots:await readWorkbookPivots(bytes),mode:'slicer'})
 expect(position.value).toBe('M5');expect(width.value).toBe('320');expect(height.value).toBe('180')
 root.querySelector<HTMLButtonElement>('[data-action="delete-control"]')!.click()
 await vi.waitFor(()=>expect(root.querySelector<HTMLElement>('[role=dialog]')!.hidden).toBe(true))
 expect(remove).toHaveBeenCalledOnce()
 expect(await readPivotControls(bytes)).toEqual([])
 dialog.dispose();root.remove()
})
