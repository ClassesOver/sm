import type { ChartReadSpec } from '@sheets-web/xlsx-engine'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const registry = vi.hoisted(() => ({ extensions: [] as Array<new () => { draw(...args: unknown[]): void }> }))
vi.mock('@univerjs/engine-render', () => ({
  SheetExtension: class {},
  SpreadsheetExtensionRegistry: { add: (extension: typeof registry.extensions[number]) => registry.extensions.push(extension) },
}))
import { setCharts } from './chart-render'
import { setSelectedChartPath } from '../../workbook-chart-selection-state'
import {hitChartElement} from '../../workbook-chart-element-hit'

type Rect = { x: number; y: number; width: number; height: number; color: string }
function render(kind: ChartReadSpec['kind'], series: Array<Array<unknown>>, extra: Partial<ChartReadSpec> = {}, rawSeries = series) {
  const fills: Rect[] = []
  const pathColors: string[] = []
  const texts: Array<{ text: string; x: number; y: number; font:string; color:string; align:string }> = []
  const allTexts: typeof texts = []
  const tickTexts: typeof texts = []
  const categoryTexts: typeof texts = []
  const paths: Array<{color:string; width:number; points:number[][]}> = []; let points:number[][] = []
  const ctx = {
    fillStyle: '', strokeStyle: '', lineWidth: 1, font: '', globalAlpha: 1, textAlign:'left', textBaseline:'alphabetic',
    arc: vi.fn(), closePath: vi.fn(),
    fill() { pathColors.push(this.fillStyle) },
    save: vi.fn(), restore: vi.fn(), strokeRect: vi.fn(), beginPath: vi.fn(() => { points = [] }), rect: vi.fn(), clip: vi.fn(), translate: vi.fn(), rotate: vi.fn(),
    moveTo: vi.fn((x:number,y:number) => { points.push([x,y]) }), lineTo: vi.fn((x:number,y:number) => { points.push([x,y]) }), stroke: vi.fn(function(this:{strokeStyle:string;lineWidth:number}) { paths.push({color:this.strokeStyle,width:this.lineWidth,points:[...points]}) }),
    measureText: (text: string) => ({ width: text.length * 6 }),
    fillText(text: string, x: number, y: number) { const item={ text, x, y, font:this.font, color:this.fillStyle, align:this.textAlign };allTexts.push(item);(this.font === '10px system-ui' ? categoryTexts : this.font === '9px system-ui' ? tickTexts : texts).push(item) },
    fillRect(x: number, y: number, width: number, height: number) {
      fills.push({ x, y, width, height, color: this.fillStyle })
    },
  }
  const specs: ChartReadSpec[] = [{ chartPath: 'xl/charts/chart1.xml', kind,
    anchor: { fromRow: 0, fromColumn: 0, toRow: 10, toColumn: 10 },
    series: series.map((_, index) => ({ valuesRef: String.fromCharCode(65 + index) + '1:' + String.fromCharCode(65 + index) + series[index]!.length })),
    ...extra,
  }]
  setCharts('test-unit', 'test-sheet', specs)
  const extension = new registry.extensions[0]!()
  extension.draw(ctx, {}, {
    worksheet: { getUnitId: () => 'test-unit', getSheetId: () => 'test-sheet', getName: () => 'Test',
      getCell: (row: number, column: number) => ({ v: series[column]?.[row] }),
      getCellRaw: (row: number, column: number) => ({ v: rawSeries[column]?.[row] }) },
    getCellWithCoordByIndex: (row: number, column: number) => ({
      startX: column * 40, endX: (column + 1) * 40, startY: row * 20, endY: (row + 1) * 20,
    }),
  })
  expect(ctx.restore.mock.calls.length).toBe(ctx.save.mock.calls.length)
  return { fills: fills.filter(rect => rect.color !== '#ffffff'), pathColors, texts, allTexts, tickTexts, categoryTexts, paths, ctx }
}
const paint = (kind: 'bar' | 'column', series: Array<Array<unknown>>) => render(kind, series).fills
it.each(['line','area','scatter','radar'] as const)('%s previews saved series and point colors',kind=>{
 const result=render(kind,[],{series:[{valuesRef:'',values:[2,4,3],xValues:[1,2,3],color:'#123456',pointColors:{1:'#abcdef'}}]})
 expect([...result.pathColors,...result.paths.map(path=>path.color)]).toContain('#123456')
 expect(result.pathColors).toContain('#abcdef')
})
it('paints radar value labels at each point using the series number format',()=>{
 const result=render('radar',[],{dataLabels:{showValue:true},series:[{valuesRef:'',values:[2,4,6],numberFormat:'"$"0.0'}]})
 expect(result.texts.map(text=>text.text)).toEqual(['$2.0','$4.0','$6.0'])
 expect(result.texts).toHaveLength(3)
})
it('keeps radar labels at their source category slots when a value is blank',()=>{
 const complete=render('radar',[[3,6,9]],{dataLabels:{showValue:true},series:[{valuesRef:'A1:A3'}]})
 const withBlank=render('radar',[[3,0,9]],{dataLabels:{showValue:true},series:[{valuesRef:'A1:A3'}],},[[3,null,9]])
 expect(withBlank.texts.map(text=>text.text)).toEqual(['3','9'])
 expect(withBlank.texts[1]!.x).toBeCloseTo(complete.texts[2]!.x)
 expect(withBlank.texts[1]!.y).toBeCloseTo(complete.texts[2]!.y)
})
it('draws four radar value rings without registering value-axis hits',()=>{
 const result=render('radar',[],{series:[{valuesRef:'',values:[2,4,6,8]}]})
 const rings=result.paths.filter(path=>path.color==='#e3e3e3'&&path.points.length===4)
 expect(rings).toHaveLength(4)
 const store=(window as unknown as {__sheetsWebCharts:{store:Map<string,ChartReadSpec[]>}}).__sheetsWebCharts.store
 const chart=store.get('test-unit::test-sheet')![0]!
 expect(hitChartElement('test-unit','test-sheet',chart,200,20)).toEqual({kind:'chart'})
 expect(hitChartElement('test-unit','test-sheet',chart,200,110)).toEqual({kind:'series',seriesIndex:0})
})
it('uses the primary radar category count, nice maximum and zero-pads shorter series',()=>{
 const result=render('radar',[],{series:[
  {valuesRef:'',values:[3,40,87],categories:['A','B','C']},
  {valuesRef:'',values:[1,2],categories:['A','B']},
 ]})
 expect(result.ctx.arc).toHaveBeenCalledTimes(5)
 expect(result.categoryTexts.map(text=>text.text)).toEqual(['A','B','C'])
 expect(result.paths.find(path=>path.color==='#ed7d31')?.points).toHaveLength(3)
 const spoke=result.paths.find(path=>path.color==='#d0d5da'&&path.points.length===2)!
 const [center,outer]=spoke.points, radius=Math.hypot(outer![0]!-center![0]!,outer![1]!-center![1]!)
 const maximumPoint=result.ctx.arc.mock.calls[2]!, distance=Math.hypot((maximumPoint![0] as number)-center![0]!, (maximumPoint![1] as number)-center![1]!)
 expect(distance/radius).toBeCloseTo(0.87)
})
it('caps radar axes to twelve primary categories and drops later-series ghost points',()=>{
 const long=render('radar',[],{series:[
  {valuesRef:'',values:Array.from({length:13},()=>1)},
  {valuesRef:'',values:Array.from({length:15},()=>2)},
 ]})
 expect(long.ctx.arc).toHaveBeenCalledTimes(24)
 expect(long.categoryTexts).toHaveLength(12)
 expect(long.paths.filter(path=>path.color==='#e3e3e3'&&path.points.length===12)).toHaveLength(4)
 const short=render('radar',[],{series:[
  {valuesRef:'',values:[0,0,0],categories:['A','B','C']},
  {valuesRef:'',values:[0,0,0,1000,900]},
 ]})
 const store=(window as unknown as {__sheetsWebCharts:{store:Map<string,ChartReadSpec[]>}}).__sheetsWebCharts.store
 const chart=store.get('test-unit::test-sheet')![0]!
 expect(short.ctx.arc).toHaveBeenCalledTimes(6)
 expect(hitChartElement('test-unit','test-sheet',chart,200,186)).toEqual({kind:'chart'})
})
it('selects a line series from its drawn segment while giving data points priority',()=>{
 const result=render('line',[[3,9]],{axes:{category:{id:1,hidden:false},value:{id:2,hidden:false}},series:[{valuesRef:'A1:A2'}]})
 const store=(window as unknown as {__sheetsWebCharts:{store:Map<string,ChartReadSpec[]>}}).__sheetsWebCharts.store
 const chart=store.get('test-unit::test-sheet')![0]!,[first,last]=result.ctx.arc.mock.calls
 const x=((first![0] as number)+(last![0] as number))/2,y=((first![1] as number)+(last![1] as number))/2
 expect(hitChartElement('test-unit','test-sheet',chart,x,y)).toEqual({kind:'series',seriesIndex:0})
 expect(hitChartElement('test-unit','test-sheet',chart,first![0] as number,first![1] as number)).toEqual({kind:'point',seriesIndex:0,pointIndex:0})
})
it('does not select a line series across a blank gap or non-finite path',()=>{
 const result=render('line',[[3,0,9]],{series:[{valuesRef:'A1:A3'}]},[[3,null,9]])
 const store=(window as unknown as {__sheetsWebCharts:{store:Map<string,ChartReadSpec[]>}}).__sheetsWebCharts.store
 const chart=store.get('test-unit::test-sheet')![0]!,[first,last]=result.ctx.arc.mock.calls
 expect(hitChartElement('test-unit','test-sheet',chart,230,((first![1] as number)+(last![1] as number))/2)).toEqual({kind:'chart'})
 const invalid=render('line',[],{series:[{valuesRef:'',values:[3,Number.POSITIVE_INFINITY,9]}]})
 const invalidChart=store.get('test-unit::test-sheet')![0]!
 expect(hitChartElement('test-unit','test-sheet',invalidChart,230,100)).toEqual({kind:'chart'})
 expect(invalid.ctx.arc).toHaveBeenCalledTimes(2)
})
it('selects an area series only inside its drawn contiguous fill',()=>{
 const result=render('area',[[3,9]],{axes:{category:{id:1,hidden:false},value:{id:2,hidden:false}},series:[{valuesRef:'A1:A2'}]})
 const store=(window as unknown as {__sheetsWebCharts:{store:Map<string,ChartReadSpec[]>}}).__sheetsWebCharts.store
 const chart=store.get('test-unit::test-sheet')![0]!,[first,last]=result.ctx.arc.mock.calls
 const x=((first![0] as number)+(last![0] as number))/2,y=((first![1] as number)+(last![1] as number)+2*192)/4
 expect(hitChartElement('test-unit','test-sheet',chart,x,y)).toEqual({kind:'series',seriesIndex:0})
 const gap=render('area',[[3,0,9]],{series:[{valuesRef:'A1:A3'}]},[[3,null,9]])
 const gapChart=store.get('test-unit::test-sheet')![0]!
 expect(hitChartElement('test-unit','test-sheet',gapChart,230,180)).toEqual({kind:'chart'})
 expect(gap.ctx.arc).toHaveBeenCalledTimes(2)
})
it('hits the drawn column point and exploded doughnut ring while leaving its hole as chart area',()=>{
 const bars=render('column',[[3,6]]);const bar=bars.fills[1]!
 const store=(window as unknown as {__sheetsWebCharts:{store:Map<string,ChartReadSpec[]>}}).__sheetsWebCharts.store
 let spec=store.get('test-unit::test-sheet')![0]!
 expect(hitChartElement('test-unit','test-sheet',spec,bar.x+bar.width/2,bar.y+bar.height/2)).toEqual({kind:'point',seriesIndex:0,pointIndex:1})
 const ring=render('doughnut',[],{holeSizePct:70,series:[{valuesRef:'',values:[1,1],pointExplosions:{1:50}}]});spec=store.get('test-unit::test-sheet')![0]!
 const arc=ring.ctx.arc.mock.calls[2]!,x=arc[0] as number,y=arc[1] as number,r=arc[2] as number
 expect(hitChartElement('test-unit','test-sheet',spec,x-r*0.85,y)).toEqual({kind:'point',seriesIndex:0,pointIndex:1})
 expect(hitChartElement('test-unit','test-sheet',spec,x,y)).toEqual({kind:'chart'})
})
it('selects scatter x/y axes while keeping plotted points ahead of their hit regions',()=>{
 const result=render('scatter',[],{series:[{valuesRef:'',values:[1,2],xValues:[10,20]}]})
 const store=(window as unknown as {__sheetsWebCharts:{store:Map<string,ChartReadSpec[]>}}).__sheetsWebCharts.store
 const chart=store.get('test-unit::test-sheet')![0]!,[point]=result.ctx.arc.mock.calls
 expect(hitChartElement('test-unit','test-sheet',chart,200,196)).toEqual({kind:'category-axis'})
 expect(hitChartElement('test-unit','test-sheet',chart,4,110)).toEqual({kind:'value-axis'})
 expect(hitChartElement('test-unit','test-sheet',chart,point![0] as number,point![1] as number)).toEqual({kind:'point',seriesIndex:0,pointIndex:0})
})
it('does not draw or register hidden scatter axes',()=>{
 const result=render('scatter',[],{axes:{category:{id:1,hidden:true},value:{id:2,hidden:true}},series:[{valuesRef:'',values:[1,2],xValues:[10,20]}]})
 const store=(window as unknown as {__sheetsWebCharts:{store:Map<string,ChartReadSpec[]>}}).__sheetsWebCharts.store
 const chart=store.get('test-unit::test-sheet')![0]!
 expect(result.tickTexts).toHaveLength(0)
 expect(hitChartElement('test-unit','test-sheet',chart,200,196)).toEqual({kind:'chart'})
 expect(hitChartElement('test-unit','test-sheet',chart,4,110)).toEqual({kind:'chart'})
})
it('clamps scatter points to explicit signed bounds and ignores reversed axis orientation',()=>{
 const result=render('scatter',[],{axes:{
  category:{id:1,hidden:false,scaling:{min:-10,max:10,majorUnit:10,reversed:true}},
  value:{id:2,hidden:false,scaling:{min:-10,max:10,majorUnit:10,reversed:true}},
 },series:[{valuesRef:'',values:[-20,0,20],xValues:[-20,0,20]}]})
 const tick=(text:string,axis:'x'|'y',leftOf?:number)=>result.tickTexts.find(item=>item.text===text&&item.font==='9px system-ui'&&(axis==='x'?item.y>150:item.x<leftOf!))!
 const minX=tick('-10','x'),zeroX=tick('0','x'),maxX=tick('10','x')
 const minY=tick('-10','y',minX.x-1),zeroY=tick('0','y',minX.x-1),maxY=tick('10','y',minX.x-1)
 const [low,middle,high]=result.ctx.arc.mock.calls
 expect(low![0]).toBeCloseTo(minX.x);expect(low![1]).toBeCloseTo(minY.y)
 expect(middle![0]).toBeCloseTo(zeroX.x);expect(middle![1]).toBeCloseTo(zeroY.y)
 expect(high![0]).toBeCloseTo(maxX.x);expect(high![1]).toBeCloseTo(maxY.y)
 const store=(window as unknown as {__sheetsWebCharts:{store:Map<string,ChartReadSpec[]>}}).__sheetsWebCharts.store
 const chart=store.get('test-unit::test-sheet')![0]!
 expect(hitChartElement('test-unit','test-sheet',chart,low![0] as number,low![1] as number)).toEqual({kind:'point',seriesIndex:0,pointIndex:0})
 const hidden=render('scatter',[],{axes:{
  category:{id:1,hidden:true,scaling:{min:-10,max:10,majorUnit:10,reversed:true}},
  value:{id:2,hidden:true,scaling:{min:-10,max:10,majorUnit:10,reversed:true}},
 },series:[{valuesRef:'',values:[-20,0,20],xValues:[-20,0,20]}]})
 expect(hidden.tickTexts).toHaveLength(0)
 expect(hidden.ctx.arc.mock.calls.map(([x,y])=>[x,y])).toEqual(result.ctx.arc.mock.calls.map(([x,y])=>[x,y]))
 const hiddenChart=store.get('test-unit::test-sheet')![0]!
 expect(hitChartElement('test-unit','test-sheet',hiddenChart,low![0] as number,low![1] as number)).toEqual({kind:'point',seriesIndex:0,pointIndex:0})
})
it('draws scatter lines only when requested, bridges blank slots, and honors noFill and marker none hits',()=>{
 const connected=render('scatter',[[3,0,9]],{scatterStyle:'lineMarker',series:[{valuesRef:'A1:A3',lineColor:'#123456',lineWidth:4,marker:'diamond'}]},[[3,null,9]])
 const line=connected.paths.find(path=>path.color==='#123456')!
 expect(line.points).toHaveLength(2);expect(line.points[0]![0]).toBeLessThan(line.points[1]![0]!);expect(line.width).toBe(4);expect(connected.ctx.arc).toHaveBeenCalledTimes(2)
 const store=(window as unknown as {__sheetsWebCharts:{store:Map<string,ChartReadSpec[]>}}).__sheetsWebCharts.store
 const chart=store.get('test-unit::test-sheet')![0]!
 expect(hitChartElement('test-unit','test-sheet',chart,connected.ctx.arc.mock.calls[0]![0] as number,connected.ctx.arc.mock.calls[0]![1] as number)).toEqual({kind:'point',seriesIndex:0,pointIndex:0})
 const markerOnly=render('scatter',[],{scatterStyle:'marker',series:[{valuesRef:'',values:[3,9],xValues:[1,2]}]})
 expect(markerOnly.paths.some(path=>path.points.length>1&&path.color==='#4472c4')).toBe(false)
 const noFill=render('scatter',[],{scatterStyle:'lineMarker',series:[{valuesRef:'',values:[3,9],xValues:[1,2],lineColor:'none'}]})
 expect(noFill.paths.some(path=>path.points.length>1&&path.color==='#4472c4')).toBe(false)
 const zeroWidth=render('scatter',[],{scatterStyle:'lineMarker',series:[{valuesRef:'',values:[3,9],xValues:[1,2],lineWidth:0}]})
 expect(zeroWidth.paths.some(path=>path.points.length>1&&path.color==='#4472c4')).toBe(false)
 const hidden=render('scatter',[],{scatterStyle:'lineMarker',series:[{valuesRef:'',values:[3,9],xValues:[1,2],marker:'none'}]})
 expect(hidden.ctx.arc).not.toHaveBeenCalled()
 const hiddenLine=hidden.paths.find(path=>path.points.length>1&&path.color==='#4472c4')!
 expect(hiddenLine.points).toHaveLength(2)
 const hiddenChart=store.get('test-unit::test-sheet')![0]!
 const lineMid={x:(hiddenLine.points[0]![0]!+hiddenLine.points[1]![0]!)/2,y:(hiddenLine.points[0]![1]!+hiddenLine.points[1]![1]!)/2}
 expect(hitChartElement('test-unit','test-sheet',hiddenChart,lineMid.x,lineMid.y)).toEqual({kind:'chart'})
})
it('draws scatter plot value labels above each marker using that series number format',()=>{
 const result=render('scatter',[],{dataLabels:{showValue:true,numberFormat:'0.000',position:'center'},series:[
  {valuesRef:'',values:[1.25],xValues:[10],numberFormat:'"$"0.0'},
  {valuesRef:'',values:[0.125],xValues:[20],numberFormat:'0.0%'},
 ]})
 const labels=result.allTexts.filter(text=>text.text==='$1.3'||text.text==='13%')
 const markers=result.ctx.arc.mock.calls
 expect(labels.map(text=>text.text)).toEqual(['$1.3','13%'])
 expect(labels.map(text=>text.align)).toEqual(['center','center'])
 expect(labels.map(text=>text.font)).toEqual(['9px system-ui','9px system-ui'])
 expect(labels.map(text=>text.color)).toEqual(['#888','#888'])
 expect(labels[0]!.x).toBeCloseTo(markers[0]![0] as number)
 expect(labels[0]!.y).toBeCloseTo((markers[0]![1] as number)-8)
 expect(labels[1]!.x).toBeCloseTo(markers[1]![0] as number)
 expect(labels[1]!.y).toBeCloseTo((markers[1]![1] as number)-8)
})
it('formats scatter percentage and General labels with the fixed source value formatter',()=>{
 const result=render('scatter',[],{dataLabels:{showValue:true,numberFormat:'"ignored"0.00%'},series:[
  {valuesRef:'',values:[0.254],xValues:[1],numberFormat:'0.00%'},
  {valuesRef:'',values:[1.234567,12345.67891],xValues:[2,3],numberFormat:'General'},
 ]})
 expect(result.allTexts.map(text=>text.text).filter(text=>['25%','1.2346','12,345.6789'].includes(text))).toEqual(['25%','1.2346','12,345.6789'])
})
it('labels zero scatter values and skips null source points',()=>{
 const result=render('scatter',[[0,5,0]],{dataLabels:{showValue:true},series:[{valuesRef:'A1:A3',xValues:[1,2,3]}]},[[0,null,0]])
 const markers=result.ctx.arc.mock.calls
 const labels=result.allTexts.filter(text=>text.text==='0'&&markers.some(([x,y])=>text.x===x&&text.y===y!-8))
 expect(labels).toHaveLength(2)
 expect(markers).toHaveLength(2)
 labels.forEach((label,index)=>{
  expect(label.x).toBeCloseTo(result.ctx.arc.mock.calls[index]![0] as number)
  expect(label.y).toBeCloseTo((result.ctx.arc.mock.calls[index]![1] as number)-8)
 })
})
it('requires plot-level value labels and ignores series and point label settings',()=>{
 const seriesOnly=render('scatter',[],{series:[{valuesRef:'',values:[2],xValues:[1],dataLabels:{showValue:true}}]})
 expect(seriesOnly.texts).toEqual([])
 const pointOnly=render('scatter',[],{series:[{valuesRef:'',values:[2],xValues:[1],dataLabels:{points:{0:{showValue:true}}}}]})
 expect(pointOnly.texts).toEqual([])
 const disabled=render('scatter',[],{dataLabels:{showValue:false},series:[{valuesRef:'',values:[2],xValues:[1]}]})
 expect(disabled.texts).toEqual([])
})
it('draws plot value labels for markerless scatter series',()=>{
 const result=render('scatter',[],{dataLabels:{showValue:true},series:[{valuesRef:'',values:[4],xValues:[1],marker:'none',numberFormat:'0.0'}]})
 expect(result.ctx.arc).not.toHaveBeenCalled()
 expect(result.allTexts.some(text=>text.text==='4.0')).toBe(true)
})
it.each([
 {values:[0.0026,0.05,0.152],expectedMax:'0.16'},
 {values:[3,40,87],expectedMax:'90',majorUnit:10},
 {values:[3,40,130],expectedMax:'140'},
])('uses source scatter bounds and major-unit ticks for $values',({values,expectedMax,majorUnit})=>{
 const result=render('scatter',[],{axes:{category:{id:1,hidden:false},value:{id:2,hidden:false,scaling:majorUnit?{majorUnit,reversed:false}:undefined}},series:[{valuesRef:'',values,xValues:[1,2,3]}]})
 const yTicks=result.tickTexts.slice(majorUnit?-10:-5).map(text=>text.text)
 expect(yTicks).toContain(expectedMax)
 if(majorUnit)expect(yTicks).toEqual(['0','10','20','30','40','50','60','70','80','90'])
})
it('draws scatter titles and independent grids with scaled tick text while retaining data coordinates',()=>{
 const axes:NonNullable<ChartReadSpec['axes']>={
  category:{id:11,hidden:false,title:'Elapsed',majorGridlines:true,displayUnit:1000,displayUnitLabel:'Not drawn',numberFormat:'0.0',scaling:{min:0,max:2000,majorUnit:1000,reversed:false}},
  value:{id:22,hidden:false,title:'Sales',majorGridlines:true,displayUnit:1000,displayUnitLabel:'Thousands',numberFormat:'0.00',scaling:{min:0,max:10000,majorUnit:5000,reversed:false}},
 }
 const result=render('scatter',[],{axes,series:[{valuesRef:'',values:[5000,10000],xValues:[1000,2000]}]})
 expect(result.allTexts.map(text=>text.text)).toEqual(expect.arrayContaining(['Elapsed','Sales','Thousands','0.0','1.0','2.0','0.00','5.00','10.00']))
 expect(result.allTexts.some(text=>text.text==='Not drawn')).toBe(false)
 const grids=result.paths.filter(path=>path.color==='#e3e3e3')
 expect(grids.filter(path=>path.points[0]![0]===path.points[1]![0])).toHaveLength(3)
 expect(grids.filter(path=>path.points[0]![1]===path.points[1]![1])).toHaveLength(3)
 const points=result.ctx.arc.mock.calls
 const xTicks=result.tickTexts.filter(text=>text.align==='center')
 const yTicks=result.tickTexts.filter(text=>text.align==='right')
 expect(points[0]![0]).toBeCloseTo(xTicks.find(text=>text.text==='1.0')!.x)
 expect(points[0]![1]).toBeCloseTo(yTicks.find(text=>text.text==='5.00')!.y)
 expect(points[1]![0]).toBeCloseTo(xTicks.find(text=>text.text==='2.0')!.x)
 expect(points[1]![1]).toBeCloseTo(yTicks.find(text=>text.text==='10.00')!.y)
 // Divisors affect labels, never the plotted domains or fractional positions.
 const unscaled=render('scatter',[],{axes:{category:{...axes.category,displayUnit:undefined,numberFormat:'0.000'},value:{...axes.value,displayUnit:undefined,numberFormat:'0.000'}},series:[{valuesRef:'',values:[5000,10000],xValues:[1000,2000]}]})
 const [a,b]=points,[c,d]=unscaled.ctx.arc.mock.calls
 const yGrid=grids.find(path=>path.points[0]![1]===path.points[1]![1])!
 expect((a![0] as number)-(yGrid.points[0]![0]!)).toBeCloseTo(((b![0] as number)-yGrid.points[0]![0]!)/2)
 expect((a![1] as number)-(b![1] as number)).toBeGreaterThan(0)
 expect((c![1] as number)-(d![1] as number)).toBeGreaterThan(0)
})
it('retains scatter titles units and the first Y gridline when hidden axes disable all other grids',()=>{
 const result=render('scatter',[],{design:{gridlines:false},axes:{
  category:{id:1,hidden:true,position:'top',title:'X hidden',majorGridlines:false,scaling:{min:0,max:2,majorUnit:1,reversed:true}},
  value:{id:2,hidden:true,position:'right',title:'Y hidden',displayUnit:1000,displayUnitLabel:'Thousands',majorGridlines:false,scaling:{min:0,max:2,majorUnit:1,reversed:true}},
 },series:[{valuesRef:'',values:[1,2],xValues:[1,2]}]})
 expect(result.allTexts.map(text=>text.text)).toEqual(expect.arrayContaining(['X hidden','Y hidden','Thousands']))
 expect(result.allTexts.map(text=>text.text)).toEqual(['X hidden','Y hidden','Thousands'])
 const grids=result.paths.filter(path=>path.color==='#e3e3e3')
 expect(grids).toHaveLength(1)
 expect(grids[0]!.points[0]![1]).toBe(grids[0]!.points[1]![1])
 expect(result.ctx.rotate.mock.calls.map(call=>call[0])).toEqual([-Math.PI/2,-Math.PI/2])
})
it('uses distinct source scatter X and Y numeric formatting including percentage rounding and series fallback',()=>{
 const result=render('scatter',[],{axes:{
  category:{id:1,hidden:false,numberFormat:'0.00%',scaling:{min:0,max:0.5,majorUnit:0.25,reversed:false}},
  value:{id:2,hidden:false,scaling:{min:0,max:0.5,majorUnit:0.25,reversed:false}},
 },series:[{valuesRef:'',values:[0.25,0.5],xValues:[0.25,0.5],numberFormat:'0.00%'}]})
 expect(result.tickTexts.filter(text=>text.align==='center').map(text=>text.text)).toEqual(['0.00%','25.00%','50.00%'])
 expect(result.tickTexts.filter(text=>text.align==='right').map(text=>text.text)).toEqual(['0%','25%','50%'])
 const general=render('scatter',[],{axes:{
  category:{id:1,hidden:false,scaling:{min:0,max:0.123456,majorUnit:0.061728,reversed:false}},
  value:{id:2,hidden:false,scaling:{min:0,max:0.123456,majorUnit:0.061728,reversed:false}},
 },series:[{valuesRef:'',values:[0.123456],xValues:[0.123456]}]})
 expect(general.tickTexts.filter(text=>text.align==='center').map(text=>text.text)).toContain('0.06173')
 expect(general.tickTexts.filter(text=>text.align==='right').map(text=>text.text)).toContain('0.0617')
})
it('reserves scatter numeric and title bands within the chart frame',()=>{
 const result=render('scatter',[],{axes:{
  category:{id:1,hidden:false,title:'X title',scaling:{min:0,max:10000,majorUnit:5000,reversed:false}},
  value:{id:2,hidden:false,title:'Y title',displayUnit:1000,displayUnitLabel:'Thousands',scaling:{min:0,max:10000,majorUnit:5000,reversed:false}},
 },series:[{valuesRef:'',values:[0,10000],xValues:[0,10000]}]})
 for(const tick of result.tickTexts.filter(text=>text.align==='right'))expect(tick.x-tick.text.length*6).toBeGreaterThanOrEqual(8)
 const xTicks=result.tickTexts.filter(text=>text.align==='center')
 const title=result.allTexts.find(text=>text.text==='X title')!
 expect(title.y).toBeGreaterThan(xTicks[0]!.y+9)
 expect(title.y).toBeLessThan(200)
})
it.each(['','Chart title'])('keeps scatter maximum value labels below the title band for %s',title=>{
 const result=render('scatter',[],{title,dataLabels:{showValue:true},axes:{
  category:{id:1,hidden:false,title:'  X\n title  ',scaling:{min:0,max:2,reversed:false}},
  value:{id:2,hidden:false,scaling:{min:0,max:2,reversed:false}},
 },series:[{valuesRef:'',values:[2],xValues:[1],numberFormat:'0.00'}]})
 const label=result.allTexts.find(text=>text.text==='2.00'&&text.color==='#888')!
 expect(label.y-9).toBeGreaterThanOrEqual(title?20:0)
 expect(result.allTexts.some(text=>text.text==='X title')).toBe(true)
})
it('keeps a long scatter value label inside the frame at the rightmost point',()=>{
 const result=render('scatter',[],{dataLabels:{showValue:true},axes:{
  category:{id:1,hidden:false,scaling:{min:0,max:2,reversed:false}},
  value:{id:2,hidden:false,scaling:{min:0,max:10000,reversed:false}},
 },series:[{valuesRef:'',values:[10000],xValues:[2],numberFormat:'0.000'}]})
 const label=result.allTexts.find(text=>text.text==='10000.000'&&text.color==='#888')!
 expect(label.x+label.text.length*3).toBeLessThanOrEqual(392)
})
it('selects radar category labels but does not invent a clickable value axis',()=>{
 const result=render('radar',[],{series:[{valuesRef:'',values:[2,4,6]}]})
 const store=(window as unknown as {__sheetsWebCharts:{store:Map<string,ChartReadSpec[]>}}).__sheetsWebCharts.store
 const chart=store.get('test-unit::test-sheet')![0]!,[point]=result.ctx.arc.mock.calls
 expect(hitChartElement('test-unit','test-sheet',chart,200,4)).toEqual({kind:'category-axis'})
 expect(hitChartElement('test-unit','test-sheet',chart,200,180)).toEqual({kind:'chart'})
 expect(hitChartElement('test-unit','test-sheet',chart,200,100)).toEqual({kind:'series',seriesIndex:0})
 expect(hitChartElement('test-unit','test-sheet',chart,point![0] as number,point![1] as number)).toEqual({kind:'point',seriesIndex:0,pointIndex:0})
})

