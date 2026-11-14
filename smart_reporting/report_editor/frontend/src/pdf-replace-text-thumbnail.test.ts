import {expect,it} from 'vitest'
import type {NativeOperation} from './native-draft'
import type {PdfPageIdentity,PdfTextObject} from './pdf-operations'
import {pdfTextReplacementThumbnailGeometry,pdfTextReplacementThumbnailStyles,pdfTextThumbnailInk} from './pdf-replace-text-thumbnail'

const sha='a'.repeat(64),pageId=`sha256:${sha}:page:0`,objectId='text-0',text='Original',expectedTextSha256='b'.repeat(64)
const target:PdfTextObject={objectId,text,rect:[30,346,65,358],expectedTextSha256,fontSize:12,fontName:'Helvetica',fontSha256:null,fillColor:[20,40,60]}
const operation:NativeOperation={kind:'replaceText',sourceSha256:sha,pageId,objectId,expectedTextSha256,newText:'Replacement'}
const page:PdfPageIdentity={pageId,index:0,rotation:0,mediaBox:{x:0,y:0,width:300,height:400},cropBox:{x:20,y:30,width:260,height:340}}
const textItems=[{str:text,dir:'ltr',transform:[12,0,0,12,30,350],width:35,height:12,fontName:'f1'}]
const viewport={width:260,height:340,convertToViewportPoint:(x:number,y:number)=>[x-20,370-y]},measureText=()=>20

it('maps one horizontal PDF.js text item to the source baseline box and PDFium ink cover',()=>{
 const preview=pdfTextReplacementThumbnailGeometry({sourceSha256:sha,operation,page,target,textItems,styles:{f1:{fontFamily:'Helvetica',ascent:.9,descent:-.1}},viewport,measureText})!
 expect(preview).toMatchObject({text:'Replacement',box:{left:10,width:35,height:14},cover:{left:8.5,width:38},fontFamily:'Helvetica',fillColor:[20,40,60],color:[20,40,60],paper:'#fff',align:'left',alignItems:'flex-end',lineHeight:'1',bold:false,italic:false})
 expect(preview.box.top).toBeCloseTo(7.2);expect(preview.cover.top).toBeCloseTo(7.7);expect(preview.cover.height).toBeCloseTo(17.8)
 expect(preview.fontSize).toBeCloseTo(11.04)
})

it.each([90,180,270])('maps a horizontal text item through a %i-degree page viewport',rotation=>{
 const pageWidth=260,pageHeight=340,crop={x:20,y:30},width=rotation%180?pageHeight:pageWidth,height=rotation%180?pageWidth:pageHeight
 const viewport={width,height,convertToViewportPoint:(x:number,y:number)=>{
  const px=x-crop.x,py=y-crop.y
  if(rotation===90)return [py,px]
  if(rotation===180)return [pageWidth-px,py]
  return [pageHeight-py,pageWidth-px]
 }}
 const preview=pdfTextReplacementThumbnailGeometry({sourceSha256:sha,operation,page:{...page,rotation},target,textItems,styles:{f1:{fontFamily:'Helvetica',ascent:.9,descent:-.1}},viewport,measureText})
 expect(preview).not.toBeNull()
 expect(Number.isFinite(preview!.box.left)).toBe(true);expect(Number.isFinite(preview!.box.top)).toBe(true)
 const expectedCover=rotation===90?{left:314.5,top:8.5,width:17.8,height:38}:rotation===180?{left:213.5,top:314.5,width:38,height:17.8}:{left:7.7,top:213.5,width:17.8,height:38}
 expect(preview!.cover.left).toBeCloseTo(expectedCover.left);expect(preview!.cover.top).toBeCloseTo(expectedCover.top);expect(preview!.cover.width).toBeCloseTo(expectedCover.width);expect(preview!.cover.height).toBeCloseTo(expectedCover.height)
 const expectedBox=rotation===90?{left:318.8,top:10,width:22,height:35}:rotation===180?{left:215,top:316.8,width:35,height:14}:{left:9.2,top:215,width:22,height:35}
 expect(preview!.box.left).toBeCloseTo(expectedBox.left);expect(preview!.box.top).toBeCloseTo(expectedBox.top);expect(preview!.box.width).toBeCloseTo(expectedBox.width);expect(preview!.box.height).toBeCloseTo(expectedBox.height)
 expect(preview!.alignItems).toBe(rotation===180?'flex-end':'center')
 expect(pdfTextReplacementThumbnailStyles(preview!,viewport).text.transform).toBeUndefined()
 expect(preview!.cover.width).toBeGreaterThan(0);expect(preview!.cover.height).toBeGreaterThan(0)
})

it('adds padding only when measured replacement text exceeds the layout width',()=>{
 const args={sourceSha256:sha,operation,page,target,textItems,styles:{f1:{fontFamily:'Helvetica',ascent:.9,descent:-.1}},viewport}
 expect(pdfTextReplacementThumbnailGeometry({...args,measureText:()=>34})!.box.width).toBe(35)
 expect(pdfTextReplacementThumbnailGeometry({...args,measureText:()=>36})!.box.width).toBe(38)
 const larger=pdfTextReplacementThumbnailGeometry({...args,operation:{...operation,fontSize:20},measureText:()=>20})!
 expect(larger.box.left).toBe(10);expect(larger.box.top).toBeCloseTo(0.2);expect(larger.box.width).toBe(35);expect(larger.box.height).toBe(21)
 expect(larger.alignItems).toBe('flex-end')
})

it('refuses stale identity, ambiguous matches, rotated text and run-level styles',()=>{
 const args={sourceSha256:sha,operation,page,target,textItems,styles:{f1:{fontFamily:'Helvetica',ascent:.9,descent:-.1}},viewport,measureText}
 expect(pdfTextReplacementThumbnailGeometry({...args,sourceSha256:'c'.repeat(64)})).toBeNull()
 expect(pdfTextReplacementThumbnailGeometry({...args,textItems:[...textItems,...textItems]})).toBeNull()
 expect(pdfTextReplacementThumbnailGeometry({...args,textItems:[{...textItems[0]!,transform:[0,12,-12,0,30,350]}]})).toBeNull()
 expect(pdfTextReplacementThumbnailGeometry({...args,operation:{...operation,styleRuns:[{start:0,end:1,color:[1,0,0]}]}})).toBeNull()
})

it('chooses source ink against the sampled paper while preserving an explicit override',()=>{
 expect(pdfTextThumbnailInk([255,255,255],[24,24,24],undefined)).toEqual([255,255,255])
 expect(pdfTextThumbnailInk([255,255,255],[24,24,24],[10,20,30])).toEqual([10,20,30])
})
