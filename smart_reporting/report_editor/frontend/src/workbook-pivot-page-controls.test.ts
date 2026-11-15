import { expect, it } from 'vitest'
import { applyCellEdits, createBlankWorkbook, createBufferEntrySource, readWorkbook } from '@sheets-web/xlsx-engine'
import { readPivotControls, supportsOwnedPivotControls } from '@sheets-web/xlsx-engine/pivot-controls'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { createPivotPlan, editPivotPlan, readWorkbookPivots } from './workbook-pivot'
import { readPivotFilterFields, pivotMemberFilterConfig, pivotTimelineFilterConfig } from './workbook-pivot-filters'

async function fixture() {
 const rows = [['Region','Date','Category','Amount'], ['East',45292,'A',10], ['West',45293,'A',20], ['East',45294,'B',30], ['West',45295,'B',40]]
 const source=await applyCellEdits(await createBlankWorkbook(),rows.flatMap((row,r)=>row.map((value,c)=>({sheetName:'Sheet1',row:r,column:c,writeValue:true,cell:{value},...(r>0&&c===1?{style:{numberFormat:'yyyy-mm-dd'}}:{})}))))
 const config={name:'Sales',sourceSheetName:'Sheet1',sourceRange:'A1:D5',targetSheetName:'Sheet1',targetCell:'G1',rowFields:['Category'],columnFields:[],pageFilters:[{field:'Region',selected:['East']},{field:'Date'}],values:[{field:'Amount',agg:'sum' as const}]}
 const bytes=await applyWorkbookOperations(source,(await createPivotPlan(source,config)).operations)
 return {bytes,pivot:(await readWorkbookPivots(bytes))[0]!}
}

it('projects page members and saves a selection/reset without changing another page filter or row filter',async()=>{
 const {bytes,pivot}=await fixture(), fields=await readPivotFilterFields(bytes,pivot)
 expect(fields.find(f=>f.name==='Region')).toMatchObject({axis:'page',level:0,members:[{value:'East'},{value:'West'}]})
 expect(fields.find(f=>f.name==='Date')).toMatchObject({axis:'page',level:1,timeline:true})
 const config=pivotMemberFilterConfig({...pivot,hiddenMembers:{row:[['B']],column:[]}},fields,'Region',['West'])
 expect(config.pageFilters).toEqual([{field:'Region',selected:['West']},{field:'Date'}])
 expect(config.hiddenMembers?.row).toEqual([['B']])
 const saved=await applyWorkbookOperations(bytes,(await editPivotPlan(bytes,pivot.tablePath,config)).operations), reopened=(await readWorkbookPivots(saved))[0]!
 expect(reopened.pageFilters).toEqual(config.pageFilters)
 expect(Object.entries((await readWorkbook(saved)).sheets[0]!.cells).some(([address,c])=>/^H\d+$/.test(address)&&c.value===20)).toBe(true)
 const reset=pivotMemberFilterConfig(reopened,await readPivotFilterFields(saved,reopened),'Region',['East','West'])
 expect(reset.pageFilters?.[0]).toEqual({field:'Region'})
})

it('persists a native page slicer and synchronizes its selected cache items across refresh',async()=>{
 const {bytes,pivot}=await fixture(),fields=await readPivotFilterFields(bytes,pivot)
 const config=pivotMemberFilterConfig(pivot,fields,'Region',['West'])
 const filtered=await applyWorkbookOperations(bytes,(await editPivotPlan(bytes,pivot.tablePath,config)).operations)
 const saved=await applyWorkbookOperations(filtered,[{kind:'upsertPivotControl',request:{kind:'slicer',tablePath:pivot.tablePath,field:'Region',name:'Regions',anchor:{row:8,column:8}}}])
 const refreshed=await applyWorkbookOperations(saved,[{kind:'refreshPivotCaches'}])
 expect(await supportsOwnedPivotControls(refreshed)).toBe(true)
 expect(await readPivotControls(refreshed)).toHaveLength(1)
 expect(await (await createBufferEntrySource(refreshed)).readText('xl/slicerCaches/slicerCache1.xml')).toContain('<x14:i x="0" s="0"')
 expect((await readWorkbookPivots(refreshed))[0]!.pageFilters?.[0]?.selected).toEqual(['West'])
})

it('persists a native page timeline interval and excludes newly changed dates during refresh',async()=>{
 const {bytes,pivot}=await fixture(),fields=await readPivotFilterFields(bytes,pivot)
 const config=pivotTimelineFilterConfig(pivot,fields,'Date','2024-01-02','2024-01-03')
 const filtered=await applyWorkbookOperations(bytes,(await editPivotPlan(bytes,pivot.tablePath,config)).operations)
 const saved=await applyWorkbookOperations(filtered,[{kind:'upsertPivotControl',request:{kind:'timeline',tablePath:pivot.tablePath,field:'Date',name:'Dates',from:'2024-01-02',to:'2024-01-03',anchor:{row:8,column:8}}}])
 const changed=await applyCellEdits(saved,[{sheetName:'Sheet1',row:3,column:1,writeValue:true,cell:{value:45323}}])
 const refreshed=await applyWorkbookOperations(changed,[{kind:'refreshPivotCaches'}])
 expect(await supportsOwnedPivotControls(refreshed)).toBe(true)
 expect((await readWorkbookPivots(refreshed))[0]!.pageFilters).toEqual([{field:'Region',selected:['East']},{field:'Date',selected:['2024-01-02']}])
 expect(await readPivotControls(refreshed)).toEqual([expect.objectContaining({from:'2024-01-02',to:'2024-01-03'})])
})

