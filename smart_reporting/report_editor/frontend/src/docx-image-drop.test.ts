import { afterEach, expect, it, vi } from 'vitest'
import { Editor } from '@tiptap/core'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { createDocxImageDrop } from './docx-image-drop'
import { docxOperations, replayDocxOperations } from './docx-operations'
const editors:Editor[]=[],cleanups:(()=>void)[]=[]
afterEach(()=>{cleanups.splice(0).forEach(dispose=>dispose());editors.splice(0).forEach(editor=>editor.destroy());vi.unstubAllGlobals();document.body.replaceChildren()})
const PNG='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRz8AAAAASUVORK5CYII='
const GIF='R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=='
function file(name='picture.png',type='image/png'){return new File([Uint8Array.from(atob(type==='image/gif'?GIF:PNG),char=>char.charCodeAt(0))],name,{type})}
function setup(){
 const root=document.createElement('div'),element=document.createElement('div');root.append(element);document.body.append(root)
 const editor=new Editor({element,extensions:editorExtensions,editorProps:{handleScrollToSelection:()=>true},content:{type:'doc',content:[{type:'docParagraph',attrs:{docxIndex:0},content:[{type:'text',text:'body'}]}]}})
 editors.push(editor);editor.commands.setTextSelection(2)
 vi.spyOn(editor.view,'posAtCoords').mockReturnValue({pos:5,inside:0})
 const errors:unknown[]=[],lock={reason:null as string|null}
 cleanups.push(createDocxImageDrop({editor,root,locked:()=>lock.reason,onError:error=>errors.push(error)}).dispose)
 return {editor,root,errors,lock}
}
function imageDecoder(defer=false){const loads:(()=>void)[]=[];class BrowserImage {naturalWidth=1200;naturalHeight=600;onload?:()=>void;onerror?:()=>void;set src(_value:string){const finish=()=>this.onload?.();if(defer)loads.push(finish);else queueMicrotask(finish)}}vi.stubGlobal('Image',BrowserImage);return loads}
function drop(target:Element,files:File[],eventType='drop'){
 const event=new Event(eventType,{bubbles:true,cancelable:true});Object.defineProperties(event,{dataTransfer:{value:{files,items:files.map(f=>({kind:'file',type:f.type})),getData:()=>''}},clientX:{value:40},clientY:{value:80}});target.dispatchEvent(event);return event
}
it('OS image drop inserts actual native image payload at hit coordinates, replays and undoes',async()=>{
 imageDecoder();const {editor,errors}=setup(),baseline=editor.getJSON()
 const event=drop(editor.view.dom,[file()]);expect(event.defaultPrevented).toBe(true)
 await vi.waitFor(()=>expect(editor.state.doc.childCount).toBe(3))
 const image=editor.state.doc.child(1);expect(image.type.name).toBe('docProtected');expect(image.attrs.genImage).toMatchObject({mime:'image/png',base64:PNG,widthPx:620,heightPx:310})
 const anchors=[{docxIndex:0,blockId:'p0',expectedObjectSha256:'hash0',editable:true}]
 const operations=docxOperations(baseline,editor.getJSON(),anchors);expect(operations.some(operation=>operation.kind==='insertParagraphImage')).toBe(true)
 expect(docxOperations(baseline,replayDocxOperations(baseline,operations,anchors),anchors)).toEqual(operations)
 editor.commands.undo();expect(editor.getJSON()).toEqual(baseline);expect(errors).toEqual([])
})
it('multiple files retain source order and empty-MIME extension fallback works',async()=>{
 imageDecoder();const {editor}=setup();drop(editor.view.dom,[file('one.PNG',''),file('two.gif','image/gif')])
 await vi.waitFor(()=>expect(editor.state.doc.content.content.filter(node=>node.attrs.genImage)).toHaveLength(2))
 expect(editor.state.doc.child(1).attrs.genImage.mime).toBe('image/png');expect(editor.state.doc.child(2).attrs.genImage.mime).toBe('image/gif')
})
it('unrelated URLs, unsupported files and drops outside editor are left to their handlers',()=>{
 const {root,editor}=setup()
 expect(drop(root,[file()]).defaultPrevented).toBe(false)
 expect(drop(editor.view.dom,[file('other.webp','image/webp')]).defaultPrevented).toBe(false)
 expect(drop(editor.view.dom,[]).defaultPrevented).toBe(false)
})
it.each(['locked','readonly','composition'] as const)('image drops refuse %s without moving original selection',async mode=>{
 imageDecoder();const {editor,lock}=setup(),before=editor.getJSON(),selection=editor.state.selection
 if(mode==='locked')lock.reason='saving';if(mode==='readonly')editor.setEditable(false);if(mode==='composition')Object.defineProperty(editor.view,'composing',{configurable:true,value:true})
 expect(drop(editor.view.dom,[file()]).defaultPrevented).toBe(true)
 await new Promise(resolve=>setTimeout(resolve,20));expect(editor.getJSON()).toEqual(before);expect(editor.state.selection.eq(selection)).toBe(true)
})
it.each(['selection','document','locked'] as const)('drop refuses stale %s changes during async image decode',async mode=>{
 const loads=imageDecoder(true),{editor,lock,errors}=setup();drop(editor.view.dom,[file()])
 await vi.waitFor(()=>expect(loads).toHaveLength(1))
 if(mode==='selection')editor.commands.setTextSelection(3);if(mode==='document')editor.commands.insertContent('changed');if(mode==='locked')lock.reason='saving'
 const before=editor.getJSON(),selection=editor.state.selection;loads[0]!()
 await vi.waitFor(()=>expect(errors).toHaveLength(1));expect(editor.getJSON()).toEqual(before)
 if(mode!=='locked')expect(editor.state.selection.eq(selection)).toBe(true)
})
it('image decode failure restores the original selection and never inserts payload',async()=>{
 class BrokenImage{onerror?:()=>void;set src(_value:string){queueMicrotask(()=>this.onerror?.())}}vi.stubGlobal('Image',BrokenImage)
 const {editor,errors}=setup(),before=editor.getJSON(),selection=editor.state.selection;drop(editor.view.dom,[file()])
 await vi.waitFor(()=>expect(errors).toHaveLength(1));expect(editor.getJSON()).toEqual(before);expect(editor.state.selection.eq(selection)).toBe(true)
})

