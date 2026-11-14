import {expect,it} from 'vitest'
import type {NativeOperation} from './native-draft'
import type {PdfPageIdentity,PdfModel} from './pdf-operations'
import {pendingStaticFillsForThumbnail,pdfStaticFillThumbnailPosition} from './pdf-static-fill-thumbnail'

const sourceSha256='a'.repeat(64),pageId=`sha256:${sourceSha256}:page:0`
const page:PdfPageIdentity={pageId,index:0,rotation:90,mediaBox:{x:0,y:0,width:400,height:500},cropBox:{x:10,y:20,width:380,height:460}}
const model={sourceSha256,pages:[page]} as Pick<PdfModel,'sourceSha256'|'pages'>
const operation:NativeOperation={kind:'setStaticFill',sourceSha256,pageId,id:'fill-1',fillKind:'check',rect:[30,50,70,90],image:'iVBORw0KGgoAAA'}

it('projects only pending static fill images bound to the current source and page identity',()=>{
 expect(pendingStaticFillsForThumbnail(model,[operation],page)).toEqual([{id:'fill-1',image:'iVBORw0KGgoAAA',rect:[30,50,70,90]}])
 expect(pendingStaticFillsForThumbnail(model,[{...operation,sourceSha256:'b'.repeat(64)}],page)).toEqual([])
 expect(pendingStaticFillsForThumbnail(model,[{...operation,pageId:`sha256:${sourceSha256}:page:1`}],page)).toEqual([])
 expect(pendingStaticFillsForThumbnail(model,[{...operation,rect:[0,50,70,90]}],page)).toEqual([])
})

it('maps a source PDF rectangle through the rotated viewport into percentage coordinates',()=>{
 const viewport={width:460,height:380,convertToViewportPoint:(x:number,y:number)=>[y-20,380-(x-10)]}
 expect(pdfStaticFillThumbnailPosition([30,50,70,90],viewport)).toEqual({left:30/460*100,top:320/380*100,width:40/460*100,height:40/380*100})
})
