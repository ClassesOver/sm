/** Fixed GenOffice f8c17004 DrawLayer drawingShape: SVG adapter, no vendored edits. */
import type { NativeOperation } from './native-draft'
import { imageViewBox, type ImageViewport } from './pdf-image-gesture'
const NS='http://www.w3.org/2000/svg'
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
      const [x,y]=point(operation.point as number[]) as [number,number]
      append('path',{d:`M${x-8} ${y+6} L${x} ${y} L${x+8} ${y+6}`,'stroke-linecap':'round','stroke-linejoin':'round'},true)
    } else {
      const [fx,fy]=point(operation.from as number[]) as [number,number],[tx,ty]=point(operation.to as number[]) as [number,number]
      append('line',{x1:fx,y1:fy,x2:tx,y2:ty,'stroke-linecap':'round'},true)
      if(shape==='arrow') {
        const angle=Math.atan2(ty-fy,tx-fx),length=Math.max(9*scale,w*4.5)
        for(const offset of [-.45,.45]){const head=append('line',{x1:tx,y1:ty,x2:tx-length*Math.cos(angle+offset),y2:ty-length*Math.sin(angle+offset),'stroke-linecap':'round'});if(!hit)head.dataset.pdfArrowHead=''}
      }
      if(shape==='measure'&&!hit) {
        let angle=Math.atan2(ty-fy,tx-fx)*180/Math.PI;if(Math.abs(angle)>90)angle+=180
        const x=(fx+tx)/2,y=(fy+ty)/2-6*scale
        const label=append('text',{x,y,fill:rgb,stroke:'none','font-size':Math.max(9,9*scale),'text-anchor':'middle',transform:`rotate(${angle} ${x} ${y})`})
        label.dataset.pdfMeasureLabel='';label.textContent=String(operation.label)
      }
    }
  }
  if(shape!=='link')build(true)
  build(false)
}
