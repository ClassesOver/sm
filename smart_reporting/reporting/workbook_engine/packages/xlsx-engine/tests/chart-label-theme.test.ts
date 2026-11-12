import JSZip from 'jszip'
import {expect,it} from 'vitest'
import {createBlankWorkbook} from '../src/blank'
import {applyChartAdditions} from '../src/chart-add'
import {readWorkbook} from '../src/workbook-read'
import {setThemePart} from '../src/theme'
import {applyChartEdits} from '../src/rules'
import {THEME_SLOT_NAMES} from '../src/style-color'

const PALETTE=['#FFFFFF','#102030','#E7E6E6','#44546A','#1A9B5D','#C13B70','#8064A2','#4BACC6','#F79646','#336699','#0563C1','#954F72']
async function fixture(token='accent1',edit?:(zip:JSZip)=>Promise<void>){
 const raw=await applyChartAdditions(await createBlankWorkbook(),[{worksheetSheetName:'Sheet1',anchor:{fromRow:0,fromColumn:3,fromRowOffset:0,fromColumnOffset:0,toRow:9,toColumn:11,toRowOffset:0,toColumnOffset:0},chart:{chartType:'bar',title:'Theme',dataLabels:'value',dataLabelPosition:'center',series:[{name:'S',categories:['A','B'],values:[10,20],valuesRef:'Sheet1!B2:B3'}]}}])
 const zip=await JSZip.loadAsync(raw),path='xl/charts/chart1.xml'
 const slots=['dk1','lt1','dk2','lt2','accent1','accent2','accent3','accent4','accent5','accent6','hlink','folHlink']
 zip.file('xl/theme/theme1.xml','<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Actual"><a:themeElements><a:clrScheme name="Actual source">'+slots.map(name=>`<a:${name}><a:srgbClr val="${PALETTE[THEME_SLOT_NAMES.indexOf(name as typeof THEME_SLOT_NAMES[number])]!.slice(1)}"/></a:${name}>`).join('')+'</a:clrScheme><a:fontScheme name="Office"><a:majorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme><a:fmtScheme name="Office"><a:fillStyleLst/><a:lnStyleLst/><a:effectStyleLst/><a:bgFillStyleLst/></a:fmtScheme></a:themeElements></a:theme>')
 const relPath='xl/_rels/workbook.xml.rels'
 zip.file(relPath,(await zip.file(relPath)!.async('string')).replace('</Relationships>','<Relationship Id="theme" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/></Relationships>'))
 zip.file('[Content_Types].xml',(await zip.file('[Content_Types].xml')!.async('string')).replace('</Types>','<Override PartName="/xl/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/></Types>'))
 zip.file(path,(await zip.file(path)!.async('string')).replace('<c:dLblPos',()=>`<c:txPr><a:p><a:pPr><a:defRPr sz="1200"><a:solidFill><a:schemeClr val="${token}"/></a:solidFill></a:defRPr></a:pPr></a:p></c:txPr><c:dLblPos`))
 if(edit)await edit(zip)
 return zip.generateAsync({type:'uint8array'})
}
const chart=async(bytes:Uint8Array)=>(await readWorkbook(bytes)).sheets[0]!.charts![0]!
it.each([['accent1',PALETTE[4]],['tx1',PALETTE[1]],['bg1',PALETTE[0]],['tx2',PALETTE[3]],['hlink',PALETTE[10]]])('resolves %s from the actual complete workbook theme',async(token,color)=>{
 const result=await chart(await fixture(token))
 expect(result.dataLabels?.style?.color).toBe(color);expect(result.dataLabels?.unsupported).toBeUndefined()
})
it('re-resolves a saved scheme token after a theme change without changing the chart XML',async()=>{
 const before=await fixture(),values=[...PALETTE];values[4]='#D06A24'
 const after=await setThemePart(before,'xl/theme/theme1.xml',{colors:{name:'Changed',values}})
 const [a,b]=await Promise.all([JSZip.loadAsync(before),JSZip.loadAsync(after)])
 expect(await a.file('xl/charts/chart1.xml')!.async('string')).toBe(await b.file('xl/charts/chart1.xml')!.async('string'))
 expect((await chart(after)).dataLabels?.style?.color).toBe('#D06A24')
})
it('follows the actual relationship to a relocated theme rather than a stale conventional part',async()=>{
 const bytes=await fixture('accent1',async zip=>{
  const theme=(await zip.file('xl/theme/theme1.xml')!.async('string')).replace(/1A9B5D/g,'A040C0')
  zip.file('xl/theme/actual.xml',theme)
  const path='xl/_rels/workbook.xml.rels'
  zip.file(path,(await zip.file(path)!.async('string')).replace('theme/theme1.xml','theme/actual.xml'))
 })
 expect((await chart(bytes)).dataLabels?.style?.color).toBe('#A040C0')
})
it.each(['missing','incomplete','duplicate','external','unknown','unsupported-transform','theme-transform','duplicate-slot'] as const)('does not guess a default theme color for %s',async mode=>{
 const bytes=await fixture(mode==='unknown'?'phClr':'accent1',async zip=>{
  const path='xl/_rels/workbook.xml.rels',rels=await zip.file(path)!.async('string')
  if(mode==='missing')zip.remove('xl/theme/theme1.xml')
  if(mode==='incomplete')zip.file('xl/theme/theme1.xml',(await zip.file('xl/theme/theme1.xml')!.async('string')).replace(/<a:dk1>[\s\S]*?<\/a:dk1>/,''))
  if(mode==='duplicate')zip.file(path,rels.replace('</Relationships>','<Relationship Id="extraTheme" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/></Relationships>'))
  if(mode==='external')zip.file(path,rels.replace('Target="theme/theme1.xml"','TargetMode="External" Target="https://example.invalid/theme.xml"'))
  if(mode==='theme-transform')zip.file('xl/theme/theme1.xml',(await zip.file('xl/theme/theme1.xml')!.async('string')).replace('<a:srgbClr val="1A9B5D"/>','<a:srgbClr val="1A9B5D"><a:lumMod val="50000"/></a:srgbClr>'))
  if(mode==='duplicate-slot')zip.file('xl/theme/theme1.xml',(await zip.file('xl/theme/theme1.xml')!.async('string')).replace('</a:clrScheme>','<a:accent1><a:srgbClr val="FFFFFF"/></a:accent1></a:clrScheme>'))
  if(mode==='unsupported-transform')zip.file('xl/charts/chart1.xml',(await zip.file('xl/charts/chart1.xml')!.async('string')).replace('<a:schemeClr val="accent1"/>','<a:schemeClr val="accent1"><a:satMod val="50000"/></a:schemeClr>'))
 })
 expect((await chart(bytes)).dataLabels?.unsupported).toBe(true)
})

