interface PlotlyFigure {
  data: Record<string, unknown>[]
  layout?: Record<string, unknown>
  config?: Record<string, unknown>
}

export interface PlotlyRenderer {
  newPlot(node: HTMLElement, data: PlotlyFigure['data'], layout?: PlotlyFigure['layout'], config?: PlotlyFigure['config']): Promise<unknown>
  purge(node: HTMLElement): void
  Plots: { resize(node: HTMLElement): void }
}

interface ChartDependencies {
  fetcher?: typeof fetch
  loadPlotly?: () => Promise<PlotlyRenderer>
}

const CHART_FONT = '"Noto Sans CJK SC", "Noto Sans SC", "Microsoft YaHei", sans-serif'

function beautifyLayout(layout: PlotlyFigure['layout']): PlotlyFigure['layout'] {
  const merged: Record<string, unknown> = { ...layout }
  // 尺寸交给容器：figure 自带的固定 width/height 会让大图模态
  // 或容器尺寸变化时图表无法自适应，统一移除。
  delete merged.width
  delete merged.height
  delete merged.autosize
  // 字体跟随编辑器；figure 自带 font 的其它属性（字号、颜色）保留。
  merged.font = { family: CHART_FONT, ...(layout?.font ?? {}) }
  // 收紧默认边距，让图表在容器边框内不显得拥挤；figure 自带边距优先。
  merged.margin = { t: 56, r: 28, b: 52, l: 68, ...(layout?.margin ?? {}) }
  // 纸面与绘图区留白交给容器边框和圆角处理。
  merged.paper_bgcolor = merged.paper_bgcolor ?? '#ffffff'
  merged.plot_bgcolor = merged.plot_bgcolor ?? '#ffffff'
  return merged
}

function beautifyConfig(config: PlotlyFigure['config']): PlotlyFigure['config'] {
  return {
    displaylogo: false,
    displayModeBar: 'hover',
    ...config,
    responsive: true,
  }
}

function whenImageLoaded(image: HTMLImageElement): Promise<void> {
  return new Promise((resolve) => {
    if (image.complete) {
      resolve()
      return
    }
    const done = () => {
      image.removeEventListener('load', done)
      image.removeEventListener('error', done)
      resolve()
    }
    image.addEventListener('load', done)
    image.addEventListener('error', done)
  })
}

