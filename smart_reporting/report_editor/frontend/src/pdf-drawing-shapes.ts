/** Fixed GenOffice f8c17004 drawing gestures; local SVG previews follow saved AP geometry. */
import type { NativeOperation } from './native-draft'
import { imageViewBox, type ImageViewport } from './pdf-image-gesture'
import './pdf-drawing-font.css'
const NS='http://www.w3.org/2000/svg'
const num=(value:number)=>Math.round(value*100)/100
export const CANVAS_DRAWING_KINDS=new Set(['image','rect','ellipse','arrow','measure','ink','polygon','caret','link'])
export function paintDrawing(group: SVGGElement, operation: NativeOperation, viewport: ImageViewport, scale: number) {
  group.replaceChildren()
  const rgb=`rgb(${(operation.color as number[]).map(n=>Math.round(n*255)).join(',')})`
  const point=(value:number[])=>viewport.convertToViewportPoint(value[0]!,value[1]!)
  const shape=String(operation.shape)
  if(shape==='image') {
    const image=document.createElementNS(NS,'image'),box=imageViewBox(operation.rect as number[],viewport)
    for(const [key,value]of Object.entries(box))image.setAttribute(key,String(value))
    image.setAttribute('href',`data:image/png;base64,${operation.image}`);image.setAttribute('preserveAspectRatio','none');image.dataset.pdfDrawing='image';image.dataset.pdfImageIndex=group.dataset.pdfShapeIndex
    group.append(image);return
  }
  const build=(hit:boolean)=>{
    const stroke=hit?'transparent':rgb,w=shape==='caret'?(hit?16:1.5):hit?Math.max(16,Number(operation.width)*scale*4):Number(operation.width)*scale
    const append=(tag:string,attributes:Record<string,string|number>,primary=false)=>{
      const element=document.createElementNS(NS,tag)
      for(const [key,value]of Object.entries({fill:'none',stroke,'stroke-width':w,...attributes}))element.setAttribute(key,String(value))
      if(hit)element.dataset.pdfShapeHit=''
      else if(primary)element.dataset.pdfDrawing=shape
      group.append(element);return element
    }
    if(shape==='rect'||shape==='ellipse'||shape==='link') {
      const box=imageViewBox(operation.rect as number[],viewport)
      const attrs:Record<string,string|number>=shape==='ellipse'?{cx:box.x+box.width/2,cy:box.y+box.height/2,rx:box.width/2,ry:box.height/2}:{...box}
      const element=append(shape==='ellipse'?'ellipse':'rect',attrs,true)
      if(shape==='link'){element.setAttribute('stroke-dasharray','5 3');const title=document.createElementNS(NS,'title');title.textContent=operation.url!==undefined?String(operation.url):`跳转到原第 ${operation.destPage} 页`;element.append(title)}
    } else if(shape==='ink') {
      for(const path of operation.paths as number[][]) {
        const points:string[]=[];for(let i=0;i<path.length;i+=2)points.push(point([path[i]!,path[i+1]!]).join(','))
        append('polyline',{points:points.join(' '),'stroke-linecap':'round','stroke-linejoin':'round'},true)
      }
    } else if(shape==='polygon')append('polygon',{points:(operation.vertices as number[][]).map(v=>point(v).join(',')).join(' '),'stroke-linejoin':'round'},true)
    else if(shape==='caret') {
      const [x,y]=operation.point as number[]
      const vertices=[[num(x!),num(y!)],[num(x!-8),num(y!-6)],[num(x!+8),num(y!-6)]].map(point)
      const d=vertices.map((v,i)=>`${i?'L':'M'}${v[0]} ${v[1]}`).join(' ')+' Z'
      append('path',{d,fill:hit?'none':rgb,stroke:hit?'transparent':'none','stroke-linejoin':'round'},true)
    } else {
      const [fx,fy]=point(operation.from as number[]) as [number,number],[tx,ty]=point(operation.to as number[]) as [number,number]
      append('line',{x1:fx,y1:fy,x2:tx,y2:ty,'stroke-linecap':'round'},true)
      if(shape==='arrow') {
        const angle=Math.atan2(ty-fy,tx-fx),length=Math.max(9*scale,w*4.5)
        for(const offset of [-.45,.45]){const head=append('line',{x1:tx,y1:ty,x2:tx-length*Math.cos(angle+offset),y2:ty-length*Math.sin(angle+offset),'stroke-linecap':'round'});if(!hit)head.dataset.pdfArrowHead=''}
      }
      if(shape==='measure'&&!hit) {
        const from=operation.from as number[],to=operation.to as number[],angle=Math.atan2(to[1]!-from[1]!,to[0]!-from[0]!),tilt=Math.abs(angle)>Math.PI/2?angle+Math.PI:angle
        const a=num(Math.cos(tilt)),b=num(Math.sin(tilt)),c=num(-Math.sin(tilt)),d=num(Math.cos(tilt)),e=num((from[0]!+to[0]!)/2),f=num((from[1]!+to[1]!)/2+6)
        // Native Tm → PDF.js viewport → SVG glyph space (whose y points down).
        const origin=point([e,f]),u=point([e+a,f+b]),down=point([e-c,f-d])
        const matrix=[u[0]!-origin[0]!,u[1]!-origin[1]!,down[0]!-origin[0]!,down[1]!-origin[1]!,...origin]
        const label=append('text',{x:0,y:0,fill:rgb,stroke:'none','font-size':9,'font-family':'PDF Standard Helvetica, Liberation Sans, Helvetica, Arial, sans-serif','dominant-baseline':'alphabetic','text-anchor':'start',transform:`matrix(${matrix.join(' ')})`})
        label.style.fontKerning='none';label.style.fontVariantLigatures='none';label.style.textRendering='geometricPrecision'
        label.dataset.pdfMeasureLabel='';label.textContent=String(operation.label)
      }
    }
  }
  if(shape!=='link')build(true)
  build(false)
}
