import { Fragment } from 'react'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { SlidesFormatColorWell } from './slides-chart-format-pane'
import type { BrushSource } from './slides-format-brush'
import './slides-shape-format-pane.css'

type Stroke = { color: string; widthPt: number }
type Style = { slideIndex: number; elementId: string; fill?: string; stroke?: Stroke | null }
type Draft = { shapeStyles?: Style[] }
type Context<T extends Draft> = { slideIndex: number; element?: { id: string; type: string; brushSource?: BrushSource }; changes: T; reason?: string }
const commands = new Set(['shapeFill','shapeNoFill','shapeOutline','shapeOutlineWidth','shapeNoOutline','shapeResetFill','shapeResetStroke'])
const hex = (value: unknown): value is string => typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value)
const equal = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
function values<T extends Draft>(context: Context<T>) {
  const source = context.element?.brushSource?.supported ? context.element.brushSource.shape : undefined
  const patch = context.changes.shapeStyles?.find(item => item.slideIndex === context.slideIndex && item.elementId === context.element?.id)
  return { source, patch, fill: patch?.fill ?? source?.fill, stroke: patch?.stroke !== undefined ? patch.stroke : source?.stroke }
}
/** 旧像素编辑器保留原行为；原生调用方先核对独立的来源能力，再构建相同wire。 */
export function shapeStyleForCommand(command: string, value: unknown, previous: Style): Style | undefined {
  const style = { ...previous }, outline = style.stroke ?? { color:'#000000',widthPt:1 }
  if (command === 'shapeFill') { if (!hex(value)) return; style.fill = value.toUpperCase() }
  else if (command === 'shapeNoFill') style.fill = 'none'
  else if (command === 'shapeOutline') { if (!hex(value)) return; style.stroke = { ...outline,color:value.toUpperCase() } }
  else if (command === 'shapeOutlineWidth') { const width = Number(value); if (!Number.isFinite(width) || !(width > 0 && width <= 100)) return; style.stroke = { ...outline,widthPt:width } }
  else if (command === 'shapeNoOutline') style.stroke = null
  else return
  return style
}
/** 单次候选保留其他样式及正文；只对明确简单摘要开放，不借显示默认值覆盖复杂轮廓。 */
export function planSlidesShapeStyle<T extends Draft>(context: Context<T>, command: string, value?: unknown): T | undefined {
  if (!commands.has(command)) return
  const element = context.element
  if (context.reason) throw new Error(context.reason)
  if (!element || !['text','shape'].includes(element.type) || element.brushSource?.supported !== true) throw new Error('此来源对象暂不支持安全修改形状格式')
  const { source, patch, fill, stroke } = values(context), field = command.includes('Fill') ? 'fill' : 'stroke'
  const reset = command.startsWith('shapeReset')
  if (!reset && (field === 'fill' ? fill : stroke) === undefined) throw new Error(field === 'fill' ? '来源填充未能安全摘要；渐变、图片或透明填充保持只读' : '来源轮廓未能安全摘要；虚线、箭头、透明色或继承缺省保持只读')
  const next: Style = { ...patch,slideIndex:context.slideIndex,elementId:element.id }
  if (reset) delete next[field]
  else {
    const merged = shapeStyleForCommand(command,value,{...next,...(stroke !== undefined ? {stroke:stroke ?? source?.stroke ?? null} : {})})
    if (!merged) throw new Error(field === 'fill' ? '填充颜色请输入六位十六进制颜色' : '轮廓颜色须为六位颜色，粗细须大于0且不超过100磅')
    if (field === 'fill') next.fill = merged.fill
    else next.stroke = merged.stroke
    if (equal(next[field],source?.[field])) delete next[field]
  }
  if (next.fill === patch?.fill && equal(next.stroke,patch?.stroke)) return
  const styles = [...(context.changes.shapeStyles ?? []).filter(item => item.slideIndex !== context.slideIndex || item.elementId !== element.id)]
  if (next.fill !== undefined || next.stroke !== undefined) styles.push(next)
  if (styles.length > 500) throw new Error('形状样式修改已达到500项，请先保存')
  if (equal(styles,context.changes.shapeStyles ?? [])) return
  const changes = { ...context.changes }
  if (styles.length) changes.shapeStyles = styles; else delete changes.shapeStyles
  return changes
}

