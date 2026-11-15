import {expect,it,vi} from 'vitest'
import {createWorkbookChartFormatPane} from './workbook-chart-format-pane'
it('preserves source explosion outside the slider range on blur and resolves point indices from the real reference',()=>{document.body.innerHTML='<main></main>';const root=document.querySelector('main')!,apply=vi.fn(async(_edit:import('@sheets-web/xlsx-engine').ChartEditLean)=>chart),pane=createWorkbookChartFormatPane(root,{apply,editable:()=>true});try{pane.open({...chart,series:[{...chart.series[0]!,valuesRef:"'收入表'!$B$2:$B$6",values:undefined,categories:[],explosionPct:250}]});const range=root.querySelector<HTMLInputElement>('[aria-label=饼图分离度]')!;range.dispatchEvent(new Event('blur'));expect(apply).not.toHaveBeenCalled();expect(range.parentElement!.textContent).toContain('来源 250');expect([...root.querySelector<HTMLSelectElement>('[aria-label=图表元素]')!.options].some(option=>option.value==='point:0:4')).toBe(true)}finally{pane.dispose()}})
const chart={chartPath:'xl/charts/chart1.xml',kind:'doughnut' as const,title:'收入',anchor:{fromRow:0,fromColumn:4,toRow:12,toColumn:12},holeSizePct:70,series:[{index:4,name:'甲',valuesRef:'',values:[3,0,7],categories:['甲','空','乙'],color:'#123456',explosionPct:20,pointExplosions:{2:45}}]}
it('shows the full fixed-source pie and point controls, echoes file values and commits one release',async()=>{
 document.body.innerHTML='<main></main>';const root=document.querySelector('main')!,apply=vi.fn(async(_edit:import('@sheets-web/xlsx-engine').ChartEditLean)=>chart);const pane=createWorkbookChartFormatPane(root,{apply,editable:()=>true})
 try{pane.open(chart);expect(root.querySelector<HTMLInputElement>('[aria-label=圆环内径]')?.value).toBe('70');expect(root.querySelector<HTMLInputElement>('[aria-label=饼图分离度]')?.value).toBe('20')
 const target=root.querySelector<HTMLSelectElement>('[aria-label=图表元素]')!;target.value='point:0:2';target.dispatchEvent(new Event('change',{bubbles:true}));expect(root.querySelector<HTMLInputElement>('[aria-label=数据点分离度]')?.value).toBe('45')
 const range=root.querySelector<HTMLInputElement>('[aria-label=圆环内径]')!;range.value='60';range.dispatchEvent(new Event('input',{bubbles:true}));expect(apply).not.toHaveBeenCalled();range.dispatchEvent(new Event('pointerup',{bubbles:true}));await vi.waitFor(()=>expect(apply).toHaveBeenCalledOnce());expect(apply.mock.calls[0]![0]).toEqual({holeSizePct:60})
 }finally{pane.dispose()}
})

it('shows hydrated series and point labels when the source chart has references without caches',()=>{
 document.body.innerHTML='<main></main>';const root=document.querySelector('main')!,apply=vi.fn(async(_edit:import('@sheets-web/xlsx-engine').ChartEditLean)=>chart)
 const pane=createWorkbookChartFormatPane(root,{apply,editable:()=>true,hydrate:source=>({...source,series:source.series.map(series=>({...series,nameCache:'Operating cost',categories:['Jan','Feb']}))})})
 try{pane.open({...chart,series:[{...chart.series[0]!,name:'Sheet1!$A$1',nameCache:undefined,nameRef:'Sheet1!$A$1',categories:[],categoriesRef:'Sheet1!$A$2:$A$4'}]})
  const targets=[...root.querySelector<HTMLSelectElement>('[aria-label="图表元素"]')!.options].map(option=>option.textContent)
  expect(targets).toContain('系列「Operating cost」');expect(targets).toContain('数据点「Jan」（系列1）');expect(targets).toContain('数据点「Feb」（系列1）')
 }finally{pane.dispose()}
})

it('bounds selectable point targets to writer-supported point indexes',()=>{
 document.body.innerHTML='<main></main>';const root=document.querySelector('main')!,apply=vi.fn(async(_edit:import('@sheets-web/xlsx-engine').ChartEditLean)=>chart),pane=createWorkbookChartFormatPane(root,{apply,editable:()=>true})
 try{pane.open({...chart,series:[{...chart.series[0]!,valuesRef:'Sheet1!B1:B1048576',values:undefined,categories:[]}]})
  const options=[...root.querySelector<HTMLSelectElement>('[aria-label="图表元素"]')!.options].map(option=>option.value)
  expect(options).toContain('point:0:999');expect(options).not.toContain('point:0:1000');expect(options.length).toBeLessThan(1_005)
 }finally{pane.dispose()}
})

