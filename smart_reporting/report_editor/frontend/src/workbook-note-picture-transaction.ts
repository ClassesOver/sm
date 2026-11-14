/** 异步选图读取与提交之间必须仍属于同一个可编辑草稿。 */
export interface NotePictureTransactionIdentity {
  book: unknown; source: unknown; epoch: number; sheetId: string; sheetName: string; row: number; column: number
}
export function assertNotePictureTransaction(expected: NotePictureTransactionIdentity, current: NotePictureTransactionIdentity, editable: boolean, disposed: boolean) {
  if (disposed || !editable || expected.book !== current.book || expected.source !== current.source || expected.epoch !== current.epoch || expected.sheetId !== current.sheetId || expected.sheetName !== current.sheetName || expected.row !== current.row || expected.column !== current.column) {
    throw new Error('工作簿内容或选区已变化，请重新选择后插入')
  }
}

export function createNotePictureFilePicker() {
  const input = document.createElement('input')
  input.type = 'file'; input.accept = 'image/png,image/jpeg,image/gif'; input.hidden = true
  document.body.append(input)
  let finish!: (file?: File) => void
  const result = new Promise<File | undefined>(resolve => {
    let settled = false
    finish = file => { if (settled) return; settled = true; input.remove(); resolve(file) }
    input.addEventListener('change', () => finish(input.files?.[0]))
    input.addEventListener('cancel', () => finish())
  })
  return { result, open: () => input.click(), cancel: () => finish() }
}
