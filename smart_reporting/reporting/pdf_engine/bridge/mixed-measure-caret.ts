/** Verify the pinned measure/caret APs, preserving their known UI/render differences. */
import {PDFArray,PDFDict,PDFDocument,PDFHexString,PDFName,PDFRawStream,PDFRef,PDFString,decodePDFRawStream} from 'pdf-lib'
import {measureLabelBounds} from '../src/main/measure-label-bounds'
interface MixedMeasuredDrawing {shape:'measure'|'caret';color:[number,number,number];width:number;from?:[number,number];to?:[number,number];point?:[number,number];label?:string}
const fail=(reason:string):never=>{throw Error('pdf_text_measure_caret_'+reason)}
const num=(value:number)=>Math.round(value*100)/100
const keys=(dict:PDFDict,allowed:string[])=>{if(dict.keys().some(key=>!allowed.includes(key.decodeText())))fail('output_unexpected_metadata')}
export function reviewMixedMeasureCaret(document:PDFDocument,pageIndex:number,annotation:PDFDict,operation:MixedMeasuredDrawing){
 const caret=operation.shape==='caret',page=document.getPage(pageIndex),[r,g,b]=operation.color
 keys(annotation,['Type','Subtype','Rect','C','F','P','AP','T',...(caret?[]:['BS','L','Contents'])])
 if(String(annotation.get(PDFName.of('Type')))!=='/Annot'||String(annotation.get(PDFName.of('Subtype')))!==(caret?'/Caret':'/Line')||String(annotation.get(PDFName.of('F')))!=='4'||String(annotation.get(PDFName.of('P')))!==String(page.ref)||String(annotation.get(PDFName.of('C')))!==document.context.obj(operation.color).toString())fail('output_identity_changed')
 let rect:number[],expected:string
 if(caret){
  const[x,y]=operation.point!;rect=[num(x-10),num(y-10),num(x+10),num(y+10)]
  expected=`${r} ${g} ${b} rg\n${num(x)} ${num(y)} m ${num(x-8)} ${num(y-6)} l ${num(x+8)} ${num(y-6)} l f`
 }else{
  const[fx,fy]=operation.from!,[tx,ty]=operation.to!,mx=(fx+tx)/2,my=(fy+ty)/2,angle=Math.atan2(ty-fy,tx-fx),tilt=Math.abs(angle)>Math.PI/2?angle+Math.PI:angle,c=Math.cos(tilt),s=Math.sin(tilt),pad=operation.width+2
  const bounds=measureLabelBounds(operation.from!,operation.to!,operation.label!)
  const xs=[fx,tx,num(fx),num(tx),bounds[0],bounds[2]],ys=[fy,ty,num(fy),num(ty),bounds[1],bounds[3]]
  rect=[Math.min(...xs)-pad,Math.min(...ys)-pad,Math.max(...xs)+pad,Math.max(...ys)+pad]
  const contents=annotation.lookup(PDFName.of('Contents')),border=annotation.lookup(PDFName.of('BS'),PDFDict);keys(border,['W'])
  if(!(contents instanceof PDFHexString||contents instanceof PDFString)||contents.decodeText()!==operation.label||String(annotation.get(PDFName.of('L')))!==document.context.obj([...operation.from!,...operation.to!]).toString()||String(border.get(PDFName.of('W')))!==String(operation.width))fail('output_measure_identity_changed')
  const escaped=operation.label!.replace(/\\/g,'\\\\').replace(/\(/g,'\\(').replace(/\)/g,'\\)')
  expected=`${num(operation.width)} w 1 J 1 j ${r} ${g} ${b} RG\n${num(fx)} ${num(fy)} m ${num(tx)} ${num(ty)} l S\nBT ${r} ${g} ${b} rg /F1 9 Tf\n${num(c)} ${num(s)} ${num(-s)} ${num(c)} ${num(mx)} ${num(my+6)} Tm\n(${escaped}) Tj ET`
 }
 const appearance=annotation.lookup(PDFName.of('AP'),PDFDict);keys(appearance,['N'])
 const ap=appearance.lookup(PDFName.of('N'));if(!(ap instanceof PDFRawStream))return fail('output_appearance_unreadable')
 keys(ap.dict,['Type','Subtype','BBox','Matrix','Length','Filter',...(caret?[]:['Resources'])])
 if(String(annotation.get(PDFName.of('Rect')))!==document.context.obj(rect).toString()||String(ap.dict.get(PDFName.of('BBox')))!==document.context.obj(rect).toString()||String(ap.dict.get(PDFName.of('Type')))!=='/XObject'||String(ap.dict.get(PDFName.of('Subtype')))!=='/Form')fail('output_bounds_changed')
 const matrix=ap.dict.lookup(PDFName.of('Matrix'))
 if(matrix!==undefined&&(!(matrix instanceof PDFArray)||String(matrix)!==document.context.obj([1,0,0,1,0,0]).toString()))fail('output_matrix_changed')
 if(!Buffer.from(decodePDFRawStream(ap).decode()).equals(Buffer.from(expected,'ascii')))fail('output_path_or_label_changed')
 if(!caret){
  const resources=ap.dict.lookup(PDFName.of('Resources'),PDFDict);keys(resources,['Font'])
  const fonts=resources.lookup(PDFName.of('Font'),PDFDict);keys(fonts,['F1'])
  if(!(fonts.get(PDFName.of('F1'))instanceof PDFRef))fail('output_font_reference_changed')
  const font=fonts.lookup(PDFName.of('F1'),PDFDict);keys(font,['Type','Subtype','BaseFont','Encoding'])
  if(String(font.get(PDFName.of('Type')))!=='/Font'||String(font.get(PDFName.of('Subtype')))!=='/Type1'||String(font.get(PDFName.of('BaseFont')))!=='/Helvetica'||String(font.get(PDFName.of('Encoding')))!=='/WinAnsiEncoding')fail('output_font_changed')
 }
}
