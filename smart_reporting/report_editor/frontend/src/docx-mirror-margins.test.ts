import { expect, it } from 'vitest'
import { docxMirrorMarginsOperations, withDocxMirrorMargins, currentDocxMirrorMargins } from './docx-mirror-margins'
import { NativeDraft } from './native-draft'
const model={expectedSettingsSha256:'a'.repeat(64),expectedProtectionSha256:'b'.repeat(64),protection:null,editable:true,contentLocked:false,hasPassword:false,readOnlyReason:null}
const op={kind:'setMirrorMargins',expectedSettingsSha256:model.expectedSettingsSha256,enabled:true}
it('journal mirror op coexists with section layout and removes itself on source-value revert',()=>{
 const section={kind:'setSectionLayout',sectionIndex:0,values:{marginLeft:1440,marginRight:1440}}
 const operations=withDocxMirrorMargins([section],model,true,false)
 expect(operations).toEqual([section,op]); expect(currentDocxMirrorMargins(operations,model,false)).toBe(true)
 expect(withDocxMirrorMargins(operations,model,false,false)).toEqual([section])
 expect(currentDocxMirrorMargins([],model,true)).toBe(true)
})
it('recovered operations reject stale hashes, duplicates, unknown fields and protected sources',()=>{
 for(const bad of [[{...op,extra:true}],[{...op,enabled:'true'}],[op,op],[{...op,expectedSettingsSha256:'c'.repeat(64)}]])expect(()=>docxMirrorMarginsOperations(bad,model)).toThrow()
 expect(()=>withDocxMirrorMargins([], {...model,contentLocked:true},true,false)).toThrow()
 expect(()=>withDocxMirrorMargins([], {...model,editable:false},true,false)).toThrow()
 expect(()=>withDocxMirrorMargins([],null,true,false)).toThrow()
})
it('mirror and section layout are one native draft undo/redo and recovery step',()=>{
 const storage=new Map<string,string>(), port={getItem:(key:string)=>storage.get(key)??null,setItem:(key:string,value:string)=>{storage.set(key,value)},removeItem:(key:string)=>{storage.delete(key)}}
 const identity={documentId:'doc',revision:1,sourceSha256:'s',scope:{database:'db',companyId:'c',userId:'u',threadId:'t'}}
 const draft=new NativeDraft(identity,port)
 const combined=withDocxMirrorMargins([{kind:'setSectionLayout',sectionIndex:0}],model,true,false)
 draft.setOperations(combined); expect(currentDocxMirrorMargins(draft.operations,model,false)).toBe(true)
 draft.undo(); expect(draft.operations).toEqual([]); draft.redo(); expect(draft.operations).toEqual(combined)
 expect(new NativeDraft(identity,port).operations).toEqual(combined)
})
