import JSZip from 'jszip'
import {expect,it} from 'vitest'
import {applyChartAdditions} from '../src/chart-add'
import {readWorkbook} from '../src/workbook-read'
import {applyChartEdits} from '../src/rules'
import {createBufferEntrySource} from '../src/zip'
import {createBlankWorkbook} from '../src/blank'

const anchor={fromRow:0,fromColumn:3,fromRowOffset:0,fromColumnOffset:0,toRow:9,toColumn:11,toRowOffset:0,toColumnOffset:0}

async function scatterWorkbook():Promise<Uint8Array>{
 const bytes=await applyChartAdditions(await createBlankWorkbook(),[{worksheetSheetName:'Sheet1',anchor,chart:{chartType:'scatter',title:'Scatter',series:[{name:'Values',categories:['A','B'],values:[3,6],valuesRef:'Sheet1!$B$2:$B$3'}]}}])
 const zip=await JSZip.loadAsync(bytes),path='xl/charts/chart1.xml'
 zip.file(path,(await zip.file(path)!.async('string')).replace('<c:formatCode>General</c:formatCode>','<c:formatCode>0.0%</c:formatCode>'))
 return zip.generateAsync({type:'uint8array'})
}

async function chartXml(bytes:Uint8Array):Promise<string>{
 return (await createBufferEntrySource(bytes)).readText('xl/charts/chart1.xml')
}

it('keeps root value precedence over first-series none and preserves the Y value format',async()=>{
 let bytes=await scatterWorkbook(),xml=await chartXml(bytes)
 xml=xml.replace('</c:ser>','<c:dLbls><c:showVal val="0"/><c:dLbl><c:idx val="1"/><c:showVal val="1"/></c:dLbl></c:dLbls></c:ser>')
 .replace('</c:ser><c:axId','</c:ser><c:dLbls><c:showVal val="1"/></c:dLbls><c:axId')
 let zip=await JSZip.loadAsync(bytes);zip.file('xl/charts/chart1.xml',xml);bytes=await zip.generateAsync({type:'uint8array'})
 let chart=(await readWorkbook(bytes)).sheets[0]!.charts![0]!
 expect(chart.dataLabels?.showValue).toBe(true)
 expect(chart.dataLabels?.points).toBeUndefined()
 expect(chart.design?.dataLabels).toBe('value')
 expect(chart.series[0]!.dataLabels?.showValue).toBe(false)
 expect(chart.series[0]!.dataLabels?.points?.[1]?.showValue).toBe(true)
 expect(chart.series[0]!.numberFormat).toBe('0.0%')

 xml=xml.replace('<c:dLbls><c:showVal val="1"/></c:dLbls>','<c:dLbls><c:showVal val="0"/></c:dLbls>')
 zip=await JSZip.loadAsync(bytes);zip.file('xl/charts/chart1.xml',xml);bytes=await zip.generateAsync({type:'uint8array'})
 chart=(await readWorkbook(bytes)).sheets[0]!.charts![0]!
 expect(chart.dataLabels?.showValue).toBe(false)
})

it('exposes a simple scatter root value mode in the chart design',async()=>{
 let bytes=await scatterWorkbook(),xml=await chartXml(bytes)
 xml=xml.replace('</c:ser><c:axId','</c:ser><c:dLbls><c:showVal val="1"/></c:dLbls><c:axId')
 const zip=await JSZip.loadAsync(bytes);zip.file('xl/charts/chart1.xml',xml);bytes=await zip.generateAsync({type:'uint8array'})
 const chart=(await readWorkbook(bytes)).sheets[0]!.charts![0]!
 expect(chart.design?.dataLabels).toBe('value')
})

it('falls back to the first series without promoting point overrides',async()=>{
 let bytes=await scatterWorkbook(),xml=await chartXml(bytes)
 xml=xml.replace('</c:ser>','<c:dLbls><c:showVal val="1"/><c:dLbl><c:idx val="0"/><c:showVal val="0"/></c:dLbl></c:dLbls></c:ser>')
 let zip=await JSZip.loadAsync(bytes);zip.file('xl/charts/chart1.xml',xml);bytes=await zip.generateAsync({type:'uint8array'})
 const chart=(await readWorkbook(bytes)).sheets[0]!.charts![0]!
 expect(chart.dataLabels?.showValue).toBe(true)
 expect(chart.design?.dataLabels).toBe('value')
 expect(chart.design?.dataLabelsOffUnavailable).toBe(true)
 expect(chart.series[0]!.dataLabels?.showValue).toBe(true)
 expect(chart.series[0]!.dataLabels?.points?.[0]?.showValue).toBe(false)
})

