import { createEvidenceGraph, mergeEvidenceGraph, graphRelations, type EvidenceGraph } from './evidence-graph'
import {
  ReportEditorApiError,
  type ReportEditorClient,
  type TraceChartSource,
  type TraceComputationDetail,
  type TraceFactDetail,
  type TracePreviewPage,
  type TraceSources,
  type TraceSubjectInfo,
  type TraceValidation,
} from './api'
import {
  assembleChartRelations,
  assembleComputationRelations,
  assembleDatasetRelations,
  assembleFactRelations,
  assembleSubjectRelations,
  bindEvidenceNavigation,
  renderRelationList,
  type EvidenceRelations,
} from './evidence-relations'
import { evidenceRefId, sameEvidenceRef, type EvidenceObjectKind, type EvidenceObjectRef, type EvidencePage } from './evidence-state'
import { markdownSha256 } from './source-validation'
import { ArrowRight, Calculator, ChartColumn, createElement, Database, Expand, ExternalLink, FileText, Hash, LocateFixed, Network, X, ZoomIn, ZoomOut } from 'lucide'

/**
 * 证据浏览器对象页渲染契约（证据浏览器 v6）。
 *
 * 渲染器职责：
 * - 使用 ctx.signal 发起请求；ctx.isStale() 为 true 时（已导航离开）不得再改写容器；
 * - 内容就绪后把焦点移到对象标题（h1[tabindex=-1]），并恢复 ctx.page.scroll；
 * - 对象页内的关系入口统一走 ctx.navigate / ctx.openBackground / ctx.setPreview，
 *   与图节点、关系列表行为一致；
 * - 服务端字段一律按纯文本渲染（textContent），不注入 HTML。
 */
export interface EvidencePageContext {
  client: ReportEditorClient
  page: EvidencePage
  graph?: EvidenceGraph
  taskLabel?: string
  signal: AbortSignal
  isStale: () => boolean
  revisionLabel: string
  downloadEnabled: boolean
  drilldownEnabled: boolean
  loadSources: () => Promise<TraceSources>
  /** 当前任务内导航到对象页。 */
  navigate: (ref: EvidenceObjectRef) => void
  /** 后台开启独立核对任务（Ctrl/⌘ + 单击、中键）。 */
  openBackground: (ref: EvidenceObjectRef, foreground?: boolean) => void
  /** 仅预览节点摘要，不改路径与历史。 */
  setPreview: (ref: EvidenceObjectRef | null) => void
  updatePage: (patch: Partial<Omit<EvidencePage, 'ref' | 'path'>>) => void
  /** 定位正文中的引用锚点。 */
  locateSubject: (subjectId: string) => void
  /** 当前草稿（引用状态校验用）；不可得时返回 null。 */
  getDraft: () => { markdown: string; sha256: string } | null
  /** 页面级数据缓存：历史返回时不重复请求。 */
  pageData: <T>() => T | undefined
  setPageData: (data: unknown) => void
}

// ---------------------------------------------------------------------------
// 文案字典与取值助手（与 trace-panel 同源，M4 删除面板前保持两份一致）
// ---------------------------------------------------------------------------

const KIND_LABELS: Record<EvidenceObjectKind, string> = {
  fact: '事实',
  computation: '计算',
  dataset: '快照',
  chart: '图表',
  subject: '引用',
}

const TRACE_ERROR_LABELS: Record<string, string> = {
  source_missing: '来源不存在或不在当前修订中',
  report_editor_session_expired: '编辑会话已过期，请从报告列表重新打开此报告',
  dataset_access_denied: '当前会话无权访问该数据',
  fact_binding_unavailable: '事实引用暂不可用，内容可能已变更',
  snapshot_expired: '数据快照已超过保留期',
  snapshot_integrity_failed: '文件完整性校验失败，已拒绝读取',
  cursor_invalid: '分页游标已失效，请重新打开预览',
  request_invalid: '请求参数无效',
  resource_limit_exceeded: '请求超出资源限制，请缩小范围',
  drilldown_unavailable: '该指标或维度未登记下钻能力',
}

const VERIFICATION_LABELS: Record<string, string> = {
  verified: '数值已核对',
  not_checked: '未做独立数值核对',
  failed: '独立核对未通过',
  not_applicable: '不适用于核对',
}

const REPRODUCIBILITY_LABELS: Record<string, string> = {
  reproducible: '具备复算条件',
  limited: '复算条件有限',
  unavailable: '无法复算',
}

const CITATION_STATUS_LABELS: Record<string, string> = {
  valid: '✓ 引用有效',
  stale: '△ 内容已变更',
  unbound: '未绑定',
}

const SUBJECT_KIND_LABELS: Record<string, string> = {
  text_claim: '文本取值',
  table_cell: '表格单元格',
  chart: '图表',
  chart_caption: '图表说明',
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function text(value: unknown): string {
  return value === null || value === undefined ? '—' : String(value)
}

function numeric(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value !== 'string' || !value.trim()) return null
  const parsed = Number(value.replaceAll(',', ''))
  return Number.isFinite(parsed) ? parsed : null
}



// ---------------------------------------------------------------------------
// 统一骨架：头部 → 状态区 → 关系区 → 详情区
// ---------------------------------------------------------------------------

interface PageSkeleton {
  title: HTMLHeadingElement
  statusBox: HTMLElement
  statusArea: HTMLElement
  relationSlot: HTMLElement
  detailBox: HTMLElement
}

function buildSkeleton(container: HTMLElement, ctx: EvidencePageContext, note: string): PageSkeleton {
  const header = document.createElement('header')
  header.className = 'evidence-object-header'
  const eyebrow = document.createElement('span')
  eyebrow.className = 'evidence-eyebrow'
  eyebrow.textContent = KIND_LABELS[ctx.page.ref.kind]
  const title = document.createElement('h1')
  title.className = 'evidence-object-title'
  title.tabIndex = -1
  title.textContent = ctx.page.ref.label
  const noteP = document.createElement('p')
  noteP.className = 'evidence-object-note'
  noteP.textContent = note
  header.append(eyebrow, title, noteP)
  const statusArea = document.createElement('div')
  statusArea.className = 'evidence-status-area'
  const statusBox = document.createElement('div')
  statusBox.className = 'evidence-status'
  statusBox.setAttribute('role', 'status')
  statusBox.setAttribute('aria-live', 'polite')
  statusBox.hidden = true
  statusArea.append(statusBox)
  const relationSlot = document.createElement('div')
  relationSlot.className = 'evidence-relation-slot'
  const detailBox = document.createElement('div')
  detailBox.className = 'evidence-detail'
  container.append(header, statusArea, relationSlot, detailBox)
  return { title, statusBox, statusArea, relationSlot, detailBox }
}

function finishRender(container: HTMLElement, ctx: EvidencePageContext, title: HTMLHeadingElement): void {
  title.focus()
  container.scrollTop = ctx.page.scroll
}

function showLoading(container: HTMLElement): void {
  const loading = document.createElement('p')
  loading.className = 'evidence-placeholder'
  loading.textContent = '对象详情加载中…'
  container.append(loading)
}

function errorInfo(error: unknown): { message: string; retryable: boolean } {
  if (error instanceof DOMException && error.name === 'AbortError') {
    return { message: '', retryable: false }
  }
  if (error instanceof ReportEditorApiError) {
    return {
      message: TRACE_ERROR_LABELS[error.code] ?? '来源加载失败，请稍后重试',
      retryable: error.status >= 500 || error.status === 0,
    }
  }
  return { message: '网络异常，来源加载失败', retryable: true }
}

/** 加载失败：保留头部，状态区给出稳定文案；仅服务器/网络故障提供重试。 */
function renderPageError(container: HTMLElement, ctx: EvidencePageContext, error: unknown): void {
  const { message, retryable } = errorInfo(error)
  if (!message) return
  container.innerHTML = ''
  const skeleton = buildSkeleton(container, ctx, ctx.revisionLabel)
  skeleton.statusBox.hidden = false
  skeleton.statusBox.textContent = message
  if (ctx.graph?.nodes.has(evidenceRefId(ctx.page.ref))) {
    renderRelationSection(skeleton.relationSlot, ctx, graphRelations(ctx.graph, ctx.page.ref))
  }
  if (retryable) {
    const retry = document.createElement('button')
    retry.type = 'button'
    retry.className = 'ui-button evidence-retry'
    retry.textContent = '重试'
    retry.addEventListener('click', () => {
      if (ctx.isStale()) return
      container.innerHTML = ''
      void renderEvidencePage(container, ctx)
    })
    skeleton.statusBox.append(' ', retry)
  }
  if (error instanceof ReportEditorApiError && error.code === 'cursor_invalid' && ctx.page.ref.kind === 'dataset') {
    const reset = makeButton('重新打开第一页')
    reset.addEventListener('click', () => {
      if (ctx.isStale()) return
      ctx.updatePage({ datasetCursors: [null], datasetPageIndex: 0 })
      ctx.setPageData(undefined)
      container.innerHTML = ''
      void renderEvidencePage(container, ctx)
    })
    skeleton.statusBox.append(' ', reset)
  }
  finishRender(container, ctx, skeleton.title)
}

