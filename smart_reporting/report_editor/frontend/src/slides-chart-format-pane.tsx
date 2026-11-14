import { Fragment, useLayoutEffect, useRef, useState, type InputHTMLAttributes } from 'react'
import { createRoot } from 'react-dom/client'
import { createPortal, flushSync } from 'react-dom'
import { ColorPicker } from './vendor/genoffice-slides/ui/color-picker'
import { armColorInput } from './vendor/genoffice-slides/color-input'
import type { NativeChartKind, NativeChartData } from './slides-native-chart-edit'
import type { ChartPointColors } from '../../../reporting/slides_engine/bridge/pptx-chart-data'
import './slides-chart-format-pane.css'

export type SlidesChartFormatState = NativeChartData & { target: string; kind: NativeChartKind; pointColors: ChartPointColors; seriesColors?: (string | null)[]; reason?: string }
const palette = ['#4472C4', '#ED7D31', '#A5A5A5', '#FFC000', '#5B9BD5', '#70AD47']
function fallback(state: SlidesChartFormatState, si: number, pi: number) {
  return ['pie', 'pie3D', 'doughnut'].includes(state.kind) ? palette[pi % palette.length]!
    : state.seriesColors?.[si % (state.seriesColors.length || 1)] ?? palette[si % palette.length]!
}

/** 固定源 ColorWell 的宿主适配：共享图库原样复用，原生弹窗保持挂载，浮层进入top-layer。 */
export function SlidesFormatColorWell({ point, value, label, disabled, onPick }: { point: string; value: string; label: string; disabled: boolean; onPick: (color: string) => void }) {
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const [popup] = useState(() => {
    const element = document.createElement('div'); element.className = 'slides-chart-point-palette'
    element.dataset.chartFormatPalette = ''; element.setAttribute('popover', 'manual'); element.setAttribute('role', 'dialog'); element.setAttribute('aria-label', label)
    // 在 Portal 注册 React 委托前安装冒泡守卫，也尊重目标控件刚消费的按键；固定源图库保持原样。
    element.addEventListener('keydown', event => {
      if ((event.isComposing || event.keyCode === 229 || event.defaultPrevented) && ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key)) event.stopImmediatePropagation()
    })
    return element
  })
  useLayoutEffect(() => {
    if (disabled) { setOpen(false); return }
    if (!open) return
    document.body.append(popup); popup.showPopover?.()
    const button = trigger.current!, anchor = button.getBoundingClientRect(), box = popup.getBoundingClientRect()
    popup.style.left = `${Math.max(8, Math.min(anchor.right - box.width, innerWidth - box.width - 8))}px`
    popup.style.top = `${Math.max(8, Math.min(anchor.bottom + 4, innerHeight - box.height - 8))}px`
    const position = () => { const rect = button.getBoundingClientRect(); return [rect.left, rect.top, innerWidth, innerHeight, scrollX, scrollY].join(',') }
    const openedPosition = position()
    const outside = (event: Event) => { if (event.target instanceof Node && !popup.contains(event.target) && !button.contains(event.target)) setOpen(false) }
    const escape = (event: KeyboardEvent) => { if (event.isComposing || event.keyCode === 229 || event.defaultPrevented) return; if (event.key === 'Escape') { event.preventDefault(); setOpen(false); button.focus({ preventScroll: true }) } }
    const move = (event: Event) => { if (!(event.target instanceof Node && popup.contains(event.target)) && position() !== openedPosition) setOpen(false) }
    window.addEventListener('pointerdown', outside, true); window.addEventListener('keydown', escape)
    window.addEventListener('resize', move); window.addEventListener('scroll', move, true)
    popup.querySelector<HTMLElement>('[tabindex="0"]')?.focus({ preventScroll: true })
    return () => {
      window.removeEventListener('pointerdown', outside, true); window.removeEventListener('keydown', escape)
      window.removeEventListener('resize', move); window.removeEventListener('scroll', move, true)
      popup.hidePopover?.(); popup.remove()
    }
  }, [open, disabled, popup])
  return <span className="fp-color-well-wrap">
    <button ref={trigger} type="button" className="fp-color-well" data-chart-format-well={point} aria-label={label} aria-haspopup="dialog" aria-expanded={open} disabled={disabled}
      onClick={() => setOpen(value => !value)} onKeyDown={event => { if (event.nativeEvent.isComposing || event.keyCode === 229 || event.defaultPrevented) return; if (event.key === 'ArrowDown') { event.preventDefault(); setOpen(true) } }}>
      <span className="fp-color-well-swatch" style={{ background: value }} />
      <span className="fp-color-well-caret" aria-hidden="true"><svg width="11" height="11" viewBox="0 0 24 24" fill="none"><path d="M5.5 9.25 12 15.75l6.5-6.5" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" /></svg></span>
    </button>
    {open && !disabled && createPortal(<ColorPicker value={value} strings={{ themeColors: '主题颜色', standardColors: '标准色', moreColors: '更多颜色…' }}
      onPick={hex => { const restoreFocus = popup.contains(document.activeElement); if (hex) onPick(hex); setOpen(false); if (restoreFocus) trigger.current?.focus({ preventScroll: true }) }}
      moreInputProps={{ 'aria-label': label, 'data-chart-format-custom': point,
        onPointerDown: event => armColorInput(event.currentTarget), onChange: event => onPick(event.currentTarget.value) } as InputHTMLAttributes<HTMLInputElement>} />, popup)}
  </span>
}

