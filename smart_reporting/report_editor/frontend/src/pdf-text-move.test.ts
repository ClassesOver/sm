import {expect,it} from 'vitest'
import {pdfPageState,type PdfPageIdentity} from './pdf-operations'
import {stagePdfTextMove} from './pdf-text-move'
const sha='a'.repeat(64),pageId=`sha256:${sha}:page:0`,objectId='original',expectedTextSha256='b'.repeat(64)
const pages:PdfPageIdentity[]=[{pageId,index:0,rotation:0,mediaBox:{x:0,y:0,width:500,height:500},cropBox:{x:0,y:0,width:500,height:500},textObjects:[{objectId,expectedTextSha256,text:'Original',rect:[60,300,130,315],fontSize:14,fontName:'Arial',fontSha256:null}]}]
const move={kind:'moveText',sourceSha256:sha,pageId,objectId,expectedTextSha256,delta:[35,-25]}
it('validates a bound original move while preserving page geometry and source inputs',()=>{const before=structuredClone(move);expect(pdfPageState(pages,[move])).toEqual(pages);expect(move).toEqual(before)})
it('replaces one pending move by absolute source delta and zero restores the original position',()=>{
 const first=stagePdfTextMove(pages,[],sha,pageId,objectId,[35,-25])
 expect(stagePdfTextMove(pages,first,sha,pageId,objectId,[20,10])).toEqual([{...move,delta:[20,10]}])
 expect(stagePdfTextMove(pages,first,sha,pageId,objectId,[0,0])).toEqual([])
})
it('rejects stale object source bounds duplicate or mixed moves before draft mutation',()=>{
 for(const patch of [{sourceSha256:'c'.repeat(64)},{objectId:'stale'},{expectedTextSha256:'c'.repeat(64)},{delta:[1000,0]},{delta:[NaN,0]},{extra:1}])expect(()=>pdfPageState(pages,[{...move,...patch}])).toThrow()
 expect(()=>pdfPageState(pages,[move,move])).toThrow()
 expect(()=>pdfPageState(pages,[move,{kind:'rotatePage',pageId,delta:90}])).toThrow()
})
