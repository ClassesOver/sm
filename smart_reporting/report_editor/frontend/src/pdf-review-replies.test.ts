import {expect,it} from 'vitest'
import {validatePdfReplies} from './pdf-replies'
import {pdfPageState} from './pdf-operations'
import {projectPageComments} from './pdf-comments'
const note={sourceRef:'20R',annotationId:'a'.repeat(64),expectedAnnotationSha256:'b'.repeat(64),contents:'Change to 700',removalReason:null,editable:true,removable:true,replyable:true}
const page={pageId:'p',index:0,rotation:0,mediaBox:{x:0,y:0,width:300,height:400},cropBox:{x:0,y:0,width:300,height:400},notes:[note],notesReadSafe:true}
const replace={kind:'replaceText',pageId:'p',objectId:'t',expectedTextSha256:'c'.repeat(64),newText:'Amount due 700'}
const reply={kind:'replyNote',pageId:'p',annotationId:note.annotationId,expectedAnnotationSha256:note.expectedAnnotationSha256,contents:'Changed to 700.',createdMs:0,author:'AI Assistant'}
it('可信已保存根批注支持混合原位改字与唯一AI作者，页状态可刷新及恢复',()=>{
 expect(()=>validatePdfReplies([page],[replace,reply])).not.toThrow()
 expect(pdfPageState([page],[replace,reply])).toHaveLength(1)
 expect(()=>validatePdfReplies([page],[replace,{...reply,author:undefined}])).not.toThrow()
})
it('AI混合批次仍拒绝任意作者、过期父身份及裁切/页面尺寸',()=>{
 for(const operations of [[replace,{...reply,author:'Reviewer'}],[replace,{...reply,expectedAnnotationSha256:'0'.repeat(64)}],[reply,{kind:'cropPage',pageId:'p',rect:[0,0,200,300]}],[reply,{kind:'setPageSize',preset:'A4'}]]) expect(()=>validatePdfReplies([page],operations)).toThrow()
})
it('待保存便签回复支持原位改字并保留精确localId和AI作者边界',()=>{
 const root={kind:'addTextAnnotation',pageId:'p',localId:'d'.repeat(32),rect:[30,100,50,118],text:'Root',createdMs:0}
 const pending={kind:'replyPendingNote',pageId:'p',parentLocalId:root.localId,contents:'Question?',createdMs:0}
 expect(()=>validatePdfReplies([page],[root,{...pending,author:'AI Assistant'},replace])).not.toThrow()
 expect(()=>validatePdfReplies([page],[root,pending,replace])).not.toThrow()
 for(const extra of [{author:'Reviewer'},{parentLocalId:'e'.repeat(32)},{sourceRef:'99R'}])expect(()=>validatePdfReplies([page],[root,{...pending,...extra},replace])).toThrow()
 expect(()=>validatePdfReplies([page],[root,pending,{kind:'cropPage',pageId:'p',rect:[0,0,200,300]}])).toThrow()
})
it('待保存AI回复在精确第二根评论线程显示可信作者',()=>{
 const first={kind:'addTextAnnotation',pageId:'p',rect:[30,100,50,118],text:'Same root'},second={...first,localId:'d'.repeat(32)}
 const roots=projectPageComments([],page,1,[first,second,{kind:'replyPendingNote',pageId:'p',parentLocalId:second.localId,contents:'Changed.',createdMs:0,author:'AI Assistant'}],false)
 expect(roots[0].replies).toHaveLength(0);expect(roots[1].replies).toHaveLength(1)
 expect(roots[1].replies[0].author).toBe('AI Assistant')
})
