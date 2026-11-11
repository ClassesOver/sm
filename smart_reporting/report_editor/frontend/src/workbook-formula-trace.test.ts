import { expect, it, vi } from 'vitest'
import vectors from './workbook-formula-trace-source-vectors.json'
import { collectPrecedents, collectDependents, planFormulaTrace, installFormulaTraceOverlay } from './workbook-formula-trace'

it('matches 18 fixed-source collector vectors', () => {
  for (const item of vectors.precedents) expect(collectPrecedents(item.formula, item.sheetName, item.bounds), item.formula).toEqual(item.expected)
  for (const item of vectors.dependents) expect(collectDependents(item.source, item.sheetName, item.target)).toEqual(item.expected)
})

it('reports unresolved names, structured and dynamic references without claiming no dependency', () => {
  const source = { sheets: { s: { name: 'S', cellData: { 0: { 0: { f: '=SUM(Revenue,Table1[Amount],INDIRECT("A1"))' }, 1: { f: '=A1+1' } } } } } }
  const plan = planFormulaTrace(source, 'S', { row: 0, column: 0 }, 'precedents', { lastRow: 4, lastColumn: 4, maxRows: 100, maxColumns: 20 })
  expect(plan.issues.join(' ')).toContain('完整')
  expect(plan.message).not.toContain('没有引用')
  expect(planFormulaTrace(source, 'S', { row: 0, column: 0 }, 'dependents', { lastRow: 4, lastColumn: 4, maxRows: 100, maxColumns: 20 }).issues.length).toBeGreaterThan(0)
  expect(() => planFormulaTrace({ sheets: { s: { name: 'S', cellData: Object.fromEntries(Array.from({length: 20001}, (_, i) => [i, { 0: { f: '=A1' } }])) } } }, 'S', { row: 0, column: 0 }, 'dependents', { lastRow: 20001, lastColumn: 0, maxRows: 21000, maxColumns: 20 })).toThrow('预算')
})

it('cleans all official range overlays when installation fails', () => {
  const dispose = vi.fn(), floatDispose = vi.fn()
  const runtime = { univerAPI: { registerComponent: vi.fn(() => ({ dispose })) } }
  const sheet = { getRange: vi.fn(() => ({})), addFloatDomToRange: vi.fn().mockReturnValueOnce({ dispose: floatDispose }).mockReturnValueOnce(null), getColumnWidth: () => 80, getRowHeight: () => 20 }
  expect(() => installFormulaTraceOverlay(runtime, sheet, { arrows: [{ from: { row: 0, column: 0 }, to: { row: 1, column: 1 } }], highlights: [{startRow: 0,endRow: 0,startColumn: 0,endColumn: 0}], issues: [], message: '' }, 'trace-test')).toThrow()
  expect(dispose).toHaveBeenCalledTimes(2); expect(floatDispose).toHaveBeenCalledTimes(1)
})

it('connects actual official endpoint bounds and follows observed pane layout without stale positions', async () => {
  const {createRoot} = await import('react-dom/client'), {flushSync} = await import('react-dom')
  const components: any[] = [], hosts: HTMLElement[] = [], roots: any[] = []
  const runtime = {univerAPI:{registerComponent: (_key: string, component: any) => {components.push(component); return {dispose(){}}}}}
  const sheet={getRange:(...range:number[])=>range,addFloatDomToRange:()=>({dispose(){}}),getColumnWidth:()=>80,getRowHeight:()=>20}
  const layer=installFormulaTraceOverlay(runtime,sheet,{arrows:[{from:{row:0,column:0},to:{row:5,column:3}}],highlights:[],issues:[],message:''},'pane')
  let targetX=300
  for(const [i,Component] of components.entries()){
    const host=document.createElement('div');document.body.append(host);hosts.push(host)
    host.getBoundingClientRect=()=>({x:i?targetX:100,y:i?440:370,left:i?targetX:100,top:i?440:370,right:(i?targetX:100)+80,bottom:(i?440:370)+20,width:80,height:20,toJSON(){}})
    const root=createRoot(host);roots.push(root);flushSync(()=>root.render(Component()))
  }
  await new Promise(resolve=>requestAnimationFrame(resolve))
  let svg=document.querySelector('.workbook-formula-trace-arrow')!
  expect(svg.querySelector('circle')!.getAttribute('cx')).toBe('140')
  expect(svg.querySelector('polygon')!.getAttribute('points')).toMatch(/^340,450 /)
  targetX=260;hosts[1]!.style.left='260px'
  await new Promise(resolve=>setTimeout(resolve,30))
  expect(svg.querySelector('polygon')!.getAttribute('points')).toMatch(/^300,450 /)
  layer.dispose();expect(document.querySelector('.workbook-formula-trace-arrow')).toBeNull()
  roots.forEach(root=>flushSync(()=>root.unmount()));hosts.forEach(host=>host.remove())
})

