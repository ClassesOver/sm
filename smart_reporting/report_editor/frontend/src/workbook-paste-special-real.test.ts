import {expect,it,vi} from 'vitest'
import {Univer,LocaleType,IUniverInstanceService} from '@univerjs/core'
import {FUniver} from '@univerjs/core/lib/facade'
import {UniverSheetsPlugin} from '@univerjs/sheets'
import {UniverFormulaEnginePlugin} from '@univerjs/engine-formula'
import {UniverSheetsFormulaPlugin} from '@univerjs/sheets-formula'
import '@univerjs/sheets/facade'
import '@univerjs/sheets-formula/facade'
import {applyPasteSpecial,type PasteSpecialOptions} from './workbook-vendor/grid/paste-special'
import {readBack} from './workbook-vendor/grid/sync'
import {createBlankWorkbook,readWorkbook} from '@sheets-web/xlsx-engine'
import {applyWorkbookOperations} from '../../../reporting/workbook_engine/bridge/operations'
import {diffToEdits} from './workbook-vendor/core/session-core'
const defaults:PasteSpecialOptions={type:'values',operation:'none',skipBlanks:false,transpose:false,link:false}
function fixture(){
 const univer=new Univer({locale:LocaleType.EN_US,locales:{[LocaleType.EN_US]:{}}});univer.registerPlugin(UniverSheetsPlugin);univer.registerPlugin(UniverFormulaEnginePlugin);univer.registerPlugin(UniverSheetsFormulaPlugin)
 const api=FUniver.newAPI(univer),book=api.createWorkbook({id:'paste-real',name:'Paste',sheetOrder:['s'],sheets:{s:{id:'s',name:'Sheet1',rowCount:30,columnCount:15,cellData:{0:{0:{v:2},1:{v:3},2:{f:'=A1+B1',si:'group',v:5}},1:{0:{v:4},1:{v:6},2:{si:'group',v:10}},3:{0:{v:10},1:{v:20}},4:{0:{v:30},1:{v:40}}}}}})
 univer.__getInjector().get(IUniverInstanceService).focusUnit(book.getId());const runtime={univer,univerAPI:api},sheet=book.getActiveSheet()!
 return {univer,api,book,sheet,runtime,source:(rows:number[],cols:number[])=>({kind:'internal' as const,unitId:book.getId(),subUnitId:'s',rows,cols,cut:false})}
}
it('real internal paste materializes shared formulas, shifts references, writes through ordinary history and persists existing diff operations',async()=>{
 const f=fixture();try{
  f.sheet.getRange('F1').activate();expect(await applyPasteSpecial(f.runtime,f.source([1],[2]),{...defaults,type:'formulas',skipBlanks:true})).toEqual({ok:true})
  expect(f.sheet.getRange('F1').getFormula()).toBe('=D1+E1');await f.api.undo();expect(f.sheet.getRange('F1').getFormula()).toBe('');await f.api.redo();expect(f.sheet.getRange('F1').getFormula()).toBe('=D1+E1')
  const source=await createBlankWorkbook(),baseline=await readWorkbook(source),edits=diffToEdits(baseline,readBack(f.runtime));expect(edits.find(e=>e.row===0&&e.column===5)?.cell.formula).toBe('=D1+E1')
  const output=await applyWorkbookOperations(source,[{kind:'applyCellEdits',edits}]),reopened=await readWorkbook(output);expect(reopened.sheets[0]!.cells.F1!.formula).toBe('=D1+E1')
 }finally{f.univer.dispose()}
},15000)
it('real numeric operations and transposed cached values keep formula semantics and one-step grid UndoRedo',async()=>{
 const f=fixture();try{
  f.sheet.getRange('A4:B5').activate();expect(await applyPasteSpecial(f.runtime,f.source([0,1],[0,1]),{...defaults,operation:'add'})).toEqual({ok:true});expect(f.sheet.getRange('A4:B5').getValues()).toEqual([[12,23],[34,46]])
  await f.api.undo();expect(f.sheet.getRange('A4:B5').getValues()).toEqual([[10,20],[30,40]]);await f.api.redo();expect(f.sheet.getRange('A4:B5').getValues()).toEqual([[12,23],[34,46]])
  f.sheet.getRange('H1').activate();expect(await applyPasteSpecial(f.runtime,f.source([0,1],[0,1]),{...defaults,transpose:true})).toEqual({ok:true});expect(f.sheet.getRange('H1:I2').getValues()).toEqual([[2,4],[3,6]])
  f.sheet.getRange('K1').activate();expect(await applyPasteSpecial(f.runtime,f.source([0],[0]),{...defaults,link:true})).toEqual({ok:true});expect(f.sheet.getRange('K1').getFormula()).toBe('=A1')
 }finally{f.univer.dispose()}
},15000)
it('real paste grows the sheet only as needed and applies to the captured range',async()=>{
 const f=fixture();try{
  f.sheet.getRange('O30').activate();const selected=JSON.stringify(f.book.getActiveRange()!.getRange()),guard=()=>JSON.stringify(f.book.getActiveRange()!.getRange())===selected
  expect(await applyPasteSpecial(f.runtime,f.source([0,1],[0,1]),{...defaults,transpose:true},guard)).toEqual({ok:true})
  expect(f.sheet.getRange('O30:P31').getValues()).toEqual([[2,4],[3,6]])
 }finally{f.univer.dispose()}
},15000)
it('does not expand or write when a target moves during an async insert preflight',async()=>{
 const f=fixture();try{
  f.sheet.getRange('O30').activate();const selected=JSON.stringify(f.book.getActiveRange()!.getRange()),guard=()=>JSON.stringify(f.book.getActiveRange()?.getRange())===selected
  const execute=f.api.executeCommand.bind(f.api);vi.spyOn(f.api,'executeCommand').mockImplementation(async(id,params)=>{if(id==='sheet.command.insert-row')f.sheet.getRange('B10').activate();return execute(id,params)})
  await expect(applyPasteSpecial(f.runtime,f.source([0,1],[0,1]),{...defaults,transpose:true},guard)).rejects.toThrow('目标区域')
  expect(f.sheet.getSheet().getRowCount()).toBe(30);expect(f.sheet.getSheet().getColumnCount()).toBe(15);expect(f.sheet.getRange('O30').getValue()).toBeNull();expect(f.book.getActiveRange()?.getA1Notation()).toContain('B10')
 }finally{f.univer.dispose()}
},15000)
