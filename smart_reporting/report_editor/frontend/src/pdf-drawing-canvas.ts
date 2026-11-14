/** Web SVG lifecycle adapter for fixed GenOffice f8c17004 DrawLayer shape gestures. */
import type { NativeOperation } from './native-draft'
import { validatePdfDrawing, type PdfPageIdentity } from './pdf-operations'
import { movePendingDrawing, translateDrawingGeometry, type PendingDrawingReference } from './pdf-pending-drawings'
import { imageViewBox, imageGestureOperations, imageGesturePlan, drawingDragDelta, type ImageBox, type ImagePoint, type ImageViewport } from './pdf-image-gesture'
import { CANVAS_DRAWING_KINDS, paintDrawing } from './pdf-drawing-shapes'
const NS='http://www.w3.org/2000/svg'
export interface DrawingCanvasController { sync(): boolean; cancel(): void; dispose(): void }
interface Options {
  host: HTMLElement; pages: PdfPageIdentity[]; pageId: string; operations: NativeOperation[]; viewport: ImageViewport
  scale?: number; imagesOnly?: boolean
  current(): boolean; unchanged?(): boolean; selected(): PendingDrawingReference | undefined
  select(reference: PendingDrawingReference): void; commit(operations: NativeOperation[]): void; error(error: unknown): void
}
/** One pointer transaction, one draft commit. Reflows and detached DOM cancel it. */
export function mountDrawingCanvas(options: Options): DrawingCanvasController {
  const {host,pages,pageId,operations,viewport}=options,snapshot=JSON.stringify(operations)
  const svg=document.createElementNS(NS,'svg');svg.setAttribute('class','pdf-pending-drawings pdf-image-canvas pdf-drawing-canvas');svg.setAttribute('width',String(viewport.width));svg.setAttribute('height',String(viewport.height))
  const records=new Map<number,SVGGElement>(),images=new Map<number,SVGImageElement>(),selection=document.createElementNS(NS,'g');selection.dataset.pdfImageSelection=''
  let disposed=false,controller:DrawingCanvasController
  type Gesture={ id:number; index:number; target:SVGElement; start:ImagePoint; end:ImagePoint; bounds:ImageBox; corner?:number }
  let gesture:Gesture|undefined
  const current=()=>!disposed&&svg.isConnected&&options.current()
  const reference=(index:number):PendingDrawingReference=>({index,pageId,snapshot})
  function paint(index:number,values=operations) {
    const group=records.get(index),op=values[index];if(!group||!op)return
    const image=images.get(index)
    if(image){const box=imageViewBox(op.rect as number[],viewport);for(const [key,value]of Object.entries(box))image.setAttribute(key,String(value))}
    else paintDrawing(group,op,viewport,options.scale??1)
  }
  function selectedIndex() {
    const ref=options.selected()
    return ref?.pageId===pageId&&ref.snapshot===snapshot&&records.has(ref.index)?ref.index:undefined
  }
  function handles(values=operations) {
    selection.replaceChildren()
    const index=selectedIndex();for(const [id,group]of records)group.classList.toggle('is-selected',id===index&&current())
    delete selection.dataset.pdfDrawingSelection
    if(index===undefined||!current())return
    selection.dataset.pdfDrawingSelection=String(index)
    if(!images.has(index))return
    const box=imageViewBox(values[index]!.rect as number[],viewport)
    const outline=document.createElementNS(NS,'rect')
    for(const [key,value]of Object.entries(box))outline.setAttribute(key,String(value))
    outline.setAttribute('class','pdf-image-outline');selection.append(outline)
    for(const corner of [0,1,2,3]) {
      const handle=document.createElementNS(NS,'circle');handle.dataset.pdfImageHandle=String(corner);handle.dataset.pdfImageIndex=String(index)
      handle.setAttribute('cx',String(box.x+(corner%2?box.width:0)));handle.setAttribute('cy',String(box.y+(corner<2?0:box.height)));handle.setAttribute('r','5');handle.setAttribute('class','pdf-image-handle')
      handle.setAttribute('aria-label',`图像${index+1}缩放角${corner+1}`)
      handle.style.cursor=corner===0||corner===3?'nwse-resize':'nesw-resize'
      handle.addEventListener('pointerdown',event=>stableDown(event,index,corner));selection.append(handle)
    }
  }
  function cancel() {
    const previous=gesture;gesture=undefined
    if(previous){paint(previous.index);try{previous.target.releasePointerCapture?.(previous.id)}catch{/* detached capture */}}
    handles()
  }
  // Capture lives on the stable SVG, never on handles that are repainted live.
  function stableDown(event:PointerEvent,index:number,corner?:number) {
    if(event.button!==0||!event.isPrimary||!current()||options.unchanged?.()===false||gesture)return
    event.preventDefault();event.stopPropagation();options.select(reference(index));if(!current())return
    const b=svg.getBoundingClientRect();gesture={id:event.pointerId,index,target:svg,start:[event.clientX,event.clientY],end:[event.clientX,event.clientY],bounds:{x:b.x,y:b.y,width:b.width,height:b.height},...(corner===undefined?{}:{corner})}
    try{svg.setPointerCapture?.(event.pointerId)}catch{cancel();return}
  }
  function valid(g:Gesture) {
    const b=svg.getBoundingClientRect()
    return current()&&Math.abs(b.x-g.bounds.x)<.1&&Math.abs(b.y-g.bounds.y)<.1&&Math.abs(b.width-g.bounds.width)<.1&&Math.abs(b.height-g.bounds.height)<.1
  }
  function proposed(g:Gesture) {if(g.corner!==undefined)return imageGestureOperations(pages,operations,reference(g.index),viewport,g.bounds,g.start,g.end,g.corner);const delta=drawingDragDelta(viewport,g.bounds,g.start,g.end);return delta?movePendingDrawing(pages,operations,reference(g.index),delta.dx,delta.dy):undefined}
  svg.addEventListener('pointermove',event=>{
    const g=gesture;if(!g||event.pointerId!==g.id)return
    event.preventDefault();event.stopPropagation()
    if(!valid(g)){cancel();return}g.end=[event.clientX,event.clientY]
    try{
      const op=operations[g.index]!,plan=g.corner===undefined?drawingDragDelta(viewport,g.bounds,g.start,g.end):imageGesturePlan(op.rect as number[],viewport,g.bounds,g.start,g.end,g.corner)
      let next=operations
      if(plan){const changed='kind' in plan?{...op,rect:plan.rect}:translateDrawingGeometry(op,plan.dx,plan.dy);validatePdfDrawing(changed,pages.find(page=>page.pageId===pageId)!.cropBox);next=[...operations];next[g.index]=changed}
      paint(g.index,next);handles(next)
    }catch{paint(g.index);handles()}
  })
  svg.addEventListener('pointerup',event=>{
    const g=gesture;if(!g||event.pointerId!==g.id)return
    event.preventDefault();event.stopPropagation();g.end=[event.clientX,event.clientY]
    if(!valid(g)||options.unchanged?.()===false){cancel();return}
    try{const next=proposed(g);cancel();if(next&&current())options.commit(next)}catch(error){cancel();options.error(error)}
  })
  const abort=new AbortController()
  for(const type of ['pointercancel','lostpointercapture'])svg.addEventListener(type,event=>{if(gesture?.id===(event as PointerEvent).pointerId)cancel()},{signal:abort.signal})
  window.addEventListener('blur',cancel,{signal:abort.signal});window.addEventListener('resize',cancel,{signal:abort.signal})
  for(const type of ['scroll','wheel'])document.addEventListener(type,cancel,{capture:true,passive:true,signal:abort.signal})
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!event.isComposing&&event.keyCode!==229&&!event.defaultPrevented)cancel()},{signal:abort.signal})
  for(const [index,operation]of operations.entries()) {
    const shape=String(operation.shape)
    if(operation.kind!=='addDrawing'||operation.pageId!==pageId||!CANVAS_DRAWING_KINDS.has(shape)||(options.imagesOnly&&shape!=='image'))continue
    const group=document.createElementNS(NS,'g');group.dataset.pdfShapeIndex=String(index);group.dataset.pdfShapeKind=shape
    paintDrawing(group,operation,viewport,options.scale??1)
    if(shape==='image')images.set(index,group.querySelector('image')!)
    if(shape!=='link')group.addEventListener('pointerdown',event=>stableDown(event,index))
    records.set(index,group);svg.append(group)
  }
  svg.append(selection);host.append(svg)
  controller={sync(){if(disposed)return false;if(!svg.isConnected){controller.dispose();return false}const enabled=current()&&options.unchanged?.()!==false;if(!enabled)cancel();svg.classList.toggle('is-interactive',enabled);handles();return true},cancel,dispose(){if(disposed)return;disposed=true;cancel();abort.abort();svg.remove()}}
  return controller
}
