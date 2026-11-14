import {describe,expect,it} from 'vitest'
import {docxTrackRevisionsEnabled,withDocxTrackRevisions} from './docx-track-revisions'

describe('DOCX track revisions setting',()=>{
 it('records and removes a source-bound document setting operation',()=>{
  const model={sourceSha256:'a'.repeat(64),enabled:false},other=[{kind:'setPageColor',color:'FFFFFF'}]
  const enabled=withDocxTrackRevisions(other,model,true)
  expect(enabled).toEqual([...other,{kind:'setTrackRevisions',sourceSha256:model.sourceSha256,enabled:true}])
  expect(docxTrackRevisionsEnabled(model,enabled)).toBe(true)
  expect(withDocxTrackRevisions(enabled,model,false)).toEqual(other)
 })

 it('restores a saved toggle operation against its frozen source model',()=>{
  const model={sourceSha256:'b'.repeat(64),enabled:true},operations=[{kind:'setTrackRevisions',sourceSha256:model.sourceSha256,enabled:false}]
  expect(docxTrackRevisionsEnabled(model,operations)).toBe(false)
 })

 it('rejects stale, malformed and repeated setting operations',()=>{
  const model={sourceSha256:'c'.repeat(64),enabled:false}
  expect(()=>docxTrackRevisionsEnabled(model,[{kind:'setTrackRevisions',sourceSha256:'d'.repeat(64),enabled:true}])).toThrow()
  expect(()=>docxTrackRevisionsEnabled(model,[{kind:'setTrackRevisions',sourceSha256:model.sourceSha256,enabled:1}])).toThrow()
  expect(()=>docxTrackRevisionsEnabled(model,[{kind:'setTrackRevisions',sourceSha256:model.sourceSha256,enabled:true},{kind:'setTrackRevisions',sourceSha256:model.sourceSha256,enabled:false}])).toThrow()
 })
})