export function createInteractiveCharts(
  root: HTMLElement,
  charts: Record<string, string>,
  basePath: string,
  dependencies: ChartDependencies = {},
) {
  const plotlyUrl = `${basePath}/asset/`
  interface ActiveEntry {
    node: HTMLElement
    plot: PlotlyRenderer
    figure: PlotlyFigure
    resize?: ResizeObserver
  }
  const active = new Map<HTMLImageElement, ActiveEntry>()
  const pending = new Set<HTMLImageElement>()
  const failed = new WeakSet<HTMLImageElement>()
  let destroyed = false
  const fetcher = dependencies.fetcher ?? fetch
  const loadPlotly = dependencies.loadPlotly ?? (async () => (await import('plotly.js-dist-min')).default)

  function position(image: HTMLImageElement, node: HTMLElement) {
    const box = image.getBoundingClientRect()
    if (box.width <= 0 || box.height <= 0) return false
    node.style.left = `${box.left + window.scrollX}px`
    node.style.top = `${box.top + window.scrollY}px`
    node.style.width = `${box.width}px`
    node.style.height = `${box.height}px`
    return true
  }

  function reposition() {
    for (const [image, entry] of active) {
      if (root.contains(image)) position(image, entry.node)
      else cleanup(image)
    }
  }
  // 编辑器渐进渲染、字体加载、图片加载都会造成无事件触发的布局漂移，
  // 只用 scroll/resize 事件会在瞬态布局下留下错位的覆盖层。
  // 用 rAF 循环持续把覆盖层钉在图片上，无活动图表时自动停止。
  let rafId: number | undefined
  function tick() {
    reposition()
    if (destroyed || active.size === 0) {
      rafId = undefined
      return
    }
    rafId = requestAnimationFrame(tick)
  }
  function startTracking() {
    if (rafId === undefined && active.size > 0 && !destroyed) {
      rafId = requestAnimationFrame(tick)
    }
  }

  function cleanup(image: HTMLImageElement) {
    const entry = active.get(image)
    if (!entry) return
    entry.resize?.disconnect()
    entry.plot.purge(entry.node)
    entry.node.remove()
    active.delete(image)
  }

  function openExpanded(entry: ActiveEntry) {
    if (destroyed) return
    const overlay = document.createElement('div')
    overlay.className = 'interactive-chart-modal'
    overlay.setAttribute('role', 'dialog')
    overlay.setAttribute('aria-modal', 'true')
    overlay.setAttribute('aria-label', entry.node.getAttribute('aria-label') ?? '交互图表大图')
    const card = document.createElement('div')
    card.className = 'interactive-chart-modal-card'
    const closeButton = document.createElement('button')
    closeButton.type = 'button'
    closeButton.className = 'interactive-chart-modal-close'
    closeButton.setAttribute('aria-label', '关闭大图')
    closeButton.textContent = '×'
    const canvas = document.createElement('div')
    canvas.className = 'interactive-chart-modal-canvas'
    card.append(closeButton, canvas)
    overlay.append(card)
    const close = () => {
      entry.plot.purge(canvas)
      overlay.remove()
      document.removeEventListener('keydown', onKeydown)
      if (document.contains(entry.node)) entry.node.focus()
    }
    const onKeydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
    }
    document.addEventListener('keydown', onKeydown)
    overlay.addEventListener('click', (event) => {
      if (event.target === overlay) close()
    })
    closeButton.addEventListener('click', close)
    document.body.append(overlay)
    void entry.plot.newPlot(canvas, entry.figure.data, beautifyLayout(entry.figure.layout), beautifyConfig(entry.figure.config))
    closeButton.focus()
  }

  function attachExpandControl(entry: ActiveEntry) {
    const expand = document.createElement('button')
    expand.type = 'button'
    expand.className = 'interactive-chart-expand'
    expand.setAttribute('aria-label', '放大查看图表')
    expand.title = '放大查看'
    expand.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M16 3h3a2 2 0 0 1 2 2v3"/><path d="M8 21H5a2 2 0 0 1-2-2v-3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/></svg>'
    expand.addEventListener('click', () => openExpanded(entry))
    entry.node.append(expand)
    entry.node.tabIndex = 0
    entry.node.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        openExpanded(entry)
      }
    })
  }

  async function refresh() {
    if (destroyed) return
    const images = new Set(root.querySelectorAll<HTMLImageElement>('img'))
    for (const image of active.keys()) {
      if (!images.has(image)) cleanup(image)
      else position(image, active.get(image)!.node)
    }
    await Promise.all(Array.from(images, async (image) => {
      if (active.has(image) || pending.has(image) || failed.has(image)) return
      let source: URL
      try {
        source = new URL(image.src, window.location.href)
      } catch {
        return
      }
      if (source.origin !== window.location.origin || !source.pathname.startsWith(plotlyUrl)) return
      const assetPath = decodeURIComponent(source.pathname.slice(plotlyUrl.length))
      const matching = Object.entries(charts).filter(([path]) =>
        path === assetPath || (assetPath.indexOf('/') === -1 && path.endsWith(`/${assetPath}`)),
      )
      const spec = matching.length === 1 ? matching[0][1] : undefined
      if (!spec) return
      pending.add(image)
      failed.add(image)
      const node = document.createElement('div')
      node.className = 'interactive-chart'
      node.setAttribute('role', 'img')
      node.setAttribute('aria-label', image.alt || '交互图表')
      node.contentEditable = 'false'
      try {
        // 图片未加载完成时 rect 可能是 0 或占位尺寸，先等加载结束再测量。
        await whenImageLoaded(image)
        if (destroyed || !root.contains(image)) return
        const response = await fetcher(`${plotlyUrl}${spec.split('/').map(encodeURIComponent).join('/')}`, { credentials: 'same-origin' })
        if (!response.ok) return
        const figure = await response.json() as PlotlyFigure
        if (!Array.isArray(figure.data) || figure.data.length === 0) return
        const plot = await loadPlotly()
        if (destroyed || !root.contains(image)) return
        if (!position(image, node)) return
        // 覆盖层挂在 body 并以白底遮盖原图，完全不改动 ProseMirror 管理的
        // 编辑器 DOM（包括 img 的 class）：否则 ProseMirror 会把外部变更当成
        // 文档修改触发自动保存，或按文档模型重绘 img 形成“改 class → 重绘 →
        // 再改 class”的渲染循环，页面布局持续抖动、图表错位。
        document.body.append(node)
        await plot.newPlot(node, figure.data, beautifyLayout(figure.layout), beautifyConfig(figure.config))
        if (destroyed || !root.contains(image)) {
          plot.purge(node)
          node.remove()
          return
        }
        const resize = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(() => {
          if (position(image, node)) plot.Plots.resize(node)
        })
        resize?.observe(image)
        const entry = { node, plot, figure, resize }
        attachExpandControl(entry)
        active.set(image, entry)
        startTracking()
      } catch {
        node.remove()
      } finally {
        pending.delete(image)
      }
    }))
  }

  const observer = new MutationObserver(() => { void refresh() })
  observer.observe(root, { childList: true, subtree: true })
  return {
    refresh,
    destroy() {
      destroyed = true
      observer.disconnect()
      if (rafId !== undefined) {
        cancelAnimationFrame(rafId)
        rafId = undefined
      }
      for (const image of active.keys()) cleanup(image)
    },
  }
}