it('preserves the scheme token through a real chart edit and then resolves a changed theme', async()=>{
 const source=await fixture(), edited=await applyChartEdits(source,[{chartPath:'xl/charts/chart1.xml',dataLabels:'value',dataLabelPosition:'outside-end',dataLabelFormat:'0.0'}])
 const zip=await JSZip.loadAsync(edited)
 expect(await zip.file('xl/charts/chart1.xml')!.async('string')).toContain('<a:schemeClr val="accent1"/>')
 const values=[...PALETTE];values[4]='#D06A24'
 const saved=await setThemePart(edited,'xl/theme/theme1.xml',{colors:{name:'Changed',values}})
 const model=await chart(saved)
 expect(model.dataLabels?.style?.color).toBe('#D06A24')
 expect(model.dataLabels?.position).toBe('outside-end')
 expect(model.dataLabels?.numberFormat).toBe('0.0')
})

it('resolves series and point scheme colors independently from plot settings', async()=>{
 const bytes=await fixture('accent1',async zip=>{
  const path='xl/charts/chart1.xml',xml=await zip.file(path)!.async('string')
  const style=(token:string)=>`<c:txPr><a:p><a:pPr><a:defRPr><a:solidFill><a:schemeClr val="${token}"/></a:solidFill></a:defRPr></a:pPr></a:p></c:txPr>`
  zip.file(path,xml.replace('</c:ser>',`<c:dLbls><c:dLbl><c:idx val="1"/>${style('bg1')}</c:dLbl>${style('accent2')}<c:showVal val="1"/></c:dLbls></c:ser>`))
 })
 const result=await chart(bytes)
 expect(result.dataLabels?.style?.color).toBe(PALETTE[4])
 expect(result.series[0]?.dataLabels?.style?.color).toBe(PALETTE[5])
 expect(result.series[0]?.dataLabels?.points?.[1]?.style?.color).toBe(PALETTE[0])
})

