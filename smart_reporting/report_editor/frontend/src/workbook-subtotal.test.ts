import { expect, it, vi } from 'vitest'
import { Univer, LocaleType, IUniverInstanceService, ICommandService, IUndoRedoService } from '@univerjs/core'
import { FUniver } from '@univerjs/core/lib/facade'
import { UniverSheetsPlugin } from '@univerjs/sheets'
import { UniverFormulaEnginePlugin } from '@univerjs/engine-formula'
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-formula/facade'
import { UniverSheetsConditionalFormattingPlugin, AddCfCommand } from '@univerjs/sheets-conditional-formatting'
import '@univerjs/sheets-conditional-formatting/facade'
import { installDataValidationStructure } from './workbook-data-validation-structure'
import { CF_MUTATION_IDS } from './workbook-conditional-formatting'
import { readWorkbookOutline } from './workbook-outline'
const implementation = './workbook-subtotal'
const product = () => import(/* @vite-ignore */ implementation)
const bounds = { startRow: 4, endRow: 8, startColumn: 2, endColumn: 3 }
it('plans C5 final coordinates, adjacent groups and validates all columns and group budget', async () => {
  const { planSubtotal } = await product(), rows = [['Group','Value'],['A',10],['A',20],['B',30],['B',40]]
  const plan = planSubtotal(bounds,rows,{groupCol:2,valueCol:3,agg:'count'})
  expect(plan.inserts).toEqual([9,7,11])
  expect(plan.cells.map((c:any)=>[c.row,c.column,c.formula??c.value])).toEqual([[7,2,'A Total'],[7,3,'=SUBTOTAL(3,$D$6:$D$7)'],[10,2,'B Total'],[10,3,'=SUBTOTAL(3,$D$9:$D$10)'],[11,2,'Grand Total'],[11,3,'=SUBTOTAL(3,$D$6:$D$11)']])
  expect(planSubtotal({...bounds,endRow:7},[['g','v'],['A',1],['B',2],['A',3]],{groupCol:2,valueCol:3,agg:'sum'}).groups).toHaveLength(3)
  for(const input of [{groupCol:2,valueCol:2,agg:'sum'},{groupCol:1,valueCol:3,agg:'sum'},{groupCol:2,valueCol:4,agg:'sum'},{groupCol:2,valueCol:3,agg:'invalid'}])expect(()=>planSubtotal(bounds,rows,input)).toThrow()
  expect(()=>planSubtotal({...bounds,endRow:205},[['g','v'],...Array.from({length:201},(_,i)=>[i,i])],{groupCol:2,valueCol:3,agg:'sum'})).toThrow('200')
})
async function fixture(options:any={}) {
  const univer=new Univer({locale:LocaleType.EN_US,locales:{[LocaleType.EN_US]:{}}})
  univer.registerPlugin(UniverSheetsPlugin);univer.registerPlugin(UniverFormulaEnginePlugin);univer.registerPlugin(UniverSheetsFormulaPlugin);if(options.cf)univer.registerPlugin(UniverSheetsConditionalFormattingPlugin)
  const api=FUniver.newAPI(univer),values=[['Group','Value'],['A',10],['A',20],['B',30],['B',40],['Tail',99]]
  const book=api.createWorkbook({id:'subtotal',name:'Subtotal',sheetOrder:['s'],sheets:{s:{id:'s',name:'Data',rowCount:30,columnCount:10,cellData:Object.fromEntries(values.map((r,i)=>[i+4,Object.fromEntries(r.map((v,c)=>[c+2,{v}]))]))}}})
  univer.__getInjector().get(IUniverInstanceService).focusUnit(book.getId())
  const sheet=book.getActiveSheet()!;sheet.getRange('C5:D9').activate()
  let metadata:any={journal:[]}
  const control=(await product()).installSubtotal({univer,univerAPI:api},{captureMetadata:()=>structuredClone(metadata),restoreMetadata:(value:any)=>{metadata=structuredClone(value)},preflight:()=>{},...options})
  return {univer,api,book,sheet,control,values,metadata:()=>metadata}
}
it.each(['sum','count','average'])('real SUBTOTAL and bold use one undo/redo (%s)',async agg=>{
  const f=await fixture()
  try {
    await f.control.apply(f.control.capture(),{groupCol:2,valueCol:3,agg})
    expect(f.sheet.getRange('C8').getValue()).toBe('A Total')
    expect(f.sheet.getRange('D8').getFormula()).toBe(`=SUBTOTAL(${agg==='sum'?9:agg==='count'?3:1},$D$6:$D$7)`)
    await vi.waitFor(()=>expect(f.sheet.getRange('D12').getValue()).toBe(agg==='sum'?100:agg==='count'?4:25))
    expect(f.book.getWorkbook().getStyles().getStyleByCell(f.sheet.getSheet().getCell(7,3))?.bl).toBe(1)
    expect(f.sheet.getRange('C13:D13').getValues()).toEqual([['Tail',99]])
    expect([...readWorkbookOutline(f.sheet).rows].map(([r,e])=>[r,e.level])).toEqual([[5,2],[6,2],[7,1],[8,2],[9,2],[10,1]])
    await f.api.undo();expect(f.sheet.getRange('C5:D10').getValues()).toEqual(f.values);expect(readWorkbookOutline(f.sheet).rows.size).toBe(0)
    await f.api.redo();expect(f.sheet.getRange('C12').getValue()).toBe('Grand Total');expect(readWorkbookOutline(f.sheet).rows.size).toBe(6)
  }finally{f.control.dispose();f.univer.dispose()}
})
it.each(['false','throw'])('every top level stage rolls back and preserves previous undo/redo (%s)',async fault=>{
  for(let stage=1;stage<=4;stage++) {
    const f=await fixture(),service=f.univer.__getInjector().get(ICommandService),history=f.univer.__getInjector().get(IUndoRedoService)
    try {
      f.sheet.getRange('A1').setValue('existing');f.sheet.getRange('A2').setValue('redo');await f.api.undo();f.sheet.getRange('C5:D9').activate()
      const undo=history.pitchTopUndoElement(),redo=history.pitchTopRedoElement(),captured=f.control.capture(),execute=service.syncExecuteCommand.bind(service)
      let n=0
      const spy=vi.spyOn(service,'syncExecuteCommand').mockImplementation(((id:string,p:any,o:any)=>{
        if((id==='sheet.command.insert-row-by-range'||id==='sheet.command.set-range-values')&&++n===stage){if(fault==='throw')throw new Error('injected');return false}
        return execute(id,p,o)
      }) as typeof service.syncExecuteCommand)
      await expect(f.control.apply(captured,{groupCol:2,valueCol:3,agg:'sum'})).rejects.toThrow();spy.mockRestore()
      expect(f.sheet.getRange('C5:D10').getValues()).toEqual(f.values);expect(readWorkbookOutline(f.sheet).rows.size).toBe(0)
      expect(history.pitchTopUndoElement()).toBe(undo);expect(history.pitchTopRedoElement()).toBe(redo)
    }finally{f.control.dispose();f.univer.dispose()}
  }
})

