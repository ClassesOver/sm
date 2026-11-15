import {expect,it,vi} from 'vitest'
import {createRoot} from 'react-dom/client'
import {flushSync} from 'react-dom'
import {DocxStoryRevisionDialog} from './docx-story-revision-dialog'
it('shows story context and submits only identities for the selected decision',()=>{
 const target={targetId:'target',partPath:'word/footer1.xml',expectedPartSha256:'part',expectedWrapperSha256:'wrapper',originalRevisionId:'7',kind:'footer' as const,type:'deletion' as const,author:'Ann',date:null,text:'old text'}
 const host=document.createElement('div'),root=createRoot(host),apply=vi.fn(),close=vi.fn()
 try{
  flushSync(()=>root.render(<DocxStoryRevisionDialog targets={[target]} onApply={apply} onClose={close}/>))
  expect(host.textContent).toContain('页脚');expect(host.textContent).toContain('old text')
  const button=(label:string)=>[...host.querySelectorAll('button')].find(b=>b.textContent===label)!
  expect(button('应用到草稿').disabled).toBe(true)
  flushSync(()=>button('拒绝').click());expect(button('应用到草稿').disabled).toBe(false)
  flushSync(()=>button('应用到草稿').click());expect(apply).toHaveBeenCalledWith([{kind:'resolveStoryRevision',targetId:'target',expectedPartSha256:'part',expectedWrapperSha256:'wrapper',action:'reject'}])
  flushSync(()=>button('取消').click());expect(close).toHaveBeenCalledOnce()
 }finally{flushSync(()=>root.unmount())}
})
