import { expect, it, vi } from 'vitest'
import { Univer, LocaleType, IUniverInstanceService, CellValueType } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-formula/facade'
import { installCriteriaCompareCacheFix } from './workbook-function-criteria'

async function setup(id='criteria-book'){
 const univer=new Univer({locale:LocaleType.EN_US,locales:{[LocaleType.EN_US]:{}}})
 univer.registerPlugin(UniverSheetsPlugin);univer.registerPlugin(UniverFormulaEnginePlugin);univer.registerPlugin(UniverSheetsFormulaPlugin)
 const api=FUniver.newAPI(univer),book=api.createWorkbook({id,name:'Criteria',sheetOrder:['data'],sheets:{data:{id:'data',name:'Data',rowCount:20,columnCount:15}}})
 univer.__getInjector().get(IUniverInstanceService).focusUnit(book.getId())
 return {univer,api,sheet:book.getActiveSheet()!}
}
it('keeps repeated SUMIFS on imported text month columns correct within one native calculation pass',async()=>{
 const c=await setup(),fix=installCriteriaCompareCacheFix()
 try{
  c.sheet.getRange('A1:B5').setValues(['2026-06','2026-05','2026-06','2026-06','2026-05'].map((v,i)=>[{v,t:CellValueType.STRING},{v:(i+1)*10}]))
  const formula='=SUMIFS(B1:B5,A1:A5,"2026-06")'
  c.sheet.getRange('D1:D3').setValues([[{f:formula}],[{f:formula+'+0'}],[{f:formula+'*1'}]])
  await vi.waitFor(()=>expect(c.sheet.getRange('D1:D3').getValues().flat().every(v=>typeof v==='number')).toBe(true))
  expect(c.sheet.getRange('D1:D3').getValues()).toEqual([[80],[80],[80]])
 }finally{fix.dispose();c.univer.dispose()}
},15000)
it('keeps SUMIF/COUNTIF/COUNTIFS/AVERAGEIFS/MINIFS/MAXIFS and ordinary cache paths correct',async()=>{
 const c=await setup('criteria-family'),fix=installCriteriaCompareCacheFix()
 try{
  c.sheet.getRange('A1:B5').setValues(['2026-06','2026-05','2026-06','2026-06','2026-05'].map((v,i)=>[{v,t:CellValueType.STRING},{v:(i+1)*10}]))
  const functions=['SUMIF(A1:A5,"2026-06",B1:B5)','COUNTIF(A1:A5,"2026-06")','COUNTIFS(A1:A5,"2026-06")','AVERAGEIFS(B1:B5,A1:A5,"2026-06")','MINIFS(B1:B5,A1:A5,"2026-06")','MAXIFS(B1:B5,A1:A5,"2026-06")','COUNTIF(B1:B5,">=30")','COUNTIF(A1:A5,"2026-0*")']
  c.sheet.getRange('D1:K3').setValues([0,1,2].map(i=>functions.map(f=>({f:`=${f}+${i}*0`}))));const expected=[80,3,3,80/3,10,40,3,5]
  await vi.waitFor(()=>expect(c.sheet.getRange('D1:K3').getValues().flat().every(v=>typeof v==='number')).toBe(true))
  for(const row of c.sheet.getRange('D1:K3').getValues())row.forEach((value,i)=>expect(value).toBeCloseTo(expected[i],10))
 }finally{fix.dispose();c.univer.dispose()}
},15000)