it('oversized files preserve original caret and never decode or insert',async()=>{
 const loads=imageDecoder(true),{editor,errors}=setup(),selection=editor.state.selection,before=editor.getJSON()
 drop(editor.view.dom,[new File([new Uint8Array(8*1024*1024+1)],'big.png',{type:'image/png'})])
 await vi.waitFor(()=>expect(errors).toHaveLength(1));expect(loads).toEqual([]);expect(editor.getJSON()).toEqual(before);expect(editor.state.selection.eq(selection)).toBe(true)
})
it('image dragover is intercepted only for an editable editor image-file drag',()=>{
 const {root,editor,lock}=setup(),observed:boolean[]=[]
 root.addEventListener('dragover',event=>observed.push(event.defaultPrevented),true)
 expect(drop(root,[file()],'dragover').defaultPrevented).toBe(false)
 expect(drop(editor.view.dom,[file()],'dragover').defaultPrevented).toBe(true)
 lock.reason='protected';drop(editor.view.dom,[file()],'dragover');expect(observed).toEqual([false,true,false])
})

it('disposing an in-flight drop cancels insertion and restores its temporary caret',async()=>{
 const loads=imageDecoder(true),{editor}=setup(),before=editor.getJSON(),selection=editor.state.selection
 drop(editor.view.dom,[file()]);await vi.waitFor(()=>expect(loads).toHaveLength(1))
 cleanups.pop()!();expect(editor.state.selection.eq(selection)).toBe(true)
 loads[0]!();await new Promise(resolve=>setTimeout(resolve,20));expect(editor.getJSON()).toEqual(before)
})
it('stale first decode aborts subsequent files rather than inserting them at a new user caret',async()=>{
 const loads=imageDecoder(true),{editor,errors}=setup();drop(editor.view.dom,[file(),file('second.png')])
 await vi.waitFor(()=>expect(loads).toHaveLength(1));editor.commands.setTextSelection(3);const before=editor.getJSON();loads[0]!()
 await vi.waitFor(()=>expect(errors).toHaveLength(1));await new Promise(resolve=>setTimeout(resolve,25))
 expect(loads).toHaveLength(1);expect(editor.getJSON()).toEqual(before)
})
