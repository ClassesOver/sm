import { expect, it } from 'vitest'
import { EMPTY_PIVOT_MODEL, addFieldToArea, moveChip, toggleField } from './vendor/genoffice-sheets-pivot/pivot-field-model'
import { pivotPaneConfig, pivotPaneModel } from './workbook-pivot-pane'
import type { PivotConfig } from './workbook-pivot'
const fields=[{label:'区域',colIndex:0},{label:'日期',colIndex:1},{label:'收入',colIndex:2,numeric:true}]
it('uses source numeric placement and removes all checked copies',()=>{
 const row=toggleField(EMPTY_PIVOT_MODEL,fields,0),value=toggleField(row,fields,2)
 expect(value.rows).toEqual([0]);expect(value.values).toEqual([{fieldIndex:2,agg:'sum'}])
 expect(toggleField(addFieldToArea(value,fields,2,'values'),fields,2).values).toEqual([])
})
it('counts same-area drop slots before removing the source chip',()=>{
 const model={...EMPTY_PIVOT_MODEL,rows:[0,1,2]}
 expect(moveChip(model,fields,{area:'rows',index:0},{area:'rows',index:2}).rows).toEqual([1,0,2])
 expect(moveChip(model,fields,{area:'rows',index:0},{area:'rows',index:3}).rows).toEqual([1,2,0])
 expect(moveChip(model,fields,{area:'rows',index:1},{area:'rows',index:2}).rows).toEqual([0,1,2])
})
it('keeps duplicate value settings with their chip and preserves multi-selection',()=>{
 const config:PivotConfig={name:'p',sourceSheetName:'s',sourceRange:'A1:C4',targetSheetName:'s',targetCell:'E1',rowFields:['区域'],columnFields:[],values:[{field:'收入',agg:'sum',numFmt:'0.00'},{field:'收入',agg:'average',showDataAs:'percentOfTotal'}],pageFilters:[{field:'日期',selected:['2025','2026']}]}
 const moved=moveChip(pivotPaneModel(config,fields),fields,{area:'values',index:0},{area:'values',index:2})
 const next=pivotPaneConfig(config,fields,moved)
 expect(next.values).toEqual([config.values[1],config.values[0]]);expect(next.pageFilters).toEqual(config.pageFilters)
})
it('preserves page members, range start, label/value filters and calculated formulas through ordinary pane edits',()=>{
 const config:PivotConfig={name:'p',sourceSheetName:'s',sourceRange:'A1:C4',targetSheetName:'s',targetCell:'E1',rowFields:['日期'],columnFields:[],pageFilters:[{field:'区域',selected:['东','西']}],values:[{field:'收入',agg:'sum',numFmt:'0.00'},{field:'单价',agg:'sum',formula:'收入/2'}],groupings:[{field:'日期',kind:'range',rangeStep:5,rangeStart:2000}],filters:[{kind:'label',field:'日期',op:'contains',value:'20'},{kind:'value',field:'日期',valueIndex:0,op:'top',count:3}]}
 const model=pivotPaneModel(config,fields),moved=moveChip(model,fields,{area:'values',index:0},{area:'values',index:2}),next=pivotPaneConfig(config,fields,moved)
 expect(next.pageFilters).toEqual(config.pageFilters);expect(next.groupings).toEqual(config.groupings);expect(next.values).toEqual([config.values[1],config.values[0]])
 expect(next.filters).toEqual([{kind:'label',field:'日期',op:'contains',value:'20'},{kind:'value',field:'日期',valueIndex:1,op:'top',count:3}])
})