it('shares one patch across runtimes and keeps the remaining runtime correct after either owner releases',async()=>{
 const {ArrayValueObject}=await import('@univerjs/engine-formula'),proto=ArrayValueObject.prototype as any,original=proto._batchOperatorValue
 const first=installCriteriaCompareCacheFix(),patched=proto._batchOperatorValue,second=installCriteriaCompareCacheFix(),c=await setup('criteria-second-runtime')
 try{
  expect(proto._batchOperatorValue).toBe(patched);first.dispose();first.dispose();expect(proto._batchOperatorValue).toBe(patched)
  c.sheet.getRange('A1:B3').setValues([[{v:'123',t:CellValueType.STRING},{v:10}],[{v:'other',t:CellValueType.STRING},{v:20}],[{v:'123',t:CellValueType.STRING},{v:30}]])
  c.sheet.getRange('D1:D3').setValues([0,1,2].map(i=>[{f:`=SUMIFS(B1:B3,A1:A3,123)+${i}*0`}]))
  await vi.waitFor(()=>expect(c.sheet.getRange('D1:D3').getValues()).toEqual([[40],[40],[40]]))
  second.dispose();expect(proto._batchOperatorValue).toBe(original)
  const next=installCriteriaCompareCacheFix();expect(proto._batchOperatorValue).not.toBe(original);next.dispose();expect(proto._batchOperatorValue).toBe(original)
 }finally{first.dispose();second.dispose();c.univer.dispose()}
},15000)
it('never overwrites a later prototype owner and releases the shared lease idempotently',async()=>{
 const {ArrayValueObject}=await import('@univerjs/engine-formula'),proto=ArrayValueObject.prototype as any,original=proto._batchOperatorValue
 const first=installCriteriaCompareCacheFix(),patched=proto._batchOperatorValue,foreign=vi.fn(function(this:any,...args:any[]){return patched.apply(this,args)})
 try{
  proto._batchOperatorValue=foreign;const second=installCriteriaCompareCacheFix();expect(proto._batchOperatorValue).toBe(foreign)
  first.dispose();second.dispose();second.dispose();expect(proto._batchOperatorValue).toBe(foreign)
 }finally{first.dispose();proto._batchOperatorValue=original}
})
it('degrades to stock behavior if the private method no longer exists',async()=>{
 const {ArrayValueObject}=await import('@univerjs/engine-formula'),proto=ArrayValueObject.prototype as any,original=proto._batchOperatorValue
 try{proto._batchOperatorValue=undefined;const fix=installCriteriaCompareCacheFix();fix.dispose();expect(proto._batchOperatorValue).toBeUndefined()}finally{proto._batchOperatorValue=original}
})
it('restores the temporary cache method even if the native comparison throws',async()=>{
 const {ArrayValueObject,NumberValueObject,StringValueObject,CELL_INVERTED_INDEX_CACHE}=await import('@univerjs/engine-formula'),proto=ArrayValueObject.prototype as any,original=proto._batchOperatorValue
 const column=()=>ArrayValueObject.create({calculateValueList:[[StringValueObject.create('123')]],rowCount:1,columnCount:1,unitId:'criteria-throw',sheetId:'data',row:0,column:0} as any)
 column().compare(NumberValueObject.create(123),'=' as never)
 const canUseCache=CELL_INVERTED_INDEX_CACHE.canUseCache,nativeThrow=()=>{throw new Error('native compare fault')}
 proto._batchOperatorValue=nativeThrow;const fix=installCriteriaCompareCacheFix()
 try{expect(()=>column().compare(NumberValueObject.create(123),'=' as never)).toThrow('native compare fault');expect(CELL_INVERTED_INDEX_CACHE.canUseCache).toBe(canUseCache)}finally{fix.dispose();proto._batchOperatorValue=original}
})
it('preserves native cached compares for numeric and same-type strings and rechecks growing mixed cache keys',async()=>{
 const {ArrayValueObject,NumberValueObject,StringValueObject,ErrorValueObject,ErrorType,CELL_INVERTED_INDEX_CACHE}=await import('@univerjs/engine-formula')
 const fix=installCriteriaCompareCacheFix(),cacheSpy=vi.spyOn(CELL_INVERTED_INDEX_CACHE,'canUseCache')
 const column=(unit:string,values:any[])=>ArrayValueObject.create({calculateValueList:values.map(v=>[v]),rowCount:values.length,columnCount:1,unitId:unit,sheetId:'data',row:0,column:0} as any)
 const read=(range:any,criterion:any)=>{const compared=range.compare(criterion,'=');return [0,1].map(i=>compared.get(i,0)?.getValue()===true)}
 try{
  for(let call=0;call<2;call++)expect(read(column('criteria-numeric',[NumberValueObject.create(10),NumberValueObject.create(20)]),NumberValueObject.create(10))).toEqual([true,false])
  for(let call=0;call<2;call++)expect(read(column('criteria-string',[StringValueObject.create('A'),StringValueObject.create('B')]),StringValueObject.create('B'))).toEqual([false,true])
  expect(cacheSpy).toHaveBeenCalled();expect(CELL_INVERTED_INDEX_CACHE.canUseCache).toBe(cacheSpy)
  column('criteria-growing',[NumberValueObject.create(10),ErrorValueObject.create(ErrorType.NA)]).compare(NumberValueObject.create(10),'=' as never)
  const map=CELL_INVERTED_INDEX_CACHE.getCellValuePositions('criteria-growing','data',0)!
  const priorSize=map.size
  column('criteria-growing',[NumberValueObject.create(10),ErrorValueObject.create(ErrorType.NA)]).compare(NumberValueObject.create(10),'=' as never)
  ;(map as Map<any,any>).set('123',[1]);expect(map.size).toBe(priorSize+1)
  // 新string key必须触发dense路径，读真实数组不被故意加入的缓存位置污染。
  expect(read(column('criteria-growing',[NumberValueObject.create(10),ErrorValueObject.create(ErrorType.NA)]),NumberValueObject.create(123))).toEqual([false,false])
 }finally{cacheSpy.mockRestore();fix.dispose()}
})