it.each(['sheet.mutation.insert-row','sheet.mutation.set-range-values'])('rolls back a mutation which throws after execution before native history push (%s)',async id=>{
  const f=await fixture(),commands=f.univer.__getInjector().get(ICommandService)
  let once=true
  const hook=commands.onCommandExecuted((command:any)=>{if(command.id===id&&once){once=false;throw new Error('post-mutation failure')}})
  try {
    await expect(f.control.apply(f.control.capture(),{groupCol:2,valueCol:3,agg:'sum'})).rejects.toThrow()
    expect(f.sheet.getRange('C5:D10').getValues()).toEqual(f.values)
    expect(f.sheet.getMaxRows()).toBe(30)
    expect(f.univer.__getInjector().get(IUndoRedoService).pitchTopUndoElement()).toBeNull()
  }finally{hook.dispose();f.control.dispose();f.univer.dispose()}
})
it('rejects protection and stale selection and awaits all preflight before mutation',async()=>{
  const f=await fixture({protectedSheet:()=>true})
  try{expect(()=>f.control.capture()).toThrow('受保护')}finally{f.control.dispose();f.univer.dispose()}
  let release:any
  const g=await fixture({preflight:()=>new Promise<void>(resolve=>{release=resolve})})
  try{
    const applying=g.control.apply(g.control.capture(),{groupCol:2,valueCol:3,agg:'sum'})
    expect(g.sheet.getMaxRows()).toBe(30);g.sheet.getRange('A1').setValue('concurrent');release()
    await expect(applying).rejects.toThrow('变化');expect(g.sheet.getRange('A1').getValue()).toBe('concurrent');expect(g.sheet.getRange('C5:D10').getValues()).toEqual(g.values)
  }finally{g.control.dispose();g.univer.dispose()}
})
it('COUNTA counts text and boolean but ignores empty cells, keeping A/B/A groups',async()=>{
  const f=await fixture()
  try{
    f.sheet.getRange('D6').setValue('text');f.sheet.getRange('D7').setValue({v:null});f.sheet.getRange('D8').setValue(true)
    f.sheet.getRange('C9').setValue('A');f.sheet.getRange('C5:D9').activate()
    const plan=await f.control.apply(f.control.capture(),{groupCol:2,valueCol:3,agg:'count'})
    expect(plan.groups.map((g:any)=>g.label)).toEqual(['A','B','A'])
    await vi.waitFor(()=>expect(f.sheet.getRange(plan.grandTotalRow,3).getValue()).toBe(3))
  }finally{f.control.dispose();f.univer.dispose()}
})
it('restores native cells, outline and journal if final history push rejects',async()=>{
  const f=await fixture(),history=f.univer.__getInjector().get(IUndoRedoService),descriptor=Object.getOwnPropertyDescriptor(history,'pushUndoRedo')
  Object.defineProperty(history,'pushUndoRedo',{configurable:true,value:()=>{throw new Error('history failure')}})
  try{
    await expect(f.control.apply(f.control.capture(),{groupCol:2,valueCol:3,agg:'sum'})).rejects.toThrow('history failure')
    expect(f.sheet.getRange('C5:D10').getValues()).toEqual(f.values)
    expect(readWorkbookOutline(f.sheet).rows.size).toBe(0)
  }finally{if(descriptor)Object.defineProperty(history,'pushUndoRedo',descriptor);else Reflect.deleteProperty(history,'pushUndoRedo');f.control.dispose();f.univer.dispose()}
})
it('restores journal and existing external outline when metadata finalization throws',async()=>{
  let captures=0,metadata:any={journal:['existing']}
  const f=await fixture({captureMetadata:()=>{if(++captures===2)throw new Error('metadata failure');return structuredClone(metadata)},restoreMetadata:(value:any)=>{metadata=structuredClone(value)}})
  try{
    const manager=f.sheet.getSheet().getRowManager();manager.getRowOrCreate(1);manager.setCustomMetadata(1,{other:'keep',genofficeOutline:{level:1,collapsed:true}})
    const core=f.sheet.getSheet();core.setCustomMetadata({unrelated:'keep',genofficeOutline:{summaryBelow:false,summaryRight:false}})
    await expect(f.control.apply(f.control.capture(),{groupCol:2,valueCol:3,agg:'sum'})).rejects.toThrow('metadata failure')
    expect(f.sheet.getRange('C5:D10').getValues()).toEqual(f.values)
    expect([...readWorkbookOutline(f.sheet).rows]).toEqual([[1,{level:1,collapsed:true}]])
    expect(core.getCustomMetadata()).toEqual({unrelated:'keep',genofficeOutline:{summaryBelow:false,summaryRight:false}})
    expect(metadata).toEqual({journal:['existing']})
  }finally{f.control.dispose();f.univer.dispose()}
})
it('rejects a replacement core even if workbook and sheet ids are reused',async()=>{
  const f=await fixture()
  try{
    const target=f.control.capture();f.api.disposeUnit('subtotal')
    f.api.createWorkbook({id:'subtotal',name:'Replacement',sheetOrder:['s'],sheets:{s:{id:'s',name:'Data',rowCount:30,columnCount:10,cellData:{0:{0:{v:'replacement'}}}}}})
    f.univer.__getInjector().get(IUniverInstanceService).focusUnit('subtotal')
    await expect(f.control.apply(target,{groupCol:2,valueCol:3,agg:'sum'})).rejects.toThrow('变化')
    expect(f.api.getActiveWorkbook()!.getActiveSheet()!.getRange('A1').getValue()).toBe('replacement')
  }finally{f.control.dispose();f.univer.dispose()}
})
it('restores existing redo and exact undo stack if native history push has already succeeded before throwing',async()=>{
  const f=await fixture(),history=f.univer.__getInjector().get(IUndoRedoService)
  f.sheet.getRange('A1').setValue('undo');f.sheet.getRange('A2').setValue('redo');await f.api.undo();f.sheet.getRange('C5:D9').activate()
  const undo=history.pitchTopUndoElement(),redo=history.pitchTopRedoElement(),descriptor=Object.getOwnPropertyDescriptor(history,'pushUndoRedo'),push=history.pushUndoRedo
  Object.defineProperty(history,'pushUndoRedo',{configurable:true,value:(item:any)=>{push(item);throw new Error('after push')}})
  try{
    await expect(f.control.apply(f.control.capture(),{groupCol:2,valueCol:3,agg:'sum'})).rejects.toThrow('after push')
    expect(f.sheet.getRange('C5:D10').getValues()).toEqual(f.values)
    expect(history.pitchTopUndoElement()).toBe(undo);expect(history.pitchTopRedoElement()).toBe(redo)
    await f.api.redo();expect(f.sheet.getRange('A2').getValue()).toBe('redo')
  }finally{if(descriptor)Object.defineProperty(history,'pushUndoRedo',descriptor);else Reflect.deleteProperty(history,'pushUndoRedo');f.control.dispose();f.univer.dispose()}
})

