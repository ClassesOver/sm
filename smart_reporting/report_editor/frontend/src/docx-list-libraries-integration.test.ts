import { afterEach, expect, it, vi } from 'vitest'
import { Editor } from '@tiptap/core'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { NativeDocxCustomList } from './docx-custom-list'
import { createDocxRibbon } from './docx-ribbon'
import { docxOperations } from './docx-operations'
const editors:Editor[]=[]
const ribbons:HTMLElement[]=[]
afterEach(()=>{ribbons.splice(0).forEach(r=>(r as HTMLElement & {dispose?:()=>void}).dispose?.());editors.splice(0).forEach(e=>e.destroy());document.body.replaceChildren()})
function fixture(){
 const editor=new Editor({extensions:[...editorExtensions,NativeDocxCustomList],content:{type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'甲'}]},{type:'docParagraph',attrs:{docxIndex:1},content:[{type:'text',text:'乙'}]}]}});editors.push(editor)
 const anchors=[0,1].map(i=>({docxIndex:i,blockId:`p${i}`,expectedObjectSha256:`hash${i}`,editable:true}))
 const report=vi.fn();const ribbon=createDocxRibbon(editor,true,undefined,undefined,undefined,anchors,undefined,undefined,undefined,report);ribbons.push(ribbon);document.body.append(ribbon)
 return {editor,ribbon,anchors,report}
}
it.each(['bullets','numbering'] as const)('真实Ribbon %s库同事务多段应用、历史与来源守卫',kind=>{
 const f=fixture(),baseline=f.editor.getJSON();f.editor.commands.setTextSelection({from:1,to:5})
 const toggle=f.ribbon.querySelector<HTMLButtonElement>(`[data-source-action=list-${kind}-gallery]`)!
 expect(toggle.disabled).toBe(false);toggle.click();f.ribbon.querySelector<HTMLButtonElement>('[data-docx-list-preset="2"]')!.click()
 expect(f.editor.getJSON().content!.map(n=>n.type)).toEqual(['docListItem','docListItem'])
 const ops=docxOperations(baseline,f.editor.getJSON(),f.anchors);expect(ops).toHaveLength(2);expect(ops[0]!.kind).toBe('setParagraphCustomList')
 expect(f.editor.commands.undo()).toBe(true);expect(f.editor.getJSON()).toEqual(baseline);expect(f.editor.commands.redo()).toBe(true)
 toggle.click();f.editor.commands.insertContent('新');f.ribbon.querySelector<HTMLButtonElement>('[data-docx-list-preset]')!.click()
 expect(f.report).toHaveBeenCalledOnce();expect(String(f.report.mock.calls[0]![0])).toContain('变化')
})
