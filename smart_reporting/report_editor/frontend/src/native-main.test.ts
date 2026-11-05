import { beforeEach, expect, it, vi } from 'vitest'
const state=vi.hoisted(()=>({view:vi.fn(), context:vi.fn()}))
vi.mock('./native-api',()=>({createNativeApi:()=>({context:state.context})}))
vi.mock('./pdf-main',()=>({createPdfEditorView:state.view}))
import { startNativeEditor } from './native-main'
beforeEach(()=>{document.body.innerHTML='<div id="app"></div>';window.history.replaceState({},'', '/reports/v1/native/doc/1');state.context.mockResolvedValue({context:{documentId:'doc',revision:1,format:'pdf',sourceFile:{sha256:'a'.repeat(64),size:10},scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},csrfToken:'csrf',editingEnabled:false});state.view.mockReset()})
it('预览失败时保留原文件下载并禁用保存',async()=>{
  state.view.mockRejectedValue(new Error('渲染失败'))
  await startNativeEditor()
  expect(document.querySelector<HTMLAnchorElement>('a[download]')?.getAttribute('href')).toBe('/reports/v1/native/doc/1/api/file')
  expect(document.body.textContent).toContain('渲染失败')
  expect(document.querySelector<HTMLButtonElement>('[data-action=save]')!.disabled).toBe(true)
  expect(document.querySelector('[data-action=save] svg')).not.toBeNull()
  expect(document.querySelector('[data-action=pdf] svg')).not.toBeNull()
})
it('路径与上下文身份不符时不加载文件编辑器',async()=>{
  state.context.mockResolvedValue({context:{documentId:'foreign',revision:1}})
  await expect(startNativeEditor()).rejects.toThrow('身份')
  expect(state.view).not.toHaveBeenCalled()
})