function renderEvidenceGraph(host: HTMLElement, ctx: EvidencePageContext, relations: EvidenceRelations, expand: (ref: EvidenceObjectRef) => void, rerender: () => void): void {
  host.innerHTML = ''
  host.dataset.graphHost = ''
  const controls = document.createElement('div')
  controls.className = 'evidence-graph-controls'
  controls.setAttribute('role', 'toolbar')
  controls.setAttribute('aria-label', '关系图工具')
  const modeToggle = makeButton(ctx.page.graphMode === '3d' ? '切换 2D' : '切换 3D', 'ui-button evidence-graph-mode-toggle')
  modeToggle.setAttribute('aria-label', ctx.page.graphMode === '3d' ? '切换到 2D 关系图' : '切换到 3D 关系图')
  modeToggle.title = ctx.page.graphMode === '3d' ? '当前为 3D，切换到 2D' : '当前为 2D，切换到 3D'
  modeToggle.addEventListener('click', () => {
    ctx.updatePage({ graphMode: ctx.page.graphMode === '3d' ? '2d' : '3d' })
    rerender()
  })
  controls.append(modeToggle)
  const zoomOut = makeButton('', 'evidence-icon-button')
  const zoomIn = makeButton('', 'evidence-icon-button')
  const fit = makeButton('', 'evidence-icon-button')
  const reset = makeButton('重置视图', 'ui-button evidence-view-reset')
  const locate = makeButton('', 'evidence-icon-button')
  locate.setAttribute('aria-label', '定位当前对象')
  locate.title = '定位当前对象'
  zoomOut.append(createElement(ZoomOut, { width: 16, height: 16, 'aria-hidden': 'true' }))
  zoomIn.append(createElement(ZoomIn, { width: 16, height: 16, 'aria-hidden': 'true' }))
  fit.append(createElement(Expand, { width: 16, height: 16, 'aria-hidden': 'true' }))
  locate.append(createElement(LocateFixed, { width: 16, height: 16, 'aria-hidden': 'true' }))
  zoomOut.setAttribute('aria-label', '缩小关系图')
  zoomIn.setAttribute('aria-label', '放大关系图')
  fit.setAttribute('aria-label', '适应关系图')
  zoomOut.title = '缩小关系图'
  zoomIn.title = '放大关系图'
  fit.title = '适应关系图'
  controls.append(zoomOut, zoomIn, fit, reset, locate)
  host.append(controls)
  const allNodes = [relations.center, ...relations.nodes.filter((node) => !sameEvidenceRef(node, relations.center))]
  const graph = ctx.graph!

  // 3D 只在真实浏览器 WebGL 环境启用；无 WebGL（例如单测 DOM）继续使用同一套 2D 关系图。
  const canRender3d = ctx.page.graphMode === '3d' && (() => {
    if (typeof WebGLRenderingContext === 'undefined') return false
    try {
      const canvas = document.createElement('canvas')
      return Boolean(canvas.getContext('webgl'))
    } catch { return false }
  })()
  if (canRender3d) {
    const viewport = document.createElement('div')
    viewport.className = 'evidence-graph-3d'
    viewport.setAttribute('role', 'img')
    viewport.setAttribute('aria-label', '3D 关系图；关系线仅作视觉提示，请使用关系列表中的文字入口')
    host.append(viewport)
    const nodeData = allNodes.map(node => ({ id: evidenceRefId(node), ref: node, label: node.label }))
    const linkData = [...graph.edges].map(([id, edge]) => ({
      id, source: evidenceRefId(edge.from), target: evidenceRefId(edge.to), label: edge.label,
    }))
    const selectedId = ctx.page.selected ? evidenceRefId(ctx.page.selected) : null
    void import('3d-force-graph').then(({ default: ForceGraph3D }) => {
    let lastNodeClick: { id: string; at: number } | null = null
    const instance: any = new (ForceGraph3D as any)(viewport)
      .backgroundColor('#f7fbfd')
      .showNavInfo(false)
      .nodeLabel((node: { ref: EvidenceObjectRef }) => `${KIND_LABELS[node.ref.kind]}：${node.ref.label}`)
      .nodeColor((node: { ref: EvidenceObjectRef }) => evidenceRefId(node.ref) === selectedId ? '#007ea7' :
        sameEvidenceRef(node.ref, ctx.page.ref) ? '#1f6f8b' : '#80a2bd')
      .linkColor(() => selectedId ? '#b8cbd5' : '#80a2bd')
      .linkOpacity(0.8)
      .linkDirectionalArrowLength(4)
      .linkDirectionalArrowRelPos(1)
      .onNodeClick((node: { ref: EvidenceObjectRef }, event: MouseEvent) => {
        const id = evidenceRefId(node.ref)
        const now = Date.now()
        if (lastNodeClick?.id === id && now - lastNodeClick.at < 350) ctx.navigate(node.ref)
        else if (event.ctrlKey || event.metaKey) ctx.openBackground(node.ref, event.shiftKey)
        else ctx.setPreview(node.ref)
        lastNodeClick = { id, at: now }
      })
      .onNodeRightClick((node: { ref: EvidenceObjectRef }, event: MouseEvent) => {
        event.preventDefault()
        ctx.openBackground(node.ref, false)
      })
      .onNodeHover((node: { ref: EvidenceObjectRef } | null) => { viewport.dataset.hovered = node ? evidenceRefId(node.ref) : '' })
    instance.graphData({ nodes: nodeData, links: linkData })
    const fit3d = makeButton('适应 3D', 'ui-button evidence-3d-fit')
    fit3d.addEventListener('click', () => instance.zoomToFit(500, 32))
    controls.append(fit3d)
    const legend = document.createElement('div')
    legend.className = 'evidence-graph-legend'
    legend.textContent = `${relations.loadedNote} · 3D 默认视图`
    host.append(legend)
    const preview = document.createElement('div')
    preview.className = 'evidence-preview'
    preview.textContent = ctx.page.selected ? `预览：${ctx.page.selected.label} · 仅查看摘要` : '选择节点查看摘要；双击节点进入对象。'
    host.append(preview)
    }).catch(() => {
      viewport.remove()
      ctx.updatePage({ graphMode: '2d' })
      rerender()
    })
    return
  }
  const mapHeight = graph.height
  const mapWidth = graph.width
  const scroll = document.createElement('div')
  scroll.className = 'evidence-graph-scroll'
  const map = document.createElement('div')
  map.className = 'evidence-graph-map'
  map.style.height = `${mapHeight}px`
  map.style.width = `${mapWidth}px`
  map.style.aspectRatio = 'auto'
  map.style.transformOrigin = '0 0'
  const applyTransform = () => {
    map.style.transform = `translate(${ctx.page.graphPan.x}px, ${ctx.page.graphPan.y}px) scale(${ctx.page.graphScale})`
  }
  applyTransform()
  scroll.append(map)
  host.append(scroll)
  scroll.scrollLeft = ctx.page.graphScroll.left
  scroll.scrollTop = ctx.page.graphScroll.top
  scroll.addEventListener('scroll', () => {
    ctx.updatePage({ graphScroll: { left: scroll.scrollLeft, top: scroll.scrollTop } })
  }, { passive: true })

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  svg.classList.add('evidence-graph-edges')
  svg.setAttribute('viewBox', `0 0 ${mapWidth} ${mapHeight}`)
  svg.setAttribute('preserveAspectRatio', 'none')
  svg.setAttribute('aria-hidden', 'true')
  const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs')
  const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker')
  marker.id = 'evidence-graph-arrow'
  marker.setAttribute('viewBox', '0 0 10 10')
  marker.setAttribute('refX', '8')
  marker.setAttribute('refY', '5')
  marker.setAttribute('markerWidth', '6')
  marker.setAttribute('markerHeight', '6')
  marker.setAttribute('orient', 'auto-start-reverse')
  const arrow = document.createElementNS('http://www.w3.org/2000/svg', 'path')
  arrow.setAttribute('d', 'M 0 0 L 10 5 L 0 10 z')
  arrow.setAttribute('fill', '#80a2bd')
  marker.append(arrow)
  defs.append(marker)
  const selectedMarker = marker.cloneNode(true) as SVGMarkerElement
  selectedMarker.id = 'evidence-graph-arrow-selected'
  selectedMarker.querySelector('path')!.setAttribute('fill', '#007ea7')
  defs.append(selectedMarker)
  svg.append(defs)
  const selectedId = ctx.page.selected ? evidenceRefId(ctx.page.selected) : null
  const relatedIds = new Set<string>()
  const relationCounts = new Map<string, number>()
  for (const edge of graph.edges.values()) {
    const from = evidenceRefId(edge.from)
    const to = evidenceRefId(edge.to)
    relationCounts.set(from, (relationCounts.get(from) ?? 0) + 1)
    if (to !== from) relationCounts.set(to, (relationCounts.get(to) ?? 0) + 1)
    if (from === selectedId) relatedIds.add(to)
    if (to === selectedId) relatedIds.add(from)
  }
  const tracePicker = document.createElement('select')
  tracePicker.className = 'evidence-trace-picker'
  tracePicker.setAttribute('aria-label', '追踪预览关系端点')
  tracePicker.disabled = selectedId === null || relatedIds.size === 0
  const allRelations = document.createElement('option')
  allRelations.value = ''
  allRelations.textContent = selectedId === null ? '追踪：先预览节点' : '追踪：全部预览关系'
  tracePicker.append(allRelations)
  for (const node of allNodes.filter(node => relatedIds.has(evidenceRefId(node)) && evidenceRefId(node) !== selectedId)) {
    const option = document.createElement('option')
    option.value = evidenceRefId(node)
    option.textContent = `追踪：${KIND_LABELS[node.kind]} · ${node.label}`
    tracePicker.append(option)
  }
  controls.append(tracePicker)
  const selectedEdge = (id: string) => {
    const edge = graph.edges.get(id)!
    return selectedId !== null && (evidenceRefId(edge.from) === selectedId || evidenceRefId(edge.to) === selectedId)
  }
  // 预览关系绘制在上层，避免共用通道中的淡化边盖住高亮边。
  const paths = [...graph.paths].sort(([a], [b]) => Number(selectedEdge(a)) - Number(selectedEdge(b)))
  const edgeElements: SVGPathElement[] = []
  for (const [id, points] of paths) {
    const edge = graph.edges.get(id)!
    const highlighted = selectedEdge(id)
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path')
    path.dataset.from = evidenceRefId(edge.from)
    path.dataset.to = evidenceRefId(edge.to)
    path.setAttribute('d', points.map((point, index) => `${index ? 'L' : 'M'} ${point.x} ${point.y}`).join(' '))
    path.setAttribute('class', `evidence-graph-edge${highlighted ? ' is-preview' : selectedId !== null ? ' is-muted' : ''}`)
    path.setAttribute('marker-end', `url(#evidence-graph-arrow${highlighted ? '-selected' : ''})`)
    svg.append(path)
    edgeElements.push(path)
  }
  map.prepend(svg)

  let hoveredId: string | null = null
  let focusedId: string | null = null
  let pinnedId: string | null = null
  const nodeElements: Array<{ id: string; button: HTMLButtonElement }> = []
  const traceRelations = () => {
    const nodeId = pinnedId ?? hoveredId ?? focusedId
    const pairOnly = nodeId !== selectedId && nodeId !== null && relatedIds.has(nodeId)
    const relevant = selectedId === null || nodeId === selectedId || pairOnly
    const traced = edgeElements.filter(path => relevant && nodeId !== null &&
      (path.dataset.from === nodeId || path.dataset.to === nodeId) &&
      (!pairOnly || path.dataset.from === selectedId || path.dataset.to === selectedId))
    host.classList.toggle('is-tracing', traced.length > 0)
    for (const path of edgeElements) {
      path.classList.toggle('is-traced', traced.includes(path))
      path.setAttribute('marker-end', `url(#evidence-graph-arrow${path.classList.contains('is-preview') || traced.includes(path) ? '-selected' : ''})`)
      svg.append(path)
    }
    // 临时追踪放在最上层，退出后恢复预览的绘制顺序。
    for (const path of traced) svg.append(path)
    const tracedIds = new Set(traced.flatMap(path => [path.dataset.from, path.dataset.to]))
    for (const { id, button } of nodeElements) {
      button.classList.toggle('is-trace-related', tracedIds.has(id))
      const staysProminent = button.classList.contains('is-current') || button.classList.contains('is-selected')
      button.classList.toggle('is-trace-dim', traced.length > 0 && !tracedIds.has(id) && !staysProminent)
    }
  }
  tracePicker.addEventListener('change', () => {
    pinnedId = tracePicker.value || null
    const fitLabel = pinnedId ? '适应追踪关系' : '适应关系图'
    fit.setAttribute('aria-label', fitLabel)
    fit.title = fitLabel
    traceRelations()
  })

  for (const node of allNodes) {
    const position = graph.positions.get(evidenceRefId(node))!
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'evidence-node'
    button.dataset.evidenceNode = evidenceRefId(node)
    button.addEventListener('pointerenter', event => {
      if (event.pointerType === 'touch') return
      hoveredId = evidenceRefId(node)
      traceRelations()
    })
    button.addEventListener('pointerleave', () => {
      hoveredId = null
      traceRelations()
    })
    button.addEventListener('focus', () => {
      focusedId = evidenceRefId(node)
      traceRelations()
    })
    button.addEventListener('blur', () => {
      focusedId = null
      traceRelations()
    })
    button.style.left = `${position.x - position.width / 2}px`
    button.style.top = `${position.y - position.height / 2}px`
    button.setAttribute('aria-label', `${KIND_LABELS[node.kind]}：${node.label}`)
    button.setAttribute('aria-pressed', String(ctx.page.selected !== null && sameEvidenceRef(ctx.page.selected, node)))
    if (relatedIds.has(evidenceRefId(node))) button.classList.add('is-related')
    if (sameEvidenceRef(node, ctx.page.ref)) button.classList.add('is-current')
    if (ctx.page.selected && sameEvidenceRef(ctx.page.selected, node)) button.classList.add('is-selected')
    const title = document.createElement('span')
    title.className = 'evidence-node-title'
    title.textContent = node.label
    title.title = node.label
    const heading = document.createElement('span')
    heading.className = 'evidence-node-heading'
    const icon = { fact: Hash, computation: Calculator, dataset: Database, chart: ChartColumn, subject: FileText }[node.kind]
    heading.append(createElement(icon, { width: 14, height: 14, 'aria-hidden': 'true' }), title)
    const tag = document.createElement('span')
    tag.className = 'evidence-node-tag'
    tag.textContent = sameEvidenceRef(node, ctx.page.ref) ? '当前页' : (ctx.page.selected && sameEvidenceRef(ctx.page.selected, node) ? '预览' : '')
    tag.hidden = !tag.textContent
    const branch = graph.branches.get(evidenceRefId(node))
    const info = document.createElement('span')
    info.className = 'evidence-node-info'
    info.textContent = `${KIND_LABELS[node.kind]} · ` + (branch?.status === 'loading' ? '关系加载中…'
      : branch?.status === 'error' ? '关系加载失败'
        : `已加载 ${relationCounts.get(evidenceRefId(node)) ?? 0} 条关系`)
    button.append(heading, info, tag)
    nodeElements.push({ id: evidenceRefId(node), button })
    button.addEventListener('click', (event) => {
      if (event.ctrlKey || event.metaKey) ctx.openBackground(node, event.shiftKey)
      else ctx.setPreview(node)
    })
    button.addEventListener('dblclick', () => ctx.navigate(node))
    button.addEventListener('auxclick', (event) => {
      if (event.button !== 1) return
      event.preventDefault()
      ctx.openBackground(node, false)
    })
    button.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault()
        ctx.navigate(node)
      } else if (event.key === ' ' || event.key === 'Spacebar') {
        event.preventDefault()
        ctx.setPreview(node)
      } else if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        ctx.setPreview(null)
      }
    })
    map.append(button)
  }

  const legend = document.createElement('div')
  legend.className = 'evidence-graph-legend'
  legend.innerHTML = '<span><i class="key"></i>当前页</span><span><i class="key outline"></i>预览</span>'
  const loaded = document.createElement('span')
  loaded.textContent = relations.loadedNote
  legend.append(loaded)
  const traceHint = document.createElement('span')
  traceHint.textContent = '悬停或聚焦节点追踪关系'
  legend.append(traceHint)
  host.append(legend)

  const updateScale = (delta: number) => {
    const scale = Math.min(2, Math.max(0.01, Number((ctx.page.graphScale + delta).toFixed(2))))
    ctx.updatePage({ graphScale: scale })
    applyTransform()
  }
  zoomOut.addEventListener('click', () => updateScale(-0.1))
  zoomIn.addEventListener('click', () => updateScale(0.1))
  fit.addEventListener('click', () => {
    const availableWidth = Math.max(1, scroll.clientWidth - 32)
    let scale = Math.min(1, availableWidth / mapWidth)
    let pan = { x: 0, y: 0 }
    if (pinnedId && selectedId) {
      const points: { x: number; y: number }[] = []
      for (const id of [pinnedId, selectedId]) {
        const position = graph.positions.get(id)!
        points.push({ x: position.x - position.width / 2, y: position.y - position.height / 2 },
          { x: position.x + position.width / 2, y: position.y + position.height / 2 })
      }
      for (const [id, edge] of graph.edges) {
        const from = evidenceRefId(edge.from)
        const to = evidenceRefId(edge.to)
        if ((from === pinnedId && to === selectedId) || (from === selectedId && to === pinnedId)) {
          points.push(...(graph.paths.get(id) ?? []))
        }
      }
      const left = Math.min(...points.map(point => point.x))
      const top = Math.min(...points.map(point => point.y))
      const width = Math.max(...points.map(point => point.x)) - left
      const height = Math.max(...points.map(point => point.y)) - top
      scale = Math.min(1, availableWidth / Math.max(1, width), Math.max(1, scroll.clientHeight - 32) / Math.max(1, height))
      pan = { x: 16 - left * scale, y: 16 - top * scale }
    }
    ctx.updatePage({ graphScale: scale, graphPan: pan, graphScroll: { left: 0, top: 0 } })
    applyTransform()
    scroll.scrollLeft = 0
    scroll.scrollTop = 0
  })
  reset.addEventListener('click', () => {
    ctx.updatePage({ graphScale: 1, graphPan: { x: 0, y: 0 }, graphScroll: { left: 0, top: 0 } })
    applyTransform()
    scroll.scrollLeft = 0
    scroll.scrollTop = 0
  })
  locate.addEventListener('click', () => {
    const position = graph.positions.get(evidenceRefId(ctx.page.ref))!
    ctx.updatePage({ graphPan: { x: 0, y: 0 } })
    applyTransform()
    scroll.scrollLeft = Math.max(0, position.x * ctx.page.graphScale - scroll.clientWidth / 2)
    scroll.scrollTop = Math.max(0, position.y * ctx.page.graphScale - scroll.clientHeight / 2)
    ctx.updatePage({ graphScroll: { left: scroll.scrollLeft, top: scroll.scrollTop } })
    map.querySelector<HTMLButtonElement>('.evidence-node.is-current')?.focus({ preventScroll: true })
  })
  let drag: { pointerId: number; x: number; y: number; panX: number; panY: number } | null = null
  const touches = new Map<number, { x: number; y: number }>()
  let pinch: { distance: number; scale: number; anchorX: number; anchorY: number } | null = null
  let suppressTouchClick = false
  const touchGeometry = () => {
    const [first, second] = [...touches.values()]
    const bounds = scroll.getBoundingClientRect()
    return {
      distance: Math.hypot(second.x - first.x, second.y - first.y),
      x: (first.x + second.x) / 2 - bounds.left - scroll.clientLeft + scroll.scrollLeft,
      y: (first.y + second.y) / 2 - bounds.top - scroll.clientTop + scroll.scrollTop,
    }
  }
  map.addEventListener('pointerdown', (event) => {
    if (event.pointerType !== 'touch' && !touches.size) suppressTouchClick = false
    if (event.pointerType === 'touch') {
      if (touches.size >= 2) return
      if (!touches.size) suppressTouchClick = false
      touches.set(event.pointerId, { x: event.clientX, y: event.clientY })
      if (touches.size === 2) {
        const center = touchGeometry()
        pinch = {
          distance: Math.max(1, center.distance), scale: ctx.page.graphScale,
          anchorX: (center.x - ctx.page.graphPan.x) / ctx.page.graphScale,
          anchorY: (center.y - ctx.page.graphPan.y) / ctx.page.graphScale,
        }
        drag = null
        suppressTouchClick = true
        for (const id of touches.keys()) map.setPointerCapture(id)
        return
      }
    }
    if (drag || event.button !== 0 || (event.target as HTMLElement).closest('.evidence-node')) return
    drag = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, panX: ctx.page.graphPan.x, panY: ctx.page.graphPan.y }
    map.setPointerCapture(event.pointerId)
  })
  map.addEventListener('pointermove', (event) => {
    if (touches.has(event.pointerId)) {
      touches.set(event.pointerId, { x: event.clientX, y: event.clientY })
      if (pinch) {
        const center = touchGeometry()
        const scale = Math.min(2, Math.max(0.01, pinch.scale * center.distance / pinch.distance))
        ctx.updatePage({ graphScale: scale, graphPan: {
          x: center.x - pinch.anchorX * scale, y: center.y - pinch.anchorY * scale,
        } })
        applyTransform()
        return
      }
    }
    if (!drag || event.pointerId !== drag.pointerId) return
    ctx.updatePage({ graphPan: { x: drag.panX + event.clientX - drag.x, y: drag.panY + event.clientY - drag.y } })
    applyTransform()
  })
  const finishDrag = (event: PointerEvent) => {
    if (event.type === 'lostpointercapture' && event.target !== map) return
    if (touches.delete(event.pointerId) && pinch) {
      pinch = null
      const remaining = [...touches.entries()][0]
      if (remaining) {
        const [pointerId, point] = remaining
        drag = { pointerId, x: point.x, y: point.y, panX: ctx.page.graphPan.x, panY: ctx.page.graphPan.y }
      }
    }
    if (event.pointerId === drag?.pointerId) drag = null
  }
  map.addEventListener('pointerup', finishDrag)
  map.addEventListener('pointercancel', finishDrag)
  map.addEventListener('lostpointercapture', finishDrag)
  const suppressGestureClick = (event: MouseEvent) => {
    if (suppressTouchClick && event.detail !== 0) {
      event.preventDefault()
      event.stopPropagation()
    }
  }
  map.addEventListener('click', suppressGestureClick, { capture: true })
  map.addEventListener('dblclick', suppressGestureClick, { capture: true })
  map.addEventListener('wheel', (event) => {
    event.preventDefault()
    updateScale(event.deltaY < 0 ? 0.1 : -0.1)
  }, { passive: false })

  const preview = document.createElement('div')
  preview.className = 'evidence-preview'
  if (ctx.page.selected) {
    const summary = document.createElement('div')
    summary.className = 'evidence-preview-summary'
    const actions = document.createElement('div')
    actions.className = 'evidence-preview-actions'
    actions.setAttribute('role', 'group')
    actions.setAttribute('aria-label', '预览操作')
    const label = document.createElement('strong')
    label.textContent = `预览：${ctx.page.selected.label}`
    const note = document.createElement('span')
    note.textContent = `${KIND_LABELS[ctx.page.selected.kind]} · 仅查看摘要`
    summary.append(label, note)
    const enter = makeButton('进入', 'ui-button ui-button--primary evidence-preview-enter')
    enter.append(createElement(ArrowRight, { width: 15, height: 15, 'aria-hidden': 'true' }))
    const current = sameEvidenceRef(ctx.page.selected, ctx.page.ref)
    enter.textContent = current ? '已在当前页' : '进入'
    enter.disabled = current
    enter.addEventListener('click', () => ctx.navigate(ctx.page.selected!))
    const open = makeButton('新页签打开', 'ui-button')
    open.append(createElement(ExternalLink, { width: 15, height: 15, 'aria-hidden': 'true' }))
    open.addEventListener('click', () => ctx.openBackground(ctx.page.selected!, true))
    const close = makeButton('关闭预览', 'ui-button')
    close.append(createElement(X, { width: 15, height: 15, 'aria-hidden': 'true' }))
    close.addEventListener('click', () => ctx.setPreview(null))
    const selected = ctx.page.selected
    const branch = graph.branches.get(evidenceRefId(selected))
    const load = makeButton(branch?.status === 'loading' ? '关系加载中…'
      : branch?.status === 'loaded' ? '已加载登记关系'
      : branch?.status === 'error' ? '重试加载关系' : '加载更多上游 / 下游', 'ui-button evidence-branch-load')
    load.append(createElement(Network, { width: 15, height: 15, 'aria-hidden': 'true' }))
    load.disabled = branch?.status === 'loading' || branch?.status === 'loaded'
    load.addEventListener('click', () => expand(selected))
    const status = document.createElement('span')
    status.className = 'evidence-branch-status'
    status.setAttribute('role', 'status')
    status.textContent = branch?.status === 'error' ? branch.message ?? '加载失败'
      : branch?.status === 'loaded' ? '仅含接口已登记关系' : ''
    actions.append(enter, open, load, close)
    preview.append(summary, actions, status)
  } else {
    preview.textContent = '选择节点查看摘要；单击只预览，Enter 或双击进入对象。'
  }
  host.append(preview)
}

