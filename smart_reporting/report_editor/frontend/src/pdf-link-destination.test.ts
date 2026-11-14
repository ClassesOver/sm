// @vitest-environment node
import {afterAll,beforeAll,expect,it} from 'vitest'
import {getDocument,type PDFDocumentLoadingTask,type PDFPageProxy} from 'pdfjs-dist/legacy/build/pdf.mjs'
import {blankPdfBytes} from './pdf-operations'
import {pdfLinkDestination} from './pdf-saved-links'

let loading:PDFDocumentLoadingTask,unit:ReturnType<PDFPageProxy['getViewport']>
beforeAll(async()=>{loading=getDocument({data:blankPdfBytes(300,400)});unit=(await(await loading.promise).getPage(1)).getViewport({scale:1})})
afterAll(async()=>{await loading?.destroy()})
const descriptor=(name:string,...parameters:unknown[])=>[0,{name},...parameters]
it.each([
 {dest:descriptor('XYZ',50,300,2),want:{scale:2,left:100,top:200}},
 {dest:descriptor('XYZ',null,null,0),want:{scale:1.5,left:0,top:0}},
 {dest:descriptor('XYZ',null,null,null),want:{scale:1.5,left:0,top:0}},
 {dest:descriptor('XYZ',50,300),want:{scale:1.5,left:75,top:150}},
 {dest:descriptor('Fit'),want:{scale:1.25,left:0,top:0}},
 {dest:descriptor('FitB'),want:{scale:1.25,left:0,top:0}},
 {dest:descriptor('FitH',250),want:{scale:2,left:0,top:300}},
 {dest:descriptor('FitBH',250),want:{scale:2,left:0,top:300}},
 {dest:descriptor('FitH',null),want:{scale:2,left:180,top:320}},
 {dest:descriptor('FitH'),want:{scale:2,left:0,top:0}},
 {dest:descriptor('FitV',50),want:{scale:1.25,left:62.5,top:0}},
 {dest:descriptor('FitBV',50),want:{scale:1.25,left:62.5,top:0}},
 {dest:descriptor('FitV'),want:{scale:1.25,left:0,top:0}},
 {dest:descriptor('FitR',50,100,250,300),want:{scale:2.5,left:125,top:250}},
])('destination $dest respects zoom and PDF coordinates',({dest,want})=>{
 expect(pdfLinkDestination(unit,dest,1.5,{width:600,height:500},[90,240])).toEqual(want)
})
it.each([
 {dest:descriptor('XYZ',60,290,2),want:{scale:2,left:1040,top:160}},
 {dest:descriptor('Fit'),want:{scale:1,left:0,top:0}},
 {dest:descriptor('FitH',260),want:{scale:1,left:460,top:0}},
 {dest:descriptor('FitV',60),want:{scale:1,left:0,top:80}},
 {dest:descriptor('FitR',60,260,180,290),want:{scale:520/240,left:460*(520/240),top:80*(520/240)}},
])('CropBox/UserUnit/90deg $dest uses the official viewport transform',({dest,want})=>{
 const Viewport=unit.constructor as new(options:{viewBox:number[];userUnit:number;scale:number;rotation:number})=>typeof unit
 const rotated=new Viewport({viewBox:[20,30,280,380],userUnit:2,scale:1,rotation:90})
 const actual=pdfLinkDestination(rotated,dest,1,{width:700,height:520})
 expect(actual.scale).toBeCloseTo(want.scale,10);expect(actual.left).toBeCloseTo(want.left,10);expect(actual.top).toBeCloseTo(want.top,10)
})
it.each([
 descriptor('XYZ',0,400,-1),descriptor('XYZ','50',400,1),descriptor('XYZ',0,Number.NaN,1),
 descriptor('FitR',50,100,50,300),descriptor('FitR',250,100,50,300),descriptor('FitR',50,null,250,300),
 descriptor('Other'),[0,{name:'XYZ'}],
].map(dest=>({dest})))('invalid destination $dest fails before a reading change',({dest})=>{
 expect(()=>pdfLinkDestination(unit,dest,1,{width:600,height:500})).toThrow('链接目标参数无效')
})
it('extreme valid zoom remains within the existing host zoom limits',()=>{
 expect(pdfLinkDestination(unit,descriptor('XYZ',50,300,40),1,{width:600,height:500})).toEqual({scale:8,left:400,top:800})
})
