import type {NativeOperation} from './native-draft'
import type {PdfPageIdentity,PdfTextObject} from './pdf-operations'

export interface PdfTextThumbnailItem {str:string;dir:string;transform:number[];width:number;height:number;fontName:string}
export interface PdfTextThumbnailStyle {fontFamily:string;ascent?:number;descent?:number;vertical?:boolean}
export interface PdfTextReplacementPreview {text:string;box:{left:number;top:number;width:number;height:number};cover:{left:number;top:number;width:number;height:number};fontSize:number;fontFamily:string;fillColor?:[number,number,number];color?:[number,number,number];paper:string;align:'left'|'center'|'right';alignItems:'center'|'flex-end';lineHeight:string;bold:boolean;italic:boolean}
type PdfViewport={width:number;height:number;convertToViewportPoint:(x:number,y:number)=>number[]}
type Args={sourceSha256:string;operation:NativeOperation;page:PdfPageIdentity;target:PdfTextObject;textItems:PdfTextThumbnailItem[];styles:Record<string,PdfTextThumbnailStyle>;viewport:PdfViewport;measureText:(text:string,font:string)=>number}
const replacementFonts={arial:"Arial, 'Helvetica Neue', sans-serif",times:"'Times New Roman', Times, serif",courier:"'Courier New', monospace"} as const

function viewportBox(rect:readonly number[],viewport:PdfViewport){
 const [x1,y1,x2,y2]=rect,corners=[[x1!,y1!],[x1!,y2!],[x2!,y1!],[x2!,y2!]].map(([x,y])=>viewport.convertToViewportPoint(x!,y!))
 const xs=corners.map(point=>point[0]!),ys=corners.map(point=>point[1]!),left=Math.min(...xs),top=Math.min(...ys)
 return {left,top,width:Math.max(...xs)-left,height:Math.max(...ys)-top}
}

export function pdfTextReplacementThumbnailGeometry({sourceSha256,operation,page,target,textItems,styles,viewport,measureText}:Args):PdfTextReplacementPreview|null{
 if(operation.kind!=='replaceText'||operation.pageId!==page.pageId||operation.sourceSha256!==undefined&&operation.sourceSha256!==sourceSha256||page.pageId!==`sha256:${sourceSha256}:page:${page.index}`||![0,90,180,270].includes(((page.rotation%360)+360)%360))return null
 if(operation.objectId!==target.objectId||operation.expectedTextSha256!==target.expectedTextSha256||typeof operation.newText!=='string'||!operation.newText||/[\r\n]/.test(operation.newText)||operation.styleRuns!==undefined||operation.colorRuns!==undefined)return null
 if(!target.fillColor&&!Array.isArray(operation.color))return null
 if(operation.font!==undefined&&(typeof operation.font!=='string'||!Object.hasOwn(replacementFonts,operation.font))||operation.align!==undefined&&!['left','center','right'].includes(String(operation.align)))return null
 if(target.rect.length!==4||target.rect.some(value=>!Number.isFinite(value))||target.rect[2]<=target.rect[0]||target.rect[3]<=target.rect[1])return null
 const candidates=textItems.filter(item=>item.str===target.text&&item.dir==='ltr'&&item.transform.length===6&&item.transform.every(Number.isFinite)&&item.width>0&&item.height>0&&Number.isFinite(item.width)&&Number.isFinite(item.height)&&item.transform[0]!>0&&item.transform[3]!>0&&Math.abs(item.transform[1]!)<.001&&Math.abs(item.transform[2]!)<.001)
 if(candidates.length!==1)return null
 const item=candidates[0]!,style=styles[item.fontName]
 if(!style||style.vertical||typeof style.fontFamily!=='string'||!style.fontFamily)return null
 const targetBox=viewportBox(target.rect,viewport),itemFontSize=Math.hypot(item.transform[0]!,item.transform[1]!),baselinePdf=[item.transform[4]!,item.transform[5]!],ascent=style.ascent??.8,descent=style.descent??-.2
 const layoutRect=[baselinePdf[0]!,baselinePdf[1]!+itemFontSize*descent,baselinePdf[0]!+item.width,baselinePdf[1]!+itemFontSize*ascent]
 const layoutPdf={left:Math.min(layoutRect[0]!,layoutRect[2]!),bottom:Math.min(layoutRect[1]!,layoutRect[3]!),right:Math.max(layoutRect[0]!,layoutRect[2]!),top:Math.max(layoutRect[1]!,layoutRect[3]!)}
 const layoutBox=viewportBox([layoutPdf.left,layoutPdf.bottom,layoutPdf.right,layoutPdf.top],viewport)
 const overlap=Math.max(0,Math.min(targetBox.left+targetBox.width,layoutBox.left+layoutBox.width)-Math.max(targetBox.left,layoutBox.left))*Math.max(0,Math.min(targetBox.top+targetBox.height,layoutBox.top+layoutBox.height)-Math.max(targetBox.top,layoutBox.top))
 if(overlap<targetBox.width*targetBox.height*.5)return null
 const fontSize=Number(operation.fontSize??target.fontSize)
 if(!Number.isFinite(fontSize)||fontSize<1||fontSize>200)return null
 const font=typeof operation.font==='string'&&Object.hasOwn(replacementFonts,operation.font)?replacementFonts[operation.font as keyof typeof replacementFonts]:style.fontFamily
 const cssFont=[operation.italic===true||operation.italic===undefined&&/italic|oblique/i.test(target.fontName)?'italic':'',operation.bold===true||operation.bold===undefined&&/bold|black|heavy/i.test(target.fontName)?'700':'',`${fontSize*.92}px`,font].filter(Boolean).join(' ')
 const measuredWidth=measureText(operation.newText,cssFont),width=measuredWidth>layoutBox.width?measuredWidth+2:layoutBox.width
 const coverPdf=[Math.min(layoutPdf.left,target.rect[0]!),Math.min(layoutPdf.bottom,target.rect[1]!),Math.max(layoutPdf.right,target.rect[2]!),Math.max(layoutPdf.top,target.rect[3]!)]
 const coverBox=viewportBox(coverPdf,viewport),cover={left:coverBox.left-1.5,top:coverBox.top-1.5,width:coverBox.width+3,height:coverBox.height+3}
 const align=operation.align==='center'||operation.align==='right'?operation.align:'left'
 const fillColor=target.fillColor
 const color=Array.isArray(operation.color)&&operation.color.length===3?operation.color.map(value=>Math.round(Number(value)*255)) as [number,number,number]:undefined
 const paper='#fff'
 const ink=color??(fillColor&&Math.abs(pdfTextThumbnailLuminance(fillColor)-pdfTextThumbnailLuminance([255,255,255]))>.15?fillColor:[17,17,17])
 const renderedFontSize=fontSize*.92,box={left:layoutBox.left,top:layoutBox.top,width,height:layoutBox.height}
 let alignItems:'center'|'flex-end'='center'
 if(renderedFontSize+2>box.height){const grown=Math.ceil(renderedFontSize)+2;box.top-=grown-box.height;box.height=grown;alignItems='flex-end'}
 return {text:operation.newText,box,cover,fontSize:renderedFontSize,fontFamily:font,fillColor,color:ink.map(value=>Math.round(value)) as [number,number,number],paper,align,alignItems,lineHeight:typeof operation.lineLeading==='number'?`${operation.lineLeading}px`:'1',bold:operation.bold===true||operation.bold===undefined&&/bold|black|heavy/i.test(target.fontName),italic:operation.italic===true||operation.italic===undefined&&/italic|oblique/i.test(target.fontName)}
}

