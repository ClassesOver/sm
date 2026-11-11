import {act} from 'react'
import {createRoot} from 'react-dom/client'
import {expect,it,vi} from 'vitest'
import {DocxNotesSource,type DocxNotesController} from './docx-notes-source'
it('中文图标入口仅在AI可用时出现，已有注释必须明确选择后才授权',async()=>{
 const host=document.body.appendChild(document.createElement('div')),root=createRoot(host)
 const controller:DocxNotesController={editable:true,entries:[{kind:'footnote',id:'1',text:'现有脚注',editable:true}],insert:vi.fn(),edit:vi.fn(),remove:vi.fn(),aiInsert:vi.fn(),aiEdit:vi.fn()}
 await act(async()=>root.render(<DocxNotesSource controller={controller}/>))
 const insert=host.querySelector<HTMLButtonElement>('[data-note-action=ai-insert]')!,edit=host.querySelector<HTMLButtonElement>('[data-note-action=ai-edit]')!
 expect(insert.textContent).toBe('AI 新增注释');expect(insert.querySelector('svg')).not.toBeNull();expect(edit.disabled).toBe(true)
 await act(async()=>insert.click());expect(controller.aiInsert).toHaveBeenCalledOnce()
 const select=host.querySelector('select')!;await act(async()=>{select.value=JSON.stringify(['footnote','1']);select.dispatchEvent(new Event('change',{bubbles:true}))})
 expect(edit.disabled).toBe(false);await act(async()=>edit.click());expect(controller.aiEdit).toHaveBeenCalledWith('footnote','1')
 await act(async()=>root.render(<DocxNotesSource controller={{...controller,aiInsert:undefined,aiEdit:undefined}}/>));expect(host.querySelector('[data-note-action=ai-edit]')).toBeNull()
 await act(async()=>root.unmount());host.remove()
})