beforeEach(() => { setCharts('test-unit', 'test-sheet', undefined); setSelectedChartPath('test-unit', 'test-sheet') })

it('combo paints actual tagged families and independent secondary scales, never assuming the last series is the only line', () => {
  const result = render('combo', [], { series: [
    { name:'Primary line',valuesRef:'',values:[10,20],plot:'lineChart',secondaryAxis:false,color:'#123456' },
    { name:'Secondary bar',valuesRef:'',values:[1000,2000],plot:'barChart',secondaryAxis:true,color:'#456789' },
    { name:'Secondary line',valuesRef:'',values:[500,1500],plot:'lineChart',secondaryAxis:true,color:'#789abc' },
  ] })
  const bars = result.fills.filter(rect => rect.height > 10 && rect.width > 10)
  expect(bars).toHaveLength(2); expect(bars.map(bar=>bar.color)).toEqual(['#456789','#456789'])
  const primary = result.paths.find(path => path.color === '#123456')!, secondary = result.paths.find(path => path.color === '#789abc')!
  expect(primary.points).toHaveLength(2); expect(secondary.points).toHaveLength(2)
  expect(primary.points[0]![1]).toBeCloseTo(bars[0]!.y); expect(primary.points[1]![1]).toBeCloseTo(bars[1]!.y)
  expect(secondary.points[0]![1]).toBeGreaterThan(primary.points[0]![1]!)
})

