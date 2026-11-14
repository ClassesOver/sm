import {describe,expect,it,vi} from 'vitest'
import {CellValueType} from '@univerjs/core'
import {applyOperation,buildPasteGrid,readPasteSpecialSource,applyPasteSpecial,pasteSpecialAvailability,transformCell,type PasteSpecialOptions} from './workbook-vendor/grid/paste-special'
const options:PasteSpecialOptions={type:'values',operation:'none',skipBlanks:false,transpose:false,link:false}
it('preserves source availability for internal copies, cuts, outside text and no source',()=>{
 const internal={kind:'internal' as const,unitId:'u',subUnitId:'s',rows:[0],cols:[0],cut:false}
 expect([...pasteSpecialAvailability(internal).types]).toHaveLength(10)
 expect(pasteSpecialAvailability(internal).types.has('comments')).toBe(false)
 expect(pasteSpecialAvailability({...internal,cut:true})).toMatchObject({operation:false,skipBlanks:false,transpose:false,link:false})
 expect([...pasteSpecialAvailability({kind:'text',rows:[['a']]}).types]).toEqual(['all','values'])
 expect(pasteSpecialAvailability({kind:'none'}).types.size).toBe(0)
})
it('uses numeric caches for operations, preserves target text and reports divide by zero as a cell value',()=>{
 expect(applyOperation({v:10},{v:3,f:'=1+2'},'subtract')).toMatchObject({v:7,f:null,si:null})
 expect(applyOperation({v:'text',t:CellValueType.STRING},{v:3},'add')).toBeNull()
 expect(applyOperation({v:10},{v:0},'divide')).toMatchObject({v:'#DIV/0!'})
})
it('transposes formulas as cached values, skips blanks and tiles while preserving number format only',()=>{
 const source=[[{cell:{v:3,f:'=A1',s:{n:{pattern:'0.00'},bl:1}},row:0,column:0},{cell:null,row:0,column:1}]]
 const result=buildPasteGrid(source,{...options,type:'values-numfmt',transpose:true,skipBlanks:true},{startRow:3,startColumn:2,rows:2,columns:1,cellAt:()=>({v:99})},()=>{throw Error('must not relocate transposed formula')},null)
 expect(result.cells[0]![0]).toMatchObject({v:3,f:null,s:{n:{pattern:'0.00'}}});expect(result.cells[0]![0]!.s).not.toHaveProperty('bl');expect(result.cells[1]![0]).toBeNull()
})
it('relocates materialized formulas and generates quoted same-workbook paste links',()=>{
 expect(transformCell({source:{f:'=A1',v:5},target:null,rowDelta:2,columnDelta:1},{...options,type:'formulas'},(formula,row,col)=>`${formula}:${row}:${col}`)).toMatchObject({f:'=A1:2:1',v:null})
 const linked=buildPasteGrid([[{cell:{v:4},row:2,column:1}]],{...options,link:true},{startRow:0,startColumn:0,rows:1,columns:1,cellAt:()=>null},f=>f,"Q1 'data")
 expect(linked.cells[0]![0]).toMatchObject({f:"='Q1 ''data'!B3"})
})
it('falls back to the last internal copy on clipboard denial without requesting permission',async()=>{
 const cache={getLastCopyId:()=> 'copy',get:()=>({unitId:'u',subUnitId:'s',range:{rows:[1],cols:[2]},copyType:0})}
 const runtime={univer:{__getInjector:()=>({get:()=>({_copyContentCache:cache})})}} as any
 const descriptor=Object.getOwnPropertyDescriptor(navigator,'clipboard');Object.defineProperty(navigator,'clipboard',{configurable:true,value:{read:vi.fn(async()=>{throw new DOMException('denied','NotAllowedError')})}})
 try{expect(await readPasteSpecialSource(runtime)).toMatchObject({kind:'internal',rows:[1],cols:[2]})}finally{if(descriptor)Object.defineProperty(navigator,'clipboard',descriptor);else Reflect.deleteProperty(navigator,'clipboard')}
})
it('does not report success when the official delegated clipboard command returns false',async()=>{
 const executeCommand=vi.fn(async()=>false),runtime={univerAPI:{executeCommand}} as any
 const result=await applyPasteSpecial(runtime,{kind:'text',rows:[['a']]},options)
 expect(result).toEqual({ok:false,reason:'not-applied'});expect(executeCommand).toHaveBeenCalledWith('sheet.command.paste-value',undefined)
})

it('checks the active-target guard before a delegated command and refuses unavailable source switches',async()=>{
 const executeCommand=vi.fn(async()=>true),runtime={univerAPI:{executeCommand}} as any
 await expect(applyPasteSpecial(runtime,{kind:'text',rows:[['7']]},options,()=>false)).rejects.toThrow('目标区域')
 await expect(applyPasteSpecial(runtime,{kind:'text',rows:[['7']]},{...options,operation:'add'})).rejects.toThrow('不支持')
 expect(executeCommand).not.toHaveBeenCalled()
})
