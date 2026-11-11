import { expect, it } from 'vitest'
import { createBlankWorkbook, applyCellEdits, createBufferEntrySource } from '@sheets-web/xlsx-engine'
import { applyWorkbookOperations } from '../../../reporting/workbook_engine/bridge/operations'
import { readPivotControls } from '../../../reporting/workbook_engine/packages/xlsx-engine/src/pivot-controls'
import { createPivotPlan, editPivotPlan, readWorkbookPivots } from './workbook-pivot'
import { pivotControlGeometryOperation, readPivotControlViews } from './workbook-pivot-controls'
import { NativeDraft } from './native-draft'

it('saves an owned native slicer through the operation bridge and keeps it synchronized across edits and refresh', async () => {
 const rows=[['Region','Amount'],['East',10],['West',20]]
 const source=await applyCellEdits(await createBlankWorkbook(),rows.flatMap((row,r)=>row.map((value,column)=>({sheetName:'Sheet1',row:r,column,writeValue:true,cell:{value}}))))
 const config={name:'Sales',sourceSheetName:'Sheet1',sourceRange:'A1:B3',targetSheetName:'Sheet1',targetCell:'F1',rowFields:['Region'],columnFields:[],values:[{field:'Amount',agg:'sum' as const}]}
 const created=await applyWorkbookOperations(source,(await createPivotPlan(source,config)).operations)
 const pivot=(await readWorkbookPivots(created))[0]!,request={kind:'slicer',tablePath:pivot.tablePath,field:'Region',name:'Regions'}
 const native=await applyWorkbookOperations(created,[{kind:'upsertPivotControl',request}])
 expect((await readWorkbookPivots(native))[0]!.readonlyReason).toBeUndefined()
 const plan=await editPivotPlan(native,pivot.tablePath,{...config,hiddenMembers:{row:[['West']],column:[]}})
 const filtered=await applyWorkbookOperations(native,plan.operations)
 expect(await readPivotControls(filtered)).toHaveLength(1)
 expect(await (await createBufferEntrySource(filtered)).readText('xl/slicerCaches/slicerCache1.xml')).toContain('<x14:i x="1" s="0"')
 const refreshed=await applyWorkbookOperations(filtered,[{kind:'refreshPivotCaches'}])
 expect(await readPivotControls(refreshed)).toHaveLength(1)
 expect(await (await createBufferEntrySource(refreshed)).readText('xl/slicerCaches/slicerCache1.xml')).toContain('<x14:i x="1" s="0"')
 await expect(applyWorkbookOperations(native,[{kind:'upsertPivotControl',request:{...request,unexpected:true}}])).rejects.toThrow()
}, 30000)

it('writes geometry alone without applying pending filters and rejects stale or invalid anchors', async () => {
 const rows=[['Region','Amount'],['East',10],['West',20]]
 const source=await applyCellEdits(await createBlankWorkbook(),rows.flatMap((row,r)=>row.map((value,column)=>({sheetName:'Sheet1',row:r,column,writeValue:true,cell:{value}}))))
 const config={name:'Sales',sourceSheetName:'Sheet1',sourceRange:'A1:B3',targetSheetName:'Sheet1',targetCell:'F1',rowFields:['Region'],columnFields:[],values:[{field:'Amount',agg:'sum' as const}],hiddenMembers:{row:[['West']],column:[]}}
 const created=await applyWorkbookOperations(source,(await createPivotPlan(source,config)).operations)
 const native=await applyWorkbookOperations(created,[{kind:'upsertPivotControl',request:{kind:'slicer',tablePath:'xl/pivotTables/pivotTable1.xml',field:'Region',name:'Regions',anchor:{row:0,column:9,width:192,height:260}}}])
 const view=(await readPivotControlViews(native))[0]!,anchor={row:4,column:12,width:320,height:180}
 const operation=await pivotControlGeometryOperation(native,view,anchor)
 expect(operation).toMatchObject({kind:'upsertPivotControl',request:{anchor}})
 // 原生草稿拒绝任何 undefined；直接引擎桥的 JSON 编码不能代替本地历史校验。
 expect(operation).toStrictEqual(JSON.parse(JSON.stringify(operation)))
 const draft = new NativeDraft({documentId:'geometry',revision:1,sourceSha256:'a'.repeat(64),scope:{database:'test',companyId:'test',userId:'test',threadId:'test'}},{getItem:()=>null,setItem(){},removeItem(){}})
 expect(()=>draft.setOperations([operation])).not.toThrow()
 const moved=await applyWorkbookOperations(native,[operation]), result=(await readPivotControls(moved))[0]!
 expect(result.anchor).toEqual(anchor)
 expect((await readWorkbookPivots(moved))[0]!.hiddenMembers).toEqual(view.pivot.hiddenMembers)
 const before=await createBufferEntrySource(native),after=await createBufferEntrySource(moved)
 expect(await after.readText(view.pivot.tablePath)).toBe(await before.readText(view.pivot.tablePath))
 await expect(pivotControlGeometryOperation(moved,view,anchor)).rejects.toThrow('已变化')
 await expect(pivotControlGeometryOperation(native,view,{...anchor,width:95})).rejects.toThrow()
},30000)
