import type {ChartReadSpec} from '@sheets-web/xlsx-engine'
import {numfmt} from '@univerjs/core'
import type {UniverRenderingContext} from '@univerjs/engine-render'
import type {Plot} from './chart-legend'
import {valueTickText} from './chart-value-axis'

export type BarLabelDatum = {value:number; index:number; seriesIndex:number; zero:number; end:number; rect:Plot}
const overlaps = (a:Plot,b:Plot) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top
const contains = (outer:Plot,inner:Plot) => inner.left >= outer.left && inner.right <= outer.right && inner.top >= outer.top && inner.bottom <= outer.bottom

function labelText(value:number,explicit:string|undefined,inherited:string|undefined):string {
  const code = explicit && explicit !== 'General' ? explicit : inherited
  if (code && code !== 'General') {
    try {
      const text = numfmt.format(code,value,{throws:false})
      // Empty sections deliberately suppress labels (e.g. a hidden zero),
      // so an empty valid result must not fall back to the raw number.
      if (typeof text === 'string') return text.trim()
    } catch { /* Preserve a readable value for an invalid external format. */ }
  }
  return valueTickText(value)
}

/** Paint after every bar. Keep explicit point indices, the original live value
 * of clipped bars and the same growth direction as their actual geometry.
 * Omit a label that cannot fit intact; never shorten a number to make it fit.
 */
export function paintBarDataLabels(ctx:UniverRenderingContext,spec:ChartReadSpec,points:ReadonlyArray<BarLabelDatum>,plot:Plot,stacked=false):void {
  if (points.length > 500) return
  const horizontal = spec.kind === 'bar', painted: Plot[] = []
  ctx.save();ctx.font = '11px system-ui';ctx.textAlign = 'left';ctx.textBaseline = 'middle'
  ctx.beginPath();ctx.rect(plot.left,plot.top,plot.right-plot.left,plot.bottom-plot.top);ctx.clip()
  for (const point of points) {
    const series = spec.series[point.seriesIndex]!
    const layers = [spec.dataLabels,series.dataLabels,spec.dataLabels?.points?.[point.index],series.dataLabels?.points?.[point.index]]
    if (layers.some(layer=>layer?.unsupported)) continue
    const setting = Object.assign({},...layers)
    if (!setting.showValue || setting.deleted) continue
    const style = Object.assign({},...layers.map(layer=>layer?.style))
    const fontSize = style.sizePt === undefined ? 11 : style.sizePt*4/3
    if (!(fontSize > 0) || !Number.isFinite(fontSize)) continue
    ctx.font = `${style.bold ? 'bold ' : ''}${fontSize}px system-ui`
    const text = labelText(point.value,setting.numberFormat,series.numberFormat)
    if (!text) continue
    const metrics = ctx.measureText(text), width = metrics.width
    const measured = Number.isFinite(metrics.actualBoundingBoxAscent) && Number.isFinite(metrics.actualBoundingBoxDescent)
    const ascent = measured ? metrics.actualBoundingBoxAscent : fontSize*6/11
    const descent = measured ? metrics.actualBoundingBoxDescent : fontSize*6/11
    const height = ascent+descent
    if (!(height > 0) || !Number.isFinite(height)) continue
    if (!(width > 0) || !Number.isFinite(width)) continue
    const zero = point.value === 0
    const position = stacked ? 'center' : zero ? 'outside-end' : setting.position ?? 'outside-end'
    const inside = position !== 'outside-end'
    const centerX = (point.rect.left+point.rect.right)/2, centerY = (point.rect.top+point.rect.bottom)/2
    const direction = point.end === point.zero ? (horizontal ? 1 : -1)*(spec.axes?.value.scaling?.reversed ? -1 : 1) : Math.sign(point.end-point.zero)
    let left = centerX-width/2, top = centerY-height/2
    if (position !== 'center') {
      if (horizontal) left = inside ? direction > 0 ? point.end-4-width : point.end+4 : direction > 0 ? point.end+4 : point.end-4-width
      else top = inside ? direction > 0 ? point.end-4-height : point.end+4 : direction > 0 ? point.end+4 : point.end-4-height
    }
    const box = {left,top,right:left+width,bottom:top+height}
    if (!contains(plot,box)) continue
    if (inside && !contains({left:point.rect.left+2,top:point.rect.top+2,right:point.rect.right-2,bottom:point.rect.bottom-2},box)) continue
    if (painted.some(other=>overlaps(box,other))) continue
    if (points.some(other=>other!==point && other.rect.right > other.rect.left && other.rect.bottom > other.rect.top && overlaps(box,other.rect))) continue
    ctx.fillStyle = style.color ?? (inside && !stacked ? '#ffffff' : '#1f2328')
    ctx.fillText(text,left,top+ascent)
    painted.push(box)
  }
  ctx.restore()
}

export function paintLineDataLabels(ctx:UniverRenderingContext,spec:ChartReadSpec,points:ReadonlyArray<{value:number;index:number;seriesIndex:number;x:number;y:number}>,plot:Plot):void {
  if(points.length>500)return
  const painted:Plot[]=[]
  ctx.save();ctx.textBaseline='middle'
  for(const point of points){
    const series=spec.series[point.seriesIndex]!
    const layers=[spec.dataLabels,series.dataLabels,spec.dataLabels?.points?.[point.index],series.dataLabels?.points?.[point.index]]
    if(layers.some(layer=>layer?.unsupported))continue
    const setting=Object.assign({},...layers)
    if(!setting.showValue||setting.deleted)continue
    const style=Object.assign({},...layers.map(layer=>layer?.style))
    const fontSize=style.sizePt===undefined?11:style.sizePt*4/3
    if(!(fontSize>0)||!Number.isFinite(fontSize))continue
    ctx.font=`${style.bold?'bold ':''}${fontSize}px system-ui`
    const text=labelText(point.value,setting.numberFormat,series.numberFormat)
    if(!text)continue
    const metrics=ctx.measureText(text),width=metrics.width
    const ascent=Number.isFinite(metrics.actualBoundingBoxAscent)?metrics.actualBoundingBoxAscent:fontSize*6/11
    const descent=Number.isFinite(metrics.actualBoundingBoxDescent)?metrics.actualBoundingBoxDescent:fontSize*6/11
    const height=ascent+descent
    if(!(width>0&&height>0)||![width,height].every(Number.isFinite))continue
    const position=setting.position??'center'
    const x=Math.max(plot.left+width/2,Math.min(plot.right-width/2,point.x))
    const top=position==='center'?point.y-height/2:position==='inside-end'?point.y-height-2:point.y-height-4
    const box={left:x-width/2,right:x+width/2,top,bottom:top+height}
    if(!contains(plot,box)||painted.some(other=>overlaps(box,other)))continue
    if(points.some(other=>other!==point&&Math.abs(other.x-point.x)<1&&Math.abs(other.y-point.y)<1&&overlaps(box,{left:other.x-2,right:other.x+2,top:other.y-2,bottom:other.y+2})))continue
    ctx.fillStyle=style.color??'#1f2328';ctx.textAlign='center';ctx.fillText(text,x,top+ascent);painted.push(box)
  }
  ctx.restore()
}
