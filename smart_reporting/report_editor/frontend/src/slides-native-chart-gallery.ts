import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import type { ChartStyleInfo } from '@genoffice/pptx-render'
import { CHART_STYLE_PRESETS, type ChartColorScheme } from '../../../reporting/slides_engine/bridge/pptx-chart-design'
import type { NativeChartKind } from './slides-native-chart-edit'
import { ChartStyleThumb, chartPresetActive } from './vendor/genoffice-slides/components/chart-style-preview'
import './slides-native-chart-gallery.css'

export type NativeChartGalleryState = { target: string; kind: NativeChartKind; style: Omit<ChartStyleInfo, 'kind'>; colorSchemes: ChartColorScheme[] }
const english = ['Classic', 'Grid', 'Data Labels', 'Labels + Grid', 'Minimal', 'Minimal Labels', 'Wide Bars', 'Thin Bars', 'Legend on Top', 'Legend on Right']

/** 固定源缩略图/匹配器，宿主只适配状态、命令和原生top-layer配色面板。 */
export function createNativeChartGallery(host: HTMLElement, onAction: (command: string, value: string) => void) {
  const root = document.createElement('div'); root.className = 'slides-native-chart-gallery'
  const toggle = document.createElement('button'); toggle.type = 'button'; toggle.dataset.chartColorsToggle = ''; toggle.dataset.sourceAction = 'onEditChart'
  toggle.textContent = /^zh\b/i.test(document.documentElement.lang) ? '更改颜色 ▾' : 'Change Colors ▾'
  toggle.setAttribute('aria-expanded', 'false'); toggle.setAttribute('aria-haspopup', 'dialog')
  const row = document.createElement('div'); row.className = 'rb-chart-style-row'; row.setAttribute('aria-label', '图表样式图库')
  root.append(toggle, row); host.append(root)
  const menu = document.createElement('div'); menu.className = 'slides-native-chart-colors'; menu.dataset.chartColorsMenu = ''; menu.hidden = true
  menu.setAttribute('popover', 'manual'); menu.setAttribute('role', 'dialog'); menu.setAttribute('aria-label', '图表配色图库')
  document.body.append(menu)
  let state: NativeChartGalleryState | null = null, locked = false, opened = false, disposed = false
  let openedPosition = ''
  function position() {
    const { left, top, width, height } = toggle.getBoundingClientRect()
    return [left, top, width, height, innerWidth, innerHeight, scrollX, scrollY].join(',')
  }
  const close = (focus = false) => {
    if (!opened) return
    menu.hidePopover?.(); menu.hidden = true; opened = false; toggle.setAttribute('aria-expanded', 'false')
    if (focus) toggle.focus()
  }
  const cards = CHART_STYLE_PRESETS.map((preset, index) => {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'rb-chart-style-card'
    button.dataset.chartPresetCard = preset.key; button.dataset.sourceAction = 'onEditChart'
    const label = /^zh\b/i.test(document.documentElement.lang) ? preset.label : english[index]!
    button.title = label; button.setAttribute('aria-label', label)
    button.addEventListener('click', () => { if (!disposed && state && !locked) onAction('chartStylePreset', preset.key) })
    row.append(button)
    return { button, preset, label }
  })
  function render() {
    close()
    toggle.disabled = disposed || locked || !state
    // 源render-tree把水平/百分比条形归到bar家族；适配宿主图库的两个别名。
    const info: ChartStyleInfo | null = state ? { ...state.style, kind: state.kind === 'barH' ? 'bar' : state.kind === 'barPercentStacked' ? 'barStacked' : state.kind } : null
    for (const { button, preset, label } of cards) {
      button.disabled = toggle.disabled
      const active = chartPresetActive(info, preset)
      button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active))
      button.innerHTML = renderToStaticMarkup(createElement(ChartStyleThumb, { kind: info?.kind, style: preset.style }))
      const caption = document.createElement('span'); caption.className = 'rb-chart-scheme-label'; caption.textContent = label; button.append(caption)
    }
  }
  function open() {
    if (disposed || locked || !state) return
    if (opened) { close(); return }
    const target = state.target
    menu.replaceChildren()
    for (const scheme of state.colorSchemes) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'rb-chart-scheme-card'
      button.dataset.chartSchemeCard = scheme.key; button.dataset.sourceAction = 'onEditChart'; button.title = scheme.label
      const swatches = document.createElement('span'); swatches.className = 'rb-chart-scheme-swatches'
      for (const color of scheme.colors.slice(0, 4)) { const dot = document.createElement('span'); dot.className = 'rb-chart-scheme-dot'; dot.style.backgroundColor = color; swatches.append(dot) }
      const label = document.createElement('span'); label.className = 'rb-chart-scheme-label'; label.textContent = scheme.label
      button.append(swatches, label)
      button.addEventListener('click', () => {
        if (disposed || !opened || locked || state?.target !== target) return
        close(true); onAction('chartColorScheme', scheme.key)
      })
      menu.append(button)
    }
    menu.hidden = false; menu.showPopover?.(); opened = true; toggle.setAttribute('aria-expanded', 'true')
    const anchor = toggle.getBoundingClientRect(), box = menu.getBoundingClientRect()
    menu.style.left = `${Math.max(8, Math.min(anchor.left, innerWidth - box.width - 8))}px`
    menu.style.top = `${Math.max(8, Math.min(anchor.bottom + 4, innerHeight - box.height - 8))}px`
    openedPosition = position()
    menu.querySelector('button')?.focus()
  }
  const outside = (event: Event) => { if (event.target instanceof Node && !menu.contains(event.target) && !toggle.contains(event.target)) close() }
  const dismiss = (event: KeyboardEvent) => { if (event.key === 'Escape') { event.preventDefault(); close(true) } }
  toggle.addEventListener('click', open)
  toggle.addEventListener('keydown', event => { if (event.key === 'ArrowDown') { event.preventDefault(); if (!opened) open() } })
  menu.addEventListener('keydown', dismiss)
  document.addEventListener('pointerdown', outside, true)
  // 只在实际位移后关闭；打开前的焦点滚动/resize事件可能延迟送达。
  window.addEventListener('resize', closeOnMove)
  window.addEventListener('scroll', closeOnMove, true)
  function closeOnMove(event: Event) {
    if (opened && !(event.target instanceof Node && menu.contains(event.target)) && position() !== openedPosition) close()
  }
  render()
  return {
    setState(value: NativeChartGalleryState | null) { state = value; render() },
    setLocked(value: boolean) { locked = value; render() },
    close,
    dispose() { close(); disposed = true; state = null; document.removeEventListener('pointerdown', outside, true); window.removeEventListener('resize', closeOnMove); window.removeEventListener('scroll', closeOnMove, true); menu.remove(); root.remove() },
  }
}
