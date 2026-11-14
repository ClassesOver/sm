import {it,expect}from'vitest'
import{Editor}from'@tiptap/core'
import{editorExtensions}from'./vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import{createDocxContextActions}from'./docx-context-actions'
import{docxOperations,type DocxPmNode}from'./docx-operations'
import type{DocxContextMenuTarget,DocxContextMenuHandler}from'./docx-context-menu'
function setup(href='https://example.com'){
 const editor=new Editor({extensions:editorExtensions,content:{type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'visit',marks:[{type:'link',attrs:{href}}]}]}]}})
 editor.commands.setTextSelection(3)
 const root=document.body.appendChild(document.createElement('div')),anchors=[{docxIndex:0,blockId:'source',expectedObjectSha256:'hash',editable:true}],host=createDocxContextActions({editor,root,anchors,onError:()=>{}})
 const target={linkHref:href,link:{href,from:1,to:6}}as DocxContextMenuTarget
 return{editor,root,anchors,host,target}
}
const run=(h:DocxContextMenuHandler,t:DocxContextMenuTarget)=>typeof h==='function'?h(t):h.run(t)
it('removes the actual selected hyperlink through the existing typed native writer',()=>{
 const f=setup(),baseline=f.editor.getJSON()as DocxPmNode
 run(f.host.actions.removeLink!,f.target)
 const ops=docxOperations(baseline,f.editor.getJSON()as DocxPmNode,f.anchors)
 expect(ops).toEqual([expect.objectContaining({kind:'setParagraphLink',href:null})])
 expect(f.editor.getText()).toBe('visit');f.host.dispose();f.editor.destroy();f.root.remove()
})
it('keeps an unsafe imported hyperlink unavailable for external opening',()=>{
 const f=setup('javascript:alert(1)'),handler=f.host.actions.openLink!
 expect(typeof handler).toBe('object')
 expect((handler as Exclude<DocxContextMenuHandler,Function>).reason?.(f.target)).toMatch(/安全/)
 expect(()=>run(handler,f.target)).toThrow(/安全/)
 f.host.dispose();f.editor.destroy();f.root.remove()
})

it('keeps whole original image cutting unavailable while preserving readable clipboard access',()=>{
 const editor=new Editor({extensions:editorExtensions,content:{type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'keep'}]},{type:'docProtected',attrs:{docxIndex:1,blockType:'image',imageDataUrl:'data:image/png;base64,AA=='}}]}})
 editor.commands.setNodeSelection(6)
 const root=document.body.appendChild(document.createElement('div')),host=createDocxContextActions({editor,root,anchors:[{docxIndex:0,blockId:'p',expectedObjectSha256:'p',editable:true},{docxIndex:1,blockId:'img',expectedObjectSha256:'img',editable:false}],onError:()=>{}})
 const cut=host.actions.cut!;expect(typeof cut).toBe('object');expect((cut as Exclude<DocxContextMenuHandler,Function>).reason?.({}as DocxContextMenuTarget)).toMatch(/对象|图片|剪切/)
 expect(host.actions.copy).toBeDefined();host.dispose();editor.destroy();root.remove()
})