/** 复用FormatPane的数据点分组；颜色patch仍走宿主已有校验、历史和保存链路。 */
export function createSlidesChartFormatPane(onConfirm: (points: ChartPointColors, target: string) => void) {
  const element = document.createElement('section'); element.className = 'slides-chart-format-pane'; element.setAttribute('aria-label', '设置图表格式'); element.hidden = true
  const root = createRoot(element)
  let state: SlidesChartFormatState | null = null, locked = false, disposed = false, generation = 0, error = ''
  let pending: ChartPointColors = {}, timer: ReturnType<typeof setTimeout> | undefined
  const cancel = () => { clearTimeout(timer); timer = undefined; pending = {} }
  function flush(): boolean {
    clearTimeout(timer); timer = undefined
    if (disposed || locked || !state || !Object.keys(pending).length) return true
    const points = pending; pending = {}
    try { onConfirm(points, state.target); error = ''; return true }
    catch (cause) { pending = points; error = cause instanceof Error ? cause.message : '单点配色未能应用，请重试'; render(); return false }
  }
  function render() {
    element.hidden = !state
    const current = state, version = generation
    const reason = current?.reason || (current?.kind === 'scatter' ? '固定源散点图不支持单点颜色写入' : '')
    const pick = (si: number, pi: number, color: string | null) => {
      if (disposed || locked || reason || !state || version !== generation) return
      const normalized = color?.toUpperCase() ?? null
      if (normalized === (current?.pointColors[si]?.[pi] ?? null)) {
        delete pending[si]?.[pi]; if (!Object.keys(pending[si] ?? {}).length) delete pending[si]
      } else (pending[si] ??= {})[pi] = normalized
      clearTimeout(timer); error = ''; render()
      if (Object.keys(pending).length) timer = setTimeout(flush, 200)
    }
    flushSync(() => root.render(current ? <Fragment key={current.target}>
      <header><h3 className="chart-format-heading">设置图表格式</h3></header>
      <div className="chart-format-body">
      <div className="fp-section">填充与线条</div>
      {reason ? <p role="status">{reason}</p> : <>
        <div className="fp-section">数据点颜色</div>
        {current.series.map((series, si) => <fieldset key={si}>
          <legend className="fp-chart-series">{series.name || `系列 ${si + 1}`}</legend>
          {series.values.map((_, pi) => {
            const category = current.categories[pi] || `#${pi + 1}`
            const override = Object.hasOwn(pending[si] ?? {}, pi) ? pending[si]![pi] : current.pointColors[si]?.[pi]
            return <div className="fp-row fp-chart-point" key={pi}>
              <SlidesFormatColorWell key={category} point={`${si}:${pi}`} value={override ?? fallback(current, si, pi)} label={`系列 ${si + 1} ${category} 颜色`} disabled={locked} onPick={color => pick(si, pi, color)} />
              <span className="fp-chart-point-label" title={category}>{category}</span>
              <button type="button" className="chart-point-reset" data-chart-format-reset={`${si}:${pi}`} disabled={locked || !override} onClick={() => pick(si, pi, null)} aria-label={`恢复系列 ${si + 1} ${category} 配色`}>恢复</button>
            </div>
          })}
        </fieldset>)}
      </>}
      <p role="alert" className="chart-format-error">{error}</p>
      </div>
    </Fragment> : null))
  }
  return {
    element,
    update(next: SlidesChartFormatState | null, nextLocked = false) { if (disposed) return; cancel(); ++generation; state = next; locked = nextLocked; error = ''; render() },
    setLocked(value: boolean) { if (disposed) return; cancel(); ++generation; locked = value; render() },
    flush,
    dispose() { if (disposed) return; disposed = true; cancel(); ++generation; flushSync(() => root.unmount()); element.remove() },
  }
}