it('replaces endpoint observers on React ref rebinding and releases them on disposal', () => {
  const original=globalThis.MutationObserver, instances: {disconnect: ReturnType<typeof vi.fn>}[]=[]
  globalThis.MutationObserver=class {disconnect=vi.fn();observe(){};takeRecords(){return []};constructor(){instances.push(this)}} as any
  try {
    const components:any[]=[],host=document.createElement('div'),element=document.createElement('div');host.append(element);document.body.append(host)
    const layer=installFormulaTraceOverlay({univerAPI:{registerComponent:(_key,component)=>{components.push(component);return {dispose(){}}}}},{getRange:()=>({}),addFloatDomToRange:()=>({dispose(){}}),getColumnWidth:()=>80,getRowHeight:()=>20},{arrows:[{from:{row:0,column:0},to:{row:1,column:1}}],highlights:[],issues:[],message:''},'rebind')
    const ref=components[0]().props.ref;ref(element);ref(null);ref(element)
    expect(instances[0]!.disconnect).toHaveBeenCalledTimes(1)
    layer.dispose();expect(instances[1]!.disconnect).toHaveBeenCalledTimes(1);host.remove()
  }finally{globalThis.MutationObserver=original}
})

it('does not draw pseudo cell references from unsupported structured or dynamic formulas', () => {
  const bounds = {lastRow: 4,lastColumn: 4,maxRows: 100,maxColumns: 20}
  const source = {sheets:{s:{name:'S',cellData:{0:{0:{f:'=SUM(Table1[A1])'},1:{f:'=A1'},2:{f:'=INDIRECT(A1)'}}}}}}
  const precedent = planFormulaTrace(source, 'S', {row:0,column:0}, 'precedents', bounds)
  expect(precedent.highlights).toEqual([]); expect(precedent.issues.join(' ')).toContain('完整')
  const dependent = planFormulaTrace(source, 'S', {row:0,column:0}, 'dependents', bounds)
  expect(dependent.arrows).toEqual([{from:{row:0,column:0},to:{row:0,column:1}}]); expect(dependent.issues.length).toBeGreaterThan(0)
})

it('anchors RTL cross-column layers to the visual left cell with explicit nonnegative extents', () => {
  const widths = [40, 0, 100, 80], heights = [20, 40]
  // 官方 rangePosition = endColumn.right - startColumn.left；RTL 跨列会得到负宽。
  const left = (column: number) => widths.slice(column + 1).reduce((a, b) => a + b, 0)
  const officialWidth = (range: number[]) => left(range[1] + range[3] - 1) + widths[range[1] + range[3] - 1]! - left(range[1])
  expect(officialWidth([0, 0, 2, 4])).toBe(-100)
  const calls: { range: number[]; width: number; height: number }[] = []
  const sheet = { getRange: (...range: number[]) => range, getColumnWidth: (i: number) => widths[i]!, getRowHeight: (i: number) => heights[i]!, addFloatDomToRange: (range: number[], _layer: unknown, anchor: {width?: number;height?: number}) => { calls.push({range, width: anchor.width ?? officialWidth(range), height: anchor.height ?? 0}); return {dispose() {}} } }
  const runtime = {univerAPI:{registerComponent: () => ({dispose() {}})}}
  const layer = installFormulaTraceOverlay(runtime, sheet, {arrows:[{from:{row:0,column:0},to:{row:1,column:3}}], highlights:[{startRow:0,endRow:0,startColumn:0,endColumn:3}],issues:[],message:''}, 'rtl-extents', true)
  expect(calls).toEqual([{range:[0,3,1,1],width:220,height:20},{range:[0,0,1,1],width:40,height:20},{range:[1,3,1,1],width:80,height:40}])
  layer.dispose()
})


it('refuses zero-area and merged anchor layers with explicit reasons', () => {
  const runtime = {univerAPI:{registerComponent:vi.fn(() => ({dispose(){}}))}}
  const sheet = {getRange:vi.fn(() => ({})),addFloatDomToRange:vi.fn(() => ({dispose(){}})),getColumnWidth:()=>0,getRowHeight:()=>20,isMergedCell:()=>false}
  const plan = {arrows:[{from:{row:0,column:0},to:{row:1,column:2}}],highlights:[],issues:[],message:''}
  expect(()=>installFormulaTraceOverlay(runtime,sheet,plan,'zero',true)).toThrow('隐藏')
  expect(sheet.addFloatDomToRange).not.toHaveBeenCalled()
  sheet.getColumnWidth=()=>80;sheet.isMergedCell=()=>true
  expect(()=>installFormulaTraceOverlay(runtime,sheet,plan,'merged',true)).toThrow('合并')
  expect(sheet.addFloatDomToRange).not.toHaveBeenCalled()
})
