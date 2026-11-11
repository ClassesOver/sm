import { expect, it, vi } from 'vitest'
import { Univer, LocaleType, IUniverInstanceService } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { IFunctionService, UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-formula/facade'
import { installRateFallback } from './workbook-function-rate'

async function setup(installBefore=false) {
 const univer=new Univer({locale:LocaleType.EN_US,locales:{[LocaleType.EN_US]:{}}})
 univer.registerPlugin(UniverSheetsPlugin);univer.registerPlugin(UniverFormulaEnginePlugin);univer.registerPlugin(UniverSheetsFormulaPlugin)
 const api=FUniver.newAPI(univer),earlyFallback=installBefore?installRateFallback({univer}):undefined,book=api.createWorkbook({id:'rate-book',name:'RATE',sheetOrder:['data'],sheets:{data:{id:'data',name:'Data',rowCount:20,columnCount:10}}})
 univer.__getInjector().get(IUniverInstanceService).focusUnit(book.getId())
 return {univer,api,book,earlyFallback,sheet:book.getActiveSheet()!,runtime:{univer,univerAPI:api},service:univer.__getInjector().get(IFunctionService)}
}

it('rescues an actual Univer RATE formula whose Newton iterate crosses -1',async()=>{
 const c=await setup(),fallback=installRateFallback(c.runtime)
 try{
  c.sheet.getRange('A1').setValue({f:'=RATE(5,-100,100,10)'})
  await vi.waitFor(()=>expect(c.sheet.getRange('A1').getValue()).not.toBeNull())
  const value=c.sheet.getRange('A1').getValue()
  console.log('RATE actual workbook result:',value)
  expect(typeof value).toBe('number');expect(value as number).toBeGreaterThan(0);expect(value as number).toBeLessThan(1)
  const r=value as number,growth=(1+r)**5
  expect(Math.abs(100*growth-100/r*(growth-1)+10)).toBeLessThan(1e-8)
 }finally{fallback.dispose();c.univer.dispose()}
},15000)

it('installs before the first workbook formula calculation',async()=>{
 const c=await setup(true)
 try{
  c.sheet.getRange('A1').setValue({f:'=RATE(5,-100,100,10)'})
  await vi.waitFor(()=>expect(typeof c.sheet.getRange('A1').getValue()).toBe('number'))
 }finally{c.earlyFallback?.dispose();c.univer.dispose()}
},15000)
it('is a no-op when a headless host has no formula provider',()=>{
 expect(()=>installRateFallback({univer:{}} as never).dispose()).not.toThrow()
})

it('preserves builtin ordinary/error/array argument behavior through real workbook formulas',async()=>{
 const c=await setup()
 const formulas=['=RATE(10,-100,1000)','=RATE(5,10,-100,0.0001)','=RATE(5,0,-100,0.0001)','=RATE(12,-100,1000,0,1,0.01)','=RATE(3,-10,-100,9)','=RATE(0,-10,100)','=RATE(5,10,100,10)','=RATE("bad",-10,100)','=RATE(5,1/0,100)','=RATE({5,10},0,-100,0.0001)']
 let fallback:ReturnType<typeof installRateFallback>|undefined
 try{
  formulas.forEach((f,row)=>c.sheet.getRange(row,0).setValue({f}))
  await vi.waitFor(()=>formulas.forEach((_,row)=>expect(c.sheet.getRange(row,0).getValue()).not.toBeNull()))
  const baseline=c.sheet.getRange('A1:B10').getValues()
  fallback=installRateFallback(c.runtime)
  formulas.forEach((f,row)=>c.sheet.getRange(row,3).setValue({f}))
  await vi.waitFor(()=>formulas.forEach((_,row)=>expect(c.sheet.getRange(row,3).getValue()).not.toBeNull()))
  expect(c.sheet.getRange('D1:E10').getValues()).toEqual(baseline)
  expect(baseline[0][0]).toBeCloseTo(0,10);expect(baseline[2][0]).toBeCloseTo(-0.93690426555,9)
  expect(baseline.slice(4,9).map(row=>row[0])).toEqual(['#NUM!','#NUM!','#NUM!','#VALUE!','#DIV/0!'])
 }finally{fallback?.dispose();c.univer.dispose()}
},15000)

it('restores the native executor once and never resurrects after disposal before the source timer',async()=>{
 const c=await setup()
 try{
  const original=c.service.getExecutor('RATE'),fallback=installRateFallback(c.runtime)
  expect(c.service.getExecutor('RATE')).not.toBe(original);fallback.dispose();fallback.dispose()
  await new Promise(resolve=>setTimeout(resolve,0));expect(c.service.getExecutor('RATE')).toBe(original)
 }finally{c.univer.dispose()}
})
it('preserves a later executor owner across startup timer and disposal',async()=>{
 const c=await setup()
 try{
  const fallback=installRateFallback(c.runtime),{createRateExecutor}=await import('./workbook-function-rate'),foreign=createRateExecutor()!
  c.service.registerExecutors(foreign);await new Promise(resolve=>setTimeout(resolve,0))
  expect(c.service.getExecutor('RATE')).toBe(foreign);fallback.dispose();expect(c.service.getExecutor('RATE')).toBe(foreign)
 }finally{c.univer.dispose()}
})
it('unregisters only its own executor when the original provider had no RATE',async()=>{
 const c=await setup()
 try{
  c.service.unregisterExecutors('RATE');const fallback=installRateFallback(c.runtime)
  expect(c.service.hasExecutor('RATE')).toBe(true);fallback.dispose();expect(c.service.hasExecutor('RATE')).toBe(false)
 }finally{c.univer.dispose()}
})
it('uses the same override for native preview, cell references, optional guess and array spill',async()=>{
 const c=await setup(),fallback=installRateFallback(c.runtime)
 try{
  c.sheet.getRange('A1:A4').setValues([[5],[-100],[100],[10]])
  const formula='=RATE(A1,A2,A3,A4)'
  const result=await c.api.getFormula().executeFormulas({'rate-book':{data:{0:{2:[formula]}}}},3000)
  const preview=result['rate-book']!.data![0]![2]![0].value
  expect(preview).toBeCloseTo(0.9623255039434997,12)
  c.sheet.getRange('C1').setValue({f:formula})
  c.sheet.getRange('C3').setValue({f:'=RATE(5,-10,-100,10.0000001,0,-2)'})
  c.sheet.getRange('C5').setValue({f:'=RATE({5,10},-100,100,10)'})
  await vi.waitFor(()=>{expect(typeof c.sheet.getRange('C1').getValue()).toBe('number');expect(typeof c.sheet.getRange('C3').getValue()).toBe('number');expect(typeof c.sheet.getRange('D5').getValue()).toBe('number')})
  expect(c.sheet.getRange('C1').getValue()).toBe(preview)
  expect(c.sheet.getRange('C3').getValue() as number).toBeGreaterThan(-1);expect(c.sheet.getRange('C3').getValue() as number).toBeLessThan(-0.99)
  for(const [at,nper] of [[0,5],[1,10]]){
   const rate=c.sheet.getRange(4,2+at).getValue() as number,growth=(1+rate)**nper
   expect(Math.abs(100*growth-100/rate*(growth-1)+10)).toBeLessThan(1e-7)
  }
 }finally{fallback.dispose();c.univer.dispose()}
},15000)
it('retains the fixed-source bisection boundaries and no-root result',async()=>{
 const {solveRateByBisection}=await import('./workbook-function-rate')
 const root=solveRateByBisection(5,-10,-100,10.0000001,0)!
 expect(root).toBeGreaterThan(-1);expect(root).toBeLessThan(-0.99)
 const growth=(1+root)**5
 expect(Math.abs(-100*growth-10/root*(growth-1)+10.0000001)).toBeLessThan(1e-6)
 expect(solveRateByBisection(3,-10,-100,9,0)).toBeNull()
})