/** 固定源FormatPane的安全子集；共享原生颜色图库，保留宿主单笔历史及保存前flush。 */
export function createSlidesShapeFormatPane<T extends Draft>(getContext: () => Context<T>, onConfirm: (changes: T) => void, ribbonHost?: HTMLElement) {
  const element = document.createElement('section'); element.className = 'slides-shape-format-pane'; element.setAttribute('aria-label','填充与轮廓'); element.hidden = true
  const root = createRoot(element)
  let context: Context<T>, pending: T | undefined, timer: ReturnType<typeof setTimeout> | undefined, generation = 0, locked = false, disposed = false, error = '', widthDraft: string | undefined
  const cancel = () => { clearTimeout(timer); timer = undefined; pending = undefined; widthDraft = undefined; error = '' }
  const target = (c: Context<T>) => `${c.slideIndex}:${c.element?.id}`
  const valid = (version: number) => !disposed && !locked && version === generation && !getContext().reason && target(getContext()) === target(context) && equal(getContext().changes,context.changes)
  const invalidWidth = () => widthDraft !== undefined && (!widthDraft.trim() || !Number.isFinite(Number(widthDraft)) || !(Number(widthDraft) > 0 && Number(widthDraft) <= 100))
  function flush(): boolean {
    clearTimeout(timer); timer = undefined
    if (disposed || locked || !context) return true
    if (invalidWidth()) { error = '轮廓粗细须大于0且不超过100磅'; render(); return false }
    if (!pending) return true
    if (!valid(generation)) { update(); return false }
    const changes = pending; pending = undefined
    try { onConfirm(changes); error = ''; return true }
    catch (cause) { pending = changes; error = cause instanceof Error ? cause.message : '形状格式未能应用，请重试'; render(); return false }
  }
  function queue(command: string, value: unknown, version: number) {
    if (!valid(version)) return
    try {
      const changes = planSlidesShapeStyle({...context,changes:pending ?? context.changes},command,value)
      if (changes) pending = equal(changes.shapeStyles ?? [],context.changes.shapeStyles ?? []) ? undefined : changes
      error = ''; clearTimeout(timer); render()
      if (pending) timer = setTimeout(flush,200)
    } catch (cause) { error = (cause as Error).message; render() }
  }
  function render() {
    const version = generation, selected = context?.element && ['text','shape'].includes(context.element.type)
    element.hidden = !selected
    const effective = context && { ...context,changes:pending ?? context.changes }, current = effective && values(effective)
    const disabled = locked || !!context?.reason || context?.element?.brushSource?.supported !== true
    flushSync(() => root.render(selected && current ? <Fragment key={target(context)}>
      <h3>填充与轮廓</h3>
      {(['fill','stroke'] as const).map(field => {
        const value = current[field], none = field === 'fill' ? value === 'none' : value === null, unavailable = disabled || value === undefined
        const label = field === 'fill' ? '填充' : '轮廓', sourceStroke = current.source?.stroke
        const color = field === 'fill' ? (current.fill === 'none' ? '#4472C4' : current.fill) : current.stroke?.color ?? sourceStroke?.color ?? '#000000'
        return <section key={field}><h4>{label}</h4>
          <label className="shape-radio"><input type="radio" name={`${target(context)}:${field}`} data-shape-none={field} checked={none} disabled={unavailable} onChange={() => queue(field === 'fill' ? 'shapeNoFill' : 'shapeNoOutline',undefined,version)} />无{field === 'fill' ? '填充' : '线条'}</label>
          <label className="shape-radio"><input type="radio" name={`${target(context)}:${field}`} checked={value !== undefined && !none} disabled={unavailable} onChange={() => queue(field === 'fill' ? 'shapeFill' : 'shapeOutline',color,version)} />{field === 'fill' ? '纯色填充' : '实线'}</label>
          <div className="shape-color-row"><span>颜色</span><SlidesFormatColorWell point={`shape-${field}`} value={color ?? '#4472C4'} label={`${label}颜色`} disabled={unavailable} onPick={value => queue(field === 'fill' ? 'shapeFill' : 'shapeOutline',value,version)} />
          <button type="button" data-shape-reset={field} disabled={disabled || current.patch?.[field] === undefined} onClick={() => { widthDraft = undefined; queue(field === 'fill' ? 'shapeResetFill' : 'shapeResetStroke',undefined,version) }}>恢复来源</button></div>
          {field === 'stroke' && <label className="shape-width">粗细<input type="number" data-shape-width aria-label="轮廓粗细（磅）" min="0.01" max="100" step="0.25" value={widthDraft ?? (current.stroke?.widthPt !== undefined ? String(current.stroke.widthPt) : '')} disabled={unavailable || none} onChange={event => { if (!valid(version)) return; widthDraft = event.target.value; if (invalidWidth()) { clearTimeout(timer); error = '轮廓粗细须大于0且不超过100磅'; render() } else queue('shapeOutlineWidth',widthDraft,version) }} onKeyDown={event => { if(event.key === 'Enter') {event.preventDefault();flush()} if(event.key === 'Escape') {widthDraft=undefined;error='';render()} }} />磅</label>}
          {value === undefined && <p>{label}来源未能安全摘要，复杂样式保持只读</p>}
        </section>
      })}
      <p role="status">{context.reason || (disabled ? '此来源对象暂不支持安全修改形状格式' : error)}</p>
    </Fragment> : null))
  }
  function update() {
    if (disposed) return
    cancel(); ++generation; context = getContext(); render()
    syncRibbon()
  }
  function syncRibbon() {
    const current = values(context)
    for (const [command,field,value] of [['shapeFill','fill',current.fill === 'none' ? '' : current.fill],['shapeNoFill','fill',''],['shapeOutline','stroke',current.stroke?.color],['shapeNoOutline','stroke',''],['shapeOutlineWidth','stroke',current.stroke?.widthPt === undefined ? '' : String(current.stroke.widthPt)]] as const) {
      for (const control of ribbonHost?.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLButtonElement>(`[data-command="${command}"]`) ?? []) {
        const unavailable = locked || !!context.reason || context.element?.brushSource?.supported !== true || current[field] === undefined
        control.disabled = unavailable; control.title = unavailable ? `来源${field === 'fill' ? '填充' : '轮廓'}暂不支持安全修改` : ''
        if (control instanceof HTMLInputElement || control instanceof HTMLSelectElement) {
          if (control instanceof HTMLSelectElement) {
            control.querySelector('[data-shape-source-width]')?.remove()
            if(value && ![...control.options].some(option=>option.value === value)) {const option=new Option(`${value} 磅`,value);option.dataset.shapeSourceWidth='';control.append(option)}
          }
          control.value = value ?? ''
        }
      }
    }
  }
  return {
    element,update,flush,
    command(command: string,value?: unknown) { if (!flush()) return; if (!valid(generation)) return; queue(command,value,generation); flush() },
    setLocked(value: boolean) { if (disposed) return; cancel(); ++generation; locked=value; context=getContext(); render();syncRibbon() },
    dispose() { if (disposed) return; disposed=true;cancel();++generation;flushSync(()=>root.unmount());element.remove() },
  }
}
