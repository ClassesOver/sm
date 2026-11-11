import assert from 'node:assert/strict'
import {test} from 'node:test'
import JSZip from 'jszip'
import {buildDocx} from '../../packages/docx-engine/tests/helpers/build-docx.ts'
import {inspectDocxCommentThreads,patchDocxCommentThreads,type CommentThreadOperation,type CommentThreadTarget} from '../docx-comment-thread.ts'

const w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
const w14='http://schemas.microsoft.com/office/word/2010/wordml'
const w15='http://schemas.microsoft.com/office/word/2012/wordml'
const cid='http://schemas.microsoft.com/office/word/2016/wordml/cid'
const cex='http://schemas.microsoft.com/office/word/2018/wordml/cex'
const main='word/document.xml',comments='word/comments.xml',ex='word/commentsExtended.xml',ids='word/commentsIds.xml',ext='word/commentsExtensible.xml'
const type='application/vnd.openxmlformats-officedocument.wordprocessingml.'
const rel=(id:string,type:string,target:string)=>'<Relationship Id="'+id+'" Type="'+type+'" Target="'+target+'"/>'
const comment=(id:number,para:string,body:string)=>'<w:comment w:id="'+id+'" w:author="A"><w:p'+(para?' w14:paraId="'+para+'"':'')+'><w:r><w:t>'+body+'</w:t></w:r></w:p></w:comment>'
const record=(id:string,parent?:string)=>'<w15:commentEx w15:paraId="'+id+'"'+(parent?' w15:paraIdParent="'+parent+'"':'')+" w15:done = '0'/>"
const idRow=(p:string,d:string)=>'<w16cid:commentId w16cid:paraId="'+p+'" w16cid:durableId="'+d+'"/>'
const extRow=(d:string)=>'<w16cex:commentExtensible w16cex:durableId="'+d+'" w16cex:dateUtc="2026-01-01T01:01:01Z"/>'
const range=(name:string,id:number)=>'<w:commentRange'+name+' w:id="'+id+'"/>'
const reference=(id:number)=>'<w:commentReference w:id="'+id+'"/>'
const rootBody='<w:p>'+range('Start',1)+range('Start',3)+'<w:r><w:rPr><w:b/></w:rPr><w:t>same &amp; preserved</w:t></w:r>'+range('End',1)+range('End',3)+'<w:r>'+reference(1)+'<w:t>preserve run</w:t>'+reference(3)+'</w:r></w:p>'
async function fixture(options:{legacy?:boolean;ambiguous?:boolean;duplicateAnchor?:boolean}={}){
 const {legacy,ambiguous,duplicateAnchor}=options
 return buildDocx({bodyXml:rootBody+(duplicateAnchor?'<w:p><w:r>'+reference(1)+'</w:r></w:p>':''),extraRels:rel('rId30','http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments','comments.xml')+(legacy?'':[
  rel('rId31','http://schemas.microsoft.com/office/2011/relationships/commentsExtended','commentsExtended.xml'),
  rel('rId32','http://schemas.microsoft.com/office/2016/09/relationships/commentsIds','commentsIds.xml'),
  rel('rId33','http://schemas.microsoft.com/office/2018/08/relationships/commentsExtensible','commentsExtensible.xml'),
 ].join('')),extraParts:[
  {path:comments,xml:'<w:comments xmlns:w="'+w+'" xmlns:w14="'+w14+'">'+comment(1,legacy?'':'00000001','Root')+(legacy?'':comment(2,'00000002','Reply'))+comment(3,legacy?'':'00000003','Other')+'</w:comments>',contentType:type+'comments+xml'},
  ...legacy?[]:[
   {path:ex,xml:'<w15:commentsEx xmlns:w15="'+w15+'">'+record('00000001')+record('00000002','00000001')+record('00000003')+'</w15:commentsEx>',contentType:type+'commentsExtended+xml'},
   {path:ids,xml:'<w16cid:commentsIds xmlns:w16cid="'+cid+'">'+idRow('00000001','A0000001')+idRow('00000002',ambiguous?'A0000001':'A0000002')+idRow('00000003','A0000003')+'</w16cid:commentsIds>',contentType:'application/vnd.ms-word.commentsIds+xml'},
   {path:ext,xml:'<w16cex:commentsExtensible xmlns:w16cex="'+cex+'">'+extRow('A0000001')+extRow('A0000002')+extRow('A0000003')+'</w16cex:commentsExtensible>',contentType:'application/vnd.ms-word.commentsExtensible+xml'},
  ],
 ]})
}
function op(target:CommentThreadTarget, done?:boolean):CommentThreadOperation{
 const {sourceId,targetId,expectedCommentsSha256,expectedObjectSha256}=target
 const identity={sourceId,targetId,expectedCommentsSha256,expectedObjectSha256}
 return done===undefined?{kind:'deleteComment',...identity}:{kind:'resolveComment',done,...identity}
}
const read=(zip:JSZip,path:string)=>zip.file(path)!.async('string')

