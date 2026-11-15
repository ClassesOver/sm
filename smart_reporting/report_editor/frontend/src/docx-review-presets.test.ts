import {afterEach,expect,it,vi} from 'vitest'
import {Editor,Node} from '@tiptap/core'
import {createDocxReviewPresets} from './docx-review-presets'
const Doc=Node.create({name:'doc',topNode:true,content:'block+'})
const Paragraph=Node.create({name:'docParagraph',group:'block',content:'text*',addAttributes:()=>({docxIndex:{default:null}}),renderHTML:()=>['p',0]})
const Text=Node.create({name:'text',group:'inline'})
const editors:Editor[]=[]
afterEach(()=>{editors.splice(0).forEach(editor=>editor.destroy());document.body.replaceChildren();vi.restoreAllMocks()})
function setup(count=2){
 const editor=new Editor({element:document.body.appendChild(document.createElement('div')),extensions:[Doc,Paragraph,Text],content:{type:'doc',content:Array.from({length:count},(_,index)=>({type:'docParagraph',attrs:{docxIndex:index},content:[{type:'text',text:'正文'+index}]}))}});editors.push(editor)
 const open=vi.fn(),error=vi.fn(),confirm=vi.fn(()=>true);let locked=false
 const controls=createDocxReviewPresets({editor,source:editor.state.doc,anchors:Array.from({length:count},(_,docxIndex)=>({docxIndex,blockId:'b'+docxIndex,expectedObjectSha256:'a'.repeat(64),editable:true})),reason:()=>locked?'正在保存':null,open,onError:error,confirm})
 document.body.append(controls.element)
 return {editor,open,error,confirm,controls,lock:()=>{locked=true}}
}
it('Editor with a range explicitly authorizes selected paragraphs and opens a candidate without running it',()=>{
 const f=setup();f.editor.commands.setTextSelection({from:1,to:3});f.controls.element.querySelector<HTMLButtonElement>('[data-action=review-editor]')!.click()
 expect(f.confirm).not.toHaveBeenCalled();expect(f.open).toHaveBeenCalledWith(expect.stringContaining('选中'),[{blockId:'b0'}],'selection')
})
it('whole-body preset requires confirmation for the actual two paragraph scope, cancellation opens nothing',()=>{
 const f=setup();f.confirm.mockReturnValue(false);f.controls.element.querySelector<HTMLButtonElement>('[data-action=review-editor]')!.click()
 expect(f.confirm).toHaveBeenCalledWith(expect.stringContaining('2'));expect(f.open).not.toHaveBeenCalled()
 f.confirm.mockReturnValue(true);f.controls.element.querySelector<HTMLButtonElement>('[data-action=review-editor]')!.click()
 expect(f.open).toHaveBeenCalledWith(expect.stringContaining('全文'),[{blockId:'b0'},{blockId:'b1'}],'document')
})
it('translation menu includes all 22 fixed-source languages and selecting English uses the selection prompt',()=>{
 const f=setup();f.editor.commands.setTextSelection({from:1,to:3})
 const trigger=f.controls.element.querySelector<HTMLButtonElement>('[data-action=review-translate]')!;trigger.click()
 const menu=f.controls.element.querySelector<HTMLElement>('[role=menu]')!;expect(menu.hidden).toBe(false);expect(menu.querySelectorAll('button')).toHaveLength(22);expect(f.open).not.toHaveBeenCalled()
 menu.querySelector<HTMLButtonElement>('[data-language=en]')!.click()
 expect(f.open).toHaveBeenCalledWith(expect.stringContaining('英文'),[{blockId:'b0'}],'selection');expect(menu.hidden).toBe(true)
})
it('stale menu, missing anchors and over 100 targets do not broaden or truncate authorization',()=>{
 const f=setup();f.controls.element.querySelector<HTMLButtonElement>('[data-action=review-translate]')!.click();f.lock();f.controls.element.querySelector<HTMLButtonElement>('[data-language=en]')!.click();expect(f.open).not.toHaveBeenCalled()
 const many=setup(101);many.controls.element.querySelector<HTMLButtonElement>('[data-action=review-editor]')!.click();expect(many.open).not.toHaveBeenCalled();expect(many.error).toHaveBeenCalled();expect(many.confirm).not.toHaveBeenCalled()
 const invalid=setup();invalid.editor.commands.insertContent({type:'docParagraph',attrs:{docxIndex:null},content:[{type:'text',text:'新增'}]});invalid.controls.element.querySelector<HTMLButtonElement>('[data-action=review-editor]')!.click();expect(invalid.open).not.toHaveBeenCalled();expect(invalid.error).toHaveBeenCalled()
})
it('Escape dismisses the language menu without starting a request and dispose removes controls',()=>{
 const f=setup();f.controls.element.querySelector<HTMLButtonElement>('[data-action=review-translate]')!.click();f.controls.element.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));expect(f.controls.element.querySelector<HTMLElement>('[role=menu]')!.hidden).toBe(true);expect(f.open).not.toHaveBeenCalled();f.controls.dispose();expect(f.controls.element.isConnected).toBe(false)
})
