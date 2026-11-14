import { expect, it } from 'vitest'
import { createBlankWorkbook, applyCellEdits, readWorkbook } from '../src/index'
import { buildPivotLayout, pivotOutputArea } from '../src/pivot-layout'
import { addPivotTable, readPivotState, rebuildPivotOutput } from '../src/pivot-add'
import { createBufferEntrySource, assemblePackage } from '../src/zip'
import { upsertPivotControl, readPivotControls, supportsOwnedPivotControls, syncOwnedPivotControls, removePivotControl } from '../src/pivot-controls'
async function fixture(numericDates=false,twoDates=false){
 const rows=[['地区','日期','收入'],['东','2024-01-01',10],['西','2024-01-02',20],['北','2024-01-03',30]]
 if(numericDates)for(let r=1;r<rows.length;r++){rows[r]![1]=45291+r;if(twoDates)rows[r]![0]=45291+r}
 const bytes=await applyCellEdits(await createBlankWorkbook(),rows.flatMap((row,r)=>row.map((value,c)=>({sheetName:'Sheet1',row:r,column:c,writeValue:true,cell:{value},...(numericDates&&r>0&&(c===1||twoDates&&c===0)?{style:{numberFormat:'yyyy-mm-dd'}}:{})}))))
 const layout=buildPivotLayout(rows,{rowFields:['地区'],columnField:['日期'],values:[{field:'收入',agg:'sum'}]})
 return addPivotTable(bytes,{...layout.definition,colLevelItems:layout.definition.colLevelItems??[],colLines:layout.definition.colLines??[],worksheetSheetName:'Sheet1',sourceSheetName:'Sheet1',sourceArea:{startRow:0,endRow:3,startColumn:0,endColumn:2},name:'Sales',location:pivotOutputArea({row:5,column:5},layout)})
}
const request={kind:'slicer' as const,tablePath:'xl/pivotTables/pivotTable1.xml',field:'地区',name:'RegionSlicer',anchor:{row:1,column:12}}
it('creates native cache, control, anchor and workbook/worksheet relationship graphs',async()=>{
 const before=await fixture(),result=await upsertPivotControl(before,request),zip=await createBufferEntrySource(result)
 expect(await readPivotControls(result)).toEqual([expect.objectContaining({kind:'slicer',name:'RegionSlicer',field:'地区',tablePath:request.tablePath})])
 expect(await supportsOwnedPivotControls(result)).toBe(true)
 expect(await zip.readText('xl/slicerCaches/slicerCache1.xml')).toContain('<x14:items count="3">')
 expect(await zip.readText('xl/workbook.xml')).toContain('x14:slicerCaches')
 expect(await zip.readText('xl/worksheets/sheet1.xml')).toContain('x14:slicerList')
 expect(await zip.readText('xl/drawings/drawing1.xml')).toContain('http://schemas.microsoft.com/office/drawing/2010/slicer')
 expect(await zip.readText('xl/drawings/drawing1.xml')).toContain('<mc:Fallback>')
 expect((await readWorkbook(result)).sheets[0]!.cells.A2?.value).toBe('东')
 expect(await zip.readText('xl/styles.xml')).toBe(await (await createBufferEntrySource(before)).readText('xl/styles.xml'))
 const edited=await upsertPivotControl(result,{...request,caption:'地区选择'})
 expect(await readPivotControls(edited)).toHaveLength(1)
 expect(await (await createBufferEntrySource(edited)).readText('xl/slicers/slicer1.xml')).toContain('caption="地区选择"')
})
it('creates a native timeline with typed dates and interval state',async()=>{
 const result=await upsertPivotControl(await fixture(true),{...request,kind:'timeline',field:'日期',name:'DateTimeline',from:'2024-01-01',to:'2024-01-03'}),zip=await createBufferEntrySource(result)
 expect(await readPivotControls(result)).toEqual([expect.objectContaining({kind:'timeline',from:'2024-01-01',to:'2024-01-03'})])
 expect(await zip.readText('xl/timelineCaches/timelineCache1.xml')).toContain('startDate="2024-01-01T00:00:00"')
 expect(await zip.readText('xl/pivotCache/pivotCacheDefinition1.xml')).toContain('<d v="2024-01-01T00:00:00"/>')
 expect(await zip.readText('xl/drawings/drawing1.xml')).toContain('http://schemas.microsoft.com/office/drawing/2012/timeslicer')
 expect(await supportsOwnedPivotControls(result)).toBe(true)
})
it('rejects damaged native associations and refuses unsafe changes',async()=>{
 const result=await upsertPivotControl(await fixture(),request),zip=await createBufferEntrySource(result),path='xl/slicerCaches/slicerCache1.xml'
 const bad=(await assemblePackage(result,{replaced:new Map([[path,(await zip.readText(path)).replace(/pivotCacheId="\d+"/,'pivotCacheId="999"')]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer
 expect(await supportsOwnedPivotControls(bad)).toBe(false)
 await expect(upsertPivotControl(bad,request)).rejects.toThrow()
 await expect(upsertPivotControl(result,{...request,field:'不存在'})).rejects.toThrow()
})
it('synchronizes owned selections after rebuilding the pivot',async()=>{
 const before=await upsertPivotControl(await fixture(),request),zip=await createBufferEntrySource(before),state=readPivotState(await zip.readText(request.tablePath))!
 const modified=await rebuildPivotOutput(before,request.tablePath,'xl/pivotCache/pivotCacheDefinition1.xml',{...state,manualHiddenMembers:[{fieldIndex:0,members:['西']}]})
 const after=await syncOwnedPivotControls(before,modified,request.tablePath),final=await createBufferEntrySource(after)
 expect(await final.readText('xl/slicerCaches/slicerCache1.xml')).toContain('<x14:i x="1" s="0"')
 expect(await supportsOwnedPivotControls(after)).toBe(true)
})

it('synchronizes changed timeline intervals without retaining stale native filter state',async()=>{
 const before=await upsertPivotControl(await fixture(true),{...request,kind:'timeline',field:'日期',name:'DateTimeline',from:'2024-01-01',to:'2024-01-03'}),zip=await createBufferEntrySource(before),state=readPivotState(await zip.readText(request.tablePath))!
 const modified=await rebuildPivotOutput(before,request.tablePath,'xl/pivotCache/pivotCacheDefinition1.xml',{...state,manualHiddenMembers:[{fieldIndex:1,members:['45292']}]})
 const after=await syncOwnedPivotControls(before,modified,request.tablePath,{...request,kind:'timeline',field:'日期',name:'DateTimeline',from:'2024-01-02',to:'2024-01-03'})
 expect(await readPivotControls(after)).toEqual([expect.objectContaining({from:'2024-01-02',to:'2024-01-03'})])
 expect(await supportsOwnedPivotControls(after)).toBe(true)
})

it('rejects a timeline with damaged typed dates or a mismatched native filter',async()=>{
 const bytes=await upsertPivotControl(await fixture(true),{...request,kind:'timeline',field:'日期',name:'DateTimeline',from:'2024-01-01',to:'2024-01-03'}),zip=await createBufferEntrySource(bytes)
 for(const [path,from,to] of [['xl/pivotCache/pivotCacheDefinition1.xml','<d v="2024-01-01T00:00:00"/>','<d v="2030-01-01T00:00:00"/>'],[request.tablePath,'val="2024-01-01T00:00:00"','val="2030-01-01T00:00:00"']]){
  const bad=(await assemblePackage(bytes,{replaced:new Map([[path!, (await zip.readText(path!)).replace(from!,to!)]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path!]})).buffer
  expect(await supportsOwnedPivotControls(bad)).toBe(false)
 }
})

it('rejects text dates for native timelines while leaving source bytes unchanged',async()=>{const bytes=await fixture(),copy=bytes.slice();await expect(upsertPivotControl(bytes,{...request,kind:'timeline',field:'日期',name:'DateTimeline',from:'2024-01-01',to:'2024-01-03'})).rejects.toThrow('数值日期');expect(bytes).toEqual(copy)})

it('retains interval boundaries and filters newly added dates during synchronization',async()=>{
 const before=await upsertPivotControl(await fixture(true),{...request,kind:'timeline',field:'日期',name:'DateTimeline',from:'2024-01-01',to:'2024-01-31'}),zip=await createBufferEntrySource(before),state=readPivotState(await zip.readText(request.tablePath))!
 const changed=await applyCellEdits(before,[{sheetName:'Sheet1',row:3,column:1,writeValue:true,cell:{value:45323}}])
 const modified=await rebuildPivotOutput(changed,request.tablePath,'xl/pivotCache/pivotCacheDefinition1.xml',state)
 const after=await syncOwnedPivotControls(before,modified,request.tablePath),reopened=await createBufferEntrySource(after)
 expect(await readPivotControls(after)).toEqual([expect.objectContaining({from:'2024-01-01',to:'2024-01-31'})])
 expect(readPivotState(await reopened.readText(request.tablePath))!.manualHiddenMembers).toContainEqual({fieldIndex:1,members:['45323']})
})

it('preserves two native timelines across refresh and independent interval edits',async()=>{
 const first={...request,kind:'timeline' as const,field:'日期',name:'DateTimeline',from:'2024-01-01',to:'2024-01-31'}
 const second={...request,kind:'timeline' as const,field:'地区',name:'SecondTimeline',from:'2024-01-01',to:'2024-01-31'}
 const before=await upsertPivotControl(await upsertPivotControl(await fixture(true,true),first),second)
 const source=await createBufferEntrySource(before),state=readPivotState(await source.readText(request.tablePath))!
 const changed=await applyCellEdits(before,[
  {sheetName:'Sheet1',row:2,column:0,writeValue:true,cell:{value:45323}},
  {sheetName:'Sheet1',row:3,column:1,writeValue:true,cell:{value:45323}},
 ])
 const rebuilt=await rebuildPivotOutput(changed,request.tablePath,'xl/pivotCache/pivotCacheDefinition1.xml',state)
 const after=await syncOwnedPivotControls(before,rebuilt,request.tablePath)
 expect(await supportsOwnedPivotControls(after)).toBe(true)
 expect(await readPivotControls(after)).toEqual([
  expect.objectContaining(first),expect.objectContaining(second),
 ])
 const zip=await createBufferEntrySource(after),cache=await zip.readText('xl/pivotCache/pivotCacheDefinition1.xml'),table=await zip.readText(request.tablePath)
 expect((cache.match(/<d v=/g)??[])).toHaveLength(8)
 expect(table).toContain('<filters count="2">')
 expect(readPivotState(table)!.manualHiddenMembers).toEqual(expect.arrayContaining([
  {fieldIndex:0,members:['45323']},{fieldIndex:1,members:['45323']},
 ]))
 const edited=await syncOwnedPivotControls(after,after,request.tablePath,{...first,to:'2024-01-02'})
 expect(await readPivotControls(edited)).toEqual([
  expect.objectContaining({...first,to:'2024-01-02'}),expect.objectContaining(second),
 ])
 expect(await supportsOwnedPivotControls(edited)).toBe(true)
})

it('removes one owned timeline and its graph while retaining sibling controls and current member selection',async()=>{
 const first={...request,kind:'timeline' as const,field:'日期',name:'DateTimeline',from:'2024-01-01',to:'2024-01-31'}
 const second={...request,kind:'timeline' as const,field:'地区',name:'SecondTimeline',from:'2024-01-01',to:'2024-01-31'}
 const before=await upsertPivotControl(await upsertPivotControl(await fixture(true,true),first),second)
 const zip=await createBufferEntrySource(before),state=readPivotState(await zip.readText(request.tablePath))!
 const after=await removePivotControl(before,{tablePath:request.tablePath,name:first.name}),out=await createBufferEntrySource(after)
 expect(await readPivotControls(after)).toEqual([expect.objectContaining(second)])
 expect(await out.has('xl/timelines/timeline1.xml')).toBe(false)
 expect(await out.has('xl/timelineCaches/timelineCache1.xml')).toBe(false)
 expect(await out.readText('xl/workbook.xml')).not.toContain('DateTimeline_Cache')
 expect(await out.readText('xl/drawings/drawing1.xml')).not.toContain('name="DateTimeline"')
 expect(await out.readText(request.tablePath)).not.toContain('id="100001"')
 expect(await out.readText(request.tablePath)).toContain('id="100000"')
 expect(readPivotState(await out.readText(request.tablePath))!.manualHiddenMembers).toEqual(state.manualHiddenMembers)
 expect(await out.readText('xl/styles.xml')).toBe(await zip.readText('xl/styles.xml'))
 const cleared=await removePivotControl(after,{tablePath:request.tablePath,name:second.name}),final=await createBufferEntrySource(cleared)
 expect(await readPivotControls(cleared)).toEqual([])
 expect(await final.readText('xl/workbook.xml')).not.toContain('timelineCacheRef')
 expect(await final.readText('xl/worksheets/sheet1.xml')).not.toContain('timelineRef')
 expect(await final.readText('xl/pivotCache/pivotCacheDefinition1.xml')).not.toContain('timelinePivotCacheDefinition')
 expect(await final.readText(request.tablePath)).not.toContain('<filters')
})
it('rejects deleting an unknown name or a damaged owned control without changing source bytes',async()=>{
 const before=await upsertPivotControl(await fixture(),request),copy=before.slice(),zip=await createBufferEntrySource(before)
 await expect(removePivotControl(before,{tablePath:request.tablePath,name:'Missing'})).rejects.toThrow()
 const path='xl/_rels/workbook.xml.rels',bad=(await assemblePackage(before,{replaced:new Map([[path,(await zip.readText(path)).replace('/xl/slicerCaches/slicerCache1.xml','/xl/slicerCaches/missing.xml')]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer
 await expect(removePivotControl(bad,{tablePath:request.tablePath,name:request.name})).rejects.toThrow()
 const shared=(await assemblePackage(before,{replaced:new Map([[path,(await zip.readText(path)).replace('</Relationships>','<Relationship Id="rId999" Type="urn:test:owner" Target="/xl/slicerCaches/slicerCache1.xml"/></Relationships>')]]),added:new Map(),addedBinary:new Map(),removedEntries:[],addedEntries:[],touchedEntries:[path]})).buffer
 await expect(removePivotControl(shared,{tablePath:request.tablePath,name:request.name})).rejects.toThrow('其他关系引用')
 expect(before).toEqual(copy)
})

it('moves and resizes one control while preserving sibling geometry, caches and pivot state',async()=>{
 const timeline={...request,kind:'timeline' as const,field:'日期',name:'DateTimeline',from:'2024-01-01',to:'2024-01-31',anchor:{row:20,column:3,width:480,height:160}}
 const before=await upsertPivotControl(await upsertPivotControl(await fixture(true),request),timeline),zip=await createBufferEntrySource(before)
 const after=await upsertPivotControl(before,{...request,anchor:{row:4,column:12,width:320,height:180}}),out=await createBufferEntrySource(after)
 expect(await readPivotControls(after)).toEqual([expect.objectContaining({name:request.name,anchor:{row:4,column:12,width:320,height:180}}),expect.objectContaining(timeline)])
 for(const path of ['xl/slicerCaches/slicerCache1.xml','xl/timelines/timeline1.xml','xl/timelineCaches/timelineCache1.xml',request.tablePath,'xl/pivotCache/pivotCacheDefinition1.xml','xl/styles.xml'])expect(await out.readText(path)).toBe(await zip.readText(path))
 const drawing=await out.readText('xl/drawings/drawing1.xml')
 expect(drawing).toContain('<xdr:col>12</xdr:col>');expect(drawing).toContain('<xdr:row>4</xdr:row>');expect(drawing).toContain('cx="3048000" cy="1714500"')
 for(const anchor of [{row:-1,column:0},{row:0,column:16384},{row:0,column:0,width:95},{row:0,column:0,height:2001}])await expect(upsertPivotControl(before,{...request,anchor})).rejects.toThrow()
})

async function pageFixture() {
 const bytes=await fixture(true),zip=await createBufferEntrySource(bytes),state=readPivotState(await zip.readText(request.tablePath))!
 const layout=buildPivotLayout([['地区','日期','收入'],['东',45292,10],['西',45293,20],['北',45294,30]],{rowFields:['地区'],values:[{field:'收入',agg:'sum'}],pageFilters:[{field:'日期',selected:['45293','45294']}]})
 return rebuildPivotOutput(bytes,request.tablePath,'xl/pivotCache/pivotCacheDefinition1.xml',{...state,...layout.definition,columnFieldIndices:[],colLevelItems:[],colLines:[]})
}
it('creates and reads a native slicer on a report-filter dimension with selected cache members',async()=>{
 const bytes=await upsertPivotControl(await pageFixture(),{...request,field:'日期'}),zip=await createBufferEntrySource(bytes)
 expect(await supportsOwnedPivotControls(bytes)).toBe(true)
 const cache=await zip.readText('xl/slicerCaches/slicerCache1.xml')
 expect(cache).toContain('<x14:i x="0" s="0"')
 expect(cache).toContain('<x14:i x="1" s="1"')
})
it('keeps a report-filter timeline interval authoritative when source dates change',async()=>{
 const native=await upsertPivotControl(await pageFixture(),{...request,kind:'timeline',field:'日期',name:'PageDates',from:'2024-01-02',to:'2024-01-03'})
 const zip=await createBufferEntrySource(native),state=readPivotState(await zip.readText(request.tablePath))!
 const changed=await applyCellEdits(native,[{sheetName:'Sheet1',row:3,column:1,writeValue:true,cell:{value:45323}}])
 const rebuilt=await rebuildPivotOutput(changed,request.tablePath,'xl/pivotCache/pivotCacheDefinition1.xml',state)
 const saved=await syncOwnedPivotControls(native,rebuilt,request.tablePath),out=await createBufferEntrySource(saved)
 expect(readPivotState(await out.readText(request.tablePath))!.pageFilters).toEqual([{fieldIndex:1,selected:['45293']}])
 expect(await supportsOwnedPivotControls(saved)).toBe(true)
})
