import JSZip from 'jszip'
import { expect, it } from 'vitest'
import { createBlankWorkbook } from '../src/blank'
import { applyChartAdditions } from '../src/chart-add'
import { readCharts } from '../src/chart-read'

async function fixture(theme=false) {
 const bytes=await applyChartAdditions(await createBlankWorkbook(),[{worksheetSheetName:'Sheet1',
  anchor:{fromRow:0,fromColumn:3,fromRowOffset:0,fromColumnOffset:0,toRow:9,toColumn:11,toRowOffset:0,toColumnOffset:0},
  chart:{chartType:'scatter',title:'XY style',series:[
   {name:'Styled',categories:['1','2','3'],categoriesRef:'Sheet1!$A$2:$A$4',values:[3,6,9],valuesRef:'Sheet1!$B$2:$B$4'},
  ]}}])
 const zip=await JSZip.loadAsync(bytes)
 if(theme){
  zip.file('xl/theme/theme1.xml','<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:themeElements><a:clrScheme name="Custom">'+
   [['dk1','000000'],['lt1','FFFFFF'],['dk2','44546A'],['lt2','E7E6E6'],['accent1','136B4A'],['accent2','A02040'],['accent3','223344'],['accent4','654321'],['accent5','AABBCC'],['accent6','123456'],['hlink','0563C1'],['folHlink','954F72']].map(([name,color])=>`<a:${name}><a:srgbClr val="${color}"/></a:${name}>`).join('')+'</a:clrScheme></a:themeElements></a:theme>')
  const rels='xl/_rels/workbook.xml.rels'
  zip.file(rels,(await zip.file(rels)!.async('string')).replace('</Relationships>','<Relationship Id="theme" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/></Relationships>'))
 }
 return zip
}
async function chart(change:(xml:string)=>string,theme=false) {
 const zip=await fixture(theme),path='xl/charts/chart1.xml'
 zip.file(path,change(await zip.file(path)!.async('string')))
 return (await readCharts(await zip.generateAsync({type:'uint8array'}),'xl/worksheets/sheet1.xml'))[0]!
}

it('reads scatter plot connectivity and the series line theme color, width, noFill, and marker symbol',async()=>{
 const result=await chart(xml=>xml
  .replace('<c:scatterStyle val="lineMarker"/>','<c:scatterStyle val="lineMarker"/>')
  .replace(/<c:spPr>([\s\S]*?)<\/c:spPr>/,'<c:spPr><a:ln w="19050"><a:solidFill><a:schemeClr val="accent1"/></a:solidFill></a:ln></c:spPr>')
  .replace('</c:yVal>','</c:yVal><c:smooth val="0"/><c:marker><c:symbol val="diamond"/></c:marker>'),true)
 expect(result.scatterStyle).toBe('lineMarker')
 expect(result.series[0]).toMatchObject({lineColor:'#136B4A',lineWidth:2,marker:'diamond'})
})

it('keeps explicit noFill and marker none as distinct scatter series states',async()=>{
 const result=await chart(xml=>xml
  .replace(/<c:spPr>[\s\S]*?<\/c:spPr>/,'<c:spPr><a:ln><a:noFill/></a:ln></c:spPr>')
  .replace('</c:yVal>','</c:yVal><c:marker><c:symbol val="none"/></c:marker>'))
 expect(result.series[0]).toMatchObject({lineColor:'none',marker:'none'})
})

it('does not invent series line or marker overrides when the OOXML omits them',async()=>{
 const result=await chart(xml=>xml.replace(/<c:spPr>[\s\S]*?<\/c:spPr>/,'').replace(/<c:marker>[\s\S]*?<\/c:marker>/g,''))
 expect(result.scatterStyle).toBe('lineMarker')
 expect(result.series[0]).not.toHaveProperty('lineColor')
 expect(result.series[0]).not.toHaveProperty('lineWidth')
 expect(result.series[0]).not.toHaveProperty('marker')
})

it('preserves an explicitly zero-width scatter series line',async()=>{
 const result=await chart(xml=>xml.replace(/<a:ln\b[^>]*>/,'<a:ln w="0">'))
 expect(result.series[0]!.lineWidth).toBe(0)
})