it.each([
 ['<c:showVal/>',false],
 ['<c:showVal val="1"/><c:showPercent val="1"/>',false],
 ['<c:showVal val="1"/><c:showPercent val="0"/>',true],
 ['<c:showVal val="1"/><c:delete val="1"/>',false],
 ['<c:extLst><c:ext uri="x"><c:showVal val="1"/></c:ext></c:extLst>',false],
])('uses source label-mode defaults and precedence for scatter root flags %s',async(flags,expected)=>{
 let bytes=await scatterWorkbook(),xml=await chartXml(bytes)
 xml=xml.replace('</c:ser><c:axId',`</c:ser><c:dLbls>${flags}</c:dLbls><c:axId`)
 const zip=await JSZip.loadAsync(bytes);zip.file('xl/charts/chart1.xml',xml);bytes=await zip.generateAsync({type:'uint8array'})
 const chart=(await readWorkbook(bytes)).sheets[0]!.charts![0]!
 expect(chart.dataLabels?.showValue).toBe(expected)
})

it('writes only scatter plot value/off labels while preserving local labels and other parts',async()=>{
 let bytes=await scatterWorkbook(),xml=await chartXml(bytes)
 const seriesLabels='<c:dLbls><c:showVal val="0"/><c:dLbl><c:idx val="1"/><c:showVal val="1"/></c:dLbl></c:dLbls>'
 xml=xml.replace('</c:ser>',seriesLabels+'</c:ser>').replace('</c:ser><c:axId','</c:ser><c:dLbls><c:delete val="1"/><c:numFmt formatCode="0.00" sourceLinked="0"/><c:dLblPos val="ctr"/><c:showVal val="0"/><c:showCatName val="1"/><c:showPercent val="1"/></c:dLbls><c:axId')
 let zip=await JSZip.loadAsync(bytes);zip.file('xl/charts/chart1.xml',xml);bytes=await zip.generateAsync({type:'uint8array'})
 const before=await JSZip.loadAsync(bytes),beforeParts=new Map<string,Uint8Array>()
 for(const [path,file] of Object.entries(before.files))if(!file.dir&&path!=='xl/charts/chart1.xml')beforeParts.set(path,await file.async('uint8array'))

 const on=await applyChartEdits(bytes,[{chartPath:'xl/charts/chart1.xml',dataLabels:'value'}])
 const onXml=await chartXml(on)
 expect(onXml).toContain('<c:numFmt formatCode="0.00" sourceLinked="0"/>')
 expect(onXml).toContain('<c:dLblPos val="ctr"/>')
 expect(onXml).toContain('<c:showVal val="1"/>')
 expect(onXml).toContain('<c:showCatName val="0"/>')
 expect(onXml).toContain('<c:showPercent val="0"/>')
 expect(onXml).toContain(seriesLabels)

 const off=await applyChartEdits(on,[{chartPath:'xl/charts/chart1.xml',dataLabels:'none'}])
 const offXml=await chartXml(off)
 expect(offXml).not.toContain('<c:dLblPos val="ctr"/>')
 expect(offXml).toContain(seriesLabels)
 const after=await JSZip.loadAsync(off)
 for(const [path,bytes] of beforeParts)expect(await after.files[path]!.async('uint8array')).toEqual(bytes)
 const recreated=await applyChartEdits(off,[{chartPath:'xl/charts/chart1.xml',dataLabels:'value'}])
 expect(await chartXml(recreated)).toContain('<c:dLbls><c:showLegendKey val="0"/><c:showVal val="1"/><c:showCatName val="0"/><c:showSerName val="0"/><c:showPercent val="0"/><c:showBubbleSize val="0"/></c:dLbls>')
})

