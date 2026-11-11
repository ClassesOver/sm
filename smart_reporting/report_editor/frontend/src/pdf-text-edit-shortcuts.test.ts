import {expect,it} from 'vitest'
import {bindPdfTextEditShortcuts} from './pdf-text-edit-shortcuts'
import {bindPdfReplacementStyle} from './pdf-replace-text-style'

function fixture(){
 const root=document.createElement('section'),textarea=document.createElement('textarea'),stage=document.createElement('button'),abort=new AbortController()
 textarea.setAttribute('aria-label','替换后的文字');textarea.value='AABBCC';stage.type='button';root.append(textarea,stage);document.body.append(root)
 const style=bindPdfReplacementStyle(root),submitted:unknown[]=[]
 stage.addEventListener('click',()=>submitted.push({newText:textarea.value,...style.read()}))
 bindPdfTextEditShortcuts(textarea,stage,abort.signal)
 return {root,textarea,stage,abort,style,submitted,key(init:KeyboardEventInit={}){const event=new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true,...init});textarea.dispatchEvent(event);return event},dispose(){abort.abort();style.dispose();root.remove()}}
}
for(const modifier of ['ctrlKey','metaKey'] as const)it(`${modifier} Enter submits current text and selected character styles once without inserting a newline`,()=>{
 const f=fixture()
 try{
  f.style.fill({kind:'replaceText',newText:'AABBCC',font:'courier',styleRuns:[{start:2,end:4,font:'times',size:18,bold:true,italic:true,color:[1,0,0]}]})
  f.textarea.focus();f.textarea.setSelectionRange(2,4,'backward')
  expect(f.key({[modifier]:true}).defaultPrevented).toBe(true)
  expect(f.submitted).toEqual([{newText:'AABBCC',font:'courier',styleRuns:[{start:2,end:4,font:'times',size:18,bold:true,italic:true,color:[1,0,0]}]}])
  expect([f.textarea.value,f.textarea.selectionStart,f.textarea.selectionEnd,f.textarea.selectionDirection]).toEqual(['AABBCC',2,4,'backward'])
 }finally{f.dispose()}
})
it('ordinary Enter and other shortcut keys preserve textarea default behavior',()=>{
 const f=fixture()
 try{expect(f.key().defaultPrevented).toBe(false);expect(f.key({key:'b',ctrlKey:true}).defaultPrevented).toBe(false);expect(f.submitted).toEqual([])}finally{f.dispose()}
})
for(const blocked of ['composing','ime229','repeat','alt','textareaDisabled','readOnly','stageDisabled','hidden','prevented','aborted'] as const)it(`${blocked} does not submit a text draft or suppress the key`,()=>{
 const f=fixture()
 try{
  const init:KeyboardEventInit={ctrlKey:true}
  if(blocked==='composing')init.isComposing=true
  if(blocked==='ime229')init.keyCode=229
  if(blocked==='repeat')init.repeat=true
  if(blocked==='alt')init.altKey=true
  if(blocked==='textareaDisabled')f.textarea.disabled=true
  if(blocked==='readOnly')f.textarea.readOnly=true
  if(blocked==='stageDisabled')f.stage.disabled=true
  if(blocked==='hidden')f.root.hidden=true
  if(blocked==='aborted')f.abort.abort()
  if(blocked==='prevented')f.textarea.addEventListener('keydown',event=>event.preventDefault(),{capture:true})
  expect(f.key(init).defaultPrevented).toBe(blocked==='prevented');expect(f.submitted).toEqual([])
 }finally{f.dispose()}
})
it('a document shortcut outside the replacement textarea cannot submit its draft',()=>{
 const f=fixture()
 try{const event=new KeyboardEvent('keydown',{key:'Enter',ctrlKey:true,bubbles:true,cancelable:true});document.dispatchEvent(event);expect(f.submitted).toEqual([]);expect(event.defaultPrevented).toBe(false)}finally{f.dispose()}
})
