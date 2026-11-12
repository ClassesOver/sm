import type { ChartReadSpec } from '@sheets-web/xlsx-engine'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const registry = vi.hoisted(() => ({ extensions: [] as Array<new () => { draw(...args: unknown[]): void }> }))
vi.mock('@univerjs/engine-render', () => ({
  SheetExtension: class {},
  SpreadsheetExtensionRegistry: { add: (extension: typeof registry.extensions[number]) => registry.extensions.push(extension) },
}))
import { setCharts } from './chart-render'

type Rect = { x: number; y: number; width: number; height: number; color: string }
function render(kind: 'bar' | 'column', series: Array<Array<unknown>>, extra: Partial<ChartReadSpec> = {}) {
  const fills: Rect[] = []
  const texts: Array<{ text: string; x: number; y: number; font:string; color:string }> = []
  const tickTexts: typeof texts = []
  const categoryTexts: typeof texts = []
  const ctx = {
    fillStyle: '', strokeStyle: '', lineWidth: 1, font: '',
    save: vi.fn(), restore: vi.fn(), strokeRect: vi.fn(), beginPath: vi.fn(), rect: vi.fn(), clip: vi.fn(), translate: vi.fn(), rotate: vi.fn(),
    moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(),
    measureText: (text: string) => ({ width: text.length * 6 }),
    fillText(text: string, x: number, y: number) { (this.font === '10px system-ui' ? categoryTexts : this.font === '9px system-ui' ? tickTexts : texts).push({ text, x, y, font:this.font, color:this.fillStyle }) },
    fillRect(x: number, y: number, width: number, height: number) {
      fills.push({ x, y, width, height, color: this.fillStyle })
    },
  }
  const specs: ChartReadSpec[] = [{ chartPath: 'xl/charts/chart1.xml', kind,
    anchor: { fromRow: 0, fromColumn: 0, toRow: 9, toColumn: 9 },
    series: series.map((_, index) => ({ valuesRef: String.fromCharCode(65 + index) + '1:' + String.fromCharCode(65 + index) + series[index]!.length })),
    ...extra,
  }]
  setCharts('test-unit', 'test-sheet', specs)
  const extension = new registry.extensions[0]!()
  extension.draw(ctx, {}, {
    worksheet: { getUnitId: () => 'test-unit', getSheetId: () => 'test-sheet', getName: () => 'Test',
      getCell: (row: number, column: number) => ({ v: series[column]?.[row] }) },
    getCellWithCoordByIndex: (row: number, column: number) => ({
      startX: column * 40, endX: (column + 1) * 40, startY: row * 20, endY: (row + 1) * 20,
    }),
  })
  expect(ctx.restore.mock.calls.length).toBe(ctx.save.mock.calls.length)
  return { fills: fills.filter(rect => rect.color !== '#ffffff'), texts, tickTexts, categoryTexts, ctx }
}
const paint = (kind: 'bar' | 'column', series: Array<Array<unknown>>) => render(kind, series).fills

beforeEach(() => setCharts('test-unit', 'test-sheet', undefined))

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

describe('actual category labels and source category order',()=>{
 const axes={category:{id:1,hidden:false},value:{id:2,hidden:false}}
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