/** 只加载目标节点的一跳登记关系；无统一反向索引，不能宣称图已完整。 */
async function loadNodeRelations(ref: EvidenceObjectRef, ctx: EvidencePageContext): Promise<EvidenceRelations> {
  switch (ref.kind) {
    case 'fact': {
      if (!ref.analysisId) throw new ReportEditorApiError(404, 'source_missing')
      const detail = await ctx.client.factDetail(ref.analysisId, ref.key, ctx.signal)
      return assembleFactRelations(ref, detail, await ctx.loadSources())
    }
    case 'computation': {
      const detail = await ctx.client.computationDetail(ref.key, 2, ctx.signal)
      return assembleComputationRelations(ref, detail, await ctx.loadSources())
    }
    case 'dataset': {
      await ctx.client.datasetPreview(ref.key, { limit: 1 }, ctx.signal)
      return assembleDatasetRelations(ref, await ctx.loadSources())
    }
    case 'chart': {
      const source = await ctx.client.chartSource(ref.key, { limit: 1, offset: 0 }, ctx.signal)
      return assembleChartRelations(ref, source)
    }
    case 'subject': {
      const subject = (await ctx.loadSources()).subjects?.find(item => item.subjectId === ref.key)
      if (!subject) throw new ReportEditorApiError(404, 'source_missing')
      return assembleSubjectRelations(ref, subject)
    }
  }
}

