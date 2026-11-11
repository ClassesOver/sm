import {expect,it,vi} from 'vitest'
import {ErrorType} from '@univerjs/engine-formula'
import {createWorkbookErrorChecking} from './workbook-error-checking'
function fixture(){
 let bookCore={},sheetCore={},active={row:0,column:0}
 let cells=[{row:9,column:2,v:'#REF!'},{row:0,column:0,v:'#DIV/0!'},{row:3,column:1,v:'#FIELD!'}]
 const activate=vi.fn((row:number,column:number)=>{active={row,column}}),matrix=vi.fn((fn:any)=>{for(const cell of cells)fn(cell.row,cell.column,cell)})
 const sheet={getSheet:()=>Object.assign(sheetCore,{getCellMatrix:()=>({forValue:matrix})}),getRange:(row:number,column:number,_rows:number,_columns:number)=>({activate:()=>activate(row,column)})}
 const book={getWorkbook:()=>bookCore,getActiveSheet:()=>sheet,getActiveRange:()=>({getRow:()=>active.row,getColumn:()=>active.column})}
 const message=vi.fn(),refreshSelection=vi.fn(),reveal=vi.fn(async(_sheet:any,_row:number,_column:number,current:()=>boolean):Promise<boolean|null>=>current()?true:null)
 const controller=createWorkbookErrorChecking({workbook:()=>book,reveal,message,refreshSelection})
 return{controller,book,sheet,message,refreshSelection,reveal,activate,matrix,replaceBook:()=>{bookCore={}},replaceSheet:()=>{sheetCore={}},setCells:(value:typeof cells)=>{cells=value},select:(row:number,column:number)=>{active={row,column}}}
}
it('scans current sparse matrix in row order and cycles after active with no writes',async()=>{
 const f=fixture();for(let n=0;n<4;n++)await f.controller.check()
 expect(f.activate.mock.calls).toEqual([[3,1],[9,2],[0,0],[3,1]])
 expect(f.matrix).toHaveBeenCalledTimes(4);expect(f.refreshSelection).toHaveBeenCalledTimes(4)
 expect(f.message.mock.lastCall?.[0]).toMatch(/当前工作表.*3.*B4.*#FIELD!/)
 expect(f.reveal.mock.calls[0]?.slice(0,3)).toEqual([f.sheet,3,1]);expect(f.controller.state().pending).toBe(false)
})
it('matches exact Univer errors plus modern source literals without parsing formula text',async()=>{
 const f=fixture(),values=[...Object.values(ErrorType),'#FIELD!','#CONNECT!','#BLOCKED!','#UNKNOWN!'];f.setCells(values.map((v,row)=>({row,column:0,v})))
 await f.controller.check();expect(f.message.mock.lastCall?.[0]).toContain(`${values.length} 个错误`)
 f.setCells(['#REF!suffix','prefix#REF!','=1/0','#ref!',''].map((v,row)=>({row,column:0,v})));f.activate.mockClear();await f.controller.check()
 expect(f.activate).not.toHaveBeenCalled();expect(f.message.mock.lastCall?.[0]).toContain('未发现错误')
})
it('rescans repaired results, uses distant sparse entries and is safe for readonly facades',async()=>{
 const f=fixture();Object.freeze(f.sheet);Object.freeze(f.book)
 f.setCells([{row:100000,column:12000,v:'#CYCLE!'}]);await f.controller.check();expect(f.activate).toHaveBeenCalledWith(100000,12000)
 f.setCells([]);await f.controller.check();expect(f.message.mock.lastCall?.[0]).toContain('未发现错误')
})
it('deduplicates pending checks and drops stale workbook/sheet, reset and disposed continuations',async()=>{
 for(const invalidate of ['replaceBook','replaceSheet','reset','dispose'] as const){
  const f=fixture();let finish!:(value:boolean)=>void;let current!:()=>boolean
  f.reveal.mockImplementationOnce(async(_s,_r,_c,check)=>{current=check;return new Promise<boolean>(resolve=>{finish=resolve})})
  const pending=f.controller.check();expect(f.controller.state().pending).toBe(true);await f.controller.check();expect(f.activate).toHaveBeenCalledTimes(1)
  if(invalidate==='reset'||invalidate==='dispose')f.controller[invalidate]();else f[invalidate]()
  expect(current()).toBe(false);finish(true);await pending;expect(f.message).not.toHaveBeenCalled();expect(f.controller.state().pending).toBe(false)
  if(invalidate==='dispose'){await f.controller.check();expect(f.activate).toHaveBeenCalledTimes(1)}
 }
})
it('reports scan/reveal failures rather than no-errors and recovers without unhandled rejection',async()=>{
 const f=fixture();f.matrix.mockImplementationOnce(()=>{throw Error('matrix unavailable')});await f.controller.check();expect(f.message.mock.lastCall?.[0]).toMatch(/检查失败.*matrix unavailable/)
 f.reveal.mockRejectedValueOnce(Error('viewport unavailable'));await f.controller.check();expect(f.message.mock.lastCall?.[0]).toMatch(/检查失败.*viewport unavailable/)
 f.reveal.mockResolvedValueOnce(false);await f.controller.check();expect(f.message.mock.lastCall?.[0]).toMatch(/错误.*未能.*可见/)
 await f.controller.check();expect(f.controller.state().pending).toBe(false)
})
it('handles unavailable workbooks without navigation or error-free claims',async()=>{
 const message=vi.fn(),reveal=vi.fn();const controller=createWorkbookErrorChecking({workbook:()=>null,reveal,message});await controller.check();expect(reveal).not.toHaveBeenCalled();expect(message.mock.lastCall?.[0]).toContain('尚未就绪')
})

it('abandons reveal and feedback after a user changes the target selection on the same sheet',async()=>{
 const f=fixture();let finish!:(value:boolean)=>void,current!:()=>boolean
 f.reveal.mockImplementationOnce(async(_s,_r,_c,check)=>{current=check;return new Promise<boolean>(resolve=>{finish=resolve})})
 const pending=f.controller.check();expect(f.activate).toHaveBeenCalledWith(3,1);expect(current()).toBe(true)
 f.select(20,4);expect(current()).toBe(false);finish(true);await pending
 expect(f.message).not.toHaveBeenCalled();expect(f.controller.state().pending).toBe(false)
})
