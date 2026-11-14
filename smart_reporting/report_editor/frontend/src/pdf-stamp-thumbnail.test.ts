import {expect,it} from 'vitest'
import type {NativeOperation} from './native-draft'
import {pendingStampsForThumbnail} from './pdf-stamp-thumbnail'

const sourceSha256='a'.repeat(64),pageIds=[0,1].map(index=>`sha256:${sourceSha256}:page:${index}`)
const pages=[0,1].map(index=>({pageId:pageIds[index]!,index,rotation:index===0?90:0,mediaBox:{x:0,y:0,width:500,height:600},cropBox:{x:10,y:20,width:380,height:460}}))
const viewport={width:460,height:380,convertToViewportPoint:(x:number,y:number)=>[y-20,x-10]}
const operation:NativeOperation={kind:'setStamps',watermark:{text:'draft'},headerFooter:null,images:['iVBORw0KGgoAAA','iVBORw0KGgoBBB'],stamps:[
 {pageId:pageIds[0],image:0,rect:[30,50,70,90],opacity:.35},
 {pageId:pageIds[1],image:1,rect:[30,50,70,90]},
]}

it('selects pending stamps by page identity and maps their crop and rotation while retaining opacity',()=>{
 const reordered=[pages[1]!,pages[0]!]
 const result=pendingStampsForThumbnail([operation],reordered,pages[0]!,sourceSha256,viewport)
 expect(result).toEqual([{image:'iVBORw0KGgoAAA',rect:{left:30/460*100,top:20/380*100,width:40/460*100,height:40/380*100},opacity:.35}])
})

it('drops stamps from a foreign source or a page absent from the current page identities',()=>{
 expect(pendingStampsForThumbnail([{...operation,sourceSha256:'b'.repeat(64)}],pages,pages[0]!,sourceSha256,viewport)).toEqual([])
 expect(pendingStampsForThumbnail([operation],[pages[0]!],pages[1]!,sourceSha256,viewport)).toEqual([])
 const remaining={...operation,stamps:[(operation.stamps as {pageId:string}[])[0]]}
 expect(pendingStampsForThumbnail([remaining],[pages[0]!],pages[0]!,sourceSha256,viewport)).toHaveLength(1)
})
