/** 固定源 f8c17004 annotations.ts 坐标函数与 App.tsx:4114 排列公式；仅计算矩形，写入仍用 applyFormWidgetEdits。 */
export interface PageGeom {
  pw: number
  ph: number
  rot: number
  /** CropBox lower-left in PDF user space. */
  x0?: number
  y0?: number
  /** PDF /UserUnit; layout coordinates use this multiplier while PDF APIs use raw units. */
  userUnit?: number
}

const normRot = (r: number) => ((r % 360) + 360) % 360

/** Display size (scale=1; width/height swap with rotation) */
export function geomDispSize(g: PageGeom): { width: number; height: number } {
  return normRot(g.rot) % 180 === 0 ? { width: g.pw, height: g.ph } : { width: g.ph, height: g.pw }
}

/** Display coords (origin at page top-left, y down, scale=1) → PDF user space (y up) */
export function viewToPdf(g: PageGeom, vx: number, vy: number): [number, number] {
  const x0 = g.x0 ?? 0
  const y0 = g.y0 ?? 0
  const unit = g.userUnit ?? 1
  const pw = g.pw / unit
  const ph = g.ph / unit
  vx /= unit
  vy /= unit
  switch (normRot(g.rot)) {
    case 90:
      return [x0 + vy, y0 + vx]
    case 180:
      return [x0 + pw - vx, y0 + vy]
    case 270:
      return [x0 + pw - vy, y0 + ph - vx]
    default:
      return [x0 + vx, y0 + ph - vy]
  }
}

/** PDF user space → display coords (scale=1) */
export function pdfToView(g: PageGeom, x: number, y: number): [number, number] {
  x -= g.x0 ?? 0
  y -= g.y0 ?? 0
  const unit = g.userUnit ?? 1
  const pw = g.pw / unit
  const ph = g.ph / unit
  let result: [number, number]
  switch (normRot(g.rot)) {
    case 90:
      result = [y, x]
      break
    case 180:
      result = [pw - x, y]
      break
    case 270:
      result = [ph - y, pw - x]
      break
    default:
      result = [x, ph - y]
  }
  return [result[0] * unit, result[1] * unit]
}

/** PDF-space rect [x1,y1,x2,y2] → displayed pixel box (scaled) */
export function pdfRectToCss(
  g: PageGeom,
  rect: readonly [number, number, number, number],
  scale: number,
): { left: number; top: number; width: number; height: number } {
  const [ax, ay] = pdfToView(g, rect[0], rect[1])
  const [bx, by] = pdfToView(g, rect[2], rect[3])
  return {
    left: Math.min(ax, bx) * scale,
    top: Math.min(ay, by) * scale,
    width: Math.abs(bx - ax) * scale,
    height: Math.abs(by - ay) * scale,
  }
}

export const FORM_ARRANGEMENTS=['left','centerH','right','top','centerV','bottom','distributeH','distributeV','sameWidth','sameHeight','sameSize'] as const
export type FormArrangement=typeof FORM_ARRANGEMENTS[number]
export function arrangeDesignRects(geom:PageGeom,rects:[number,number,number,number][],how:FormArrangement){
 const boxes=rects.map(rect=>pdfRectToCss(geom,rect,1)),anchor=boxes[0],minL=Math.min(...boxes.map(b=>b.left)),maxR=Math.max(...boxes.map(b=>b.left+b.width)),minT=Math.min(...boxes.map(b=>b.top)),maxB=Math.max(...boxes.map(b=>b.top+b.height)),next=boxes.map(b=>({...b}))
 switch(how){
  case 'left':next.forEach(b=>b.left=minL);break
  case 'right':next.forEach(b=>b.left=maxR-b.width);break
  case 'top':next.forEach(b=>b.top=minT);break
  case 'bottom':next.forEach(b=>b.top=maxB-b.height);break
  case 'centerH':next.forEach(b=>b.left=(minL+maxR)/2-b.width/2);break
  case 'centerV':next.forEach(b=>b.top=(minT+maxB)/2-b.height/2);break
  case 'sameWidth':next.forEach(b=>b.width=anchor.width);break
  case 'sameHeight':next.forEach(b=>b.height=anchor.height);break
  case 'sameSize':next.forEach(b=>{b.width=anchor.width;b.height=anchor.height});break
  case 'distributeH':case 'distributeV':{const horizontal=how==='distributeH',order=next.map((_,i)=>i).sort((i,j)=>horizontal?next[i].left-next[j].left:next[i].top-next[j].top),total=next.reduce((sum,b)=>sum+(horizontal?b.width:b.height),0),gap=((horizontal?maxR-minL:maxB-minT)-total)/(next.length-1);let cursor=horizontal?minL:minT;for(const i of order){const b=next[i];if(horizontal)b.left=cursor;else b.top=cursor;cursor+=(horizontal?b.width:b.height)+gap}break}
 }
 const size=geomDispSize(geom)
 return next.map(b=>{const width=Math.min(b.width,size.width),height=Math.min(b.height,size.height),left=Math.min(Math.max(b.left,0),size.width-width),top=Math.min(Math.max(b.top,0),size.height-height),[ax,ay]=viewToPdf(geom,left,top),[bx,by]=viewToPdf(geom,left+width,top+height);return [Math.min(ax,bx),Math.min(ay,by),Math.max(ax,bx),Math.max(ay,by)] as [number,number,number,number]})
}
