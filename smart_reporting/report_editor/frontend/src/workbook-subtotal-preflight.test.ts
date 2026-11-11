import {expect,it} from 'vitest'
import {planSubtotal} from './workbook-subtotal'
const plan=()=>planSubtotal({startRow:4,endRow:8,startColumn:2,endColumn:4},[['g','v','x'],['A',1,0],['A',2,0],['B',3,0],['B',4,0]],{groupCol:2,valueCol:3,agg:'sum'})
it('counts each inserted-row journal operation before allowing a request at the 500 operation boundary',async()=>{
 const path='./workbook-subtotal-preflight';const {subtotalPreflightOperations}=await import(path)
 const source=Array.from({length:495},()=>({kind:'applySheetOutline',sheetName:'Data',summaryRight:true}))
 const before=structuredClone(source),operations=subtotalPreflightOperations(source,'Data',plan())
 expect(operations).toHaveLength(500);expect(source).toEqual(before)
 expect(operations.slice(495,498)).toEqual(plan().inserts.map(index=>({kind:'applyRowColumnOps',sheetName:'Data',ops:[{kind:'insert-rows',index,count:1}]})))
 expect(()=>subtotalPreflightOperations([...source,{kind:'applySheetOutline',sheetName:'Data',summaryRight:true}],'Data',plan())).toThrow('500')
 expect(operations.at(-1)).toMatchObject({kind:'applySheetOutline',summaryBelow:true})
 expect(operations.at(-2)).toMatchObject({kind:'applyCellEdits',edits:expect.arrayContaining([expect.objectContaining({row:7,column:3,style:{bold:true}})])})
})
