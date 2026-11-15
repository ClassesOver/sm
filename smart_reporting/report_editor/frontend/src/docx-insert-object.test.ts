import {afterEach,expect,it} from 'vitest'
import {Editor,Extension} from '@tiptap/core'
import {editorExtensions} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import {insertDocxObject,projectNewDocxObject,DOCX_OBJECT_SHAPES,WORDART_PRESETS,normalizeDocxInsertObject} from './docx-insert-object'
const editors:Editor[]=[]
afterEach(()=>editors.splice(0).forEach(e=>e.destroy()))
const ObjectAttrs=Extension.create({name:'testObjectAttrs',addGlobalAttributes:()=>[{types:['docProtected'],attributes:{nativeObjectInsert:{default:null}}}]})
it('inserts protected textbox PM nodes and preserves draft JSON across undo/redo',()=>{
 const editor=new Editor({extensions:[...editorExtensions,ObjectAttrs],editorProps:{handleScrollToSelection:()=>true},content:{type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'正文'}]}]}});editors.push(editor)
 const baseline=editor.getJSON();insertDocxObject(editor,{type:'textbox',text:'可保存文字'})
 const draft=JSON.parse(JSON.stringify(editor.getJSON()))
 expect(draft.content[1].attrs.nativeObjectInsert).toEqual({type:'textbox',text:'可保存文字'})
 expect(draft.content[1].attrs.textboxes[0].paras[0].runs[0].text).toBe('可保存文字')
 expect(draft.content[1]).toEqual(projectNewDocxObject({type:'textbox',text:'可保存文字'},editor.schema))
 editor.commands.undo();expect(editor.getJSON()).toEqual(baseline)
 editor.commands.redo();expect(editor.getJSON()).toEqual(draft)
 editor.commands.setContent(draft);expect(editor.getJSON()).toEqual(draft)
})
it('validates every canonical shape and wordart preset and rejects arbitrary XML',()=>{
 for(const preset of DOCX_OBJECT_SHAPES)expect(normalizeDocxInsertObject({type:'shape',preset}).preset).toBe(preset)
 for(const preset of WORDART_PRESETS)expect(normalizeDocxInsertObject({type:'wordArt',preset:preset.id}).preset).toBe(preset.id)
 for(const bad of [{type:'textbox',genXml:'<w:p/>'},{type:'shape',preset:'evil'},{type:'wordArt',preset:'evil'},{type:'textbox',widthEmu:NaN}])expect(()=>normalizeDocxInsertObject(bad)).toThrow()
})

import {docxInsertObjectOperation,replayDocxInsertObject} from './docx-insert-object'
import {createDocxInsertObjectControls} from './docx-insert-object-ui'
import {NodeSelection} from '@tiptap/pm/state'
it('strictly diffs, replays, edits and removes pending objects through the actual modal',()=>{
 const editor=new Editor({extensions:[...editorExtensions,ObjectAttrs],editorProps:{handleScrollToSelection:()=>true},content:{type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'正文'}]}]}});editors.push(editor)
 const baseline=editor.getJSON(),anchors=[{docxIndex:0,blockId:'a',expectedObjectSha256:'sha',editable:true}]
 const host=document.createElement('div');document.body.append(host)
 const controls=createDocxInsertObjectControls({editor,root:host,editable:()=>true})
 controls.open('shape')
 const form=host.querySelector('form')!,text=host.querySelector('textarea')!
 text.value='真实形状文字';form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))
 expect(host.querySelector('form')).toBeNull()
 const draft=editor.getJSON(),operation=docxInsertObjectOperation(baseline,draft,1,anchors,editor.schema)!
 expect(operation).toMatchObject({kind:'insertDocxObject',blockId:'a',position:'after',object:{type:'shape',preset:'rect',text:'真实形状文字'}})
 const restored=JSON.parse(JSON.stringify(baseline));replayDocxInsertObject(restored,operation,anchors,editor.schema,new Map())
 expect(restored).toEqual(draft)
 const tampered=JSON.parse(JSON.stringify(draft));tampered.content[1].attrs.genXml='<w:p/>'
 expect(()=>docxInsertObjectOperation(baseline,tampered,1,anchors,editor.schema)).toThrow()
 expect(()=>replayDocxInsertObject(restored,{...operation,expectedObjectSha256:'fake'},anchors,editor.schema,new Map())).toThrow()
 const pos=editor.state.doc.child(0).nodeSize
 editor.view.dispatch(editor.state.tr.setSelection(NodeSelection.create(editor.state.doc,pos)))
 controls.open('shape');host.querySelector('textarea')!.value='改文字'
 host.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))
 expect(editor.getJSON().content![1].attrs!.nativeObjectInsert).toMatchObject({text:'改文字'})
 editor.view.dispatch(editor.state.tr.setSelection(NodeSelection.create(editor.state.doc,pos)))
 controls.open('shape');host.querySelector<HTMLButtonElement>('[data-action=remove]')!.click()
 expect(editor.getJSON()).toEqual(baseline)
 editor.commands.undo();expect(editor.getJSON().content).toHaveLength(2)
 controls.dispose();host.remove()
})