describe('native chart numeric source', () => {
  it.each(['column', 'bar'] as const)('%s paints Select Data literal series without inventing grid references', kind => {
    const { fills } = render(kind, [], { series: [{ name: 'Literal', valuesRef: '', values: [10, 20], categories: ['A', 'B'] }] })
    expect(fills).toHaveLength(2)
    expect(kind === 'column' ? fills[0]!.height / fills[1]!.height : fills[0]!.width / fills[1]!.width).toBeCloseTo(0.5)
  })
  it.each(['pie', 'doughnut'] as const)('%s paints Select Data literal slices and category identity', kind => {
    const result = render(kind, [], { series: [{ name: 'Literal', valuesRef: '', values: [10, 20], categories: ['A', 'B'] }] })
    expect(result.pathColors.filter(color => color !== '#ffffff')).toHaveLength(2)
  })
  it('uses actual numeric values instead of numfmt display strings', () => {
    const { fills } = render('column', [['10.00', '$20.00']], {}, [[10, 20]])
    expect(fills).toHaveLength(2)
    expect(fills[0]!.height / fills[1]!.height).toBeCloseTo(0.5)
  })
  it('does not coerce text or stale display values into chart facts', () => {
    const { fills } = render('column', [[10, 20, 30]], {}, [['10', null, 30]])
    expect(fills).toHaveLength(1)
  })
})