it('removes the plot delete choice when enabling value labels but preserves point delete',async()=>{
 let bytes=await scatterWorkbook(),xml=await chartXml(bytes)
 const seriesLabels='<c:dLbls><c:showVal val="0"/><c:dLbl><c:idx val="1"/><c:delete val="1"/></c:dLbl></c:dLbls>'
 xml=xml.replace('</c:ser>',seriesLabels+'</c:ser>').replace('</c:ser><c:axId','</c:ser><c:dLbls><c:delete val="1"/></c:dLbls><c:axId')
 const zip=await JSZip.loadAsync(bytes);zip.file('xl/charts/chart1.xml',xml);bytes=await zip.generateAsync({type:'uint8array'})
 const on=await applyChartEdits(bytes,[{chartPath:'xl/charts/chart1.xml',dataLabels:'value'}])
 const onXml=await chartXml(on),plotLabels=onXml.match(/<c:scatterChart\b[^>]*>[\s\S]*?<\/c:ser>(<c:dLbls\b[^>]*>[\s\S]*?<\/c:dLbls>)/)?.[1]
 expect(plotLabels).toContain('<c:showVal val="1"/>')
 expect(plotLabels).not.toContain('<c:delete')
 expect(onXml).toContain(seriesLabels)
})

it.each(['none','value'] as const)('finds scatter plot labels after comments when selecting %s',async mode=>{
 let bytes=await scatterWorkbook(),xml=await chartXml(bytes)
 const comment='\n<!-- keep scatter plot labels -->\n'
 const seriesLabels='<c:dLbls><c:dLbl><c:idx val="1"/><c:delete val="1"/></c:dLbl><c:showVal val="0"/></c:dLbls>'
 const plotLabels='<c:dLbls><c:numFmt formatCode="0.00" sourceLinked="0"/><c:dLblPos val="ctr"/><c:showVal val="0"/></c:dLbls>'
 xml=xml.replace('</c:ser>',seriesLabels+'</c:ser>').replace('</c:ser><c:axId','</c:ser>'+comment+plotLabels+'<c:axId')
 const source=await JSZip.loadAsync(bytes);source.file('xl/charts/chart1.xml',xml);bytes=await source.generateAsync({type:'uint8array'})
 const before=await JSZip.loadAsync(bytes),parts=new Map<string,Uint8Array>()
 for(const [path,file] of Object.entries(before.files))if(!file.dir)parts.set(path,await file.async('uint8array'))

 const edited=await applyChartEdits(bytes,[{chartPath:'xl/charts/chart1.xml',dataLabels:mode}])
 const editedXml=await chartXml(edited),withoutSeries=editedXml.replace(/<c:ser\b[^>]*>[\s\S]*?<\/c:ser>/g,'')
 expect([...withoutSeries.matchAll(/<c:dLbls\b/g)]).toHaveLength(mode==='value'?1:0)
 expect(editedXml).toContain(comment)
 expect(editedXml).toContain(seriesLabels)
 if(mode==='value'){
  expect(withoutSeries).toContain('<c:numFmt formatCode="0.00" sourceLinked="0"/>')
  expect(withoutSeries).toContain('<c:dLblPos val="ctr"/>')
  expect(withoutSeries).toContain('<c:showVal val="1"/>')
 }
 const after=await JSZip.loadAsync(edited)
 expect(Object.entries(after.files).filter(([,file])=>!file.dir).map(([path])=>path).sort()).toEqual([...parts.keys()].sort())
 for(const [path,content] of parts)if(path!=='xl/charts/chart1.xml')expect(await after.files[path]!.async('uint8array')).toEqual(content)
})

it('does not allow scatter label position or format edits',async()=>{
 const bytes=await scatterWorkbook()
 await expect(applyChartEdits(bytes,[{chartPath:'xl/charts/chart1.xml',dataLabels:'value',dataLabelPosition:'outside-end'}])).rejects.toThrow(/data labels/)
 await expect(applyChartEdits(bytes,[{chartPath:'xl/charts/chart1.xml',dataLabels:'percent'}])).rejects.toThrow(/only value data labels/)
})