it.each([
 ['<a:srgbClr val="4472C4"><a:lumMod val="75000"/></a:srgbClr>','#2F5597'],
 ['<a:srgbClr val="7F0000"><a:lumMod val="40000"/><a:lumOff val="60000"/></a:srgbClr>','#FF6666'],
 ['<a:srgbClr val="808080"><a:lumMod val="0"/></a:srgbClr>','#000000'],
 ['<a:srgbClr val="000000"><a:lumOff val="100000"/></a:srgbClr>','#FFFFFF'],
 ['<a:srgbClr val="808080"><a:lumOff val="80000"/></a:srgbClr>','#FFFFFF'],
 ['<a:schemeClr val="accent1"><a:lumMod val="100000"/></a:schemeClr>',PALETTE[4]],
])('resolves a bounded DrawingML luminance transform %s',async(fill,expected)=>{
 const bytes=await fixture('accent1',async zip=>{
  const path='xl/charts/chart1.xml'
  zip.file(path,(await zip.file(path)!.async('string')).replace('<a:schemeClr val="accent1"/>',fill!))
 })
 const result=await chart(bytes)
 expect(result.dataLabels?.style?.color).toBe(expected)
 expect(result.dataLabels?.unsupported).toBeUndefined()
})
it.each([
 '<a:lumMod val="-1"/>','<a:lumMod val="100001"/>','<a:lumMod val="NaN"/>',
 '<a:lumOff val="-1"/>','<a:lumOff val="100001"/>','<a:lumMod/>',
 '<a:lumMod val="50000"/><a:lumMod val="50000"/>',
 '<a:lumOff val="10000"/><a:lumMod val="50000"/>',
 '<a:lumMod val="50000"/><a:alpha val="50000"/>',
 '<a:lumMod val="50000"><a:lumOff val="10000"/></a:lumMod>',
])('does not silently reinterpret unsupported luminance input %s',async(mods)=>{
 const bytes=await fixture('accent1',async zip=>{
  const path='xl/charts/chart1.xml'
  zip.file(path,(await zip.file(path)!.async('string')).replace('<a:schemeClr val="accent1"/>',`<a:schemeClr val="accent1">${mods}</a:schemeClr>`))
 })
 expect((await chart(bytes)).dataLabels?.unsupported).toBe(true)
})
it('retains original luminance XML through chart edits and theme replay',async()=>{
 const fill='<a:schemeClr val="accent1"><a:lumMod val="40000"/><a:lumOff val="60000"/></a:schemeClr>'
 const source=await fixture('accent1',async zip=>{
  const path='xl/charts/chart1.xml'
  zip.file(path,(await zip.file(path)!.async('string')).replace('<a:schemeClr val="accent1"/>',fill))
 })
 const edited=await applyChartEdits(source,[{chartPath:'xl/charts/chart1.xml',dataLabels:'value',dataLabelFormat:'0.0'}])
 const values=[...PALETTE];values[4]='#7F0000'
 const saved=await setThemePart(edited,'xl/theme/theme1.xml',{colors:{name:'Changed',values}})
 const zip=await JSZip.loadAsync(saved)
 expect(await zip.file('xl/charts/chart1.xml')!.async('string')).toContain(fill)
 expect((await chart(saved)).dataLabels?.style?.color).toBe('#FF6666')
})