describe('source chart anchor geometry', () => {
  it('paints the exact source 24px minimum frame and all eight selected resize handles', () => {
    setSelectedChartPath('test-unit', 'test-sheet', 'xl/charts/chart1.xml')
    const result = render('column', [[3]], { anchorKind: 'twoCellAnchor', anchor: { fromRow: 0, fromColumn: 0, toRow: 0, toColumn: 0, toRowOffset: 24 * 9525, toColumnOffset: 24 * 9525 } })
    expect(result.ctx.strokeRect).toHaveBeenCalledWith(0.5, 0.5, 23, 23)
    expect(result.fills.filter(fill => fill.color === '#2563eb').map(({ x, y }) => [x, y])).toEqual([[-4, -4], [8, -4], [20, -4], [20, 8], [20, 20], [8, 20], [-4, 20], [-4, 8]])
  })
  it.each(['oneCellAnchor', 'absoluteAnchor'] as const)('keeps the selected %s border without advertising unsupported resize handles', anchorKind => {
    setSelectedChartPath('test-unit', 'test-sheet', 'xl/charts/chart1.xml')
    const result = render('column', [[3]], { anchorKind })
    expect(result.ctx.strokeRect).toHaveBeenCalledWith(1, 1, 398, 198)
    expect(result.fills.filter(fill => fill.color === '#2563eb')).toHaveLength(0)
  })
  it('ends at the to marker rather than the far edge of its cell', () => {
    const result = render('bar', [[3, 6]], {
      anchor: { fromRow: 1, fromColumn: 2, toRow: 5, toColumn: 6 },
    })
    expect(result.ctx.strokeRect).toHaveBeenCalledWith(80.5, 20.5, 159, 79)
  })
  it('keeps a chart inside one cell at its exact EMU offsets', () => {
    const result = render('bar', [[3, 6]], {
      anchor: { fromRow: 1, fromColumn: 2, toRow: 1, toColumn: 2,
        fromRowOffset: 3 * 9525, fromColumnOffset: 5 * 9525,
        toRowOffset: 63 * 9525, toColumnOffset: 75 * 9525 },
    })
    expect(result.ctx.strokeRect).toHaveBeenCalledWith(85.5, 23.5, 69, 59)
  })
  it('supports signed source offsets without adding whole cells to the extent', () => {
    const result = render('bar', [[3, 6]], {
      anchor: { fromRow: 2, fromColumn: 2, toRow: 6, toColumn: 6,
        fromRowOffset: -4 * 9525, fromColumnOffset: -3 * 9525,
        toRowOffset: -2 * 9525, toColumnOffset: -7 * 9525 },
    })
    expect(result.ctx.strokeRect).toHaveBeenCalledWith(77.5, 36.5, 155, 81)
  })
})

