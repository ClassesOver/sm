import {expect,it} from 'vitest'
import {pdfPageState,type PdfPageIdentity} from './pdf-operations'
const sha='a'.repeat(64),pageId=`sha256:${sha}:page:0`,objectId='target',expectedTextSha256='b'.repeat(64)
const pages:PdfPageIdentity[]=[{pageId,index:0,rotation:0,mediaBox:{x:0,y:0,width:500,height:500},cropBox:{x:0,y:0,width:500,height:500},markupReadSafe:true,drawingsReadSafe:true,markups:[],drawings:[],textObjects:[{objectId,expectedTextSha256,text:'Original',rect:[60,300,130,315],fontSize:14,fontName:'Arial',fontSha256:null}]}]
const replace={kind:'replaceText',sourceSha256:sha,pageId,objectId,expectedTextSha256,newText:'New\nSecond',font:'courier',fontSize:12}
const rect={kind:'addDrawing',pageId,shape:'rect',rect:[40,280,150,330],color:[1,0,0],width:2}
it('permits a source-bound rectangle or ellipse together with styled text without changing either draft',()=>{
 const ops=[rect,replace,{...rect,shape:'ellipse',rect:[200,200,240,260]}],copy=structuredClone(ops);expect(pdfPageState(pages,ops)).toEqual(pages);expect(ops).toEqual(copy)
})
it('rejects unsupported drawings stale identities and unsafe geometry before mixing drafts',()=>{
 for(const patch of [{shape:'arrow',from:[20,20],to:[30,30]},{shape:'ink',paths:[[20,20,30,30]]},{shape:'link',url:'javascript:alert(1)'},{rect:[40,280,550,330]},{rect:[40,280,40,330]},{width:Infinity},{width:0},{color:[1,-1,0]},{sourceSha256:'c'.repeat(64)},{pageId:`sha256:${'c'.repeat(64)}:page:0`},{from:[20,20]}])expect(()=>pdfPageState(pages,[replace,{...rect,...patch}])).toThrow()
 expect(()=>pdfPageState([{...pages[0]!,drawingsReadSafe:false}],[replace,rect])).toThrow()
})