it('rolls back real CF followers using their original owned params identities',async()=>{
  const f=await fixture({cf:true}),commands=f.univer.__getInjector().get(ICommandService)
  commands.syncExecuteCommand(AddCfCommand.id,{unitId:'subtotal',subUnitId:'s',rule:{ranges:[{startRow:5,endRow:8,startColumn:3,endColumn:3}],stopIfTrue:false,rule:{type:'highlightCell',subType:'number',operator:'greaterThan',value:5,style:{bl:1}}}})
  const original=structuredClone(f.sheet.getConditionalFormattingRules())
  const structure=installDataValidationStructure({univer:f.univer,univerAPI:f.api})
  let calls=0,rejections=0
  const guard=commands.beforeCommandExecuted((command:any)=>{if(CF_MUTATION_IDS.has(command.id)&&!structure.ownsMutation(command.params)){rejections++;throw new Error('unowned CF')}})
  const execute=commands.syncExecuteCommand.bind(commands)
  const spy=vi.spyOn(commands,'syncExecuteCommand').mockImplementation(((id:string,p:any,o:any)=>{
    if(id==='sheet.command.insert-row-by-range'&&++calls===3)return false
    return execute(id,p,o)
  }) as typeof commands.syncExecuteCommand)
  try{
    await expect(f.control.apply(f.control.capture(),{groupCol:2,valueCol:3,agg:'sum'})).rejects.toThrow()
    expect(f.sheet.getConditionalFormattingRules()).toEqual(original)
    expect(f.sheet.getRange('C5:D10').getValues()).toEqual(f.values)
    expect(rejections).toBe(0)
  }finally{spy.mockRestore();guard.dispose();structure.dispose();f.control.dispose();f.univer.dispose()}
})
it.each([false,true])('preserves foreign native unit history during subtotal (rollback=%s)',async rollback=>{
  const f=await fixture(),history=f.univer.__getInjector().get(IUndoRedoService),commands=f.univer.__getInjector().get(ICommandService)
  const foreign=f.api.createWorkbook({id:'subtotal-doc-editor-unit',name:'Foreign',sheetOrder:['foreign'],sheets:{foreign:{id:'foreign',name:'Other',rowCount:10,columnCount:10}}})
  const foreignSheet=foreign.getActiveSheet()!
  f.univer.__getInjector().get(IUniverInstanceService).focusUnit('subtotal');f.sheet.getRange('C5:D9').activate()
  let fired=false
  const hook=commands.onCommandExecuted((command:any)=>{
    if(command.id==='sheet.mutation.insert-row'&&!fired){fired=true;foreignSheet.getRange('A1').setValue('foreign-history')}
  })
  const execute=commands.syncExecuteCommand.bind(commands);let inserts=0
  const spy=vi.spyOn(commands,'syncExecuteCommand').mockImplementation(((id:string,p:any,o:any)=>{
    if(rollback&&id==='sheet.command.insert-row-by-range'&&++inserts===2)return false
    return execute(id,p,o)
  }) as typeof commands.syncExecuteCommand)
  try{
    const applying=f.control.apply(f.control.capture(),{groupCol:2,valueCol:3,agg:'sum'})
    if(rollback)await expect(applying).rejects.toThrow();else await applying
    expect(foreignSheet.getRange('A1').getValue()).toBe('foreign-history')
    f.univer.__getInjector().get(IUniverInstanceService).focusUnit('subtotal-doc-editor-unit')
    expect(history.pitchTopUndoElement()?.unitID).toBe('subtotal-doc-editor-unit')
    await f.api.undo();expect(foreignSheet.getRange('A1').getValue()).toBeNull()
    await f.api.redo();expect(foreignSheet.getRange('A1').getValue()).toBe('foreign-history')
    if(rollback)expect(f.sheet.getRange('C5:D10').getValues()).toEqual(f.values)
    else expect(f.sheet.getRange('C12').getValue()).toBe('Grand Total')
  }finally{spy.mockRestore();hook.dispose();f.control.dispose();f.univer.dispose()}
})