/** 关系区：图与等价文字列表可切换，收起状态持久在当前历史页面。 */
function renderRelationSection(slot: HTMLElement, ctx: EvidencePageContext, relations: EvidenceRelations): void {
  ctx.graph ??= createEvidenceGraph()
  mergeEvidenceGraph(ctx.graph, relations)
  ctx.graph.branches.set(evidenceRefId(relations.center), { status: 'loaded' })
  const loaded = graphRelations(ctx.graph, ctx.page.ref)
  const section = document.createElement('section')
  section.className = 'evidence-relations'
  const head = document.createElement('div')
  head.className = 'evidence-relations-head'
  const heading = document.createElement('h2')
  heading.textContent = `${ctx.taskLabel ?? ctx.page.path[0].label} · 来源与引用`
  const headingId = `evidence-relations-heading-${evidenceRefId(relations.center).replace(/[^a-zA-Z0-9_-]/g, '-')}`
  heading.id = headingId
  section.setAttribute('aria-labelledby', headingId)
  const note = document.createElement('span')
  note.className = 'evidence-relations-note'
  note.textContent = loaded.loadedNote
  const viewToggle = document.createElement('button')
  viewToggle.type = 'button'
  viewToggle.className = 'ui-button evidence-view-toggle'
  const toggle = document.createElement('button')
  toggle.type = 'button'
  toggle.className = 'ui-button evidence-relations-toggle'
  const openGraph = makeButton('查看关系图', 'ui-button evidence-mobile-graph-open')
  const returnDetail = makeButton('返回详情', 'ui-button evidence-mobile-graph-return')
  head.append(heading, note, viewToggle, toggle, openGraph, returnDetail)
  const body = document.createElement('div')
  body.className = 'evidence-relations-body'
  const graph = document.createElement('div')
  graph.className = 'evidence-graph'
  graph.setAttribute('role', 'region')
  graph.setAttribute('aria-label', '关系图；关系线仅作视觉提示，请使用关系列表中的文字入口')
  const list = document.createElement('div')
  list.className = 'evidence-relation-list'
  list.setAttribute('role', 'region')
  list.setAttribute('aria-label', '关系列表')
  renderRelationList(list, loaded, {
    navigate: ctx.navigate,
    openBackground: ctx.openBackground,
  })
  const expand = async (ref: EvidenceObjectRef) => {
    const id = evidenceRefId(ref)
    const branch = ctx.graph!.branches.get(id)
    if (ctx.isStale() || branch?.status === 'loading' || branch?.status === 'loaded') return
    const loading = { status: 'loading' as const }
    ctx.graph!.branches.set(id, loading)
    const cancel = () => {
      if (ctx.graph!.branches.get(id) === loading) ctx.graph!.branches.delete(id)
    }
    ctx.signal.addEventListener('abort', cancel, { once: true })
    const redraw = () => {
      if (ctx.isStale()) return
      slot.replaceChildren()
      renderRelationSection(slot, ctx, relations)
      slot.querySelector<HTMLButtonElement>('.evidence-branch-load')?.focus({ preventScroll: true })
    }
    redraw()
    try {
      const next = await loadNodeRelations(ref, ctx)
      if (ctx.isStale()) return
      mergeEvidenceGraph(ctx.graph!, next)
      ctx.graph!.branches.set(id, { status: 'loaded' })
    } catch (error) {
      if (ctx.isStale()) return
      ctx.graph!.branches.set(id, { status: 'error', message: errorInfo(error).message || '加载失败' })
    } finally {
      ctx.signal.removeEventListener('abort', cancel)
    }
    redraw()
  }
  renderEvidenceGraph(graph, ctx, loaded, ref => void expand(ref), () => {
    slot.replaceChildren()
    renderRelationSection(slot, ctx, relations)
  })
  body.append(graph, list)
  section.append(head, body)
  slot.append(section)
  const sync = () => {
    const collapsed = ctx.page.collapsed
    toggle.textContent = collapsed ? '展开' : '收起'
    toggle.setAttribute('aria-expanded', String(!collapsed))
    section.classList.toggle('is-graph-view', ctx.page.graphView)
    body.hidden = collapsed && !ctx.page.graphView
    graph.hidden = ctx.page.showList && !ctx.page.graphView
    list.hidden = !ctx.page.showList || ctx.page.graphView
    if (!body.hidden && !graph.hidden) {
      const viewport = graph.querySelector<HTMLElement>('.evidence-graph-scroll')!
      viewport.scrollLeft = ctx.page.graphScroll.left
      viewport.scrollTop = ctx.page.graphScroll.top
    }
    viewToggle.textContent = ctx.page.showList ? '关系图' : '关系列表'
    viewToggle.setAttribute('aria-label', ctx.page.showList ? '切换到关系图' : '切换到关系列表')
  }
  openGraph.addEventListener('click', () => {
    ctx.updatePage({ graphView: true })
    sync()
    returnDetail.focus()
  })
  const leaveGraph = () => {
    ctx.updatePage({ graphView: false })
    sync()
    openGraph.focus({ preventScroll: true })
  }
  returnDetail.addEventListener('click', leaveGraph)
  section.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && ctx.page.graphView && !ctx.page.selected) {
      event.preventDefault()
      leaveGraph()
    }
  })
  toggle.addEventListener('click', () => {
    ctx.updatePage({ collapsed: !ctx.page.collapsed })
    sync()
  })
  viewToggle.addEventListener('click', () => {
    ctx.updatePage({ showList: !ctx.page.showList })
    sync()
  })
  sync()
}

