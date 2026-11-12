import JSZip from 'jszip'
import {expect,it} from 'vitest'
import {createBlankWorkbook} from '../src/blank'
import {applyChartAdditions} from '../src/chart-add'
import {applyChartEdits} from '../src/rules'
import {readWorkbook} from '../src/workbook-read'

const STYLE='<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="1200" b="1"><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill></a:defRPr></a:pPr><a:endParaRPr/></a:p></c:txPr>'
const POINT='<c:dLbl><c:idx val="1"/><c:numFmt formatCode="0.00" sourceLinked="0"/><c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr b="0"/></a:pPr></a:p></c:txPr><c:dLblPos val="inEnd"/><c:showVal val="1"/></c:dLbl>'
async function source(style=STYLE,point=POINT){
 const raw=await applyChartAdditions(await createBlankWorkbook(),[{worksheetSheetName:'Sheet1',anchor:{fromRow:0,fromColumn:3,fromRowOffset:0,fromColumnOffset:0,toRow:9,toColumn:11,toRowOffset:0,toColumnOffset:0},chart:{chartType:'bar',title:'Style',dataLabels:'value',dataLabelPosition:'center',dataLabelFormat:'0.000',series:[{name:'S',categories:['A','B'],values:[10,20],valuesRef:'Sheet1!B2:B3'}]}}])
 const zip=await JSZip.loadAsync(raw),path='xl/charts/chart1.xml'
 zip.file(path,(await zip.file(path)!.async('string')).replace('<c:dLbls>',()=>'<c:dLbls>'+point).replace('<c:dLblPos val="ctr"/>',()=>style+'<c:dLblPos val="ctr"/>'))
 return zip.generateAsync({type:'uint8array'})
}
const model=async(bytes:Uint8Array)=>(await readWorkbook(bytes)).sheets[0]!.charts![0]!
it('reads plot typography and an explicit per-point bold reset without inheriting defaults in the reader',async()=>{
 const chart=await model(await source())
 expect(chart.dataLabels?.style).toEqual({sizePt:12,bold:true,color:'#FFFFFF'})
 expect(chart.dataLabels?.points?.[1]?.style).toEqual({bold:false})
})
it('reads endParaRPr only when no default run properties exist',async()=>{
 const chart=await model(await source('<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr sz="900" b="false"><a:solidFill><a:srgbClr val="a02040"/></a:solidFill></a:endParaRPr></a:p></c:txPr>',''))
 expect(chart.dataLabels?.style).toEqual({sizePt:9,bold:false,color:'#A02040'})
})
it('accepts an empty paired RGB element without treating it as a transform',async()=>{
 expect((await model(await source(STYLE.replace('<a:srgbClr val="FFFFFF"/>','<a:srgbClr val="FFFFFF"></a:srgbClr>'),''))).dataLabels?.style?.color).toBe('#FFFFFF')
})
it.each(['sz="NaN"','sz="0"','sz="400001"','b="maybe"'])(
 'does not invent typography for invalid properties %s',async attributes=>{
  expect((await model(await source(`<c:txPr><a:p><a:pPr><a:defRPr ${attributes}/></a:pPr></a:p></c:txPr>`,''))).dataLabels?.unsupported).toBe(true)
 })
it('does not substitute a default RGB for an unresolved theme or color transform',async()=>{
 for(const fill of ['<a:schemeClr val="tx1"/>','<a:srgbClr val="FFFFFF"><a:alpha val="50000"/></a:srgbClr>']){
  expect((await model(await source(`<c:txPr><a:p><a:pPr><a:defRPr><a:solidFill>${fill}</a:solidFill></a:defRPr></a:pPr></a:p></c:txPr>`,''))).dataLabels?.unsupported).toBe(true)
 }
})
it('preserves the root style and point XML exactly when editing the global label mode and details',async()=>{
 const before=await source(),after=await applyChartEdits(before,[{chartPath:'xl/charts/chart1.xml',dataLabels:'value',dataLabelPosition:'outside-end',dataLabelFormat:'0.0'}])
 const zip=await JSZip.loadAsync(after),xml=await zip.file('xl/charts/chart1.xml')!.async('string')
 expect(xml).toContain(STYLE);expect(xml).toContain(POINT)
 const chart=await model(after)
 expect(chart.dataLabels?.numberFormat).toBe('0.0');expect(chart.dataLabels?.position).toBe('outside-end')
 expect(chart.dataLabels?.points?.[1]?.numberFormat).toBe('0.00');expect(chart.dataLabels?.points?.[1]?.position).toBe('inside-end')
})
it('keeps point formats with a literal greater-than sign and preserves unrelated extension bytes',async()=>{
 const point=POINT.replace('0.00','[>1]0.00').replace('<c:numFmt','<c:tx><c:rich><a:p><a:r><a:t>💡</a:t></a:r></a:p></c:rich></c:tx><c:numFmt')
 const extension='<c:extLst><c:ext uri="source"><x:payload xmlns:x="urn:source">💡</x:payload></c:ext></c:extLst>'
 const raw=await source(STYLE,point),zip=await JSZip.loadAsync(raw),path='xl/charts/chart1.xml'
 zip.file(path,(await zip.file(path)!.async('string')).replace('</c:dLbls>',()=>extension+'</c:dLbls>'))
 const after=await applyChartEdits(await zip.generateAsync({type:'uint8array'}),[{chartPath:path,dataLabels:'value',dataLabelFormat:'0.0',dataLabelPosition:'center'}])
 const result=await JSZip.loadAsync(after),xml=await result.file(path)!.async('string')
 expect(xml).toContain(point);expect(xml).toContain(extension);expect(xml).toContain(STYLE)
})
