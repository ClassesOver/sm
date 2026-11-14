import {expect,it} from 'vitest'
import type {NativeOperation} from './native-draft'
import {pendingMarkupsForThumbnail} from './pdf-markup-thumbnail'

const sourceSha256='a'.repeat(64),pageId=`sha256:${sourceSha256}:page:0`
const page={pageId,index:0,rotation:90,mediaBox:{x:0,y:0,width:500,height:600},cropBox:{x:10,y:20,width:380,height:460},markups:[{markupType:'highlight' as const,quads:[[130,190,170,190,130,150,170,150]],color:[1,1,0]}]}
const viewport={width:460,height:380,convertToViewportPoint:(x:number,y:number)=>[y-20,x-10]}

it('projects only pending markups with the matching page identity through the rotated crop viewport',()=>{
 const operations:NativeOperation[]=[
  {kind:'addMarkup',pageId,markupType:'highlight',quads:[[30,90,70,90,30,50,70,50]],color:[1,.5,0]},
  {kind:'addMarkup',pageId,markupType:'underline',quads:[[30,90,70,90,30,50,70,50]],color:[0,0,1]},
  {kind:'addMarkup',pageId,markupType:'squiggly',quads:[[30,90,70,90,30,50,70,50]],color:[0,1,0]},
  {kind:'addMarkup',pageId,markupType:'strikeout',quads:[[30,90,70,90,30,50,70,50]],color:[1,0,0]},
  {kind:'addMarkup',pageId:`sha256:${'b'.repeat(64)}:page:0`,markupType:'highlight',quads:[[30,90,70,90,30,50,70,50]],color:[1,1,0]},
  {kind:'addMarkup',pageId,sourceSha256:'b'.repeat(64),markupType:'highlight',quads:[[30,90,70,90,30,50,70,50]],color:[1,1,0]},
  {kind:'removeMarkup',pageId,annotationId:'saved-markup',expectedAnnotationSha256:'c'.repeat(64)},
 ]
 const result=pendingMarkupsForThumbnail(operations,page,sourceSha256,viewport)
 expect(result.map(markup=>markup.markupType)).toEqual(['highlight','underline','squiggly','strikeout'])
 expect(result[0]).toMatchObject({left:30/460*100,top:20/380*100,width:40/460*100,height:40/380*100,color:[1,.5,0]})
})