it('offers page fields in the real filter modal and restores a saved slicer selection',async()=>{
 const {createPivotFilterDialog}=await import('./workbook-pivot-filters-dialog')
 const {bytes,pivot}=await fixture(),root=document.createElement('div');document.body.append(root)
 let saved=bytes
 const dialog=createPivotFilterDialog(root,async(config,path,control)=>{
  const operations=(await editPivotPlan(saved,path,config)).operations
  if(control)operations.push({kind:'upsertPivotControl',request:control})
  saved=await applyWorkbookOperations(saved,operations)
 })
 try {
  await dialog.open({bytes:saved,pivots:[pivot],mode:'slicer'})
  const chooser=root.querySelector<HTMLSelectElement>('[aria-label="筛选字段"]')!
  expect([...chooser.options].map(o=>o.value)).toContain('Region')
  chooser.value='Region';chooser.dispatchEvent(new Event('change'))
  expect([...root.querySelectorAll<HTMLInputElement>('[data-members] input:checked')].map(c=>c.value)).toEqual(['East'])
  root.querySelector<HTMLInputElement>('[data-native-control]')!.click()
  root.querySelector<HTMLButtonElement>('[data-action="all"]')!.click()
  root.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))
  await import('vitest').then(({vi})=>vi.waitFor(()=>expect(root.querySelector<HTMLElement>('[role="dialog"]')!.hidden).toBe(true)))
  await dialog.open({bytes:saved,pivots:await readWorkbookPivots(saved),mode:'slicer'})
  chooser.value='Region';chooser.dispatchEvent(new Event('change'))
  expect([...root.querySelectorAll<HTMLInputElement>('[data-members] input:checked')].map(c=>c.value)).toEqual(['East','West'])
  expect(await readPivotControls(saved)).toHaveLength(1)
 } finally {dialog.dispose();root.remove()}
})

it('includes blank report members and refuses empty or stale selections',async()=>{
 const {bytes,pivot}=await fixture()
 const changed=await applyCellEdits(bytes,[{sheetName:'Sheet1',row:4,column:0,writeValue:true,cell:{value:null}}])
 const fields=await readPivotFilterFields(changed,pivot)
 expect(fields.find(f=>f.name==='Region')!.members).toContainEqual({value:''})
 expect(pivotMemberFilterConfig(pivot,fields,'Region',['']).pageFilters?.[0]).toEqual({field:'Region',selected:['']})
 expect(()=>pivotMemberFilterConfig(pivot,fields,'Region',[])).toThrow('至少选择')
 expect(()=>pivotMemberFilterConfig(pivot,fields,'Region',['missing'])).toThrow('成员已变化')
})

it('uses the 1904 epoch for a native report-filter timeline',async()=>{
 const {assemblePackage}=await import('@sheets-web/xlsx-engine/zip')
 const {bytes}=await fixture(),zip=await createBufferEntrySource(bytes),xml=await zip.readText('xl/workbook.xml')
 const epoch=(await assemblePackage(bytes,{replaced:new Map([['xl/workbook.xml',xml.replace(/<workbookPr\b[^>]*(?:\/>|>\s*<\/workbookPr>)/,'').replace('<sheets>','<workbookPr date1904="1"/><sheets>')]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:['xl/workbook.xml']})).buffer
 const pivot=(await readWorkbookPivots(epoch))[0]!,fields=await readPivotFilterFields(epoch,pivot)
 expect(fields.find(f=>f.name==='Date')!.members[0]!.date).toBe('2028-01-02')
 const config=pivotTimelineFilterConfig(pivot,fields,'Date','2028-01-03','2028-01-04')
 const ops=(await editPivotPlan(epoch,pivot.tablePath,config)).operations
 ops.push({kind:'upsertPivotControl',request:{kind:'timeline',tablePath:pivot.tablePath,field:'Date',name:'Dates1904',from:'2028-01-03',to:'2028-01-04'}})
 const saved=await applyWorkbookOperations(epoch,ops)
 expect(await supportsOwnedPivotControls(saved)).toBe(true)
 expect((await readWorkbookPivots(saved))[0]!.pageFilters?.[1]?.selected).toEqual(['2028-01-03','2028-01-04'])
})

it('refuses refresh when all previously selected report members disappeared',async()=>{
 const {bytes}=await fixture()
 const changed=await applyCellEdits(bytes,[1,3].map(row=>({sheetName:'Sheet1',row,column:0,writeValue:true,cell:{value:'North'}}))),copy=changed.slice()
 await expect(applyWorkbookOperations(changed,[{kind:'refreshPivotCaches'}])).rejects.toThrow('selection is empty')
 expect(changed).toEqual(copy)
})
