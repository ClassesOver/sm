import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {NativeDraft} from './native-draft'
import {bindPdfPendingText} from './pdf-pending-text'
const sha='a'.repeat(64),pageId=`sha256:${sha}:page:0`
const operation={kind:'insertText',sourceSha256:sha,pageId,origin:[60,80],text:'Same <text>',fontSize:12,color:[0,0,0],align:'left'}
const controllers:ReturnType<typeof bindPdfPendingText>[]=[]
beforeEach(()=>{Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value(this:HTMLDialogElement){this.open=true}});Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value(this:HTMLDialogElement){this.open=false}})})
afterEach(()=>{controllers.splice(0).forEach(control=>control.dispose());document.body.replaceChildren()})
function fixture(count=2){
 const root=document.body.appendChild(document.createElement('div')),draft=new NativeDraft({documentId:'pending-text',revision:1,sourceSha256:sha,scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem(){},removeItem(){}})
 draft.setOperations(Array.from({length:count},()=>structuredClone(operation)))
 let blocked:string|null=null
 const edit=vi.fn(),refresh=vi.fn(async()=>{}),status=vi.fn()
 const controller=bindPdfPendingText({root,draft,pages:()=>[{pageId,index:0,rotation:0,cropBox:{x:0,y:0,width:300,height:400},mediaBox:{x:0,y:0,width:300,height:400}}],unavailable:()=>blocked,edit,refresh,status})
 controllers.push(controller);controller.open()
 return {root,draft,edit,refresh,status,controller,block:()=>{blocked='只读'}}
}
it('lists text safely and deletes only the selected duplicate with undo/redo',async()=>{
 const f=fixture(),before=f.draft.operations,rows=f.root.querySelectorAll('[data-pdf-pending-text-row]')
 expect(rows).toHaveLength(2);expect(rows[0]!.textContent).toContain('Same <text>');expect(rows[0]!.querySelector('text')).toBeNull()
 rows[1]!.querySelector<HTMLButtonElement>('[data-pdf-pending-text-delete]')!.click();await Promise.resolve()
 expect(f.draft.operations).toEqual([before[0]]);expect(f.refresh).toHaveBeenCalledTimes(1)
 f.draft.undo();expect(f.draft.operations).toEqual(before);f.draft.redo();expect(f.draft.operations).toHaveLength(1)
})
it('hands the exact index to the existing editor and closes the list',()=>{
 const f=fixture();f.root.querySelectorAll('[data-pdf-pending-text-edit]')[1]!.dispatchEvent(new MouseEvent('click'))
 expect(f.edit).toHaveBeenCalledWith(1);expect(f.root.querySelector('dialog')!.open).toBe(false)
})
it.each(['draft','permission','closed'])('stale %s cannot delete or edit another entry',reason=>{
 const f=fixture(),buttons=[...f.root.querySelectorAll<HTMLButtonElement>('[data-pdf-pending-text-delete],[data-pdf-pending-text-edit]')]
 if(reason==='draft')f.draft.setOperations([{...operation,text:'New snapshot'}])
 if(reason==='permission')f.block()
 if(reason==='closed')f.controller.dispose()
 const before=f.draft.operations;buttons.forEach(button=>button.click())
 expect(f.draft.operations).toEqual(before);expect(f.edit).not.toHaveBeenCalled()
})
it('supports management at the 500-operation limit and clean state after last deletion',()=>{
 const full=fixture(500);expect(full.root.querySelectorAll('[data-pdf-pending-text-row]')).toHaveLength(500)
 full.root.querySelector<HTMLButtonElement>('[data-pdf-pending-text-delete]')!.click();expect(full.draft.operations).toHaveLength(499)
 const last=fixture(1);last.root.querySelector<HTMLButtonElement>('[data-pdf-pending-text-delete]')!.click();expect(last.draft.dirty).toBe(false)
})
it('reports accepted deletion honestly when refresh fails',async()=>{
 const f=fixture();f.refresh.mockRejectedValueOnce(Error('offline'))
 f.root.querySelector<HTMLButtonElement>('[data-pdf-pending-text-delete]')!.click();await Promise.resolve();await Promise.resolve()
 expect(f.draft.operations).toHaveLength(1);expect(f.status).toHaveBeenLastCalledWith(expect.stringContaining('已删除'))
 expect(f.status).toHaveBeenLastCalledWith(expect.stringContaining('offline'))
})
it('detached row callbacks remain invalid after rerender and reopening',()=>{
 const f=fixture(3),old=[...f.root.querySelectorAll<HTMLButtonElement>('[data-pdf-pending-text-delete]')],edit=f.root.querySelectorAll<HTMLButtonElement>('[data-pdf-pending-text-edit]')[1]!
 old[0]!.click();const after=f.draft.operations
 old[1]!.click();edit.click();expect(f.draft.operations).toEqual(after);expect(f.edit).not.toHaveBeenCalled()
 const prior=f.root.querySelector<HTMLButtonElement>('[data-pdf-pending-text-delete]')!
 f.controller.open();prior.click();expect(f.draft.operations).toEqual(after)
})