function makeStatusRow(area: HTMLElement, label: string, key: string): HTMLElement {
  const row = document.createElement('div')
  row.className = 'evidence-status-row'
  row.dataset.statusRow = key
  const name = document.createElement('span')
  name.className = 'evidence-status-label'
  name.textContent = label
  const value = document.createElement('span')
  value.className = 'evidence-status-value'
  row.append(name, value)
  area.append(row)
  return value
}

function makeButton(label: string, className = 'ui-button'): HTMLButtonElement {
  const button = document.createElement('button')
  button.type = 'button'
  button.className = className
  button.textContent = label
  return button
}

function renderTable(wrap: HTMLElement, columns: string[], rows: (string | null)[][], ctx?: EvidencePageContext): void {
  wrap.innerHTML = ''
  const table = document.createElement('table')
  table.className = 'evidence-table'
  const widths = columns.map(column => {
    const stored = ctx?.page.columnWidths[column]
    return typeof stored === 'number' && Number.isFinite(stored) ? Math.max(80, Math.min(640, stored)) : 144
  })
  const group = document.createElement('colgroup')
  const cols = columns.map(() => document.createElement('col'))
  if (ctx) {
    group.append(...cols)
    table.append(group)
    table.style.tableLayout = 'fixed'
  }
  const applyWidths = () => {
    cols.forEach((col, index) => { col.style.width = `${widths[index]}px` })
    table.style.width = `${widths.reduce((sum, width) => sum + width, 0)}px`
  }
  if (ctx) applyWidths()
  const header = table.insertRow()
  for (const [index, column] of columns.entries()) {
    const cell = document.createElement('th')
    cell.scope = 'col'
    cell.textContent = column
    if (ctx) {
      const handle = makeButton('', 'evidence-column-resize')
      const label = () => handle.setAttribute('aria-label', `调整 ${column} 列宽，当前 ${widths[index]} 像素，左右方向键调整`)
      const resize = (width: number) => {
        if (ctx.isStale()) return
        widths[index] = Math.max(80, Math.min(640, Math.round(width)))
        ctx.updatePage({ columnWidths: { ...ctx.page.columnWidths, [column]: widths[index] } })
        applyWidths()
        label()
      }
      label()
      let drag: { x: number; width: number } | null = null
      handle.addEventListener('pointerdown', (event) => {
        if (event.button !== 0) return
        event.preventDefault()
        handle.focus({ preventScroll: true })
        drag = { x: event.clientX, width: widths[index] }
        handle.setPointerCapture(event.pointerId)
      })
      handle.addEventListener('pointermove', (event) => {
        if (drag) resize(drag.width + event.clientX - drag.x)
      })
      handle.addEventListener('pointerup', () => { drag = null })
      handle.addEventListener('pointercancel', () => { drag = null })
      handle.addEventListener('keydown', (event) => {
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
        event.preventDefault()
        resize(widths[index] + (event.key === 'ArrowRight' ? 10 : -10))
      })
      cell.append(handle)
    }
    header.append(cell)
  }
  for (const row of rows) {
    const tr = table.insertRow()
    for (const value of row) {
      const cell = tr.insertCell()
      cell.textContent = text(value)
    }
  }
  wrap.append(table)
  if (ctx) wrap.scrollLeft = ctx.page.tableScroll
}

type Draft = NonNullable<ReturnType<EvidencePageContext['getDraft']>>
interface DraftValidation {
  validation: TraceValidation | null
  validatedDraft?: Draft | null
}

function sameDraft(a: Draft | null | undefined, b: Draft | null): boolean {
  return !!a && !!b && a.markdown === b.markdown && a.sha256 === b.sha256
}

/** 登记详情可缓存；草稿校验只复用与当前正文及基准 SHA 完全匹配的结果。 */
async function refreshDraftValidation(data: DraftValidation, ctx: EvidencePageContext, container: HTMLElement): Promise<void> {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    if (ctx.isStale()) return
    const draft = ctx.getDraft()
    if (draft && data.validation && sameDraft(data.validatedDraft, draft)) return
    data.validation = null
    data.validatedDraft = null
    if (!draft) return
    const loading = document.createElement('p')
    loading.className = 'evidence-placeholder'
    loading.textContent = '当前草稿引用校验中…'
    container.replaceChildren(loading)
    try {
      const digest = await markdownSha256(draft.markdown)
      if (ctx.isStale()) return
      if (!sameDraft(draft, ctx.getDraft())) continue
      const result = await ctx.client.validateSources(draft.markdown, digest, ctx.signal)
      if (ctx.isStale()) return
      if (sameDraft(draft, ctx.getDraft())) {
        if (result.draftSha256 !== digest) return
        data.validation = result
        data.validatedDraft = { ...draft }
        return
      }
      // 请求期间正文变化时只补验一次最新草稿，持续变化则保持未确认状态。
    } catch {
      return
    }
  }
}

// ---------------------------------------------------------------------------
// 入口分发
// ---------------------------------------------------------------------------

export async function renderEvidencePage(
  container: HTMLElement,
  ctx: EvidencePageContext,
): Promise<void> {
  if (ctx.page.ref.kind === 'fact') return renderFactPage(container, ctx)
  if (ctx.page.ref.kind === 'computation') return renderComputationPage(container, ctx)
  if (ctx.page.ref.kind === 'dataset') return renderDatasetPage(container, ctx)
  if (ctx.page.ref.kind === 'chart') return renderChartPage(container, ctx)
  return renderSubjectPage(container, ctx)
}

// ---------------------------------------------------------------------------
// 事实页
// ---------------------------------------------------------------------------

interface FactPageData extends DraftValidation {
  detail: TraceFactDetail
  relations: EvidenceRelations
  computation: TraceComputationDetail | null
  citingSubjects: TraceSubjectInfo[]
}

