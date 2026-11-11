import {expect,it,vi} from 'vitest'
import {captureWorkbookReadContext} from './workbook-ai-read-context'

function fixture() {
  let epoch=0,editing=false,sheetName='经营',row=2
  const operations=[{kind:'applyCellEdits',edits:[{sheetName:'经营',address:'B3',value:'当前草稿73'}]}]
  const setOperations=vi.fn()
  const runtime={univerAPI:{getActiveWorkbook:()=>({isCellEditing:()=>editing,getActiveSheet:()=>({getSheetName:()=>sheetName,getSelection:()=>({getActiveRange:()=>({getRow:()=>row,getColumn:()=>1,getHeight:()=>2,getWidth:()=>3})})})})}}
  const options={runtime:runtime as never,closed:()=>false,epoch:()=>epoch,persisted:async()=>{},operations:async()=>operations,setOperations}
  return {options,operations,setOperations,change:()=>{epoch++},edit:()=>{editing=true},switchSheet:()=>{sheetName='其他'},moveRange:()=>{row++}}
}
it('读取实际网格选区和当前未保存操作，整篇显式返回null',async()=>{
  const f=fixture(),context=await captureWorkbookReadContext('selection',f.options)
  expect(context.selection).toEqual({sheetName:'经营',startRow:2,endRow:3,startColumn:1,endColumn:3})
  expect(context.operations).toEqual(f.operations);expect(context.operations).not.toBe(f.operations)
  expect(f.setOperations).toHaveBeenCalledWith(f.operations)
  expect((await captureWorkbookReadContext('document',f.options)).selection).toBeNull()
})
it('正在编辑的单元格拒绝读取旧值，也不采集草稿',async()=>{
  const f=fixture();f.edit();const operations=vi.spyOn(f.options,'operations')
  await expect(captureWorkbookReadContext('document',f.options)).rejects.toThrow('按 Enter')
  expect(operations).not.toHaveBeenCalled();expect(f.setOperations).not.toHaveBeenCalled()
})
it.each(['change','switchSheet','moveRange','edit'] as const)('异步采集期间%s拒绝旧快照',async mutation=>{
  const f=fixture();let release!:()=>void
  f.options.persisted=()=>new Promise<void>(resolve=>{release=resolve})
  const result=captureWorkbookReadContext('selection',f.options)
  f[mutation]();release()
  await expect(result).rejects.toThrow('草稿或选区已变化')
  expect(f.setOperations).not.toHaveBeenCalled()
})
