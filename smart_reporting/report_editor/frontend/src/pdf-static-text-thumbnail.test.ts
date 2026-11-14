import {expect,it} from 'vitest'
import type {NativeOperation} from './native-draft'
import type {PdfPageIdentity} from './pdf-operations'
import {pendingPdfTextInsertsForThumbnail,pdfTextInsertThumbnailStyle} from './pdf-static-text-thumbnail'

const sourceSha256='a'.repeat(64),pageId=`sha256:${sourceSha256}:page:0`
const page:PdfPageIdentity={pageId,index:0,rotation:90,mediaBox:{x:0,y:0,width:400,height:500},cropBox:{x:10,y:20,width:380,height:460}}
const operation:NativeOperation={kind:'insertText',sourceSha256,pageId,origin:[30,40],text:'待保存文字',fontSize:14,color:[.2,.4,.6],align:'left'}

it('projects inserted text only when source and page identities match',()=>{
 expect(pendingPdfTextInsertsForThumbnail(sourceSha256,[operation],page)).toEqual([operation])
 expect(pendingPdfTextInsertsForThumbnail('b'.repeat(64),[operation],page)).toEqual([])
 expect(pendingPdfTextInsertsForThumbnail(sourceSha256,[{...operation,pageId:`sha256:${sourceSha256}:page:1`}],page)).toEqual([])
})

it.each([
 ['90 degrees',460,380,(x:number,y:number)=>[y-20,x-10],`${20/460*100}%`,`${6/380*100}%`],
 ['270 degrees',460,380,(x:number,y:number)=>[480-y,390-x],`${440/460*100}%`,`${(360-14)/380*100}%`],
])('maps the first-line baseline and font scale through a %s thumbnail viewport',(_rotation,width,height,convert,expectedLeft,expectedTop)=>{
 const viewport={width,height,convertToViewportPoint:convert}
 expect(pdfTextInsertThumbnailStyle(operation,viewport)).toMatchObject({left:expectedLeft,top:expectedTop,fontSize:`${14*.92/460*100}cqw`,pointerEvents:'none'})
})
