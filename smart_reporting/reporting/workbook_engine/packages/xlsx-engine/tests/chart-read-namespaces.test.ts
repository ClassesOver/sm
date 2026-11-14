import JSZip from 'jszip'
import {expect,it} from 'vitest'
import {readCharts} from '../src/chart-read'

const drawingNS='http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing'
const chartNS='http://schemas.openxmlformats.org/drawingml/2006/chart'
const mainNS='http://schemas.openxmlformats.org/drawingml/2006/main'
const relNS='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
const packageNS='http://schemas.openxmlformats.org/package/2006/relationships'
async function fixture(drawingPrefix:string,chartPrefix:string,namespace=chartNS,withOffsets=false){
 const zip=new JSZip()
 const relationships=(target:string,type='drawing')=>`<Relationships xmlns="${packageNS}"><Relationship Id="rId1" Type="${relNS}/${type}" Target="${target}"/></Relationships>`
 zip.file('xl/worksheets/_rels/sheet1.xml.rels',relationships('../drawings/drawing1.xml'))
 zip.file('xl/drawings/_rels/drawing1.xml.rels',relationships('../charts/chart1.xml','chart'))
 const tag=(name:string)=>drawingPrefix?drawingPrefix+':'+name:name
 const marker=(col:number,row:number,colOff:number,rowOff:number)=>`<${tag('col')}>${col}</${tag('col')}><${tag('colOff')}>${colOff}</${tag('colOff')}><${tag('row')}>${row}</${tag('row')}><${tag('rowOff')}>${rowOff}</${tag('rowOff')}>`
 zip.file('xl/drawings/drawing1.xml',`<${tag('wsDr')} xmlns${drawingPrefix?':'+drawingPrefix:''}="${drawingNS}"><${tag('twoCellAnchor')}><${tag('from')}>${marker(4,1,withOffsets?47625:0,withOffsets?28575:0)}</${tag('from')}><${tag('to')}>${marker(12,9,withOffsets?-66675:0,withOffsets?-19050:0)}</${tag('to')}><${tag('graphicFrame')}><a:graphic xmlns:a="${mainNS}"><a:graphicData><c:chart xmlns:c="${chartNS}" xmlns:r="${relNS}" r:id="rId1"/></a:graphicData></a:graphic></${tag('graphicFrame')}></${tag('twoCellAnchor')}></${tag('wsDr')}>`)
 const c=(name:string)=>chartPrefix?chartPrefix+':'+name:name
 zip.file('xl/charts/chart1.xml',`<${c('chartSpace')} xmlns${chartPrefix?':'+chartPrefix:''}="${namespace}"><${c('chart')}><${c('title')}><${c('tx')}><${c('rich')}><a:p xmlns:a="${mainNS}"><a:r><a:t>Quarterly &amp; 收入</a:t></a:r></a:p></${c('rich')}></${c('tx')}></${c('title')}><${c('plotArea')}><${c('barChart')}><${c('barDir')} val="col"/><${c('ser')}><${c('val')}><${c('numRef')}><${c('f')}>'Sheet'!$B$2:$B$3</${c('f')}></${c('numRef')}></${c('val')}></${c('ser')}></${c('barChart')}></${c('plotArea')}></${c('chart')}></${c('chartSpace')}>`)
 return zip.generateAsync({type:'uint8array'})
}
it.each([['',''],['drawing','chart']])('读取默认或任意前缀图表 %s/%s，来源字节不变',async(drawing,chart)=>{
 const bytes=await fixture(drawing,chart),before=bytes.slice()
 const charts=await readCharts(bytes,'xl/worksheets/sheet1.xml')
 expect(charts).toHaveLength(1);expect(charts[0]!.kind).toBe('column')
 expect(charts[0]!.title).toBe('Quarterly & 收入')
 expect(charts[0]!.anchor).toMatchObject({fromRow:1,fromColumn:4,toRow:9,toColumn:12})
 expect(charts[0]!.series[0]!.valuesRef).toBe("'Sheet'!$B$2:$B$3")
 expect(bytes).toEqual(before)
})
it('不把同名前缀的外来命名空间当作图表',async()=>{
 const bytes=await fixture('xdr','c','https://example.invalid/chart')
 expect(await readCharts(bytes,'xl/worksheets/sheet1.xml')).toEqual([])
})
it('读取并保留EMU偏移，包括带符号的终点偏移',async()=>{
 const bytes=await fixture('','',chartNS,true)
 const charts=await readCharts(bytes,'xl/worksheets/sheet1.xml')
 expect(charts[0]!.anchor).toMatchObject({fromRowOffset:28575,fromColumnOffset:47625,toRowOffset:-19050,toColumnOffset:-66675})
})
