import JSZip from 'jszip'
import { expect, it } from 'vitest'
import { createBlankWorkbook } from '../src/blank'
import { applyChartAdditions } from '../src/chart-add'
import { applyChartEdits } from '../src/rules'
import { readWorkbook } from '../src/workbook-read'

async function fixture() {
 return applyChartAdditions(await createBlankWorkbook(),[{worksheetSheetName:'Sheet1',
  anchor:{fromRow:0,fromColumn:3,fromRowOffset:0,fromColumnOffset:0,toRow:9,toColumn:11,toRowOffset:0,toColumnOffset:0},
  chart:{chartType:'bar',title:'Range',valueAxis:{min:2,max:8},series:[{name:'Values',categories:['A','B'],values:[3,6],valuesRef:'Sheet1!$B$2:$B$3'}]}}])
}
const chart=async(bytes: Uint8Array)=>(await readWorkbook(bytes)).sheets[0]!.charts![0]!
async function scaling(content:string) {
 const zip=await JSZip.loadAsync(await fixture()),path='xl/charts/chart1.xml'
 zip.file(path,(await zip.file(path)!.async('string')).replace(/(<c:valAx>[\s\S]*?)<c:scaling>[\s\S]*?<\/c:scaling>/,(_all,prefix)=>prefix+'<c:scaling>'+content+'</c:scaling>'))
 return zip.generateAsync({type:'uint8array'})
}
async function scatterAxesFixture() {
 const bytes=await applyChartAdditions(await createBlankWorkbook(),[{worksheetSheetName:'Sheet1',
  anchor:{fromRow:0,fromColumn:3,fromRowOffset:0,fromColumnOffset:0,toRow:9,toColumn:11,toRowOffset:0,toColumnOffset:0},
  chart:{chartType:'scatter',title:'XY axes',series:[{name:'XY',categories:['-20','0','20'],categoriesRef:'Sheet1!$A$2:$A$4',values:[-20,0,20],valuesRef:'Sheet1!$B$2:$B$4'}]}}])
 const zip=await JSZip.loadAsync(bytes),path='xl/charts/chart1.xml',xml=await zip.file(path)!.async('string')
 const plot=xml.match(/<c:scatterChart>([\s\S]*?)<\/c:scatterChart>/)![1]!
 const ids=[...plot.matchAll(/<c:axId val="(\d+)"\/>/g)].map(match=>match[1]!)
 const axes=[...xml.matchAll(/<c:valAx>[\s\S]*?<\/c:valAx>/g)].map(match=>match[0])
 expect(ids).toHaveLength(2);expect(axes).toHaveLength(2)
 const linked=axes.map(axis=>{
  const axisId=axis.match(/<c:axId val="(\d+)"\/>/)![1]!,isX=axisId===ids[0]
  return axis.replace('<c:scaling><c:orientation val="minMax"/></c:scaling>',
   '<c:scaling><c:orientation val="maxMin"/><c:max val="10"/><c:min val="-10"/></c:scaling>')
   .replace('<c:delete val="0"/>',`<c:delete val="${isX?'1':'0'}"/>`)
   .replace('</c:valAx>',`<c:majorUnit val="10"/></c:valAx>`)
 })
 zip.file(path,xml.replace(axes.join(''),linked.reverse().join('')))
 return zip.generateAsync({type:'uint8array'})
}
it('reads min/max only from the plot-linked value axis',async()=>{
 const result=await chart(await fixture())
 expect(result.axes?.value.scaling).toEqual({min:2,max:8,reversed:false})
 expect(result.axes?.category.scaling).toBeUndefined()
})
it('maps scatter X and Y value axes by scatter axId order, not XML order',async()=>{
 const result=await chart(await scatterAxesFixture())
 expect(result.axes?.category).toMatchObject({hidden:true,scaling:{min:-10,max:10,majorUnit:10,reversed:true}})
 expect(result.axes?.value).toMatchObject({hidden:false,scaling:{min:-10,max:10,majorUnit:10,reversed:true}})
 expect(result.series[0]).toMatchObject({xValuesRef:'Sheet1!$A$2:$A$4',valuesRef:'Sheet1!$B$2:$B$4'})
})
it('returns to automatic bounds after explicit null removal',async()=>{
 const reset=await applyChartEdits(await fixture(),[{chartPath:'xl/charts/chart1.xml',valueAxis:{min:null,max:null}}])
 expect((await chart(reset)).axes?.value.scaling).toBeUndefined()
})
it('keeps single bounds and reverse orientation',async()=>{
 const result=await chart(await scaling('<c:orientation val="maxMin"/><c:min val="-2.5e1"/>'))
 expect(result.axes?.value.scaling).toEqual({min:-25,reversed:true})
})
it.each(['<c:min val="NaN"/>','<c:max val="Infinity"/>','<c:min val=""/>','<c:min val="5"/><c:max val="2"/>','<c:orientation val="unknown"/>'])(
 'does not silently reinterpret invalid scaling as auto: %s',async xml=>{
  expect((await chart(await scaling(xml))).axes?.value.scaling?.unsupported).toBe('invalid')
 })
it('recognizes logarithmic axes without claiming a linear rendering',async()=>{
 expect((await chart(await scaling('<c:logBase val="10"/><c:min val="1"/><c:max val="100"/>'))).axes?.value.scaling?.unsupported).toBe('logarithmic')
})
it('marks explicit scaling unavailable when axis ownership is ambiguous',async()=>{
 const zip=await JSZip.loadAsync(await fixture()),path='xl/charts/chart1.xml'
 zip.file(path,(await zip.file(path)!.async('string')).replace(/(<c:catAx>[\s\S]*?<\/c:catAx>)/,'$1$1'))
 const result=await chart(await zip.generateAsync({type:'uint8array'}))
 expect(result.axes).toBeUndefined();expect(result.valueScaleUnavailable).toBe(true)
})

it('reads value-axis major unit and decoded number format without borrowing the category format',async()=>{
 const zip=await JSZip.loadAsync(await fixture()),path='xl/charts/chart1.xml'
 zip.file(path,(await zip.file(path)!.async('string'))
  .replace('<c:valAx>',()=>'<c:valAx><c:majorUnit val="0.5"/><c:numFmt formatCode="&quot;$&quot;0.00" sourceLinked="0"/>')
  .replace('<c:catAx>','<c:catAx><c:numFmt formatCode="0%" sourceLinked="0"/>'))
 const result=await chart(await zip.generateAsync({type:'uint8array'}))
 expect(result.axes?.value.scaling).toEqual({min:2,max:8,majorUnit:0.5,reversed:false})
 expect(result.axes?.value.numberFormat).toBe('"$"0.00')
})
it.each(['0','-1','NaN','Infinity'])('does not silently treat invalid major unit %s as automatic',async unit=>{
 const zip=await JSZip.loadAsync(await fixture()),path='xl/charts/chart1.xml'
 zip.file(path,(await zip.file(path)!.async('string')).replace('<c:valAx>',`<c:valAx><c:majorUnit val="${unit}"/>`))
 expect((await chart(await zip.generateAsync({type:'uint8array'}))).axes?.value.scaling?.unsupported).toBe('invalid')
})