test('resolves and reopens an entire native thread, touching only the two done attributes',async()=>{
 const input=await fixture(),start=await inspectDocxCommentThreads(input)
 assert.equal(start.readOnlyReason,null)
 assert.deepEqual(start.targets.map(t=>[t.originalCommentId,t.parentId,t.done,t.canDelete,t.canResolve]),[['1',null,false,true,true],['2','1',false,true,false],['3',null,false,true,true]])
 const resolved=await patchDocxCommentThreads(input,[op(start.targets[0],true)])
 const original=await JSZip.loadAsync(input),after=await JSZip.loadAsync(resolved)
 for(const path of Object.keys(original.files))if(!original.files[path].dir&&path!==ex)assert.equal(await read(after,path),await read(original,path),path)
 assert.equal(await read(after,ex),(await read(original,ex)).replace(record('00000001'),record('00000001').replace("'0'","'1'")).replace(record('00000002','00000001'),record('00000002','00000001').replace("'0'","'1'")))
 const reopened=await inspectDocxCommentThreads(resolved)
 assert.deepEqual(reopened.targets.map(t=>t.done),[true,true,false])
 const restored=await patchDocxCommentThreads(resolved,[op(reopened.targets[0],false)])
 assert.equal(await read(await JSZip.loadAsync(restored),ex),await read(original,ex))
 await assert.rejects(patchDocxCommentThreads(resolved,[op(start.targets[0])]),/operation/)
})

test('deleting a root removes its replies and mapped records without moving other anchors or text',async()=>{
 const input=await fixture(),model=await inspectDocxCommentThreads(input)
 const result=await patchDocxCommentThreads(input,[op(model.targets[0])])
 const original=await JSZip.loadAsync(input),after=await JSZip.loadAsync(result)
 assert.equal(await read(after,main),(await read(original,main)).replace(range('Start',1),'').replace(range('End',1),'').replace(reference(1),''))
 assert.equal(await read(after,comments),(await read(original,comments)).replace(comment(1,'00000001','Root'),'').replace(comment(2,'00000002','Reply'),''))
 assert.equal(await read(after,ex),(await read(original,ex)).replace(record('00000001'),'').replace(record('00000002','00000001'),''))
 assert.equal(await read(after,ids),(await read(original,ids)).replace(idRow('00000001','A0000001'),'').replace(idRow('00000002','A0000002'),''))
 assert.equal(await read(after,ext),(await read(original,ext)).replace(extRow('A0000001'),'').replace(extRow('A0000002'),''))
 for(const path of Object.keys(original.files))if(!original.files[path].dir&&![main,comments,ex,ids,ext].includes(path))assert.equal(await read(after,path),await read(original,path),path)
 assert.deepEqual((await inspectDocxCommentThreads(result)).targets.map(t=>t.originalCommentId),['3'])
 const oneReply=await patchDocxCommentThreads(input,[op(model.targets[1])])
 assert.deepEqual((await inspectDocxCommentThreads(oneReply)).targets.map(t=>t.originalCommentId),['1','3'])
})

test('resolves a legacy comment without changing the body; refuses ambiguous identities and overlapping operations',async()=>{
 const input=await fixture({legacy:true}),start=await inspectDocxCommentThreads(input)
 const output=await patchDocxCommentThreads(input,[op(start.targets[0],true)])
 const reopened=await inspectDocxCommentThreads(output)
 assert.equal(reopened.readOnlyReason,null)
 assert.deepEqual(reopened.targets.map(t=>t.done),[true,false])
 assert.equal(await read(await JSZip.loadAsync(output),main),await read(await JSZip.loadAsync(input),main))
 const ambiguous=await fixture({ambiguous:true})
 assert.match((await inspectDocxCommentThreads(ambiguous)).readOnlyReason??'',/durable/)
 const duplicate=await inspectDocxCommentThreads(await fixture({duplicateAnchor:true}))
 assert.equal(duplicate.targets[0]?.canDelete,false)
 assert.equal(duplicate.targets[0]?.canResolve,false)
 const modern=await fixture(),m=await inspectDocxCommentThreads(modern)
 await assert.rejects(patchDocxCommentThreads(modern,[op(m.targets[0],true),op(m.targets[1])]),/overlap/)
})