it.each([
 ['', '<c:showVal val="1"/>', true, true],
 ['<c:dLbls><c:showVal val="0"/></c:dLbls>', '<c:showVal val="1"/>', true, true],
 ['<c:dLbls><c:delete val="1"/></c:dLbls>', '<c:showVal val="true"/>', true, true],
 ['', '<c:showVal val="1"/><c:showPercent val="1"/>', false, false],
 ['', '<c:showCatName val="1"/><c:showVal val="1"/><c:showPercent val="1"/>', false, false],
 ['', '<c:showVal val="1"/><c:delete val="1"/>', false, false],
 ['', '<c:dLbl><c:idx val="0"/><c:showVal val="1"/></c:dLbl>', false, false],
 ['', '<c:extLst><c:ext uri="test"><c:showVal val="1"/></c:ext></c:extLst>', false, false],
 ['<c:dLbls><c:showPercent val="1"/></c:dLbls>', '<c:showVal val="1"/>', false, true],
 ['<c:dLbls><c:showVal val="1"/></c:dLbls>', '<c:showPercent val="1"/>', true, false],
] as const)('matches pinned precedence for root %s / first series %s',async(root,flags,visible,blocksOff)=>{
 let bytes=await scatterWorkbook(),xml=await chartXml(bytes)
 xml=xml.replace('</c:ser>',`<c:dLbls>${flags}</c:dLbls></c:ser>`)
 xml=xml.replace('</c:ser><c:axId',`</c:ser><!-- root -->${root}<c:axId`)
 const zip=await JSZip.loadAsync(bytes);zip.file('xl/charts/chart1.xml',xml);bytes=await zip.generateAsync({type:'uint8array'})
 const chart=(await readWorkbook(bytes)).sheets[0]!.charts![0]!
 expect(!!chart.dataLabels?.showValue).toBe(visible)
 expect(!!chart.design?.dataLabelsOffUnavailable).toBe(blocksOff)
 const on=await applyChartEdits(bytes,[{chartPath:'xl/charts/chart1.xml',dataLabels:'value'}])
 expect((await readWorkbook(on)).sheets[0]!.charts![0]!.dataLabels?.showValue).toBe(true)
 if(blocksOff){
  await expect(applyChartEdits(bytes,[{chartPath:'xl/charts/chart1.xml',dataLabels:'none'}])).rejects.toThrow(/first.series.*value/i)
  await expect(applyChartEdits(bytes,[{chartPath:'xl/charts/chart1.xml',title:'must not commit'},{chartPath:'xl/charts/chart1.xml',dataLabels:'none'}])).rejects.toThrow(/first.series.*value/i)
  expect(await chartXml(bytes)).toBe(xml)
 }else{
  const off=await applyChartEdits(bytes,[{chartPath:'xl/charts/chart1.xml',dataLabels:'none'}])
  expect(!!(await readWorkbook(off)).sheets[0]!.charts![0]!.dataLabels?.showValue).toBe(false)
 }
})

it('does not use later series as fallback and preserves their source bytes',async()=>{
 let bytes=await scatterWorkbook(),xml=await chartXml(bytes)
 const first=xml.match(/<c:ser\b[^>]*>[\s\S]*?<\/c:ser>/)![0]
 const later=first.replace('<c:idx val="0"/>','<c:idx val="1"/>').replace('<c:order val="0"/>','<c:order val="1"/>').replace('</c:ser>','<c:dLbls><c:showVal val="1"/></c:dLbls></c:ser>')
 xml=xml.replace(first,first+later)
 const zip=await JSZip.loadAsync(bytes);zip.file('xl/charts/chart1.xml',xml);bytes=await zip.generateAsync({type:'uint8array'})
 const chart=(await readWorkbook(bytes)).sheets[0]!.charts![0]!
 expect(!!chart.dataLabels?.showValue).toBe(false)
 expect(chart.design?.dataLabelsOffUnavailable).not.toBe(true)
 const off=await applyChartEdits(bytes,[{chartPath:'xl/charts/chart1.xml',dataLabels:'none'}])
 expect(await chartXml(off)).toContain(later)
})

it.each(['alternate','default'] as const)('reads fallback with %s chart namespaces and ignores foreign flags',async namespace=>{
 let bytes=await scatterWorkbook(),xml=await chartXml(bytes)
 const seriesLabels='<c:dLbls xmlns:f="urn:foreign"><f:delete val="1"/><f:showPercent val="1"/><c:showVal val="1"/></c:dLbls>'
 xml=xml.replace('</c:ser>',seriesLabels+'</c:ser>')
 xml=namespace==='alternate'?xml.replaceAll('xmlns:c=','xmlns:chart=').replaceAll('c:', 'chart:'):xml.replaceAll('xmlns:c=','xmlns=').replaceAll('<c:','<').replaceAll('</c:','</')
 const zip=await JSZip.loadAsync(bytes);zip.file('xl/charts/chart1.xml',xml);bytes=await zip.generateAsync({type:'uint8array'})
 const chart=(await readWorkbook(bytes)).sheets[0]!.charts![0]!
 expect(chart.dataLabels?.showValue).toBe(true)
 expect(chart.design?.dataLabelsOffUnavailable).toBe(true)
 await expect(applyChartEdits(bytes,[{chartPath:'xl/charts/chart1.xml',dataLabels:'none'}])).rejects.toThrow(/first.series.*value/i)
})