export function pdfTextThumbnailRgb(color:readonly number[]){return `rgb(${color.map(value=>Math.round(value)).join(', ')})`}
export function pdfTextThumbnailLuminance(color:readonly number[]){return (0.2126*color[0]!+0.7152*color[1]!+0.0722*color[2]!)/255}
export function pdfTextThumbnailInk(fillColor:[number,number,number]|undefined,paper:[number,number,number],override:[number,number,number]|undefined){
 return override??(fillColor&&Math.abs(pdfTextThumbnailLuminance(fillColor)-pdfTextThumbnailLuminance(paper))>.15?fillColor:[17,17,17])
}

export function pdfTextReplacementThumbnailStyles(preview:PdfTextReplacementPreview,viewport:PdfViewport):{cover:Record<string,string>;text:Record<string,string>}{
 const percent=(value:number,total:number)=>`${value/total*100}%`
 const text:Record<string,string>={position:'absolute',left:percent(preview.box.left,viewport.width),top:percent(preview.box.top,viewport.height),width:percent(preview.box.width,viewport.width),height:percent(preview.box.height,viewport.height),fontSize:`${preview.fontSize/viewport.width*100}cqw`,fontFamily:preview.fontFamily,color:pdfTextThumbnailRgb(preview.color??[17,17,17]),background:preview.paper,display:'flex',alignItems:preview.alignItems,overflow:'hidden',whiteSpace:'pre',lineHeight:preview.lineHeight,textAlign:preview.align,pointerEvents:'none'}
 if(preview.bold)text.fontWeight='700'
 if(preview.italic)text.fontStyle='italic'
 if(preview.align==='center')text.justifyContent='center'
 else if(preview.align==='right')text.justifyContent='flex-end'
 const cover={position:'absolute',left:percent(preview.cover.left,viewport.width),top:percent(preview.cover.top,viewport.height),width:percent(preview.cover.width,viewport.width),height:percent(preview.cover.height,viewport.height),background:preview.paper,pointerEvents:'none'}
 return {cover,text}
}
