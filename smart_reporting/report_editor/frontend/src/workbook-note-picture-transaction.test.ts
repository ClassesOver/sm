import { expect, it } from 'vitest'
import { assertNotePictureTransaction, createNotePictureFilePicker } from './workbook-note-picture-transaction'

it('异步读图结束后拒绝草稿、工作簿、源文件、表名及选区变化', async () => {
  const identity = { book: {}, source: {}, epoch: 1, sheetId: 's', sheetName: '表', row: 0, column: 0 }
  let resolve!: () => void
  const reading = new Promise<void>(done => { resolve = done })
  const changes = [{ epoch: 2 }, { book: {} }, { source: {} }, { sheetId: 't' }, { sheetName: '新表名' }, { row: 1 }, { column: 1 }]
  resolve(); await reading
  for (const change of changes) expect(() => assertNotePictureTransaction(identity, { ...identity, ...change }, true, false)).toThrow(/变化/)
  expect(() => assertNotePictureTransaction(identity, identity, false, false)).toThrow()
  expect(() => assertNotePictureTransaction(identity, identity, true, true)).toThrow()
  expect(() => assertNotePictureTransaction(identity, identity, true, false)).not.toThrow()
})

it('取消事件与销毁均结束文件选择并移除临时input', async () => {
  const picker = createNotePictureFilePicker()
  document.querySelector('input[type=file]')!.dispatchEvent(new Event('cancel'))
  expect(await picker.result).toBeUndefined()
  expect(document.querySelector('input[type=file]')).toBeNull()
  const disposed = createNotePictureFilePicker()
  disposed.cancel(); disposed.cancel()
  expect(await disposed.result).toBeUndefined()
  expect(document.querySelector('input[type=file]')).toBeNull()
})
it('同一底层工作簿使用不同facade时仍允许事务',()=>{
 const core={},source={},facade=()=>({getWorkbook:()=>core})
 const identity={book:facade().getWorkbook(),source,epoch:0,sheetId:'s',sheetName:'表',row:0,column:0}
 expect(()=>assertNotePictureTransaction(identity,{...identity,book:facade().getWorkbook()},true,false)).not.toThrow()
})