describe('source chart fills', () => {
  it('pie legend preserves a blank category slot without suppressing the chart', () => {
    const result = render('pie', [[25, 75]], {
      series: [{ valuesRef: 'A1:A2', categories: ['', '乙'] }],
      legend: { position: 'right', overlay: false, hiddenEntries: [] },
    })
    expect(result.pathColors).toHaveLength(2)
    expect(result.texts.map(text => text.text)).toContain('乙')
  })
  it.each(['pie', 'doughnut'] as const)('%s keeps blank pie-category identity while drawing the categorical legend and slices', kind => {
    const result = render(kind, [[25, null, 75]], {
      series: [{ valuesRef: 'A1:A3', categories: ['甲', null, '丙'], pointColors: { 0: '#375623', 2: '#70ad47' } }],
      dataLabels: { showCategory: true, showPercent: true },
      legend: { position: 'right', overlay: false, hiddenEntries: [] },
    })
    expect(result.fills.filter(rect => rect.width === 8).map(rect => rect.color)).toEqual(['#375623', '#ed7d31', '#70ad47'])
    expect(result.pathColors.filter(color => color !== '#ffffff')).toEqual(['#375623', '#70ad47'])
    expect(result.texts.map(text => text.text)).toEqual(expect.arrayContaining(['甲', '', '丙', '25%', '75%']))
    expect(result.texts.map(text => text.text)).not.toContain('系列 1')
  })
  it.each(['pie', 'doughnut'] as const)('%s renders quick-layout category percents and categorical legend', kind => {
    const result = render(kind, [[25, null, 75]], {
      series: [{ valuesRef: 'A1:A3', categories: ['甲', '空', '丙'], pointColors: { 0: '#375623', 2: '#70ad47' } }],
      dataLabels: { showCategory: true, showPercent: true },
      legend: { position: 'right', overlay: false, hiddenEntries: [] },
    })
    expect(result.texts.map(text => text.text)).toEqual(expect.arrayContaining(['甲', '25%', '丙', '75%']))
    expect(result.texts.filter(text => text.text === '甲')).toHaveLength(2)
    expect(result.texts.filter(text => text.text === '丙')).toHaveLength(2)
    expect(result.texts.map(text => text.text)).not.toContain('系列 1')
    expect(result.fills.filter(rect => rect.width === 8).map(rect => rect.color)).toEqual(['#375623', '#ed7d31', '#70ad47'])
  })
  it.each(['bar', 'column'] as const)('%s keeps point identities across empty grid values', kind => {
    const result = render(kind, [[3, null, 6]], { palette: ['#136B4A'], series: [{ valuesRef: 'A1:A3', pointColors: { 2: '#A02040' } }] })
    expect(result.fills.map(rect => rect.color)).toEqual(['#136B4A', '#A02040'])
  })
  it.each(['pie', 'doughnut'] as const)('%s applies explicit series/point fills without compressing missing slots', kind => {
    const result = render(kind, [[3, null, 6]], { series: [{ valuesRef: 'A1:A3', color: '#136B4A', pointColors: { 2: '#A02040' } }] })
    expect(result.pathColors.filter(color => color !== '#ffffff')).toEqual(['#136B4A', '#A02040'])
  })
  it('respects explicit varyColors=false and noFill instead of inventing per-point colors', () => {
    expect(render('pie', [[3, 6]], { varyColors: false }).pathColors).toEqual(['#4472c4', '#4472c4'])
    const result = render('column', [[3, 6]], { series: [{ valuesRef: 'A1:A2', color: 'transparent', pointColors: { 1: '#A02040' } }] })
    expect(result.fills.map(rect => rect.color)).toEqual(['transparent', '#A02040'])
  })
  it('does not paint guessed colors when source fill cannot be previewed reliably', () => {
    const result = render('column', [[3, 6]], { series: [{ valuesRef: 'A1:A2', colorPreviewUnavailable: true }] })
    expect(result.fills).toEqual([])
    expect(result.texts.some(text => text.text.includes('填充暂不支持预览'))).toBe(true)
  })
})

describe('chart title fits its actual frame', () => {
  it('keeps a title longer than 24 characters when it fits', () => {
    const title = 'Quarterly revenue and cost comparison'
    expect(render('bar', [[3, 6]], { title }).texts[0]!.text).toBe(title)
  })
  it('uses measured ellipsis for a narrow frame instead of painting into adjacent cells', () => {
    const result = render('bar', [[3, 6]], { title: '很长的季度收入与成本比较标题',
      anchor: { fromRow: 0, fromColumn: 0, toRow: 9, toColumn: 1 } })
    const title = result.texts[0]!
    expect(title.text.endsWith('…')).toBe(true)
    expect(title.x + result.ctx.measureText(title.text).width).toBeLessThanOrEqual(34)
  })
})

describe.each(['bar', 'column'] as const)('%s actual registered canvas extension', kind => {
  it('draws positive/negative values on opposite sides of one zero line', () => {
    const [positive, negative] = paint(kind, [[3, -5]])
    expect(positive).toBeDefined(); expect(negative).toBeDefined()
    if (kind === 'bar') {
      expect(negative!.x + negative!.width).toBeCloseTo(positive!.x)
      expect(negative!.width / positive!.width).toBeCloseTo(5 / 3)
      expect(positive!.width).toBeGreaterThan(positive!.height)
    } else {
      expect(positive!.y + positive!.height).toBeCloseTo(negative!.y)
      expect(negative!.height / positive!.height).toBeCloseTo(5 / 3)
    }
    for (const rect of [positive!, negative!]) {
      expect(rect.x).toBeGreaterThanOrEqual(8); expect(rect.x + rect.width).toBeLessThanOrEqual(392)
      expect(rect.y).toBeGreaterThanOrEqual(8); expect(rect.y + rect.height).toBeLessThanOrEqual(192)
    }
  })

  it('does not invent a visible magnitude for zero, missing, or non-finite values', () => {
    const bars = paint(kind, [[0, null, undefined, 'text', NaN, Infinity, -Infinity]])
    expect(bars).toEqual([])
  })

  it('keeps missing category slots and longer later-series values aligned', () => {
    const bars = paint(kind, [[10, null, 20], [5, 8, 15, 7]])
    expect(bars).toHaveLength(6)
    const first = bars.filter(bar => bar.color === '#4472c4')
    const second = bars.filter(bar => bar.color === '#ed7d31')
    expect(first).toHaveLength(2); expect(second).toHaveLength(4)
    if (kind === 'bar') {
      expect(first[1]!.y - first[0]!.y).toBeCloseTo(2 * (second[1]!.y - second[0]!.y))
      expect(first[1]!.width / first[0]!.width).toBeCloseTo(2)
      expect(second[3]!.y + second[3]!.height).toBeLessThanOrEqual(192)
    } else {
      expect(first[1]!.x - first[0]!.x).toBeCloseTo(2 * (second[1]!.x - second[0]!.x))
      expect(first[1]!.height / first[0]!.height).toBeCloseTo(2)
      expect(second[3]!.x + second[3]!.width).toBeLessThanOrEqual(392)
    }
  })

  it('keeps all-negative bars inside the plot with zero at its far edge', () => {
    const bars = paint(kind, [[-10, -20]])
    expect(bars).toHaveLength(2)
    if (kind === 'bar') {
      expect(bars[0]!.x + bars[0]!.width).toBeCloseTo(392)
      expect(bars[1]!.x).toBeCloseTo(8+384*(2.5/22.5))
    } else {
      expect(bars[0]!.y).toBeCloseTo(8)
      expect(bars[1]!.y + bars[1]!.height).toBeCloseTo(8+184*20/22.5)
    }
  })

  it('uses finite geometry even when the raw numeric span overflows', () => {
    const bars = paint(kind, [[Number.MAX_VALUE, -Number.MAX_VALUE]])
    expect(bars).toHaveLength(2)
    expect(bars.every(rect => [rect.x, rect.y, rect.width, rect.height].every(Number.isFinite))).toBe(true)
    const extents = bars.map(rect => kind === 'bar' ? rect.width : rect.height)
    expect(extents[0]).toBeCloseTo(extents[1]!)
  })
})