async function renderFactPage(container: HTMLElement, ctx: EvidencePageContext): Promise<void> {
  const cached = ctx.pageData<FactPageData>()
  let data = cached
  if (!data) {
    if (!ctx.page.ref.analysisId) {
      renderPageError(container, ctx, new ReportEditorApiError(400, 'request_invalid'))
      return
    }
    showLoading(container)
    try {
      const detail = await ctx.client.factDetail(ctx.page.ref.analysisId, ctx.page.ref.key, ctx.signal)
      if (ctx.isStale()) return
      const sources = await ctx.loadSources()
      if (ctx.isStale()) return
      const citingSubjects = (sources.subjects ?? []).filter((subject) =>
        subject.factRefs.some(
          (item) => item.factId === ctx.page.ref.key && item.analysisId === ctx.page.ref.analysisId,
        ),
      )
      const computationId = citingSubjects.find((subject) => subject.computationId)?.computationId
      let computation: TraceComputationDetail | null = null
      if (computationId) {
        try {
          computation = await ctx.client.computationDetail(computationId, 2, ctx.signal)
        } catch {
          computation = null
        }
        if (ctx.isStale()) return
      }
      data = {
        detail,
        relations: assembleFactRelations(ctx.page.ref, detail, sources),
        validation: null,
        computation,
        citingSubjects,
      }
      ctx.setPageData(data)
    } catch (error) {
      if (ctx.isStale()) return
      renderPageError(container, ctx, error)
      return
    }
  }
  await refreshDraftValidation(data, ctx, container)
  if (ctx.isStale()) return
  container.innerHTML = ''
  const { detail } = data
  const entry = detail.entry as Record<string, unknown>
  const unit = typeof entry.unit === 'string' ? entry.unit : ''
  const skeleton = buildSkeleton(container, ctx, `分析 ${detail.analysisId} · ${detail.factKind} · ${ctx.revisionLabel}`)

  // 登记值摘要：只展示登记值与登记公式，缺失时不拼造「计算过程」。
  const valueLine = document.createElement('p')
  valueLine.className = 'evidence-fact-value'
  valueLine.textContent = `登记值 ${text(detail.displayValue)}${unit ? ` ${unit}` : ''}`
  skeleton.statusArea.append(valueLine)

  if (!data.validation && ctx.getDraft()) {
    makeStatusRow(skeleton.statusArea, '引用状态', 'citation').textContent = '当前草稿引用状态未确认'
  }

  // 引用状态：依赖草稿校验，校验不可用时整行不显示，不猜测。
  if (data.validation) {
    const value = makeStatusRow(skeleton.statusArea, '引用状态', 'citation')
    if (!data.citingSubjects.length) {
      value.textContent = '当前修订没有引用此事实的正文位置'
    }
    for (const subject of data.citingSubjects) {
      const chip = document.createElement('span')
      chip.className = 'evidence-status-chip'
      const entryResult = data.validation.subjects.find((item) => item.subjectId === subject.subjectId)
      chip.dataset.status = entryResult?.status ?? 'unbound'
      const status = entryResult ? (CITATION_STATUS_LABELS[entryResult.status] ?? entryResult.status) : '未绑定'
      let chipText = `正文引用 ${subject.subjectId.slice(0, 8)}：${status}`
      if (entryResult?.status === 'stale' || entryResult?.warnings?.length) {
        chipText += ' · 需核对口径'
        const warning = document.createElement('div')
        warning.className = 'evidence-warning'
        const message = document.createElement('p')
        // factValue、unit、periods 与 scope 均取自登记事实，不是草稿提取值。
        const draftValue = numeric(entryResult.draftValue)
        const registeredValue = numeric(detail.displayValue)
        const difference = draftValue !== null && registeredValue !== null && entryResult.comparable
          ? draftValue - registeredValue
          : null
        message.textContent = entryResult.status === 'stale' && difference !== null
          ? `正文当前值 ${text(entryResult.draftValue)}${unit ? ` ${unit}` : ''}，登记值 ${text(detail.displayValue)}${unit ? ` ${unit}` : ''}，差异 ${difference >= 0 ? '+' : ''}${text(difference)}。正文引用内容已变更，登记值核对结论不受影响。`
          : entryResult.status === 'stale'
            ? '正文引用内容已变更，需核对口径。当前正文值、单位与期间的可比性尚未确认，暂不计算差额。登记值核对结论不受影响。'
            : '正文引用命中登记值，但单位或期间存在软告警，需核对口径。登记值核对结论不受影响。'
        warning.append(message)
        for (const note of entryResult.warnings ?? []) {
          const item = document.createElement('p')
          item.textContent = note
          warning.append(item)
        }
        const locate = makeButton('定位正文')
        locate.addEventListener('click', () => ctx.locateSubject(subject.subjectId))
        warning.append(locate)
        skeleton.statusArea.append(warning)
      }
      chip.textContent = chipText
      value.append(chip)
    }
  }

  // 登记值核对与复算条件：取自产出此事实的计算记录；找不到计算记录时如实标注。
  const verification = makeStatusRow(skeleton.statusArea, '登记值核对', 'verification')
  verification.textContent = data.computation
    ? (VERIFICATION_LABELS[data.computation.verification] ?? data.computation.verification)
    : '未核对'
  const reproducibility = makeStatusRow(skeleton.statusArea, '复算条件', 'reproducibility')
  reproducibility.textContent = data.computation
    ? (REPRODUCIBILITY_LABELS[data.computation.reproducibility] ?? data.computation.reproducibility)
    : '不适用'

  renderRelationSection(skeleton.relationSlot, ctx, data.relations)

  const formula = typeof entry.formula === 'string' && entry.formula ? entry.formula : ''
  if (formula) {
    const formulaP = document.createElement('p')
    formulaP.className = 'evidence-fact-formula'
    formulaP.textContent = `公式：${formula}`
    skeleton.detailBox.append(formulaP)
  }
  if (detail.warnings.length) {
    const warnings = document.createElement('ul')
    warnings.className = 'evidence-fact-warnings'
    for (const warning of detail.warnings) {
      const li = document.createElement('li')
      li.textContent = warning
      warnings.append(li)
    }
    skeleton.detailBox.append(warnings)
  }
  if (detail.inputFactRefs.length) {
    const heading = document.createElement('h2')
    heading.textContent = '输入事实'
    const list = document.createElement('ul')
    list.className = 'evidence-fact-inputs'
    for (const input of detail.inputFactRefs) {
      const li = document.createElement('li')
      li.textContent = `输入事实 ${input.factId ?? input.analysisId}`
      if (input.factId) {
        const jump = makeButton('查看', 'ui-button evidence-link')
        bindEvidenceNavigation(jump, {
          kind: 'fact', key: input.factId, analysisId: input.analysisId, label: input.factId,
        }, ctx)
        li.append(' ', jump)
      }
      list.append(li)
    }
    skeleton.detailBox.append(heading, list)
  }
  finishRender(container, ctx, skeleton.title)
}

// ---------------------------------------------------------------------------
// 计算页
// ---------------------------------------------------------------------------

interface ComputationPageData {
  detail: TraceComputationDetail
  relations: EvidenceRelations
}

async function renderComputationPage(container: HTMLElement, ctx: EvidencePageContext): Promise<void> {
  let data = ctx.pageData<ComputationPageData>()
  if (!data) {
    showLoading(container)
    try {
      const detail = await ctx.client.computationDetail(ctx.page.ref.key, 2, ctx.signal)
      if (ctx.isStale()) return
      const sources = await ctx.loadSources()
      if (ctx.isStale()) return
      data = { detail, relations: assembleComputationRelations(ctx.page.ref, detail, sources) }
      ctx.setPageData(data)
    } catch (error) {
      if (ctx.isStale()) return
      renderPageError(container, ctx, error)
      return
    }
  }
  container.innerHTML = ''
  const { detail } = data
  const skeleton = buildSkeleton(container, ctx, `${ctx.revisionLabel} · 计算记录 ${detail.computationId}`)
  renderRelationSection(skeleton.relationSlot, ctx, data.relations)

  const section = document.createElement('div')
  section.className = 'evidence-computation'
  const method = document.createElement('p')
  method.textContent = `方法：${detail.method}`
  section.append(method)
  const parameters = document.createElement('pre')
  parameters.className = 'evidence-computation-parameters'
  parameters.tabIndex = 0
  parameters.setAttribute('aria-label', '计算参数，可滚动查看')
  parameters.textContent = `参数：${JSON.stringify(detail.parameters, null, 2)}`
  section.append(parameters)
  if (detail.preprocessing !== undefined && detail.preprocessing !== null) {
    const preprocessing = document.createElement('pre')
    preprocessing.className = 'evidence-computation-parameters'
    preprocessing.tabIndex = 0
    preprocessing.setAttribute('aria-label', '预处理参数，可滚动查看')
    preprocessing.textContent = `预处理：${JSON.stringify(detail.preprocessing, null, 2)}`
    section.append(preprocessing)
  }
  const env = detail.environment
    ? Object.entries(detail.environment)
        .map(([key, value]) => `${key} ${value}`)
        .join(' · ')
    : '环境信息缺失（复算条件有限）'
  const execution = document.createElement('p')
  execution.textContent = `执行：${detail.executionId ?? '—'} · ${env}`
  section.append(execution)
  const verification = document.createElement('p')
  verification.className = 'evidence-computation-verification'
  verification.textContent =
    `核对状态：${VERIFICATION_LABELS[detail.verification] ?? detail.verification} · ` +
    `${REPRODUCIBILITY_LABELS[detail.reproducibility] ?? detail.reproducibility}`
  section.append(verification)
  for (const note of detail.limitations) {
    const p = document.createElement('p')
    p.className = 'evidence-limitation'
    p.textContent = note
    section.append(p)
  }
  const heading = document.createElement('h2')
  heading.textContent = '输出事实'
  section.append(heading)
  const outputs = document.createElement('ul')
  outputs.className = 'evidence-computation-outputs'
  if (!detail.outputFactRefs.length) {
    const li = document.createElement('li')
    li.textContent = '没有登记的输出事实'
    outputs.append(li)
  }
  for (const ref of detail.outputFactRefs.slice(0, 20)) {
    const li = document.createElement('li')
    li.textContent = `${ref.analysisId} ${ref.jsonPointer}`
    if (ref.factKey) {
      const jump = makeButton('查看事实', 'ui-button evidence-link')
      bindEvidenceNavigation(jump, {
        kind: 'fact', key: ref.factKey, analysisId: ref.analysisId, label: ref.factKey,
      }, ctx)
      li.append(' ', jump)
    }
    outputs.append(li)
  }
  section.append(outputs)
  skeleton.detailBox.append(section)
  finishRender(container, ctx, skeleton.title)
}

