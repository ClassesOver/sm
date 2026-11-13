import JSZip from 'jszip'
import { describe, expect, it } from 'vitest'
import { createBlankWorkbook } from '../src/blank'
import { applyChartAdditions } from '../src/chart-add'
import { readWorkbook } from '../src/workbook-read'

async function fixture(legend: 'none' | 'right' | 'left' | 'top' | 'bottom') {
 return applyChartAdditions(await createBlankWorkbook(), [{worksheetSheetName:'Sheet1',
  anchor:{fromRow:0,fromColumn:3,fromRowOffset:0,fromColumnOffset:0,toRow:9,toColumn:11,toRowOffset:0,toColumnOffset:0},
  chart:{chartType:'bar',title:'Sales',legend,series:[
   {name:'Revenue',categories:['Q1','Q2'],values:[10,20],valuesRef:'Sheet1!$B$2:$B$3',color:'#126B3A'},
   {name:'Costs',categories:['Q1','Q2'],values:[3,4],valuesRef:'Sheet1!$C$2:$C$3'},
  ]}}])
}
async function mutate(bytes: Uint8Array, change: (xml: string)=>string) {
 const zip=await JSZip.loadAsync(bytes),path='xl/charts/chart1.xml'
 zip.file(path,change(await zip.file(path)!.async('string')))
 return zip.generateAsync({type:'uint8array'})
}
const chart=async(bytes: Uint8Array)=>(await readWorkbook(bytes)).sheets[0]!.charts![0]!

describe('actual OOXML legend projection',()=>{
 it.each(['right','left','top','bottom'] as const)('retains %s legend position and source fill',async position=>{
  const result=await chart(await fixture(position))
  expect(result.legend).toEqual({position,overlay:false,hiddenEntries:[]})
  expect(result.series[0]!.color).toBe('#126B3A')
  expect(result.series[0]!.index).toBe(0)
 })
 it('does not invent a legend when the source has none',async()=>{
  expect((await chart(await fixture('none'))).legend).toBeUndefined()
 })
 it('separates reference identity from cached text and respects deleted entries',async()=>{
  const bytes=await mutate(await fixture('bottom'),xml=>xml
   .replace('<c:tx><c:v>Revenue</c:v></c:tx>',`<c:tx><c:strRef><c:f>'Sheet1'!$B$1</c:f><c:strCache><c:ptCount val="1"/><c:pt idx="0"><c:v>Cached &amp; Revenue</c:v></c:pt></c:strCache></c:strRef></c:tx>`)
   .replace('<c:legendPos val="b"/>','<c:legendPos val="tr"/><c:legendEntry><c:idx val="1"/><c:delete val="true"/></c:legendEntry>')
   .replace(/(<c:legend>[\s\S]*?)<c:overlay val="0"\/>/,'$1<c:overlay val="1"/>')
   .replace('<c:idx val="0"/>','<c:idx val="3"/>'))
  const result=await chart(bytes)
  expect(result.legend).toEqual({position:'top-right',overlay:true,hiddenEntries:[1]})
  expect(result.series[0]).toMatchObject({index:3,name:"'Sheet1'!$B$1",nameRef:"'Sheet1'!$B$1",nameCache:'Cached & Revenue'})
 })
 it('defaults an existing empty legend to right and does not steal point/line fills',async()=>{
  const bytes=await mutate(await fixture('right'),xml=>xml
   .replace(/<c:legend>[\s\S]*?<\/c:legend>/,'<c:legend/>')
   .replace(/<c:spPr>[\s\S]*?<\/c:spPr>/,'<c:spPr><a:ln><a:solidFill><a:srgbClr val="ABCDEF"/></a:solidFill></a:ln></c:spPr><c:dPt><c:idx val="0"/><c:spPr><a:solidFill><a:srgbClr val="FF0000"/></a:solidFill></c:spPr></c:dPt>'))
  const result=await chart(bytes)
  expect(result.legend).toEqual({position:'right',overlay:false,hiddenEntries:[]})
  expect(result.series[0]!.color).toBeUndefined()
 })
})