describe('actual bar/column legends', () => {
  const series = [
    { name: 'Revenue', valuesRef: 'A1:A2', color: '#126B3A', index: 3 },
    { name: 'Cost', valuesRef: 'B1:B2', color: '#A02040', index: 8 },
  ]
  it.each(['top', 'bottom', 'left', 'right', 'top-right'] as const)('paints %s names and matching swatches outside the bars', position => {
    const result = render('bar', [[3, 5], [1, 2]], { series, legend: { position, overlay: false, hiddenEntries: [] } })
    expect(result.texts.map(item => item.text)).toEqual(['Revenue', 'Cost'])
    const swatches = result.fills.filter(rect => rect.width === 8 && rect.height === 8)
    const bars = result.fills.filter(rect => !swatches.includes(rect))
    expect(swatches.map(rect => rect.color)).toEqual(['#126B3A', '#A02040'])
    expect(bars).toHaveLength(4)
    for (const swatch of swatches) for (const bar of bars) {
      expect(swatch.x + swatch.width <= bar.x || bar.x + bar.width <= swatch.x ||
        swatch.y + swatch.height <= bar.y || bar.y + bar.height <= swatch.y).toBe(true)
    }
  })
  it('hides a canonical legend entry while retaining its plotted series', () => {
    const result = render('column', [[3, 5], [1, 2]], { series: series.map((entry, index) => ({...entry, index})),
      legend: { position: 'bottom', overlay: false, hiddenEntries: [0] } })
    expect(result.texts.map(item => item.text)).toEqual(['Cost'])
    expect(result.fills.filter(rect => rect.color === '#126B3A')).toHaveLength(2)
  })
  it('does not guess exception targets for noncanonical series identities', () => {
    const result = render('column', [[3, 5], [1, 2]], { series,
      legend: { position: 'bottom', overlay: false, hiddenEntries: [3] } })
    expect(result.texts).toEqual([])
    expect(result.fills).toHaveLength(4)
  })
  it('shows an omission marker for more entries than fit and clips text to the legend box', () => {
    const entries = Array.from({length:20}, (_,index) => ({name:'Series '+index, valuesRef:'A1:A2'}))
    const result = render('bar', [[3, 5]], {series:entries,legend:{position:'bottom',overlay:false,hiddenEntries:[]}})
    expect(result.texts.at(-1)!.text).toBe('… +15')
    expect(result.ctx.clip).toHaveBeenCalledOnce()
    expect(result.texts.every(text => text.x + text.text.length * 6 <= 392)).toBe(true)
  })
  it('does not reserve space when absent and paints overlay legends after the bars', () => {
    const normal = render('bar', [[3, 5], [1, 2]], { series })
    const overlay = render('bar', [[3, 5], [1, 2]], { series,
      legend: { position: 'right', overlay: true, hiddenEntries: [] } })
    expect(overlay.fills.slice(0, 4)).toEqual(normal.fills)
    expect(overlay.fills.slice(4)).toHaveLength(2)
  })
  it('shows source legends even when all data are missing and bounds long labels', () => {
    const result = render('bar', [[null, null]], {series:[{name:'Very long '.repeat(40),valuesRef:'A1:A2'}],
      legend:{position:'bottom',overlay:false,hiddenEntries:[]}})
    expect(result.texts).toHaveLength(1)
    expect(result.texts[0]!.text.endsWith('…')).toBe(true)
    expect(result.texts[0]!.x + result.texts[0]!.text.length * 6).toBeLessThanOrEqual(392)
  })
})

describe('actual linked axis titles', () => {
 const axes = {
  category:{id:1,position:'bottom' as const,hidden:false,title:'Quarter'},
  value:{id:2,position:'left' as const,hidden:false,title:'Amount (USD)'},
 }
 it.each(['bar','column'] as const)('places %s role titles on distinct bands without losing the bars',kind=>{
  const result=render(kind,[[3,5]],{axes})
  expect(result.texts.map(item=>item.text)).toEqual(['Quarter','Amount (USD)'])
  expect(result.ctx.rotate).toHaveBeenCalledWith(-Math.PI/2)
  expect(result.fills).toHaveLength(2)
  expect(result.fills.every(bar=>bar.x>=32&&bar.y+bar.height<=168)).toBe(true)
 })
 it('honors hidden axes without hiding the data or reserving an empty title band',()=>{
  const baseline=render('bar',[[3,5]],{axes:{category:{id:1,hidden:true},value:{id:2,hidden:true}}})
  const result=render('bar',[[3,5]],{axes:{category:{...axes.category,hidden:true},value:{...axes.value,hidden:true}}})
  expect(result.texts).toEqual([])
  expect(result.fills).toEqual(baseline.fills)
 })
 it('accepts top and right titles for a column and keeps them inside the frame',()=>{
  const result=render('column',[[3,5]],{axes:{category:{...axes.category,position:'top'},value:{...axes.value,position:'right'}}})
  expect(result.texts).toHaveLength(2)
  expect(result.ctx.rotate).toHaveBeenCalledWith(Math.PI/2)
  expect(result.fills.every(bar=>bar.y>=32&&bar.x+bar.width<=368)).toBe(true)
 })
 it('does not invent titles for an unreadable reference without a cache',()=>{
  const baseline=render('bar',[[3,5]],{axes:{category:{id:1,hidden:false},value:{id:2,hidden:false}}})
  const result=render('bar',[[3,5]],{axes:{category:{id:1,hidden:false,titleRef:'Other!A1'},value:{id:2,hidden:false}}})
  expect(result.texts).toEqual([])
  expect(result.fills).toEqual(baseline.fills)
 })
 it('truncates long titles inside their reserved horizontal and rotated bands',()=>{
  const result=render('bar',[[3,5]],{axes:{category:{...axes.category,title:'Long category '.repeat(80)},value:{...axes.value,title:'Long units '.repeat(80)}}})
  expect(result.texts.every(text=>text.text.endsWith('…'))).toBe(true)
  expect(result.texts[0]!.text.length*6).toBeLessThanOrEqual(160)
  expect(result.texts[1]!.text.length*6).toBeLessThanOrEqual(360)
  expect(result.ctx.clip).toHaveBeenCalledTimes(4)
 })
})

describe.each(['bar','column'] as const)('%s saved value bounds',kind=>{
 const axes=(scaling:NonNullable<NonNullable<ChartReadSpec['axes']>['value']['scaling']>)=>({category:{id:1,hidden:false},value:{id:2,hidden:false,scaling}})
 it('uses visible min/max and the clamped zero baseline',()=>{
  const bars=render(kind,[[3,6]],{axes:axes({min:2,max:8,reversed:false})}).fills
  expect(bars).toHaveLength(2)
  const length=kind==='bar'?'width':'height',extent=kind==='bar'?368:164
  expect(bars[0]![length]).toBeCloseTo(extent/6)
  expect(bars[1]![length]).toBeCloseTo(extent*4/6)
 })
 it('clips values at both range ends and omits bars wholly outside',()=>{
  const bars=render(kind,[[-5,3,12]],{axes:axes({min:2,max:8,reversed:false})}).fills
  expect(bars).toHaveLength(2)
  for(const bar of bars){expect(bar.x).toBeGreaterThanOrEqual(8);expect(bar.x+bar.width).toBeLessThanOrEqual(392);expect(bar.y).toBeGreaterThanOrEqual(8);expect(bar.y+bar.height).toBeLessThanOrEqual(192)}
  expect(kind==='bar'?bars[1]!.width:bars[1]!.height).toBeCloseTo(kind==='bar'?368:164)
 })
 it('honors reverse orientation while retaining lengths',()=>{
  const bars=render(kind,[[3,6]],{axes:axes({min:2,max:8,reversed:true})}).fills
  if(kind==='bar'){expect(bars[0]!.x+bars[0]!.width).toBeCloseTo(392);expect(bars[1]!.x).toBeLessThan(bars[0]!.x)}
  else {expect(bars[0]!.y).toBeCloseTo(8);expect(bars[1]!.y+bars[1]!.height).toBeGreaterThan(bars[0]!.y+bars[0]!.height)}
 })
 it('does not render an unsupported logarithmic axis as linear bars',()=>{
  const result=render(kind,[[3,6]],{axes:axes({reversed:false,unsupported:'logarithmic'})})
  expect(result.fills).toEqual([])
  expect(result.texts.some(text=>text.text.includes('暂不支持'))).toBe(true)
 })
})

it('does not apply automatic bounds when explicit scaling has no trustworthy axis pair',()=>{
 const result=render('bar',[[3,6]],{valueScaleUnavailable:true})
 expect(result.fills).toEqual([]);expect(result.texts.some(text=>text.text.includes('暂不支持'))).toBe(true)
})

