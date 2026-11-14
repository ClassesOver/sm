// @vitest-environment jsdom
import {expect,it} from 'vitest'
import {uploadDocxMailMergeSource} from './docx-mail-merge'
import {Editor} from '@tiptap/core'
import {editorExtensions} from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import {NativeDocxHistory,commitDocxNativeOperations,docxNativeOperationsOf,seedDocxNativeOperations} from './docx-native-history'
import {documentText,substituteMergeFields} from './docx-mail-merge-template'
it('uploads a real CSV larger than 256 KiB without an argument overflow',async()=>{
 const text='Name\n'+('A'.repeat(1023)+'\n').repeat(300),bytes=new TextEncoder().encode(text)
 const file={name:'large.csv',size:bytes.length,arrayBuffer:async()=>bytes.buffer} as File
 let received=''
 const api={mailMergeSource:async(payload:{bytesBase64:string})=>{received=payload.bytesBase64;return {source:{name:file.name,path:'native/mailmerge/hash.csv',sourceSha256:'hash',fields:['Name'],records:[{Name:'Ada'}],recordCount:1}}}}
 const source=await uploadDocxMailMergeSource(api,file)
 expect(atob(received)).toBe(text);expect(source.sourceBase64).toBe(received)
})
it('keeps merge intents in native Undo/Redo and restored document state',()=>{
 const editor=new Editor({extensions:[...editorExtensions,NativeDocxHistory],content:{type:'doc',content:[{type:'docParagraph',content:[{type:'text',text:'Dear ,'}]}]}})
 try{
  const operation={kind:'insertMailMergeField',name:'Name',offset:5}
  expect(commitDocxNativeOperations(editor,[operation])).toBe(true)
  expect(docxNativeOperationsOf(editor.getJSON())).toEqual([operation])
  expect(editor.commands.undo()).toBe(true);expect(docxNativeOperationsOf(editor.getJSON())).toEqual([])
  expect(editor.commands.redo()).toBe(true);expect(docxNativeOperationsOf(editor.getJSON())).toEqual([operation])
  seedDocxNativeOperations(editor,[{kind:'mailMergeSingle',sourceSha256:'source'}])
  expect(docxNativeOperationsOf(editor.getJSON())[0].kind).toBe('mailMergeSingle')
 }finally{editor.destroy()}
})
it('previews a field split across formatted text nodes once using source substitution',()=>{
 const mark={type:'instrField',attrs:{instr:'MERGEFIELD "Name"'}}
 const doc={type:'doc',content:[{type:'docParagraph',content:[{type:'text',text:'old',marks:[mark]},{type:'text',text:'cached',marks:[mark,{type:'bold'}]}]}]}
 expect(documentText(substituteMergeFields(doc,{Name:'Ada'}))).toBe('Ada')
})