// ---------------------------------------------------------------------------
// 快照页
// ---------------------------------------------------------------------------

interface DatasetPageData {
  detail: {
    columns: string[]
    rows: (string | null)[][]
    rowCountTotal: number
    offset: number
    nextCursor: string | null
    truncatedByBudget: boolean
  }
  relations: EvidenceRelations
}

async function renderDatasetPage(container: HTMLElement, ctx: EvidencePageContext): Promise<void> {
  let data = ctx.pageData<DatasetPageData>()
  if (!data) {
    showLoading(container)
    try {
      const cursor = ctx.page.datasetCursors[ctx.page.datasetPageIndex]
      const page = await ctx.client.datasetPreview(ctx.page.ref.key, { limit: 50, ...(cursor ? { cursor } : {}) }, ctx.signal)
      if (ctx.isStale()) return
      const sources = await ctx.loadSources()
      if (ctx.isStale()) return
      data = {
        detail: {
          columns: page.columns,
          rows: [...page.rows],
          rowCountTotal: page.rowCountTotal,
          offset: page.offset,
          nextCursor: page.nextCursor,
          truncatedByBudget: page.truncatedByBudget,
        },
        relations: assembleDatasetRelations(ctx.page.ref, sources),
      }
      ctx.setPageData(data)
    } catch (error) {
      if (ctx.isStale()) return
      renderPageError(container, ctx, error)
      return
    }
  }
  container.innerHTML = ''
  const skeleton = buildSkeleton(container, ctx, `数据快照 ${ctx.page.ref.key} · ${ctx.revisionLabel}`)
  renderRelationSection(skeleton.relationSlot, ctx, data.relations)

  const scope = document.createElement('p')
  scope.className = 'evidence-dataset-scope'
  skeleton.detailBox.append(scope)

  const filterRow = document.createElement('div')
  filterRow.className = 'evidence-filter-row'
  const filter = document.createElement('input')
  filter.type = 'search'
  filter.className = 'evidence-filter'
  filter.placeholder = '筛选本页内容'
  filter.setAttribute('aria-label', '筛选本页已加载内容')
  filter.value = ctx.page.filter
  const filterNote = document.createElement('span')
  filterNote.className = 'evidence-filter-note'
  filterNote.textContent = '仅筛选本页已加载内容'
  const clearFilter = makeButton('清除筛选')
  clearFilter.addEventListener('click', () => {
    filter.value = ''
    filter.dispatchEvent(new Event('input'))
    filter.focus()
  })
  filterRow.append(filter, filterNote, clearFilter)
  const matchLine = document.createElement('p')
  matchLine.className = 'evidence-filter-count'
  skeleton.detailBox.append(filterRow, matchLine)

  const wrap = document.createElement('div')
  wrap.className = 'evidence-table-wrap'
  const emptyNote = document.createElement('p')
  emptyNote.className = 'evidence-dataset-empty'
  emptyNote.setAttribute('role', 'status')
  skeleton.detailBox.append(wrap, emptyNote)
  wrap.addEventListener('scroll', () => {
    if (!ctx.isStale()) ctx.updatePage({ tableScroll: wrap.scrollLeft })
  }, { passive: true })

  const moreSlot = document.createElement('div')
  moreSlot.className = 'evidence-pagination'
  moreSlot.setAttribute('role', 'group')
  moreSlot.setAttribute('aria-label', '数据快照分页')
  skeleton.detailBox.append(moreSlot)

  const actions = document.createElement('div')
  actions.className = 'evidence-dataset-actions'
  actions.setAttribute('role', 'group')
  actions.setAttribute('aria-label', '数据快照操作')
  const actionNote = document.createElement('p')
  actionNote.className = 'evidence-dataset-note'
  actionNote.setAttribute('role', 'status')
  skeleton.detailBox.append(actions, actionNote)

  const visibleRows = (): (string | null)[][] => {
    const keyword = ctx.page.filter.trim().toLowerCase()
    if (!keyword) return data!.detail.rows
    return data!.detail.rows.filter((row) =>
      row.some((value) => value !== null && String(value).toLowerCase().includes(keyword)),
    )
  }

  const renderBody = () => {
    const { detail } = data!
    scope.textContent =
      `完整快照共 ${detail.rowCountTotal} 行 · 预览序号 ${detail.rows.length ? detail.offset + 1 : 0}–${detail.offset + detail.rows.length} · 第 ${ctx.page.datasetPageIndex + 1} 页` +
      (detail.truncatedByBudget ? ' · 已按响应预算截断' : '')
    const rows = visibleRows()
    const keyword = ctx.page.filter.trim()
    clearFilter.hidden = !keyword
    emptyNote.hidden = rows.length > 0
    emptyNote.textContent = rows.length ? '' : detail.rowCountTotal === 0
      ? '此快照没有数据行。'
      : keyword && detail.rows.length > 0
        ? '本页没有匹配内容，可清除筛选查看本页数据。'
        : '本页没有可预览的数据行，请查看快照范围说明。'
    matchLine.textContent = keyword ? `本页匹配 ${rows.length} / ${detail.rows.length} 行` : ''
    matchLine.hidden = !keyword
    if (keyword && !rows.length) {
      matchLine.textContent += ' · 未对完整数据集执行搜索'
    }
    renderTable(wrap, detail.columns, rows, ctx)
    moreSlot.innerHTML = ''
    if (ctx.page.datasetPageIndex > 0) {
      const previous = makeButton('上一页', 'ui-button evidence-previous')
      previous.addEventListener('click', () => void changePage(ctx.page.datasetPageIndex - 1))
      moreSlot.append(previous)
    }
    if (detail.nextCursor) {
      const next = makeButton('下一页', 'ui-button evidence-more')
      next.addEventListener('click', () => void changePage(ctx.page.datasetPageIndex + 1, detail.nextCursor))
      moreSlot.append(next)
    }
  }

  let paging = false
  const changePage = async (index: number, nextCursor?: string | null) => {
    if (paging || ctx.isStale()) return
    const cursor = nextCursor ?? ctx.page.datasetCursors[index]
    paging = true
    moreSlot.querySelectorAll<HTMLButtonElement>('button').forEach(button => { button.disabled = true })
    try {
      const page = await ctx.client.datasetPreview(ctx.page.ref.key, { limit: 50, ...(cursor ? { cursor } : {}) }, ctx.signal)
      if (ctx.isStale()) return
      data!.detail = {
        columns: page.columns, rows: [...page.rows], rowCountTotal: page.rowCountTotal,
        offset: page.offset, nextCursor: page.nextCursor, truncatedByBudget: page.truncatedByBudget,
      }
      const cursors = nextCursor
        ? [...ctx.page.datasetCursors.slice(0, index), nextCursor] : ctx.page.datasetCursors
      ctx.updatePage({ datasetCursors: cursors, datasetPageIndex: index })
      renderBody()
    } catch (error) {
      if (ctx.isStale()) return
      // 失败不改变游标、当前数据或筛选；保留分页按钮以便重试。
      const failure = document.createElement('span')
      failure.className = 'evidence-more-error'
      failure.setAttribute('role', 'status')
      failure.textContent = errorInfo(error).message || '加载失败'
      moreSlot.querySelector('.evidence-more-error')?.remove()
      moreSlot.append(failure)
      if (error instanceof ReportEditorApiError && error.code === 'cursor_invalid') {
        moreSlot.querySelector('.evidence-cursor-reset')?.remove()
        const reset = makeButton('重新加载第一页', 'ui-button evidence-cursor-reset')
        reset.addEventListener('click', () => void changePage(0))
        moreSlot.append(reset)
      }
      moreSlot.querySelectorAll<HTMLButtonElement>('button').forEach(button => { button.disabled = false })
    } finally {
      paging = false
    }
  }

  filter.addEventListener('input', () => {
    ctx.updatePage({ filter: filter.value })
    renderBody()
  })

  if (ctx.downloadEnabled) {
    const download = makeButton('下载此快照')
    download.addEventListener('click', () => void downloadSnapshot(download))
    actions.append(download)
    const copy = makeButton('复制本页')
    copy.addEventListener('click', () => void copyVisible())
    actions.append(copy)
    actionNote.textContent = '下载为完整快照，不含本页筛选；复制仅含当前可见行。'
  } else {
    const copy = makeButton('复制本页')
    copy.addEventListener('click', () => void copyVisible())
    actions.append(copy)
    actionNote.textContent = '复制仅含当前可见行。'
  }

  const downloadSnapshot = async (button: HTMLButtonElement) => {
    button.disabled = true
    try {
      const response = await fetch(ctx.client.datasetDownloadUrl(ctx.page.ref.key), {
        method: 'HEAD',
        credentials: 'same-origin',
        signal: ctx.signal,
      })
      if (ctx.isStale()) return
      if (response.ok) {
        const link = document.createElement('a')
        link.href = ctx.client.datasetDownloadUrl(ctx.page.ref.key)
        link.download = ctx.page.ref.label
        document.body.append(link)
        link.click()
        link.remove()
      } else if (response.status === 403) {
        actionNote.textContent = '当前会话（分享链接）无权下载原始文件'
      } else if (response.status === 409) {
        actionNote.textContent = '文件完整性校验失败，已拒绝下载'
      } else if (response.status === 410) {
        actionNote.textContent = '编辑会话或数据快照已过期，请重新打开报告或核对来源保留期'
      } else if (response.status === 404) {
        actionNote.textContent = '来源不存在或不在当前修订中'
      } else {
        actionNote.textContent = '下载失败，请稍后重试'
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return
      if (!ctx.isStale()) actionNote.textContent = '网络异常，下载失败'
    } finally {
      button.disabled = false
    }
  }

  const copyVisible = async () => {
    const rows = visibleRows()
    const lines = [
      data!.detail.columns.join('\t'),
      ...rows.map((row) => row.map((value) => value ?? '').join('\t')),
    ]
    try {
      await navigator.clipboard.writeText(lines.join('\n'))
      if (!ctx.isStale()) actionNote.textContent = `已复制本页可见 ${rows.length} 行`
    } catch {
      if (!ctx.isStale()) actionNote.textContent = '复制不可用，请手动选择表格内容复制'
    }
  }

  renderBody()
  finishRender(container, ctx, skeleton.title)
}

// ---------------------------------------------------------------------------
// 图表页
// ---------------------------------------------------------------------------

interface ChartPageData {
  detail: {
    source: TraceChartSource
    offset: number
  }
  relations: EvidenceRelations
}

async function renderChartPage(container: HTMLElement, ctx: EvidencePageContext): Promise<void> {
  let data = ctx.pageData<ChartPageData>()
  if (!data) {
    showLoading(container)
    try {
      const source = await ctx.client.chartSource(ctx.page.ref.key, { limit: 20, offset: ctx.page.chartOffset }, ctx.signal)
      if (ctx.isStale()) return
      data = { detail: { source, offset: ctx.page.chartOffset }, relations: assembleChartRelations(ctx.page.ref, source) }
      ctx.setPageData(data)
    } catch (error) {
      if (ctx.isStale()) return
      renderPageError(container, ctx, error)
      return
    }
  }
  container.innerHTML = ''
  const { source } = data.detail
  const skeleton = buildSkeleton(
    container,
    ctx,
    `图表 ${source.chartId} · 图像 ${formatBytes(source.image.size)} · ${ctx.revisionLabel}`,
  )
  renderRelationSection(skeleton.relationSlot, ctx, data.relations)

  const info = document.createElement('div')
  info.className = 'evidence-chart-info'
  const datasetsLine = document.createElement('p')
  datasetsLine.textContent = `数据集：${source.datasetIds.length ? source.datasetIds.join('、') : '未登记'}`
  info.append(datasetsLine)
  for (const noteText of source.transformNotes) {
    const p = document.createElement('p')
    p.textContent = noteText
    info.append(p)
  }
  skeleton.detailBox.append(info)

  const plotBox = document.createElement('div')
  skeleton.detailBox.append(plotBox)

  const moreSlot = document.createElement('div')
  skeleton.detailBox.append(moreSlot)

  const renderPlots = () => {
    plotBox.innerHTML = ''
    for (const plot of data!.detail.source.plotData) {
      const heading = document.createElement('h2')
      heading.textContent = plot.role ? `作图数据（${plot.role}）` : '作图数据'
      plotBox.append(heading)
      const wrap = document.createElement('div')
      wrap.className = 'evidence-table-wrap'
      renderTable(wrap, plot.columns, plot.rows as (string | null)[][])
      plotBox.append(wrap)
      const range = document.createElement('p')
      range.className = 'evidence-plot-range'
      range.textContent = `共 ${plot.rowCount} 行 · ` + (plot.rows.length
        ? `预览序号 ${plot.offset + 1}–${plot.offset + plot.rows.length}` : '当前页无预览记录')
      plotBox.append(range)
    }
    moreSlot.innerHTML = ''
    const pageNumber = document.createElement('span')
    pageNumber.textContent = `第 ${Math.floor(data!.detail.offset / 20) + 1} 页`
    moreSlot.append(pageNumber)
    if (data!.detail.offset > 0) {
      const previous = makeButton('上一页', 'ui-button evidence-previous')
      previous.addEventListener('click', () => void changePage(Math.max(0, data!.detail.offset - 20)))
      moreSlot.append(previous)
    }
    if (data!.detail.source.plotData.some((plot) => plot.truncated)) {
      const next = makeButton('下一页', 'ui-button evidence-more')
      next.addEventListener('click', () => void changePage(data!.detail.offset + 20))
      moreSlot.append(next)
    }
  }

  let paging = false
  const changePage = async (offset: number) => {
    if (paging || ctx.isStale()) return
    paging = true
    moreSlot.querySelectorAll<HTMLButtonElement>('button').forEach(button => { button.disabled = true })
    try {
      const next = await ctx.client.chartSource(ctx.page.ref.key, { limit: 20, offset }, ctx.signal)
      if (ctx.isStale()) return
      data!.detail = { source: next, offset }
      ctx.updatePage({ chartOffset: offset })
      renderPlots()
    } catch (error) {
      if (ctx.isStale()) return
      const failure = document.createElement('span')
      failure.className = 'evidence-more-error'
      failure.textContent = errorInfo(error).message || '加载失败'
      moreSlot.querySelector('.evidence-more-error')?.remove()
      moreSlot.append(failure)
      moreSlot.querySelectorAll<HTMLButtonElement>('button').forEach(button => { button.disabled = false })
    } finally {
      paging = false
    }
  }

  renderPlots()
  finishRender(container, ctx, skeleton.title)
}

// ---------------------------------------------------------------------------
// 引用页
// ---------------------------------------------------------------------------

interface SubjectPageData extends DraftValidation {
  detail: TraceSubjectInfo
  relations: EvidenceRelations
  validation: TraceValidation | null
}

async function renderSubjectPage(container: HTMLElement, ctx: EvidencePageContext): Promise<void> {
  let data = ctx.pageData<SubjectPageData>()
  if (!data) {
    showLoading(container)
    try {
      const sources = await ctx.loadSources()
      if (ctx.isStale()) return
      const subject = sources.subjects?.find((item) => item.subjectId === ctx.page.ref.key)
      if (!subject) throw new ReportEditorApiError(404, 'source_missing')
      data = { detail: subject, relations: assembleSubjectRelations(ctx.page.ref, subject), validation: null }
      ctx.setPageData(data)
    } catch (error) {
      if (ctx.isStale()) return
      renderPageError(container, ctx, error)
      return
    }
  }
  await refreshDraftValidation(data, ctx, container)
  if (ctx.isStale()) return
  container.innerHTML = ''
  const { detail } = data
  const skeleton = buildSkeleton(container, ctx, `${ctx.revisionLabel} · 引用 ${detail.subjectId}`)

  if (data.validation) {
    const value = makeStatusRow(skeleton.statusArea, '引用状态', 'citation')
    const entryResult = data.validation.subjects.find((item) => item.subjectId === detail.subjectId)
    const chip = document.createElement('span')
    chip.className = 'evidence-status-chip'
    chip.dataset.status = entryResult?.status ?? 'unbound'
    chip.textContent = entryResult
      ? (CITATION_STATUS_LABELS[entryResult.status] ?? entryResult.status)
      : '未绑定'
    value.append(chip)
    if (entryResult?.warnings?.length) {
      const warning = document.createElement('div')
      warning.className = 'evidence-warning'
      for (const note of entryResult.warnings) {
        const item = document.createElement('p')
        item.textContent = note
        warning.append(item)
      }
      skeleton.statusArea.append(warning)
    }
  }

  if (!data.validation && ctx.getDraft()) {
    makeStatusRow(skeleton.statusArea, '引用状态', 'citation').textContent = '当前草稿引用状态未确认'
  }

  renderRelationSection(skeleton.relationSlot, ctx, data.relations)

  const identity = document.createElement('div')
  identity.className = 'evidence-subject-identity'
  const kind = document.createElement('p')
  kind.textContent = `引用类型：${SUBJECT_KIND_LABELS[detail.subjectKind] ?? detail.subjectKind}`
  identity.append(kind)
  const locatorParts: string[] = []
  if (detail.locator.sectionId) locatorParts.push(`章节 ${detail.locator.sectionId}`)
  if (detail.locator.tableId) locatorParts.push(`表格 ${detail.locator.tableId}`)
  if (detail.locator.rowKey) locatorParts.push(`行 ${detail.locator.rowKey}`)
  if (detail.locator.columnKey) locatorParts.push(`列 ${detail.locator.columnKey}`)
  if (detail.locator.chartId) locatorParts.push(`图表 ${detail.locator.chartId}`)
  const locator = document.createElement('p')
  locator.textContent = `位置：${locatorParts.length ? locatorParts.join(' · ') : '未登记位置'}`
  identity.append(locator)
  skeleton.detailBox.append(identity)

  const heading = document.createElement('h2')
  heading.textContent = '关联事实与计算'
  const list = document.createElement('ul')
  list.className = 'evidence-subject-links'
  for (const factRef of detail.factRefs) {
    if (!factRef.factId) continue
    const li = document.createElement('li')
    const jump = makeButton(`事实 ${factRef.factId}`, 'ui-button evidence-link')
    bindEvidenceNavigation(jump, {
      kind: 'fact', key: factRef.factId, analysisId: factRef.analysisId, label: factRef.factId,
    }, ctx)
    li.append(jump)
    list.append(li)
  }
  if (detail.computationId) {
    const li = document.createElement('li')
    const jump = makeButton(`计算 ${detail.computationId}`, 'ui-button evidence-link')
    bindEvidenceNavigation(jump, {
      kind: 'computation', key: detail.computationId, label: detail.computationId,
    }, ctx)
    li.append(jump)
    list.append(li)
  }
  if (!list.children.length) {
    const li = document.createElement('li')
    li.textContent = '没有登记的关联对象'
    list.append(li)
  }
  skeleton.detailBox.append(heading, list)

  const locate = makeButton('定位正文', 'ui-button evidence-locate')
  locate.addEventListener('click', () => ctx.locateSubject(detail.subjectId))
  skeleton.detailBox.append(locate)
  finishRender(container, ctx, skeleton.title)
}
