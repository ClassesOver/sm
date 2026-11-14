import {afterEach,beforeEach,expect,it} from 'vitest'
import {bindPdfSplitHost} from './pdf-split-host'
import {createNativeApi,type NativeContext} from './native-api'

beforeEach(()=>{
  Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value(this:HTMLDialogElement){this.open=true}})
  Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value(this:HTMLDialogElement){this.open=false;this.dispatchEvent(new Event('close'))}})
})
afterEach(()=>document.body.replaceChildren())
function fixture(){
  const root=document.createElement('div');document.body.append(root)
  const context:NativeContext={documentId:'parent',revision:4,format:'pdf',parentRevision:null,origin:'upload',scope:{database:'db',companyId:'c',userId:'u',threadId:'t'},sourceFile:{path:'source.pdf',size:1,sha256:'a'.repeat(64),mediaType:'application/pdf'}}
  const state={disposed:false,loaded:true,locked:false,previewing:false,printing:false,mutating:false,blocked:false,editable:true,pages:3,closed:false,dirty:false,unstaged:false}
  const host=bindPdfSplitHost({root,api:createNativeApi('parent',4,'csrf'),context,state:()=>state,beginMutation:()=>()=>{},setLocked:value=>{state.locked=value}})
  return{root,state,host}
}
it('小宿主同步可用，首次打开才挂载对话框，重复打开复用唯一句柄',async()=>{
  const f=fixture();expect(f.root.querySelector('dialog')).toBeNull();expect(f.host.unavailable()).toBeNull()
  await Promise.all([f.host.open(),f.host.open()]);expect(f.root.querySelectorAll('dialog')).toHaveLength(1)
  f.root.querySelector('dialog')!.close();await f.host.open();expect(f.root.querySelectorAll('dialog')).toHaveLength(1)
  f.host.dispose();expect(f.root.querySelector('dialog')).toBeNull()
})
it('动态模块返回前宿主已销毁时不挂载迟到对话框',async()=>{
  const f=fixture();const pending=f.host.open();f.host.dispose();await pending
  expect(f.root.querySelector('dialog')).toBeNull();expect(f.host.unavailable()).not.toBeNull()
})
it('忙碌/刷新或无flush脏草稿时阻止入口，恢复后重新可用',async()=>{
  const f=fixture();f.state.mutating=true;await f.host.open();expect(f.root.querySelector('dialog')).toBeNull()
  f.state.mutating=false;f.state.blocked=true;expect(f.host.unavailable()).not.toBeNull()
  f.state.blocked=false;f.state.dirty=true;expect(f.host.unavailable()).toContain('请先保存')
  f.state.dirty=false;f.state.pages=1;expect(f.host.unavailable()).toContain('至少两页')
  f.state.pages=3;await f.host.open();expect(f.root.querySelector('dialog')?.open).toBe(true);f.host.dispose()
})
