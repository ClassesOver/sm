// Component-level browser fixture: actual paintDrawing + actual PDF.js saved AP.
import {paintDrawing} from '../src/pdf-drawing-shapes.ts'
import {getDocument, GlobalWorkerOptions, OPS} from 'pdfjs-dist/legacy/build/pdf.mjs'
GlobalWorkerOptions.workerSrc='/pdf.worker.mjs'
if(new URLSearchParams(location.search).has('fallback')){
 const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('width','300');svg.setAttribute('height','100');svg.style.background='white';document.body.append(svg)
 const group=document.createElementNS(svg.namespaceURI,'g');svg.append(group)
 paintDrawing(group,{kind:'addDrawing',shape:'measure',from:[20,20],to:[80,20],label:'Visible fallback',color:[.86,.22,.18],width:1},{convertToViewportPoint:(x,y)=>[x,100-y]},1)
 await document.fonts.load('9px "PDF Standard Helvetica"').catch(()=>{})
 await document.fonts.ready
 const label=svg.querySelector('[data-pdf-measure-label]')
 const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d'),families={}
 for(const family of ['Helvetica','Arial','Liberation Sans','sans-serif','"PDF Standard Helvetica", Helvetica, Arial, sans-serif','"PDF Standard Helvetica", Arial, sans-serif']){ctx.font=`9px ${family}`;families[family]=ctx.measureText(label.textContent).width}
 window.fallbackResult={label:label.textContent,width:label.getBBox().width,family:getComputedStyle(label).fontFamily,families,faces:[...document.fonts].map(font=>({family:font.family,status:font.status}))}
 window.drawingReady=true
}else{
const evidence=await(await fetch('/native-ap.json')).json()
const pdf=await getDocument({url:'/saved-ap.pdf',standardFontDataUrl:'/reports/v1/editor/assets/pdfjs/standard_fonts/'}).promise
const diagnosticPdf=await getDocument({url:'/saved-labels.pdf',standardFontDataUrl:'/reports/v1/editor/assets/pdfjs/standard_fonts/'}).promise
const page=await pdf.getPage(1)
const diagnosticPage=await diagnosticPdf.getPage(1)
const fontName='PDF Standard Helvetica'
await document.fonts.load(`9px "${fontName}"`)
if(!document.fonts.check(`9px "${fontName}"`))throw Error('Standard14 draft font not loaded')
const operators=await page.getOperatorList()
const fonts=[...new Set(operators.fnArray.flatMap((op,index)=>op===OPS.setFont?[operators.argsArray[index][0]]:[]))]
const actualFonts=fonts.map(id=>page.commonObjs.get(id))
const pdfFont=actualFonts.find(font=>font.name==='Helvetica')??actualFonts[0]
if(!pdfFont?.loadedName)throw Error('Actual AP font missing')
const canvas=document.createElement('canvas'),context=canvas.getContext('2d')
context.fontKerning='none';context.textRendering='geometricPrecision'
window.checkDrawing=async(rotation,zoom)=>{
 document.body.replaceChildren()
 const viewport=page.getViewport({rotation,scale:zoom})
 const caption=document.createElement('p');caption.textContent=`${rotation}° / ${zoom}× — SVG draft (left), saved native AP in PDF.js (right)`;document.body.append(caption)
 const row=document.createElement('div');row.style.cssText='display:flex;gap:20px;align-items:start';document.body.append(row)
 const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('width',viewport.width);svg.setAttribute('height',viewport.height);svg.style.background='white';row.append(svg)
 for(const operation of evidence.operations){const group=document.createElementNS(svg.namespaceURI,'g');svg.append(group);paintDrawing(group,operation,viewport,zoom)}
 const saved=document.createElement('canvas');saved.width=viewport.width;saved.height=viewport.height;row.append(saved)
 await page.render({canvasContext:saved.getContext('2d'),viewport}).promise
 const diagnostic=document.createElement('canvas');diagnostic.width=viewport.width;diagnostic.height=viewport.height
 await diagnosticPage.render({canvasContext:diagnostic.getContext('2d'),viewport}).promise
 await document.fonts.ready
 const labels=[...svg.querySelectorAll('[data-pdf-measure-label]')].map(label=>{
  context.font=`9px ${pdfFont.systemFontInfo?.css??`"${pdfFont.loadedName}"`}`;const pdfAdvance=context.measureText(label.textContent).width,pdfCanvasFont=context.font
  context.font=`9px "${fontName}"`;const assetAdvance=context.measureText(label.textContent).width,assetCanvasFont=context.font
  const box=label.getBBox(),matrix=label.transform.baseVal.consolidate().matrix
  const corners=[[box.x,box.y],[box.x+box.width,box.y],[box.x,box.y+box.height],[box.x+box.width,box.y+box.height]].map(([x,y])=>new DOMPoint(x,y).matrixTransform(matrix))
  const xs=corners.map(p=>p.x),ys=corners.map(p=>p.y)
  return {label:label.textContent,matrix:[matrix.a,matrix.b,matrix.c,matrix.d,matrix.e,matrix.f],inkBox:[Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)],svgAdvance:label.getComputedTextLength(),assetAdvance,pdfAdvance,pdfCanvasFont,assetCanvasFont,fontSize:getComputedStyle(label).fontSize,family:getComputedStyle(label).fontFamily,kerning:getComputedStyle(label).fontKerning,ligatures:getComputedStyle(label).fontVariantLigatures}
 })
 const caret=svg.querySelector('[data-pdf-drawing="caret"]')
 const fontAsset=await(await fetch('/reports/v1/editor/assets/pdfjs/standard_fonts/LiberationSans-Regular.ttf')).arrayBuffer()
 const fontSha256=[...new Uint8Array(await crypto.subtle.digest('SHA-256',fontAsset))].map(x=>x.toString(16).padStart(2,'0')).join('')
 return {rotation,zoom,width:viewport.width,height:viewport.height,viewport:viewport.transform,labels,labelOnlyPng:diagnostic.toDataURL('image/png').split(',')[1],caret:{path:caret.getAttribute('d'),fill:caret.getAttribute('fill'),stroke:caret.getAttribute('stroke')},pdfFont:{name:pdfFont.name,loadedName:pdfFont.loadedName,systemFontInfo:{css:pdfFont.systemFontInfo?.css,loadedName:pdfFont.systemFontInfo?.loadedName},fontExtraProperties:Object.keys(pdfFont)},fontSha256,loadedFaces:[...document.fonts].map(font=>({family:font.family,status:font.status})),evidence}
}
window.drawingReady=true
}
