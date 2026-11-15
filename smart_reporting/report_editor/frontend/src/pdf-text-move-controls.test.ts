import {afterEach,expect,it,vi} from 'vitest'
import {NativeDraft} from './native-draft'
import {bindPdfTextMove} from './pdf-text-move'
const sha='a'.repeat(64),pageId=`sha256:${sha}:page:0`,objectId='original',expectedTextSha256='b'.repeat(64),controllers:ReturnType<typeof bindPdfTextMove>[]=[]
afterEach(()=>{controllers.splice(0).forEach(control=>control.dispose());document.body.replaceChildren()})
function fixture(){
 const root=document.body.appendChild(document.createElement('div')),draft=new NativeDraft({documentId:'move',revision:1,sourceSha256:sha,scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}},{getItem:()=>null,setItem(){},removeItem(){}})
 const pages=[{pageId,index:0,rotation:0,mediaBox:{x:0,y:0,width:500,height:500},cropBox:{x:0,y:0,width:500,height:500},textObjects:[{objectId,expectedTextSha256,text:'Original',rect:[60,300,130,315] as [number,number,number,number],fontSize:14,fontName:'Arial',fontSha256:null}]}]
 let blocked:string|null=null
 const refresh=vi.fn(async()=>{}),status=vi.fn(),control=bindPdfTextMove({root,draft,pages:()=>pages,target:()=>({pageId,objectId}),unavailable:()=>blocked,refresh,status});controllers.push(control)
 const x=root.querySelector<HTMLInputElement>('[aria-label="原文位移 X"]')!,y=root.querySelector<HTMLInputElement>('[aria-label="原文位移 Y"]')!,submit=root.querySelector<HTMLButtonElement>('[data-pdf-move-text]')!
 return {root,draft,control,x,y,submit,refresh,status,block:()=>{blocked='只读'}}
}
it('stages and restores source-relative movement with undo redo and zero reset',async()=>{
 const f=fixture();f.x.value='35';f.y.value='-25';expect(f.control.incompleteReason()).toContain('暂存');f.submit.click();await Promise.resolve()
 expect(f.draft.operations[0]).toEqual({kind:'moveText',sourceSha256:sha,pageId,objectId,expectedTextSha256,delta:[35,-25]});expect(f.control.incompleteReason()).toBeNull()
 f.draft.undo();f.control.update();expect(f.x.value).toBe('0');f.draft.redo();f.control.update();expect(f.x.value).toBe('35')
 f.x.value='0';f.y.value='0';f.submit.click();expect(f.draft.operations).toEqual([])
})
it.each(['permission','snapshot','disposed'])('forced movement submission cannot bypass %s changes',reason=>{
 const f=fixture();f.x.value='35'
 if(reason==='permission')f.block()
 if(reason==='snapshot')f.draft.setOperations([{kind:'rotatePage',pageId,delta:90}])
 if(reason==='disposed')f.control.dispose()
 const before=f.draft.operations;f.submit.dispatchEvent(new MouseEvent('click'));expect(f.draft.operations).toEqual(before)
})
it('does not stage out-of-page movement and retains accepted draft when refresh fails',async()=>{
 const f=fixture();f.x.value='1000';f.submit.click();expect(f.draft.operations).toEqual([])
 f.x.value='35';f.refresh.mockRejectedValueOnce(Error('offline'));f.submit.click();await Promise.resolve();await Promise.resolve()
 expect(f.draft.operations).toHaveLength(1);expect(f.status).toHaveBeenLastCalledWith(expect.stringContaining('已加入草稿，但刷新失败：offline'))
})
