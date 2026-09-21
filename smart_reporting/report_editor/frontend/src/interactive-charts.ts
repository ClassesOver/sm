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

export function createInteractiveCharts(
  root: HTMLElement,
  charts: Record<string, string>,
  basePath: string,
  dependencies: ChartDependencies = {},
) {
  const plotlyUrl = `${basePath}/asset/`
  const active = new Map<HTMLImageElement, { node: HTMLElement; plot: PlotlyRenderer; resize?: ResizeObserver }>()
  const pending = new Set<HTMLImageElement>()
  const failed = new WeakSet<HTMLImageElement>()
  let destroyed = false
  const fetcher = dependencies.fetcher ?? fetch
  const loadPlotly = dependencies.loadPlotly ?? (async () => (await import('plotly.js-dist-min')).default)

  function position(image: HTMLImageElement, node: HTMLElement) {
    const box = image.getBoundingClientRect()
    node.style.left = `${box.left + window.scrollX}px`
    node.style.top = `${box.top + window.scrollY}px`
    node.style.width = `${box.width}px`
    node.style.height = `${box.height}px`
  }

  function reposition() {
    for (const [image, entry] of active) {
      if (root.contains(image)) position(image, entry.node)
      else cleanup(image)
    }
  }
  window.addEventListener('scroll', reposition, { passive: true })
  window.addEventListener('resize', reposition)

  function cleanup(image: HTMLImageElement) {
    const entry = active.get(image)
    if (!entry) return
    entry.resize?.disconnect()
    entry.plot.purge(entry.node)
    entry.node.remove()
    image.classList.remove('interactive-chart-fallback')
    active.delete(image)
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
        const response = await fetcher(`${plotlyUrl}${spec.split('/').map(encodeURIComponent).join('/')}`, { credentials: 'same-origin' })
        if (!response.ok) return
        const figure = await response.json() as PlotlyFigure
        if (!Array.isArray(figure.data) || figure.data.length === 0) return
        const plot = await loadPlotly()
        if (destroyed || !root.contains(image)) return
        position(image, node)
        document.body.append(node)
        await plot.newPlot(node, figure.data, figure.layout, { ...figure.config, responsive: true })
        if (destroyed || !root.contains(image)) {
          plot.purge(node)
          node.remove()
          return
        }
        image.classList.add('interactive-chart-fallback')
        const resize = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(() => {
          position(image, node)
          plot.Plots.resize(node)
        })
        resize?.observe(image)
        active.set(image, { node, plot, resize })
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
      window.removeEventListener('scroll', reposition)
      window.removeEventListener('resize', reposition)
      for (const image of active.keys()) cleanup(image)
    },
  }
}
