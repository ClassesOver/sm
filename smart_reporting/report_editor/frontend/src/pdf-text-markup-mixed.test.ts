import {expect,it} from 'vitest'
import {pdfPageState,type PdfPageIdentity} from './pdf-operations'
import {validatePdfStyledReplacement} from './pdf-replace-text-style'
const sha='a'.repeat(64),pageId=`sha256:${sha}:page:0`,objectId='object-a',expectedTextSha256='b'.repeat(64)
const pages:PdfPageIdentity[]=[{pageId,index:0,rotation:0,mediaBox:{x:0,y:0,width:500,height:500},cropBox:{x:0,y:0,width:500,height:500},markupReadSafe:true,markups:[],textObjects:[{objectId,expectedTextSha256,text:'Original',rect:[60,300,130,315],fontSize:14,fontName:'Arial',fontSha256:null}]}]
const replace={kind:'replaceText',sourceSha256:sha,pageId,objectId,expectedTextSha256,newText:'First\nSecond',font:'times',fontSize:18,lineLeading:24}
const markup={kind:'addMarkup',pageId,markupType:'underline',quads:[[60,320,130,320,60,300,130,300]],color:[1,0,0]}
const highlight={kind:'highlight',sourceSha256:sha,pageId,rect:[50,200,100,220],color:[0,1,0]}
it('permits only new simple markups with styled replacement while preserving source page and operations',()=>{
 const ops=[markup,replace,highlight],copy=structuredClone(ops);expect(()=>validatePdfStyledReplacement(pages,ops)).not.toThrow();expect(pdfPageState(pages,ops)).toEqual(pages);expect(ops).toEqual(copy)
 for(const op of [{kind:'rotatePage',pageId,delta:90},{kind:'addTextAnnotation',pageId,rect:[20,100,40,120],text:'note'},{kind:'removeMarkup',pageId,annotationId:'c'.repeat(64),expectedAnnotationSha256:'d'.repeat(64)}])expect(()=>validatePdfStyledReplacement(pages,[replace,op])).toThrow('分别保存')
})
it('rejects stale markup identity and bounds before a mixed draft is staged',()=>{
 for(const op of [{...markup,pageId:`sha256:${'c'.repeat(64)}:page:0`},{...markup,sourceSha256:'c'.repeat(64)},{...markup,quads:[[60,320,130,320,60,-1,130,-1]]},{...highlight,rect:[50,200,550,220]},{...highlight,rect:[100,220,50,200]}])expect(()=>pdfPageState(pages,[replace,op])).toThrow()
 expect(()=>pdfPageState([{...pages[0]!,markupReadSafe:false}],[replace,markup])).toThrow()
})
