import { expect, it, vi } from 'vitest'
const path = './workbook-outline-gutter'
async function product(): Promise<any> { return import(/* @vite-ignore */ path) }
function frames() {
  let serial = 0
  const pending = new Map<number, () => void>()
  return { request: (fn: () => void) => { pending.set(++serial, fn); return serial }, cancel: (id: number) => pending.delete(id),
    flush: () => { const all = [...pending.values()]; pending.clear(); all.forEach(fn => fn()) }, pending }
}
it('coalesces outline paint triggers and sleeps after geometry stabilizes', async () => {
  const { paintLoop } = await product(), f = frames()
  let paints = 0
  const loop = paintLoop(f.request, f.cancel, () => ++paints < 2)
  loop.schedule(); loop.schedule(); expect(f.pending.size).toBe(1)
  f.flush(); expect(f.pending.size).toBe(1)
  f.flush(); expect(f.pending.size).toBe(0); expect(paints).toBe(2)
  loop.schedule(); f.flush(); expect(paints).toBe(3)
  loop.schedule(); loop.dispose(); loop.schedule(); expect(f.pending.size).toBe(0)
}, 15000)

it('supports a real headless Univer lifecycle without creating canvas or render observers', async () => {
  const { Univer } = await import('@univerjs/core')
  const { FUniver } = await import('@univerjs/core/lib/facade')
  const univer = new Univer(), host = document.createElement('div')
  try {
    const { installOutlineGutter } = await product()
    const gutter = installOutlineGutter({runtime: {univer, univerAPI: FUniver.newAPI(univer)}, host, onLevel: vi.fn(), onToggleGroup: vi.fn()})
    gutter.refresh(); gutter.dispose(); gutter.dispose()
    expect(host.querySelector('canvas')).toBeNull()
    expect(host.classList.contains('has-outline')).toBe(false)
  } finally {univer.dispose()}
}, 15000)