describe('actual numeric axis ticks',()=>{
 const axes={category:{id:1,hidden:false},value:{id:2,hidden:false}}
 it('paints numeric labels from the same automatic scale as the bars',()=>{
  const result=render('bar',[[300,-500]],{axes})
  expect(result.tickTexts.map(t=>t.text)).toEqual(['-600','-400','-300','-200','-100','0','100','200','300','400'])
  for(let i=1;i<result.tickTexts.length;i++){
   const previous=result.tickTexts[i-1]!,current=result.tickTexts[i]!
   expect(current.x-current.text.length*3).toBeGreaterThanOrEqual(previous.x+previous.text.length*3+4)
  }
  const [positive,negative]=result.fills
  expect(positive!.x).toBeCloseTo(24+368*0.6)
  expect(negative!.width).toBeCloseTo(368*0.5)
  expect(result.ctx.stroke).toHaveBeenCalled()
 })
 it('honors percentage number format and a saved major unit',()=>{
  const result=render('bar',[[0.1,0.4]],{axes:{...axes,value:{...axes.value,numberFormat:'0%',scaling:{min:0,max:0.5,majorUnit:0.1,reversed:false}}}})
  expect(result.tickTexts.map(t=>t.text)).toEqual(['0%','10%','20%','30%','40%','50%'])
 })
 it('reverses labels and bars together at the top value axis',()=>{
  const result=render('bar',[[3,6]],{axes:{...axes,value:{...axes.value,position:'top',scaling:{min:2,max:8,reversed:true}}}})
  expect(result.tickTexts.find(t=>t.text==='2')!.x).toBeGreaterThan(result.tickTexts.find(t=>t.text==='8')!.x)
  expect(result.tickTexts.every(t=>t.y<result.fills[0]!.y)).toBe(true)
 })
 it('puts right-side column labels outside the data and preserves full numbers',()=>{
  const result=render('column',[[5000,10000]],{axes:{...axes,value:{...axes.value,position:'right'}}})
  expect(result.tickTexts.some(t=>t.text==='10,000')).toBe(true)
  expect(result.tickTexts.every(t=>t.x>=Math.max(...result.fills.map(b=>b.x+b.width)))).toBe(true)
 })
 it('does not invent ticks for hidden or unowned axes',()=>{
  expect(render('bar',[[3,6]],{axes:{...axes,value:{...axes.value,hidden:true}}}).tickTexts).toEqual([])
  expect(render('bar',[[3,6]]).tickTexts).toEqual([])
 })
})

describe('line chart value labels',()=>{
 const axes={category:{id:1,hidden:false},value:{id:2,hidden:false}}
 it('formats labels with the series number format at their plotted points',()=>{
  const result=render('line',[[2,4]],{axes,dataLabels:{showValue:true},series:[{valuesRef:'A1:A2',numberFormat:'"$"0.0'}]})
  expect(result.ctx.arc).toHaveBeenCalledTimes(2)
  expect(result.ctx.arc).toHaveBeenCalled()
  const labels=result.texts.filter(text=>text.text.startsWith('$'))
  expect(labels.map(text=>[text.text,text.font])).toEqual([['$2.0','11px system-ui'],['$4.0','11px system-ui']])
  expect(labels[0]!.y).toBeCloseTo(result.ctx.arc.mock.calls[0]![1] as number)
  expect(labels[1]!.y).toBeCloseTo(result.ctx.arc.mock.calls[1]![1] as number)
 })
 it('skips null values without shifting the remaining category slots',()=>{
  const result=render('line',[[2,null,8]],{axes,dataLabels:{showValue:true,numberFormat:'0.0'},series:[{valuesRef:'A1:A3'}]})
  const labels=result.texts.filter(text=>text.text==='2.0'||text.text==='8.0')
  expect(labels.map(text=>text.text)).toEqual(['2.0','8.0'])
  expect(result.ctx.arc).toHaveBeenCalledTimes(2)
  expect((result.ctx.arc.mock.calls[1]![0] as number)-(result.ctx.arc.mock.calls[0]![0] as number)).toBeGreaterThan(300)
  expect(labels[1]!.x).toBeGreaterThan(labels[0]!.x)
 })
})

describe('actual category labels and source category order',()=>{
 const axes={category:{id:1,hidden:false},value:{id:2,hidden:false}}
 it.each(['line','area'] as const)('places %s categories on the bottom axis aligned to series points',kind=>{
  const result=render(kind,[[3,6,9]],{axes,series:[{valuesRef:'A1:A3',categories:['Alpha','Beta','Gamma']}]})
  const labels=result.categoryTexts.filter(text=>['Alpha','Beta','Gamma'].includes(text.text))
  const points=result.ctx.arc.mock.calls
  expect(labels.map(text=>text.text)).toEqual(['Alpha','Beta','Gamma'])
  expect(labels.map(text=>text.x)).toEqual(points.map(point=>point[0]))
  expect(labels.every(text=>text.y>Math.max(...points.map(point=>point[1] as number)))).toBe(true)
 })
 it.each(['line','area'] as const)('keeps a single %s category at the first point slot',kind=>{
  const result=render(kind,[[3]],{axes,series:[{valuesRef:'A1:A1',categories:['Only']}]})
  const label=result.categoryTexts[0]!,point=result.ctx.arc.mock.calls[0]!
  expect(label.x).toBe(point[0])
  expect(label.x).toBeLessThan(50)
 })
 it.each(['line','area'] as const)('%s labels follow the primary category count and ignore unsupported reverse orientation',kind=>{
  const cases:Array<[number[],number[]]>=[[[3,6],[2,4,8]],[[3,6,9],[2,8]]]
  for(const [primaryValues,laterValues] of cases){
   const primaryLength=primaryValues.length
   const spec={axes,series:[{valuesRef:`A1:A${primaryLength}`,categories:Array.from({length:primaryLength},(_,index)=>`P${index+1}`)},{valuesRef:`B1:B${laterValues.length}`}]}
   const normal=render(kind,[primaryValues,laterValues],spec)
   const reversed=render(kind,[primaryValues,laterValues],{...spec,axes:{...axes,category:{...axes.category,reversed:true}}})
   const normalLabels=normal.categoryTexts.filter(text=>text.text.startsWith('P'))
   const reversedLabels=reversed.categoryTexts.filter(text=>text.text.startsWith('P'))
   const normalPoints=normal.ctx.arc.mock.calls
   const reversedPoints=reversed.ctx.arc.mock.calls
   expect(normalLabels.map(text=>text.x)).toEqual(normalPoints.slice(0,primaryLength).map(point=>point[0]))
   expect(reversedLabels.map(text=>text.x)).toEqual(reversedPoints.slice(0,primaryLength).map(point=>point[0]))
   expect(reversedPoints.map(point=>point[0])).toEqual(normalPoints.map(point=>point[0]))
  }
 })
 it.each(['bar','column'] as const)('paints outer multi-level groups beside %s leaf labels',kind=>{
  const result=render(kind,[[3,6,9,12]],{axes,series:[{valuesRef:'A1:A4',categories:['Q1','Q2','Q3','Q4'],categoryGroups:[{label:'H1',start:0,end:2},{label:'H2',start:2,end:4}]}]})
  const groups=result.categoryTexts.filter(text=>text.text==='H1'||text.text==='H2')
  expect(groups.map(text=>text.text)).toEqual(['H1','H2'])
  const leaves=result.categoryTexts.filter(text=>text.text.startsWith('Q'))
  expect(leaves).toHaveLength(4)
  if(kind==='column')expect(groups.every(group=>group.y>Math.max(...leaves.map(label=>label.y)))).toBe(true)
  else expect(groups.every(group=>group.x<Math.min(...leaves.map(label=>label.x)))).toBe(true)
 })
 it('keeps group spans in their reversed category slots when all leaf labels are blank',()=>{
  const result=render('column',[[3,6,9,12]],{axes:{...axes,category:{...axes.category,reversed:true}},series:[{valuesRef:'A1:A4',categories:['','','',''],categoryGroups:[{label:'H1',start:0,end:2},{label:'H2',start:2,end:4}]}]})
  const groups=result.categoryTexts.filter(text=>text.text==='H1'||text.text==='H2')
  expect(groups.map(text=>text.text)).toEqual(['H1','H2'])
  expect(groups[0]!.x).toBeGreaterThan(groups[1]!.x)
 })
 const series=[{valuesRef:'A1:A3',categoriesRef:"'Test'!$B$1:$B$3",categories:['STALE A','STALE B','STALE C']}]
 it.each(['bar','column'] as const)('keeps %s live blank labels and missing values in their original slots',kind=>{
  const result=render(kind,[[3,null,9],['Alpha',null,'Gamma']],{axes,series})
  expect(result.categoryTexts.map(t=>t.text).sort()).toEqual(['Alpha','Gamma'])
  expect(result.fills).toHaveLength(2)
  const [first,last]=result.fills
  const alpha=result.categoryTexts.find(t=>t.text==='Alpha')!,gamma=result.categoryTexts.find(t=>t.text==='Gamma')!
  if(kind==='bar'){
   expect(first!.y).toBeGreaterThan(last!.y)
   expect(alpha.y).toBeCloseTo(first!.y+first!.height/2)
   expect(gamma.y).toBeCloseTo(last!.y+last!.height/2)
  }else{
   expect(alpha.x).toBeCloseTo(first!.x+first!.width/2)
   expect(gamma.x).toBeCloseTo(last!.x+last!.width/2)
  }
 })
 it.each(['bar','column'] as const)('reverses %s categories and within-group series as in the source',kind=>{
  const entries=[{valuesRef:'A1:A2',categories:['North','South']},{valuesRef:'B1:B2'}]
  const normal=render(kind,[[3,6],[2,4]],{axes,series:entries})
  const reverse=render(kind,[[3,6],[2,4]],{axes:{...axes,category:{...axes.category,reversed:true}},series:entries})
  const axis=kind==='bar'?'y':'x'
  expect(Math.sign(normal.fills[0]![axis]-normal.fills[1]![axis])).toBe(-Math.sign(reverse.fills[0]![axis]-reverse.fills[1]![axis]))
  expect(Math.sign(normal.fills[0]![axis]-normal.fills[2]![axis])).toBe(-Math.sign(reverse.fills[0]![axis]-reverse.fills[2]![axis]))
 })
 it('uses cached external categories without reading same-address cells in the active sheet',()=>{
  const result=render('bar',[[3,6],['WRONG','WRONG']],{axes,series:[{valuesRef:'A1:A2',categoriesRef:'Other!B1:B2',categories:['Cached A','Cached B']}]})
  expect(result.categoryTexts.map(t=>t.text).sort()).toEqual(['Cached A','Cached B'])
 })
 it('paints a top category axis and a right category axis inside their own bands',()=>{
  for(const kind of ['column','bar'] as const){
   const result=render(kind,[[3,6]],{axes:{...axes,category:{...axes.category,position:kind==='bar'?'right':'top'}},series:[{valuesRef:'A1:A2',categories:['A','B']}]})
   expect(result.categoryTexts).toHaveLength(2)
   expect(result.categoryTexts.every(t=>kind==='bar'?t.x>Math.max(...result.fills.map(b=>b.x+b.width)):t.y<Math.min(...result.fills.map(b=>b.y)))).toBe(true)
  }
 })
 it('formats literal numeric categories with their saved percentage format',()=>{
  const result=render('column',[[3,6]],{axes,series:[{valuesRef:'A1:A2',categories:['0.1','0.25'],categoryNumberFormat:'0.0%'}]})
  expect(result.categoryTexts.map(t=>t.text)).toEqual(['10.0%','25.0%'])
 })
 it('hides category labels without changing category order or data',()=>{
  const result=render('bar',[[3,6]],{axes:{...axes,category:{...axes.category,hidden:true}},series:[{valuesRef:'A1:A2',categories:['A','B']}]})
  expect(result.categoryTexts).toEqual([])
  expect(result.fills[0]!.y).toBeGreaterThan(result.fills[1]!.y)
 })
})