it('offers only scatter plot value labels and commits the plot mode without format or series edits',async()=>{
 document.body.innerHTML='<main></main>';const root=document.querySelector('main')!
 const scatter={...chart,kind:'scatter' as const,design:{dataLabels:'none' as const},dataLabels:{showValue:false}}
 const next={...scatter,design:{dataLabels:'value' as const},dataLabels:{showValue:true}}
 const apply=vi.fn(async(_edit:import('@sheets-web/xlsx-engine').ChartEditLean)=>next)
 const pane=createWorkbookChartFormatPane(root,{apply,editable:()=>true})
 try{pane.open(scatter)
  const labels=root.querySelector<HTMLSelectElement>('[aria-label="数据标签"]')
  expect(labels).not.toBeNull()
  expect([...labels!.options].map(option=>option.value)).toEqual(['none','value'])
  expect(labels!.value).toBe('none')
  expect(root.querySelector('[aria-label="标签位置"]')).toBeNull()
  expect(root.querySelector('[aria-label="标签数字格式"]')).toBeNull()
  labels!.value='value';labels!.dispatchEvent(new Event('change',{bubbles:true}))
  await vi.waitFor(()=>expect(apply).toHaveBeenCalledExactlyOnceWith({dataLabels:'value'}))
  expect(root.querySelector<HTMLSelectElement>('[aria-label="数据标签"]')!.value).toBe('value')
  expect(root.querySelector('[aria-label="标签数字格式"]')).toBeNull()
 }finally{pane.dispose()}
})

it('preserves unsupported scatter label detail settings and disables its plot selector when read-only',()=>{
 document.body.innerHTML='<main></main>';const root=document.querySelector('main')!,apply=vi.fn(async()=>chart)
 const scatter={...chart,kind:'scatter' as const,design:{dataLabels:'value' as const},dataLabels:{showValue:true,numberFormat:'0.000',position:'inside-end' as const}}
 const before=JSON.stringify(scatter),pane=createWorkbookChartFormatPane(root,{apply,editable:()=>false})
 try{pane.open(scatter)
  const labels=root.querySelector<HTMLSelectElement>('[aria-label="数据标签"]')
  expect(labels?.value).toBe('value');expect(labels?.disabled).toBe(true)
  expect(root.querySelector('[aria-label="标签位置"]')).toBeNull()
  expect(root.querySelector('[aria-label="标签数字格式"]')).toBeNull()
  expect(JSON.stringify(scatter)).toBe(before);expect(apply).not.toHaveBeenCalled()
  pane.open({...scatter,kind:'radar'})
  expect(root.querySelector('[aria-label="数据标签"]')).toBeNull()
 }finally{pane.dispose()}
})

it('explains the conditional scatter off restriction, guards synthetic changes and resets on another chart',async()=>{
 document.body.innerHTML='<main></main>'
 const root=document.querySelector('main')!,apply=vi.fn(async()=>chart),pane=createWorkbookChartFormatPane(root,{apply,editable:()=>true})
 try{
  pane.open({...chart,kind:'scatter',design:{dataLabels:'value',dataLabelsOffUnavailable:true}})
  const labels=root.querySelector<HTMLSelectElement>('[aria-label="数据标签"]')!
  expect(labels.querySelector<HTMLOptionElement>('option[value="none"]')!.disabled).toBe(true)
  expect(root.textContent).toContain('首个系列')
  labels.value='none';labels.dispatchEvent(new Event('change',{bubbles:true}))
  await Promise.resolve()
  expect(apply).not.toHaveBeenCalled()
  expect(root.querySelector('[role="alert"]')!.textContent).toContain('首个系列')
  pane.open({...chart,kind:'scatter',design:{dataLabels:'value'}})
  const next=root.querySelector<HTMLSelectElement>('[aria-label="数据标签"]')!
  expect(next.querySelector<HTMLOptionElement>('option[value="none"]')!.disabled).toBe(false)
  next.value='none';next.dispatchEvent(new Event('change',{bubbles:true}))
  await vi.waitFor(()=>expect(apply).toHaveBeenCalledWith({dataLabels:'none'}))
 }finally{pane.dispose()}
})
