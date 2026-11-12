import JSZip from 'jszip'
import {expect,it} from 'vitest'
import {createBlankWorkbook} from '../src/blank'
import {applyChartAdditions} from '../src/chart-add'
import {readWorkbook} from '../src/workbook-read'

async function fixture(category?:string,reverse=false){
 const bytes=await applyChartAdditions(await createBlankWorkbook(),[{worksheetSheetName:'Sheet1',
  anchor:{fromRow:0,fromColumn:3,fromRowOffset:0,fromColumnOffset:0,toRow:9,toColumn:11,toRowOffset:0,toColumnOffset:0},
  chart:{chartType:'bar',title:'Categories',series:[{name:'Values',categories:['A','B','C'],categoriesRef:'Sheet1!$A$2:$A$4',values:[3,6,9],valuesRef:'Sheet1!$B$2:$B$4'}]}}])
 const zip=await JSZip.loadAsync(bytes),path='xl/charts/chart1.xml'
 let xml=await zip.file(path)!.async('string')
 if(category!==undefined)xml=xml.replace(/<c:cat>[\s\S]*?<\/c:cat>/,()=>category)
 if(reverse)xml=xml.replace(/(<c:catAx>[\s\S]*?)<c:orientation val="minMax"\/>/,'$1<c:orientation val="maxMin"/>')
 zip.file(path,xml)
 return (await readWorkbook(await zip.generateAsync({type:'uint8array'}))).sheets[0]!.charts![0]!
}
it('retains the actual category reference and writer cache',async()=>{
 const chart=await fixture()
 expect(chart.series[0]!.categoriesRef).toBe('Sheet1!$A$2:$A$4')
 expect(chart.series[0]!.categories).toEqual(['A','B','C'])
})
it('keeps sparse string cache indices and decoded empty labels in place',async()=>{
 const chart=await fixture('<c:cat><c:strRef><c:f>Other!A1:A4</c:f><c:strCache><c:ptCount val="4"/><c:pt idx="2"><c:v>C &amp; D</c:v></c:pt><c:pt idx="0"><c:v>A</c:v></c:pt><c:pt idx="3"><c:v></c:v></c:pt></c:strCache></c:strRef></c:cat>')
 expect(chart.series[0]!.categories).toEqual(['A',null,'C & D',''])
})
it('reads literal numeric categories and their own number format',async()=>{
 const chart=await fixture('<c:cat><c:numLit><c:formatCode>0.0%</c:formatCode><c:ptCount val="2"/><c:pt idx="0"><c:v>0.1</c:v></c:pt><c:pt idx="1"><c:v>0.25</c:v></c:pt></c:numLit></c:cat>')
 expect(chart.series[0]!.categories).toEqual(['0.1','0.25'])
 expect(chart.series[0]!.categoryNumberFormat).toBe('0.0%')
 expect(chart.series[0]!.categoriesRef).toBeUndefined()
})
it.each([
 '<c:strLit><c:ptCount val="1000000000"/></c:strLit>',
 '<c:strLit><c:ptCount val="2"/><c:pt idx="0"><c:v>A</c:v></c:pt><c:pt idx="0"><c:v>B</c:v></c:pt></c:strLit>',
 '<c:multiLvlStrRef><c:f>Other!A1:B3</c:f><c:multiLvlStrCache/></c:multiLvlStrRef>',
])('does not flatten unsupported or unbounded category data: %s',async body=>{
 expect((await fixture('<c:cat>'+body+'</c:cat>')).series[0]!.categories).toEqual([])
})
it('reads reversal only from the actual linked category axis',async()=>{
 const chart=await fixture(undefined,true)
 expect(chart.axes?.category.reversed).toBe(true)
 expect(chart.axes?.value.scaling?.reversed).not.toBe(true)
})