describe('actual bar and column numeric data labels',()=>{
 it.each(['bar','column'] as const)('paints %s live signed and zero values without inventing a zero bar',kind=>{
  const result=render(kind,[[3,-5,0,null]],{dataLabels:{showValue:true}})
  expect(result.texts.map(t=>t.text)).toEqual(['3','-5','0'])
  expect(result.fills).toHaveLength(2)
 })
 it.each(['center','inside-end'] as const)('keeps %s labels inside positive and negative bars',position=>{
  const result=render('bar',[[3,-5]],{dataLabels:{showValue:true,position,numberFormat:'"$"0.0'}})
  expect(result.texts.map(t=>t.text)).toEqual(['$3.0','-$5.0'])
  result.texts.forEach((t,index)=>{
   const bar=result.fills[index]!
   expect(t.x).toBeGreaterThanOrEqual(bar.x)
   expect(t.x+t.text.length*6).toBeLessThanOrEqual(bar.x+bar.width)
   expect(t.y).toBeGreaterThan(bar.y);expect(t.y).toBeLessThan(bar.y+bar.height)
  })
 })
 it('follows the actual reversed growth direction for outside-end labels',()=>{
  const result=render('bar',[[3,-5]],{axes:{category:{id:1,hidden:true},value:{id:2,hidden:true,scaling:{min:-6,max:4,reversed:true}}},dataLabels:{showValue:true}})
  expect(result.texts.map(t=>t.text)).toEqual(['3','-5'])
  expect(result.texts[0]!.x+6).toBeLessThan(result.fills[0]!.x)
  expect(result.texts[1]!.x).toBeGreaterThan(result.fills[1]!.x+result.fills[1]!.width)
 })
 it('applies per-point enable/delete on top of series disable without changing point identity',()=>{
  const result=render('bar',[[3,6,9]],{dataLabels:{showValue:true},series:[{valuesRef:'A1:A3',dataLabels:{showValue:false,points:{0:{showValue:true},1:{showValue:true,deleted:true}}}}]})
  expect(result.texts.map(t=>t.text)).toEqual(['3'])
 })
 it('uses the original value of a clipped bar and omits a wholly invisible value',()=>{
  const result=render('bar',[[-5,12]],{axes:{category:{id:1,hidden:true},value:{id:2,hidden:true,scaling:{min:2,max:8,reversed:false}}},dataLabels:{showValue:true,position:'center'}})
  expect(result.texts.map(t=>t.text)).toEqual(['12']);expect(result.fills).toHaveLength(1)
 })
 it('keeps absent/disabled labels off and skips unsupported custom point labels',()=>{
  expect(render('bar',[[3,6]]).texts).toEqual([])
  expect(render('bar',[[3,6]],{dataLabels:{showValue:false}}).texts).toEqual([])
  const result=render('bar',[[3,6]],{dataLabels:{showValue:true,points:{1:{unsupported:true}}}})
  expect(result.texts.map(t=>t.text)).toEqual(['3'])
 })
 it('does not truncate numbers into partial labels when there is no room inside a thin bar',()=>{
  const result=render('bar',[Array(100).fill(3)],{dataLabels:{showValue:true,position:'inside-end'}})
  expect(result.texts).toEqual([]);expect(result.fills).toHaveLength(100)
 })
 it.each([[';;;',[]],['0;-0;;',['3']]] as const)('honors intentional empty number-format sections: %s',(numberFormat,expected)=>{
  expect(render('bar',[[0,3]],{dataLabels:{showValue:true,numberFormat}}).texts.map(t=>t.text)).toEqual(expected)
 })
})

describe('actual data-label typography',()=>{
 it('converts source points to CSS pixels and applies explicit RGB and bold',()=>{
  const result=render('bar',[[3,6]],{dataLabels:{showValue:true,position:'center',style:{sizePt:12,bold:true,color:'#123456'}}})
  expect(result.texts.map(t=>({font:t.font,color:t.color}))).toEqual([{font:'bold 16px system-ui',color:'#123456'},{font:'bold 16px system-ui',color:'#123456'}])
 })
 it('inherits style properties individually and honors an explicit point-level bold=false',()=>{
  const result=render('bar',[[3,6]],{dataLabels:{showValue:true,position:'center',style:{sizePt:12,bold:true,color:'#FF0000'}},series:[{valuesRef:'A1:A2',dataLabels:{style:{color:'#00AA00'},points:{0:{style:{bold:false}},1:{style:{sizePt:9}}}}}]})
  expect(result.texts.map(t=>({font:t.font,color:t.color}))).toEqual([{font:'16px system-ui',color:'#00AA00'},{font:'bold 12px system-ui',color:'#00AA00'}])
 })
 it('measures large labels before painting and omits those that cannot fit intact',()=>{
  const result=render('bar',[[3,6]],{dataLabels:{showValue:true,position:'center',style:{sizePt:72}}})
  expect(result.texts).toEqual([]);expect(result.fills).toHaveLength(2)
 })
})
it('previews source gap width, doughnut hole and exploded point geometry instead of fixed defaults',()=>{
 const wide=render('column',[[10,20]],{gapWidthPct:0}).fills,narrow=render('column',[[10,20]],{gapWidthPct:400}).fills;expect(wide[0]!.width).toBeGreaterThan(narrow[0]!.width*3)
 const base=render('doughnut',[],{holeSizePct:30,series:[{valuesRef:'',values:[3,7],explosionPct:0}]}),large=render('doughnut',[],{holeSizePct:70,series:[{valuesRef:'',values:[3,7],explosionPct:0}]})
 expect(large.ctx.arc.mock.calls[1]![2]).toBeCloseTo(base.ctx.arc.mock.calls[1]![2]!*7/3)
 const exploded=render('pie',[],{series:[{valuesRef:'',values:[3,7],pointExplosions:{1:40}}]}),plain=render('pie',[],{series:[{valuesRef:'',values:[3,7]}]})
 expect(exploded.ctx.arc.mock.calls[0]!.slice(0,2)).toEqual(plain.ctx.arc.mock.calls[0]!.slice(0,2));expect(exploded.ctx.arc.mock.calls[1]!.slice(0,2)).not.toEqual(plain.ctx.arc.mock.calls[1]!.slice(0,2))
})
