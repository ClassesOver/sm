import JSZip from 'jszip'
import {expect,it} from 'vitest'
import {createBlankWorkbook} from '../src/blank'
import {applyChartAdditions} from '../src/chart-add'
import {readWorkbook} from '../src/workbook-read'

async function fixture(mode:'value'|'none'|'percent'|undefined='value',mutate?:(xml:string)=>string){
 const bytes=await applyChartAdditions(await createBlankWorkbook(),[{worksheetSheetName:'Sheet1',
  anchor:{fromRow:0,fromColumn:3,fromRowOffset:0,fromColumnOffset:0,toRow:9,toColumn:11,toRowOffset:0,toColumnOffset:0},
  chart:{chartType:'bar',title:'Labels',...(mode===undefined?{}:{dataLabels:mode}),...(mode==='value'?{dataLabelPosition:'inside-end' as const,dataLabelFormat:'"$"0.0'}:{}),
   series:[{name:'Values',categories:['A','B','C'],values:[3,6,9],valuesRef:'Sheet1!$B$2:$B$4'}]}}])
 const zip=await JSZip.loadAsync(bytes),path='xl/charts/chart1.xml'
 if(mutate)zip.file(path,mutate(await zip.file(path)!.async('string')))
 return (await readWorkbook(await zip.generateAsync({type:'uint8array'}))).sheets[0]!.charts![0]!
}
it('reads plot value labels, canonical position and decoded explicit number format',async()=>{
 expect((await fixture()).dataLabels).toMatchObject({showValue:true,position:'inside-end',numberFormat:'"$"0.0'})
})
it('keeps absent labels absent and an explicit off flag off',async()=>{
 // Passing undefined uses the function default, so remove the real plot block.
 const absent=await fixture('value',xml=>xml.replace(/<c:dLbls>[\s\S]*?<\/c:dLbls>/,''))
 expect(absent.dataLabels).toBeUndefined()
 const off=await fixture('value',xml=>xml.replace('<c:showVal val="1"/>','<c:showVal val="0"/>'))
 expect(off.dataLabels?.showValue).toBe(false)
})
it('keeps series settings separate from the plot and uses actual point indices',async()=>{
 const chart=await fixture('value',xml=>xml.replace('</c:ser>','<c:dLbls><c:dLbl><c:idx val="2"/><c:delete val="1"/></c:dLbl><c:dLbl><c:idx val="0"/><c:showVal val="0"/></c:dLbl><c:showVal val="1"/></c:dLbls></c:ser>'))
 expect(chart.dataLabels?.position).toBe('inside-end')
 expect(chart.series[0]!.dataLabels).toMatchObject({showValue:true,points:{2:{deleted:true},0:{showValue:false}}})
})
it.each([
 '<c:dLbl><c:idx val="0"/><c:tx><c:v>Custom</c:v></c:tx></c:dLbl>',
 '<c:dLbl><c:idx val="0"/><c:layout><c:manualLayout/></c:layout></c:dLbl>',
])('marks custom point text/layout unsupported rather than replacing it with a number',async point=>{
 const chart=await fixture('value',xml=>xml.replace('<c:dLbls>',()=>'<c:dLbls>'+point))
 expect(chart.dataLabels?.points?.[0]?.unsupported).toBe(true)
})
it('does not reinterpret percent labels as raw values',async()=>{
 expect((await fixture('percent')).dataLabels?.unsupported).toBe(true)
})
it('keeps the value cache format separate from the category and explicit label formats',async()=>{
 const chart=await fixture('value',xml=>xml.replace(/(<c:val>[\s\S]*?<c:formatCode>)General/,(_all,prefix)=>prefix+'0.0%'))
 expect(chart.series[0]!.numberFormat).toBe('0.0%')
 expect(chart.dataLabels?.numberFormat).toBe('"$"0.0')
})
it.each(['<c:dLblPos val="bestFit"/>','<c:dLbl><c:idx val="0"/></c:dLbl><c:dLbl><c:idx val="0"/></c:dLbl>'])(
 'declines unknown placement or duplicate point identity: %s',async extra=>{
  const chart=await fixture('value',xml=>xml.replace('<c:dLbls>',()=>'<c:dLbls>'+extra))
  expect(chart.dataLabels?.unsupported).toBe(true)
 })
