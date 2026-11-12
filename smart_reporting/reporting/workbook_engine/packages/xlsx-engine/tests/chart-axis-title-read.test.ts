import JSZip from 'jszip'
import { expect, it } from 'vitest'
import { createBlankWorkbook } from '../src/blank'
import { applyChartAdditions } from '../src/chart-add'
import { applyChartEdits } from '../src/rules'
import { readWorkbook } from '../src/workbook-read'

async function fixture(kind: 'column' | 'bar' = 'column') {
 return applyChartAdditions(await createBlankWorkbook(), [{worksheetSheetName:'Sheet1',
  anchor:{fromRow:0,fromColumn:3,fromRowOffset:0,fromColumnOffset:0,toRow:9,toColumn:11,toRowOffset:0,toColumnOffset:0},
  chart:{chartType:kind,title:'Main title',axisTitles:{category:'Quarter & year',value:'Amount (USD)'},series:[
   {name:'Revenue',categories:['Q1','Q2'],values:[10,20],valuesRef:'Sheet1!$B$2:$B$3'},
  ]}}])
}
async function mutate(bytes: Uint8Array, change: (xml: string)=>string) {
 const zip=await JSZip.loadAsync(bytes),path='xl/charts/chart1.xml'
 zip.file(path,change(await zip.file(path)!.async('string')))
 return zip.generateAsync({type:'uint8array'})
}
const chart=async(bytes: Uint8Array)=>(await readWorkbook(bytes)).sheets[0]!.charts![0]!

it.each(['column','bar'] as const)('reads linked %s axis roles without confusing the main title',async kind=>{
 const result=await chart(await fixture(kind))
 expect(result.title).toBe('Main title')
 expect(result.axes?.category).toMatchObject({hidden:false,title:'Quarter & year',position:'bottom'})
 expect(result.axes?.value).toMatchObject({hidden:false,title:'Amount (USD)',position:'left'})
 expect(result.axes!.category.id).not.toBe(result.axes!.value.id)
})
it('does not promote an axis title to the absent chart title',async()=>{
 const result=await chart(await mutate(await fixture(),xml=>xml.replace(/<c:title>[\s\S]*?<\/c:title>/,'')))
 expect(result.title).toBeUndefined()
 expect(result.axes?.category.title).toBe('Quarter & year')
})
it('keeps cached references, rich runs, hidden flags and opposite-side positions scoped to the axes',async()=>{
 const result=await chart(await mutate(await fixture(),xml=>xml
  .replace(/(<c:catAx>[\s\S]*?)<c:delete val="0"\/>/,'$1<c:delete/>')
  .replace('<c:axPos val="b"/>','<c:axPos val="t"/>')
  .replace('<c:axPos val="l"/>','<c:axPos val="r"/>')
  .replace('<a:t>Quarter &amp; year</a:t>','<a:t xml:space="preserve">Quarter </a:t><a:t>&amp; year</a:t>')
  .replace(/(<c:valAx>[\s\S]*?<c:title>)[\s\S]*?<\/c:title>/,(_full,prefix)=>prefix+'<c:tx><c:strRef><c:f>Sheet1!$D$1</c:f><c:strCache><c:ptCount val="1"/><c:pt idx="0"><c:v>Cached USD</c:v></c:pt></c:strCache></c:strRef></c:tx></c:title>')))
 expect(result.axes?.category).toMatchObject({hidden:true,title:'Quarter & year',position:'top'})
 expect(result.axes?.value).toMatchObject({hidden:false,titleRef:'Sheet1!$D$1',titleCache:'Cached USD',position:'right'})
})
it('uses the plot-linked axes, not an earlier unreferenced axis',async()=>{
 const result=await chart(await mutate(await fixture(),xml=>xml.replace('<c:catAx>',
  '<c:catAx><c:axId val="4294967295"/><c:axPos val="b"/><c:title><c:tx><c:rich><a:p><a:r><a:t>Wrong axis</a:t></a:r></a:p></c:rich></c:tx></c:title><c:crossAx val="4294967294"/></c:catAx><c:catAx>')))
 expect(result.axes?.category.title).toBe('Quarter & year')
})
it.each(['duplicate','broken-cross'])('declines %s axis identity instead of guessing',async fault=>{
 const result=await chart(await mutate(await fixture(),xml=>fault==='duplicate'
  ? xml.replace(/(<c:catAx>[\s\S]*?<\/c:catAx>)/,'$1$1')
  : xml.replace(/<c:crossAx val="\d+"\/>/,'<c:crossAx val="4294967295"/>')))
 expect(result.axes).toBeUndefined()
 expect(result.title).toBe('Main title')
})
it('reads date-axis titles and explicit title removal without reviving stale text',async()=>{
 const bytes=await applyChartEdits(await fixture(),[{chartPath:'xl/charts/chart1.xml',axisTitles:{category:null}}])
 const result=await chart(await mutate(bytes,xml=>xml.replaceAll('c:catAx','c:dateAx')))
 expect(result.axes?.category.title).toBeUndefined()
 expect(result.axes?.value.title).toBe('Amount (USD)')
})
