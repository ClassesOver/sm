import {expect,it} from 'vitest'
import {pdfPageState,type PdfPageIdentity} from './pdf-operations'
const sha='a'.repeat(64),pageId=`sha256:${sha}:page:0`,objectId='original',expectedTextSha256='b'.repeat(64)
const pages:PdfPageIdentity[]=[{pageId,index:0,rotation:0,mediaBox:{x:0,y:0,width:500,height:500},cropBox:{x:0,y:0,width:500,height:500},textObjects:[{objectId,expectedTextSha256,text:'Original',rect:[60,300,130,315],fontSize:14,fontName:'Arial',fontSha256:null}]}]
const insert={kind:'insertText',sourceSha256:sha,pageId,origin:[60,200],text:'Added text',fontSize:12,color:[0,0,0],align:'left'}
const replace={kind:'replaceText',sourceSha256:sha,pageId,objectId,expectedTextSha256,newText:'Updated',font:'times'}
it('accepts styled or plain replacements with inserts in either order without changing source identities',()=>{
 const {font,...plain}=replace
 for(const operation of [replace,plain])for(const operations of [[insert,operation],[operation,insert]]){const before=structuredClone(operations);expect(pdfPageState(pages,operations)).toEqual(pages);expect(operations).toEqual(before)}
})
it('validates all replacement options and identities even when plain text is mixed with an insert',()=>{
 for(const patch of [{sourceSha256:'c'.repeat(64)},{objectId:'stale'},{expectedTextSha256:'c'.repeat(64)},{newText:'x\u0000y'},{font:'other'},{fontSize:0}])expect(()=>pdfPageState(pages,[insert,{...replace,...patch}])).toThrow()
 for(const patch of [{sourceSha256:'c'.repeat(64)},{origin:[-1,0]},{text:' '}])expect(()=>pdfPageState(pages,[replace,{...insert,...patch}])).toThrow()
 for(const operation of [{kind:'rotatePage',pageId,delta:90},{kind:'addMarkup',pageId,markupType:'underline',quads:[[60,320,130,320,60,300,130,300]],color:[1,0,0]}])expect(()=>pdfPageState(pages,[replace,insert,operation])).toThrow()
})
