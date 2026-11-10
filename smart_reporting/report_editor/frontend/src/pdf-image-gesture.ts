/** Fixed GenOffice f8c17004 DrawLayer.tsx shape/handle gestures adapted to PDF.js.
 * The viewport owns CropBox/UserUnit/rotation; no separate rotation formula. */
import type { NativeOperation } from './native-draft'
import { pendingDrawingTarget, movePendingDrawing, resizePendingImage, type PendingDrawingReference, type PendingImageAnchor } from './pdf-pending-drawings'
import type { PdfPageIdentity } from './pdf-operations'
export interface ImageViewport { width: number; height: number; convertToViewportPoint(x: number, y: number): number[]; convertToPdfPoint(x: number, y: number): number[] }
export interface ImageBox { x: number; y: number; width: number; height: number }
export type ImagePoint = readonly [number, number]
export function imageViewBox(rect: number[], viewport: ImageViewport): ImageBox {
  const a = viewport.convertToViewportPoint(rect[0]!, rect[1]!), b = viewport.convertToViewportPoint(rect[2]!, rect[3]!)
  return { x: Math.min(a[0]!,b[0]!), y: Math.min(a[1]!,b[1]!), width: Math.abs(b[0]!-a[0]!), height: Math.abs(b[1]!-a[1]!) }
}
export function imageClientPoint(point: ImagePoint, bounds: ImageBox, viewport: ImageViewport): ImagePoint {
  if (![...point,bounds.x,bounds.y,bounds.width,bounds.height,viewport.width,viewport.height].every(Number.isFinite) || bounds.width <= 0 || bounds.height <= 0 || viewport.width <= 0 || viewport.height <= 0) throw Error('图像视口已变化，请重新选择')
  return [(point[0]-bounds.x)*viewport.width/bounds.width,(point[1]-bounds.y)*viewport.height/bounds.height]
}
export function imageGesturePlan(rect: number[], viewport: ImageViewport, bounds: ImageBox, start: ImagePoint, end: ImagePoint, corner?: number) {
  const from=imageClientPoint(start,bounds,viewport),to=imageClientPoint(end,bounds,viewport)
  if(corner===undefined) {
    if(Math.hypot(end[0]-start[0],end[1]-start[1])<3)return undefined
    const a=viewport.convertToPdfPoint(...from),b=viewport.convertToPdfPoint(...to),dx=b[0]!-a[0]!,dy=b[1]!-a[1]!
    return {kind:'move' as const,dx,dy,rect:[rect[0]!+dx,rect[1]!+dy,rect[2]!+dx,rect[3]!+dy]}
  }
  if(!Number.isInteger(corner)||corner<0||corner>3)throw Error('图像控制柄身份无效')
  if(start[0]===end[0]&&start[1]===end[1])return undefined
  const box=imageViewBox(rect,viewport),fx=corner%2===0?box.x+box.width:box.x,fy=corner<2?box.y+box.height:box.y
  const cssWidth=box.width*bounds.width/viewport.width,cssHeight=box.height*bounds.height/viewport.height
  const factor=Math.max(Math.abs(to[0]-fx)/box.width,Math.abs(to[1]-fy)/box.height,16/Math.max(cssWidth,cssHeight))
  if(!Number.isFinite(factor))throw Error('图像缩放范围无效')
  if(Math.abs((factor-1)*cssWidth)<2&&Math.abs((factor-1)*cssHeight)<2)return undefined
  const fixed=viewport.convertToPdfPoint(fx,fy)
  const anchor:PendingImageAnchor=`${Math.abs(fixed[1]!-rect[1]!)<Math.abs(fixed[1]!-rect[3]!)?'bottom':'top'}-${Math.abs(fixed[0]!-rect[0]!)<Math.abs(fixed[0]!-rect[2]!)?'left':'right'}`
  const w=(rect[2]!-rect[0]!)*factor,h=(rect[3]!-rect[1]!)*factor,x=anchor.endsWith('left')?rect[0]!:rect[2]!-w,y=anchor.startsWith('bottom')?rect[1]!:rect[3]!-h
  return {kind:'resize' as const,factor,anchor,rect:[x,y,anchor.endsWith('left')?rect[0]!+w:rect[2]!,anchor.startsWith('bottom')?rect[1]!+h:rect[3]!]}
}
export function imageGestureOperations(pages: PdfPageIdentity[], operations: NativeOperation[], reference: PendingDrawingReference, viewport: ImageViewport, bounds: ImageBox, start: ImagePoint, end: ImagePoint, corner?: number): NativeOperation[] | undefined {
  const {operation}=pendingDrawingTarget(pages,operations,reference)
  if(operation.shape!=='image')throw Error('只有待保存图像可使用画布控制柄')
  const plan=imageGesturePlan(operation.rect as number[],viewport,bounds,start,end,corner)
  return !plan?undefined:plan.kind==='move'?movePendingDrawing(pages,operations,reference,plan.dx,plan.dy):resizePendingImage(pages,operations,reference,plan.factor,plan.anchor)
}