// jsdom没有真实Univer renderer，以下仅替代视口/Canvas环境；metadata仍用产品reader。
async function environment() {
  const { Univer, IUniverInstanceService } = await import('@univerjs/core')
  const { FUniver } = await import('@univerjs/core/lib/facade')
  const { UniverSheetsPlugin } = await import('@univerjs/sheets')
  await import('@univerjs/sheets/facade')
  const univer = new Univer(); univer.registerPlugin(UniverSheetsPlugin)
  const native = FUniver.newAPI(univer)
  const outlineEntry = {custom:{genofficeOutline:{level:1,collapsed:false}}}
  let workbook = native.createWorkbook({id:'gutter-unit',name:'Gutter',sheetOrder:['data'],sheets:{data:{id:'data',name:'Data',rowCount:30,columnCount:10,rowData:{1:structuredClone(outlineEntry)},columnData:{1:structuredClone(outlineEntry)}}}})
  univer.__getInjector().get(IUniverInstanceService).focusUnit(workbook.getId())
  const host=document.createElement('div'),canvas=document.createElement('canvas'),grid=document.createElement('div');grid.id='workbook-grid';grid.append(canvas);host.append(grid);document.body.append(host)
  const f=frames(),triggers:Record<string,(command?:any)=>void>={},subscriptions:{dispose:ReturnType<typeof vi.fn>}[]=[],commands:any[]=[]
  const rowAccum=Array.from({length:30},(_,i)=>(i+1)*20),colAccum=Array.from({length:10},(_,i)=>(i+1)*60)
  const skeleton:any={get worksheet(){return workbook.getActiveSheet()!.getSheet()},columnHeaderHeight:24,rowHeightAccumulation:rowAccum,columnWidthAccumulation:colAccum,rowTotalHeight:600,columnTotalWidth:600}
  const viewport={isActive:true,top:24,left:40,width:560,height:376,viewportScrollX:0,viewportScrollY:0}
  const render={with:()=>({getCurrentSkeleton:()=>skeleton}),scene:{getAncestorScale:()=>({scaleX:1,scaleY:1}),getViewport:(key:string)=>key==='viewMain'?viewport:undefined,makeDirty:vi.fn()},engine:{getCanvasElement:()=>canvas}}
  const rectSpy=vi.spyOn(HTMLElement.prototype,'getBoundingClientRect').mockImplementation(function(this:HTMLElement){const x=this===canvas?32:0,width=this.classList.contains('outline-gutter-rows')?32:600,height=this.classList.contains('outline-gutter-cols')?Number.parseFloat(this.style.height)||0:400;return {x,y:0,left:x,top:0,right:x+width,bottom:height,width,height,toJSON(){}} as DOMRect})
  const ctx=new Proxy({}, {get:()=>()=>{},set:()=>true})
  const contextSpy=vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue(ctx as any)
  vi.stubGlobal('ResizeObserver',class {observe(){}unobserve(){}disconnect(){}})
  vi.stubGlobal('requestAnimationFrame',f.request);vi.stubGlobal('cancelAnimationFrame',f.cancel)
  const runtime={univer:{__getInjector:()=>({has:()=>true,get:()=>({getRenderById:()=>render})})},univerAPI:{
    getActiveWorkbook:()=>workbook,Event:{Scroll:'scroll'},addEvent:(_event:string,callback:()=>void)=>{triggers.scroll=callback;const s={dispose:vi.fn()};subscriptions.push(s);return s},onCommandExecuted:(callback:()=>void)=>{triggers.command=callback;const s={dispose:vi.fn()};subscriptions.push(s);return s},
    executeCommand:(_id:string,params:any)=>{commands.push(params);skeleton.columnHeaderHeight=params.size;return Promise.resolve(true)}
  }}
  return {host,canvas,f,skeleton,commands,subscriptions,triggers,runtime,replace(){native.disposeUnit(workbook.getId());workbook=native.createWorkbook({id:'gutter-unit',name:'New',sheetOrder:['data'],sheets:{data:{id:'data',name:'Data',rowCount:30,columnCount:10}}})},async flush(){for(let i=0;i<5;i++){f.flush();await Promise.resolve()}},dispose(){host.remove();contextSpy.mockRestore();rectSpy.mockRestore();vi.unstubAllGlobals();univer.dispose()}}
}
it('restores header geometry, removes gutter DOM and cancels observers and pending frames on dispose',async()=>{
 const current=await environment()
 try {
  const {installOutlineGutter}=await product(),gutter=installOutlineGutter({...current,onLevel:vi.fn(),onToggleGroup:vi.fn()})
  await current.flush()
  expect(current.host.classList.contains('has-outline')).toBe(true)
  expect(current.skeleton.columnHeaderHeight).toBeGreaterThan(24)
  gutter.dispose()
  expect(current.skeleton.columnHeaderHeight).toBe(24)
  expect(current.host.querySelector('.outline-gutter')).toBeNull()
  expect(current.f.pending.size).toBe(0)
  expect(current.subscriptions.every(s=>s.dispose.mock.calls.length===1)).toBe(true)
 }finally{current.dispose()}
},15000)
it('rejects painted group hits after same-id workbook core replacement and clears the old canvases', async()=>{
 const current=await environment()
 try {
  const {installOutlineGutter}=await product(),onToggleGroup=vi.fn()
  const gutter=installOutlineGutter({...current,onLevel:vi.fn(),onToggleGroup})
  await current.flush()
  const canvas=current.host.querySelector('.outline-gutter-rows')!
  canvas.dispatchEvent(new MouseEvent('click',{clientX:10,clientY:74,bubbles:true}))
  expect(onToggleGroup).toHaveBeenCalledTimes(1)
  expect(onToggleGroup.mock.calls[0][1]).toMatchObject({level:1,start:1,end:1,summary:2})
  current.replace()
  canvas.dispatchEvent(new MouseEvent('click',{clientX:10,clientY:74,bubbles:true}))
  expect(onToggleGroup).toHaveBeenCalledTimes(1)
  await current.flush()
  expect(current.host.querySelector('.outline-gutter')).toBeNull()
  gutter.dispose()
 }finally{current.dispose()}
},15000)
it('does not reschedule or mutate a replaced core when a pending header promise settles after dispose',async()=>{
 const current=await environment()
 try{
  const original=current.runtime.univerAPI.executeCommand
  let settle:()=>void=()=>{}
  current.runtime.univerAPI.executeCommand=(id,params)=>{void original(id,params);return new Promise(resolve=>{settle=()=>resolve(true)})}
  const {installOutlineGutter}=await product(),gutter=installOutlineGutter({...current,onLevel:vi.fn(),onToggleGroup:vi.fn()})
  current.f.flush()
  current.replace()
  const count=current.commands.length
  gutter.dispose();settle();await Promise.resolve();await Promise.resolve()
  expect(current.commands.length).toBe(count)
  expect(current.f.pending.size).toBe(0)
 }finally{current.dispose()}
},15000)
it('measures real 10000-row metadata refresh and returns the paint loop to sleep',async()=>{
 const current=await environment()
 try{
  const sheet=current.runtime.univerAPI.getActiveWorkbook().getActiveSheet()!
  const manager=sheet.getSheet().getRowManager()
  sheet.getSheet().setRowCount(10100)
  for(let index=0;index<10000;index++){manager.getRowOrCreate(index);manager.setCustomMetadata(index,{genofficeOutline:{level:1,collapsed:false}})}
  const {installOutlineGutter}=await product(),gutter=installOutlineGutter({...current,onLevel:vi.fn(),onToggleGroup:vi.fn()})
  await current.flush()
  const samples:number[]=[]
  for(let i=0;i<8;i++){const start=performance.now();gutter.refresh();await current.flush();samples.push(performance.now()-start)}
  expect(current.f.pending.size).toBe(0)
  console.log(JSON.stringify({case:'outline-gutter-10000-rows',samplesMs:samples,averageMs:samples.reduce((a,b)=>a+b)/samples.length,sleeping:true}))
  gutter.dispose()
 }finally{current.dispose()}
},15000)

