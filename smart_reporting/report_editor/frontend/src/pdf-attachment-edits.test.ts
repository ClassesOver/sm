import { describe, it, expect } from 'vitest'
import { attachmentEditState, attachmentFileOperation, validateAttachmentEdits } from './pdf-attachment-edits'
import { pdfPageState } from './pdf-operations'
const row={key:'original/key',name:'same.txt',description:'',size:1,contentSha256:'a'.repeat(64),attachmentId:'b'.repeat(64),expectedAttachmentSha256:'c'.repeat(64)}
const model={sourceSha256:'d'.repeat(64),attachments:[row],attachmentsEditable:true}
const remove={kind:'removeAttachment',attachmentId:row.attachmentId,expectedAttachmentSha256:row.expectedAttachmentSha256}
const add={kind:'addAttachment',name:'new.txt',bytesBase64:'aGk='}
describe('attachment draft projection',()=>{
 it('binds deletion to key and exact source identity and permits explicit replacement',()=>{
  expect([...attachmentEditState(model,[remove]).removed]).toEqual(['original/key'])
  expect(attachmentEditState(model,[remove,{...add,name:'original'}]).added).toHaveLength(1)
  expect(()=>attachmentEditState(model,[{...remove,expectedAttachmentSha256:'f'.repeat(64)}])).toThrow(/身份/)
  expect(()=>attachmentEditState(model,[{...remove,sourceSha256:'f'.repeat(64)}])).toThrow(/来源/)
  expect(()=>attachmentEditState({...model,attachmentsEditable:false},[remove])).toThrow(/查看/)
 })
 it('rejects restored malformed drafts, duplicates, collisions and text mixtures',()=>{
  for(const ops of [[{...add,name:'../x'}],[{...add,bytesBase64:'Zh=='}],[add,add],[remove,remove],[{...add,extra:true}],[add,{kind:'replaceText'}]])expect(()=>validateAttachmentEdits(ops)).toThrow()
  const simple={...model,attachments:[{...row,key:'new.txt'}]}
  expect(()=>attachmentEditState(simple,[add])).toThrow(/已存在/)
  expect(attachmentEditState(simple,[remove,add]).added).toHaveLength(1)
 })
 it('handles empty/binary files and document-level operations without page identity',async()=>{
  expect(await attachmentFileOperation({name:'empty.bin',size:0,arrayBuffer:async()=>new ArrayBuffer(0)} as File)).toEqual({kind:'addAttachment',name:'empty.bin',bytesBase64:''})
  const pages=[{pageId:'p',index:0,mediaBox:{x:0,y:0,width:300,height:400},cropBox:{x:0,y:0,width:300,height:400},rotation:0}]
  expect(pdfPageState(pages,[add,remove])).toEqual(pages)
 })
 it('enforces byte budgets including decoded size and aggregate count',()=>{
  expect(()=>validateAttachmentEdits([{...add,bytesBase64:btoa('x'.repeat(2*1024*1024+1))}])).toThrow()
  expect(()=>validateAttachmentEdits([0,1,2,3].map(i=>({...add,name:String(i),bytesBase64:btoa('x'.repeat(2*1024*1024))})))).toThrow(/总量/)
 })
})
