import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { NativeDraft } from './native-draft'
import { bindPdfStaticText } from './pdf-static-text'

const controllers: ReturnType<typeof bindPdfStaticText>[] = []
beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value(this: HTMLDialogElement) { this.open = true } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value(this: HTMLDialogElement) { this.open = false } })
})
afterEach(() => { controllers.splice(0).forEach(controller => controller.dispose()); document.body.replaceChildren(); vi.restoreAllMocks() })
function fixture(refresh:()=>Promise<void>=async()=>{}) {
  const root = document.body.appendChild(document.createElement('div')), input = root.appendChild(document.createElement('input'))
  const sha = 'a'.repeat(64), pageId = `sha256:${sha}:page:0`
  const values=new Map<string,string>(),storage={getItem:(key:string)=>values.get(key)??null,setItem:(key:string,value:string)=>{values.set(key,value)},removeItem:(key:string)=>{values.delete(key)}}
  const draft = new NativeDraft({ documentId: 'static-text-keyboard', revision: 1, sourceSha256: sha, scope: { database: 'fixture', companyId: 'c', userId: 'u', threadId: 't' } }, storage)
  let active = false
  const messages:string[]=[]
  const controller = bindPdfStaticText({ root, draft, pages: () => [{ pageId, index: 0, rotation: 0, cropBox: { x: 10, y: 20, width: 300, height: 400 }, mediaBox: { x: 0, y: 0, width: 400, height: 500 } }], unavailable: () => null,
    start: () => { active = true }, stop: () => { active = false }, refresh, status:message=>messages.push(message) })
  controllers.push(controller)
  controller.open(); root.querySelector<HTMLTextAreaElement>('textarea')!.value = '测试文字'
  root.querySelector<HTMLButtonElement>('[data-pdf-static-text-confirm]')!.click(); input.focus()
  return { root, input, controller, draft, storage, messages, pageId, active: () => active }
}
it.each(['consumed', 'composition', '229'])('插入落点等待保留%s输入拥有的Escape', async reason => {
  const f = fixture()
  if (reason === 'consumed') f.input.addEventListener('keydown', event => event.preventDefault())
  f.input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true, isComposing: reason === 'composition', keyCode: reason === '229' ? 229 : 27 }))
  expect(f.active()).toBe(true); expect(f.controller.incompleteReason()).toContain('落点')
  await f.controller.place(f.pageId, [75, 120])
  expect(f.draft.operations).toEqual([expect.objectContaining({ kind: 'insertText', origin: [75, 120], text: '测试文字' })])
})
it('普通Escape取消落点等待并不新增草稿', async () => {
  const f = fixture()
  f.root.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
  expect(f.active()).toBe(false); expect(f.controller.incompleteReason()).toBeNull()
  await f.controller.place(f.pageId, [75, 120]); expect(f.draft.operations).toEqual([])
})
it('连续放置追加原草稿并可逐次撤销重做',async()=>{
 const f=fixture();await f.controller.place(f.pageId,[75,120]);const first=f.draft.operations
 f.controller.open();f.root.querySelector<HTMLTextAreaElement>('textarea')!.value='第二段文字'
 f.root.querySelector<HTMLButtonElement>('[data-pdf-static-text-confirm]')!.click()
 await f.controller.place(f.pageId,[90,180])
 expect(f.draft.operations).toEqual([...first,expect.objectContaining({text:'第二段文字',origin:[90,180]})])
 f.draft.undo();expect(f.draft.operations).toEqual(first)
 f.draft.redo();expect(f.draft.operations).toHaveLength(2)
 const restored=new NativeDraft(f.draft.identity,f.storage);expect(restored.operations).toEqual(f.draft.operations)
})
it('配置后草稿变化不会覆盖或追加过期的文字',async()=>{
 const f=fixture();f.draft.setOperations([{kind:'rotatePage',pageId:f.pageId,delta:90}]);const changed=f.draft.operations
 await expect(f.controller.place(f.pageId,[75,120])).rejects.toThrow('草稿已变化')
 expect(f.draft.operations).toEqual(changed)
})
it('修改指定待保存文字的内容样式和基线，保留重复条目及撤销历史',async()=>{
 const f=fixture();await f.controller.place(f.pageId,[75,120]);const first=f.draft.operations[0]!
 f.draft.setOperations([first,{...first,origin:[90,180]}]);const before=f.draft.operations
 f.controller.edit(1)
 const dialog=f.root.querySelector<HTMLDialogElement>('dialog')!
 expect(dialog.open).toBe(true);expect(dialog.querySelector<HTMLTextAreaElement>('textarea')!.value).toBe('测试文字')
 dialog.querySelector<HTMLTextAreaElement>('textarea')!.value='更新段落'
 ;(dialog.querySelector('[aria-label="插入文字粗体"]') as HTMLInputElement).checked=true
 ;(dialog.querySelector('[aria-label="插入文字基线 X"]') as HTMLInputElement).value='150'
 ;(dialog.querySelector('[aria-label="插入文字基线 Y"]') as HTMLInputElement).value='210'
 dialog.querySelector<HTMLButtonElement>('[data-pdf-static-text-confirm]')!.click()
 await Promise.resolve()
 expect(f.draft.operations).toEqual([before[0],{...before[1],text:'更新段落',origin:[150,210],bold:true}])
 expect(f.active()).toBe(false)
 f.draft.undo();expect(f.draft.operations).toEqual(before);f.draft.redo();expect(f.draft.operations[1]!.text).toBe('更新段落')
})
it('待保存文字编辑拒绝越界和过期快照，取消不改变草稿',async()=>{
 const f=fixture();await f.controller.place(f.pageId,[75,120]);const before=f.draft.operations
 f.controller.edit(0)
 f.root.querySelector<HTMLInputElement>('[aria-label="插入文字基线 X"]')!.value='0'
 f.root.querySelector<HTMLButtonElement>('[data-pdf-static-text-confirm]')!.click()
 expect(f.draft.operations).toEqual(before);expect(f.root.querySelector('[role="alert"]')!.textContent).toContain('超出')
 f.controller.cancel();expect(f.draft.operations).toEqual(before)
 f.controller.edit(0);f.draft.setOperations([...before,{...before[0]!,origin:[120,150]}]);const changed=f.draft.operations
 f.root.querySelector<HTMLButtonElement>('[data-pdf-static-text-confirm]')!.click()
 expect(f.draft.operations).toEqual(changed);expect(f.root.querySelector('[role="alert"]')!.textContent).toContain('草稿已变化')
})

it('编辑采纳后刷新失败仍保留文字修改并如实提示',async()=>{
 let fail=false
 const f=fixture(async()=>{if(fail)throw Error('offline')});await f.controller.place(f.pageId,[75,120]);fail=true
 f.controller.edit(0);f.root.querySelector<HTMLTextAreaElement>('textarea')!.value='Retained edit'
 f.root.querySelector<HTMLButtonElement>('[data-pdf-static-text-confirm]')!.click();await Promise.resolve();await Promise.resolve()
 expect(f.draft.operations[0]!.text).toBe('Retained edit');expect(f.messages.at(-1)).toContain('已加入草稿，但刷新失败：offline')
})
