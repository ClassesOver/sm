import {expect,it} from 'vitest'
import {applyCellEdits,createBlankWorkbook,createBufferEntrySource,readWorkbook} from '@sheets-web/xlsx-engine'
import {assemblePackage} from '@sheets-web/xlsx-engine/zip'
import {applyWorkbookOperations} from '../../../reporting/workbook_engine/bridge/operations'
import {createPivotPlan,readWorkbookPivots} from './workbook-pivot'
import {readPivotFilterFields} from './workbook-pivot-filters'

it.each([['identifier',1,'0000',false,'0001'],['date1900',45292,'yyyy-mm-dd',false,'2024-01-01'],['date1904',0,'yyyy-mm-dd',true,'1904-01-01']] as const)('persists formatted %s dimension identity and numeric measures',async(_,value,pattern,epoch,expected)=>{
 let bytes=await applyCellEdits(await createBlankWorkbook(),[['Code','Amount'],[value,2]].flatMap((row,r)=>row.map((value,c)=>({sheetName:'Sheet1',row:r,column:c,writeValue:true,cell:{value},...(r>0?{style:{numberFormat:c===0?pattern:'$0.00'}}:{})}))))
 if(epoch){const zip=await createBufferEntrySource(bytes),xml=await zip.readText('xl/workbook.xml');bytes=(await assemblePackage(bytes,{replaced:new Map([['xl/workbook.xml',xml.replace('<sheets>','<workbookPr date1904="1"/><sheets>')]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:['xl/workbook.xml']})).buffer}
 const plan=await createPivotPlan(bytes,{name:'Formats',sourceSheetName:'Sheet1',sourceRange:'A1:B2',targetSheetName:'Sheet1',targetCell:'D1',rowFields:['Code'],columnFields:[],values:[{field:'Amount',agg:'sum'}]})
 expect(plan.addition.rowLevelItems).toEqual([[expected]])
 const saved=await applyWorkbookOperations(bytes,plan.operations),pivot=(await readWorkbookPivots(saved))[0]!,wb=await readWorkbook(saved),zip=await createBufferEntrySource(saved)
 expect(wb.sheets[0]!.cells.D2?.value).toBe(expected);expect(wb.sheets[0]!.cells.E2?.value).toBe(2)
 expect(wb.sheets[0]!.cells.A2?.value).toBe(value)
 expect(await zip.readText('xl/pivotCache/pivotCacheRecords1.xml')).toContain('<r><x v="0"/><n v="2"/></r>')
 expect((await readPivotFilterFields(saved,pivot)).find(f=>f.name==='Code')!.members).toEqual([{value:expected,...(pattern==='yyyy-mm-dd'?{date:expected}:{})}])
})

it('maps formatted date members back to raw numeric dates for native timelines',async()=>{
 const {pivotTimelineFilterConfig}=await import('./workbook-pivot-filters'),{editPivotPlan}=await import('./workbook-pivot')
 const {supportsOwnedPivotControls}=await import('@sheets-web/xlsx-engine/pivot-controls')
 const source=await applyCellEdits(await createBlankWorkbook(),[['Date','Amount'],[45292,2],[45293,3]].flatMap((row,r)=>row.map((value,c)=>({sheetName:'Sheet1',row:r,column:c,writeValue:true,cell:{value},...(r>0&&c===0?{style:{numberFormat:'yyyy-mm-dd'}}:{})}))))
 const bytes=await applyWorkbookOperations(source,(await createPivotPlan(source,{name:'Dates',sourceSheetName:'Sheet1',sourceRange:'A1:B3',targetSheetName:'Sheet1',targetCell:'D1',rowFields:['Date'],columnFields:[],values:[{field:'Amount',agg:'sum'}]})).operations)
 const pivot=(await readWorkbookPivots(bytes))[0]!,fields=await readPivotFilterFields(bytes,pivot),config=pivotTimelineFilterConfig(pivot,fields,'Date','2024-01-02','2024-01-02')
 const operations=(await editPivotPlan(bytes,pivot.tablePath,config)).operations
 operations.push({kind:'upsertPivotControl',request:{kind:'timeline',tablePath:pivot.tablePath,field:'Date',name:'Dates',from:'2024-01-02',to:'2024-01-02'}})
 const saved=await applyWorkbookOperations(bytes,operations)
 expect(await supportsOwnedPivotControls(saved)).toBe(true)
})

it('offers formatted numeric base members in the real value settings picker',async()=>{
 const {createPivotDialog}=await import('./workbook-pivot-dialog'),{vi}=await import('vitest')
 const bytes=await applyCellEdits(await createBlankWorkbook(),[['Code','Amount'],[1,2],[2,3]].flatMap((row,r)=>row.map((value,c)=>({sheetName:'Sheet1',row:r,column:c,writeValue:true,cell:{value},...(r>0&&c===0?{style:{numberFormat:'0000'}}:{})}))))
 const source=await applyWorkbookOperations(bytes,(await createPivotPlan(bytes,{name:'Codes',sourceSheetName:'Sheet1',sourceRange:'A1:B3',targetSheetName:'Sheet1',targetCell:'D1',rowFields:['Code'],columnFields:[],values:[{field:'Amount',agg:'sum',showDataAs:'percentOf',baseField:'Code',baseItem:'0001'}]})).operations)
 const root=document.body.appendChild(document.createElement('div')),dialog=createPivotDialog(root,async()=>{})
 try{
  await dialog.open({bytes:source,sourceSheetName:'Sheet1',sourceRange:'A1:B3',targetCell:'D1',pivots:await readWorkbookPivots(source)})
  root.querySelector<HTMLButtonElement>('[data-pivot-area="values"] button[aria-haspopup="menu"]')!.click()
  await vi.waitFor(()=>expect(root.querySelector('[role="menu"]')).not.toBeNull())
  Array.from(root.querySelectorAll<HTMLButtonElement>('[role="menu"] button')).find(b=>b.textContent==='值字段设置…')!.click()
  await vi.waitFor(()=>expect(root.querySelector('[aria-label="值字段设置：Amount"]')).not.toBeNull())
  const settings=root.querySelector<HTMLElement>('[aria-label="值字段设置：Amount"]')!
  const label=Array.from(settings.querySelectorAll('label')).find(l=>l.textContent?.startsWith('基项'))!
  label.querySelector<HTMLButtonElement>('button.gs-dd-btn')!.click()
  await vi.waitFor(()=>expect(Array.from(settings.querySelectorAll('[role="option"]')).map(o=>o.getAttribute('data-value'))).toEqual(['0001','0002']))
 }finally{dialog.dispose();root.remove()}
})

it('keeps legacy raw member identities when refreshing an explicitly unprojected pivot',async()=>{
 const source=await applyCellEdits(await createBlankWorkbook(),[['Code','Amount'],[1,2]].flatMap((row,r)=>row.map((value,c)=>({sheetName:'Sheet1',row:r,column:c,writeValue:true,cell:{value},...(r>0&&c===0?{style:{numberFormat:'0000'}}:{})}))))
 const config={name:'Legacy',dimensionFormatProjection:false,sourceSheetName:'Sheet1',sourceRange:'A1:B2',targetSheetName:'Sheet1',targetCell:'D1',rowFields:['Code'],columnFields:[],values:[{field:'Amount',agg:'sum' as const}]}
 const bytes=await applyWorkbookOperations(source,(await createPivotPlan(source,config)).operations)
 expect((await readWorkbook(bytes)).sheets[0]!.cells.D2?.value).toBe('1')
 const zip=await createBufferEntrySource(bytes),path='xl/pivotTables/pivotTable1.xml',xml=await zip.readText(path)
 const legacy=(await assemblePackage(bytes,{replaced:new Map([[path,xml.replace(/&quot;dimensionFormatProjection&quot;:false,?/,'')]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer
 expect((await readWorkbookPivots(legacy))[0]!.dimensionFormatProjection).toBe(false)
 const refreshed=await applyWorkbookOperations(legacy,[{kind:'refreshPivotCaches'}])
 expect((await readWorkbook(refreshed)).sheets[0]!.cells.D2?.value).toBe('1')
})

it.each([['row','0000',1,'0001'],['column','0000',1,'0001'],['row','yyyy-mm-dd',45292,'2024-01-01'],['column','yyyy-mm-dd',45292,'2024-01-01']] as const)('uses inherited %s %s formats in the actual plan and saved members',async(kind,pattern,value,expected)=>{
 const source=await applyCellEdits(await createBlankWorkbook(),[['Code','Amount'],[value,2]].flatMap((row,r)=>row.map((value,c)=>({sheetName:'Sheet1',row:r,column:c,writeValue:true,cell:{value},...(r>0&&c===0?{style:{numberFormat:pattern}}:{})}))))
 const zip=await createBufferEntrySource(source),path='xl/worksheets/sheet1.xml',xml=await zip.readText(path),cell=xml.match(/<c\b[^>]*r="A2"[^>]*>/)![0],style=cell.match(/\bs="(\d+)"/)![1]
 let next=xml.replace(cell,cell.replace(/\s+s="\d+"/,''));next=kind==='row'?next.replace(/<row\b[^>]*r="2"[^>]*>/,tag=>tag.replace('>',` s="${style}" customFormat="1">`)):next.replace('<sheetData>',`<cols><col min="1" max="1" style="${style}"/></cols><sheetData>`)
 const bytes=(await assemblePackage(source,{replaced:new Map([[path,next]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer
 const plan=await createPivotPlan(bytes,{name:'Inherited',sourceSheetName:'Sheet1',sourceRange:'A1:B2',targetSheetName:'Sheet1',targetCell:'D1',rowFields:['Code'],columnFields:[],values:[{field:'Amount',agg:'sum'}]})
 expect(plan.addition.rowLevelItems).toEqual([[expected]])
 const saved=await applyWorkbookOperations(bytes,plan.operations),pivot=(await readWorkbookPivots(saved))[0]!
 expect((await readWorkbook(saved)).sheets[0]!.cells.D2?.value).toBe(expected)
 expect((await readPivotFilterFields(saved,pivot))[0]!.members).toEqual([{value:expected,...(pattern==='yyyy-mm-dd'?{date:expected}:{})}])
})
