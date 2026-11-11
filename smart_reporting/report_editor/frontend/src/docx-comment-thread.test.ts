import {describe,expect,it} from 'vitest'
import {
 docxCommentThreadOperationsOf, normalizeDocxCommentThreads, projectedDocxCommentThreads, replayDocxCommentThreads,
 updateDocxCommentThreadOperations, verifiedDocxCommentThreadModel, type DocxCommentThreadModel, type DocxCommentThreadTarget,
} from './docx-comment-thread'

const sha='a'.repeat(64),source='b'.repeat(64),commentsSha='c'.repeat(64),obj='d'.repeat(64)
const target=(id:string,ordinal:number,parentId:string|null):DocxCommentThreadTarget=>({
 sourceId:source,targetId:id.repeat(64),expectedCommentsSha256:commentsSha,expectedObjectSha256:obj,
 originalCommentId:id,ordinal,author:'Author',date:null,initials:null,text:id,editableText:true,relationshipIds:[],readOnlyReason:null,
 parentId,done:false,canDelete:true,canResolve:parentId===null,threadReadOnlyReason:null,
})
const model:DocxCommentThreadModel={sourceSha256:sha,sourceId:source,targets:[target('1',0,null),target('2',1,'1'),target('3',2,null)],readOnlyReason:null}
const display=model.targets.map(t=>({id:t.originalCommentId,author:t.author,text:t.text,parentId:t.parentId??undefined}))
const body={type:'doc',content:[{type:'paragraph',content:[{type:'text',text:'anchored text',marks:[{type:'comment',attrs:{ids:['1','3']}}]}]}]}

describe('native Word comment thread draft',()=>{
 it('projects resolve, reopen and cascade delete without editing the source body, and replays the saved draft',()=>{
  const verified=verifiedDocxCommentThreadModel(model,sha,display)
  const resolved=updateDocxCommentThreadOperations(verified,[],model.targets[0].targetId,true)
  const live=replayDocxCommentThreads(body,resolved,verified)
  expect(projectedDocxCommentThreads(display,live,verified).map(c=>c.done)).toEqual([true,true,undefined])
  expect(normalizeDocxCommentThreads(body,live,verified)).toEqual({current:body,operations:resolved})
  expect(updateDocxCommentThreadOperations(verified,resolved,model.targets[0].targetId,false)).toEqual([])
  const deleted=updateDocxCommentThreadOperations(verified,resolved,model.targets[0].targetId)
  expect(projectedDocxCommentThreads(display,replayDocxCommentThreads(body,deleted,verified),verified).map(c=>c.id)).toEqual(['3'])
  expect(docxCommentThreadOperationsOf(replayDocxCommentThreads(body,deleted,verified),verified)).toEqual(deleted)
  expect(body.content[0].content[0].marks[0].attrs.ids).toEqual(['1','3'])
 })
 it('disables the whole thread on mismatched parsed ancestry and refuses malformed or overlapping intents',()=>{
  const wrong=verifiedDocxCommentThreadModel(model,sha,[display[0],{...display[1],parentId:'3'},display[2]])
  expect(wrong.targets[0].canDelete).toBe(false)
  expect(wrong.targets[2].canResolve).toBe(false)
  const root=updateDocxCommentThreadOperations(model,[],model.targets[0].targetId,true)
  const reply=updateDocxCommentThreadOperations(model,[],model.targets[1].targetId)
  expect(()=>replayDocxCommentThreads(body,[...root,...reply],model)).toThrow()
  expect(()=>replayDocxCommentThreads(body,[{...root[0],expectedObjectSha256:'wrong'}],model)).toThrow()
 })
 it('keeps ordinary editing available when source identities are ambiguous',()=>{
  const unavailable=verifiedDocxCommentThreadModel({sourceSha256:sha,sourceId:null,targets:[],readOnlyReason:'docx_comment_thread_durable_identity'},sha,display)
  const baseline={...body,attrs:{nativeCommentThreadOperations:null}}
  expect(normalizeDocxCommentThreads(baseline,baseline,unavailable)).toEqual({current:body,operations:[]})
  expect(projectedDocxCommentThreads(display,baseline,unavailable)).toEqual(display)
  const operations=updateDocxCommentThreadOperations(model,[],model.targets[0].targetId,true)
  expect(()=>replayDocxCommentThreads(baseline,operations,unavailable)).toThrow()
 })
})
