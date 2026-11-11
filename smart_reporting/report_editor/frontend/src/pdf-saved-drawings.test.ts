import { describe, expect, it } from 'vitest'
import { NativeDraft } from './native-draft'
import { pdfPageState, type PdfPageIdentity } from './pdf-operations'
import { toggleSavedDrawing, validateSavedDrawing } from './pdf-saved-drawings'
const a='a'.repeat(64),b='b'.repeat(64),hash='c'.repeat(64)
const page: PdfPageIdentity={pageId:'sha256:source:page:0',index:0,mediaBox:{x:0,y:0,width:400,height:500},cropBox:{x:0,y:0,width:400,height:500},rotation:0,drawingsReadSafe:true,drawings:[a,b].map((annotationId,i)=>({annotationId,expectedAnnotationSha256:hash,annotationIndex:i,subtype:'Line',rect:[20,30,120,90],removable:true,removalReason:null}))}
const identity={documentId:'doc',revision:1,sourceSha256:'d'.repeat(64),scope:{database:'db',companyId:'company',userId:'user',threadId:'thread'}}
describe('saved drawing exact identity draft',()=>{
 it('selects one of identical twins and supports undo, redo, restoration and local cancellation',()=>{
  const values=new Map<string,string>(),storage={getItem:(key:string)=>values.get(key)??null,setItem:(key:string,value:string)=>{values.set(key,value)},removeItem:(key:string)=>{values.delete(key)}}
  const draft=new NativeDraft(identity,storage)
  draft.setOperations(toggleSavedDrawing([],page,b))
  expect(pdfPageState([page],draft.operations)[0].drawings?.map(d=>d.annotationId)).toEqual([a])
  expect(page.drawings).toHaveLength(2)
  draft.undo();expect(draft.operations).toEqual([])
  draft.redo();expect(draft.operations).toHaveLength(1)
  const restored=new NativeDraft(identity,storage);expect(restored.operations).toEqual(draft.operations)
  expect(toggleSavedDrawing(restored.operations,page,b)).toEqual([])
 })
 it('rejects stale, foreign, readonly, duplicate and incompatible operations without altering source',()=>{
  const [op]=toggleSavedDrawing([],page,b)
  for(const invalid of [{...op,expectedAnnotationSha256:'f'.repeat(64)},{...op,annotationId:'e'.repeat(64)},{...op,pageId:'foreign'},{...op,rect:[20,30,120,90]}]) expect(()=>validateSavedDrawing(invalid,page)).toThrow()
  expect(()=>validateSavedDrawing(op,{...page,drawingsReadSafe:false})).toThrow()
  expect(()=>validateSavedDrawing(op,{...page,drawings:page.drawings?.map(d=>({...d,removable:false}))})).toThrow()
  expect(()=>pdfPageState([page],[op,op])).toThrow()
  for(const kind of ['replaceText','cropPage','setPageSize']) expect(()=>pdfPageState([page],[op,{kind}])).toThrow()
  const rotated=pdfPageState([page],[op,{kind:'rotatePage',pageId:page.pageId,delta:90}]);expect(rotated[0].rotation).toBe(90);expect(rotated[0].drawings).toHaveLength(1)
 })
})