it('reuses metadata on scroll and coalesces command or explicit refresh invalidation until the next paint',async()=>{
 const current=await environment()
 try{
  const sheet=current.runtime.univerAPI.getActiveWorkbook().getActiveSheet()!
  const manager=sheet.getSheet().getRowManager(),reads=vi.spyOn(manager,'getRowData')
  const {installOutlineGutter}=await product(),gutter=installOutlineGutter({...current,onLevel:vi.fn(),onToggleGroup:vi.fn()})
  await current.flush();reads.mockClear()
  for(let i=0;i<5;i++){current.triggers.scroll();await current.flush()}
  expect(reads).not.toHaveBeenCalled()
  for(const id of ['sheet.operation.set-scroll','sheet.command.set-scroll-relative']){current.triggers.command({id});await current.flush()}
  expect(reads).not.toHaveBeenCalled()
  current.triggers.command();current.triggers.command();expect(reads).not.toHaveBeenCalled()
  await current.flush();expect(reads).toHaveBeenCalled()
  reads.mockClear()
  manager.setCustomMetadata(1,{genofficeOutline:{level:2,collapsed:false}})
  current.triggers.scroll();await current.flush()
  expect(current.host.style.getPropertyValue('--outline-gutter-w')).toBe('32px')
  gutter.refresh();expect(reads).not.toHaveBeenCalled();await current.flush();expect(reads).toHaveBeenCalled()
  expect(current.host.style.getPropertyValue('--outline-gutter-w')).toBe('45px')
  reads.mockClear();current.triggers.command({id:'sheet.operation.set-selections'});await current.flush();expect(reads).toHaveBeenCalled()
  reads.mockClear();current.triggers.command({id:'univer.command.undo'});await current.flush();expect(reads).toHaveBeenCalled()
  gutter.dispose();reads.mockRestore()
 }finally{current.dispose()}
},15000)
