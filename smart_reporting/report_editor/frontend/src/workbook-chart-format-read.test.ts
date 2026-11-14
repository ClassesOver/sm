import {expect,it} from 'vitest'
import {createBlankWorkbook,readWorkbook} from '@sheets-web/xlsx-engine'
import {applyChartAdditions} from '@sheets-web/xlsx-engine/chart-add'
import {applyWorkbookOperations} from '../../../reporting/workbook_engine/bridge/operations'
const anchor={fromRow:0,fromColumn:4,fromRowOffset:0,fromColumnOffset:0,toRow:12,toColumn:12,toRowOffset:0,toColumnOffset:0}
it.each(['column','doughnut','pie','line','area'] as const)('reads full %s format from the real existing writer without inventing defaults',async chartType=>{
 let bytes=await applyChartAdditions(await createBlankWorkbook(),[{worksheetSheetName:'Sheet1',anchor,chart:{chartType,title:'实际格式',series:[{name:'收入',valuesRef:'Sheet1!B2:B4',values:[3,0,7],categories:['甲','空','乙']}]}}])
 const path=(await readWorkbook(bytes)).sheets[0]!.charts![0]!.chartPath
 if(chartType==='line'||chartType==='area'){bytes=await applyWorkbookOperations(bytes,[{kind:'applyChartEdits',edits:[{chartPath:path,dataLabels:'value',dataLabelFormat:'0.00',valueAxis:{min:-5,max:25},seriesColors:{0:'#123456'},pointColors:{0:{2:'#abcdef'}}}]}]);expect((await readWorkbook(bytes)).sheets[0]!.charts![0]).toMatchObject({dataLabels:{showValue:true,numberFormat:'0.00'},series:[{color:'#123456',pointColors:{2:'#ABCDEF'}}]});return}
 bytes=await applyWorkbookOperations(bytes,[{kind:'applyChartEdits',edits:[{chartPath:path,...(chartType==='column'?{gapWidthPct:230,valueAxis:{min:-5,max:25}}:{explosionPct:20,pointExplosions:{'2':45},...(chartType==='doughnut'?{holeSizePct:70}:{})})}]}])
 const c=(await readWorkbook(bytes)).sheets[0]!.charts![0]!
 if(chartType==='column'){expect(c).toMatchObject({gapWidthPct:230,axes:{value:{scaling:{min:-5,max:25}}}})}
 else {expect(c.series[0]).toMatchObject({explosionPct:20,pointExplosions:{2:45}});if(chartType==='doughnut')expect(c).toMatchObject({holeSizePct:70})}
})
