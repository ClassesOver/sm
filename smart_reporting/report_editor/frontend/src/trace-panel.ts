import { ReportEditorApiError, type ReportEditorClient } from './api'
import type {
  TraceChartInfo,
  TraceComputationInfo,
  TraceDatasetInfo,
  TraceDrilldownMetric,
  TraceDrilldownPage,
  TraceFactDetail,
  TracePreviewPage,
} from './api'
import { createModal } from './modal'

/**
 * 数据追溯面板（B5）：数据集 / 事实 / 图表 / 计算记录四个视图，对接
 * /api/sources、/api/facts、/api/charts、/api/computations 与预览接口。
 *
 * 状态语义（计划 B5-4/5）：
 * - loading：切换对象立即进入加载态并取消上一次请求（AbortController）；
 * - empty：修订无来源索引时如实提示，不猜测；
 * - missing/stale/无权限/完整性失败：按稳定错误码给出明确文案与重试；
 * - 下载原始 CSV 前先探测权限，403 时禁用并说明原因，不让浏览器跳错误页。
 */

type TraceTab = 'datasets' | 'facts' | 'charts' | 'computations' | 'drilldowns'

const TAB_LABELS: Record<TraceTab, string> = {
  datasets: '数据快照',
  facts: '事实',
  charts: '图表',
  computations: '计算记录',
  drilldowns: '下钻',
}

const TRACE_ERROR_LABELS: Record<string, string> = {
  source_missing: '来源不存在或不在当前修订中',
  // 会话过期（含分享会话）与服务器故障不同：重试无意义，应从报告列表重新打开。
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

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function text(value: unknown): string {
  return value === null || value === undefined ? '—' : String(value)
}

export function createTracePanel(root: HTMLElement, client: ReportEditorClient) {
  const modal = createModal({
    root,
    closeLabel: '关闭来源面板',
    labelledBy: 'trace-title',
    variant: 'wide',
    onRequestClose: () => closePanel(),
    content: `<div class="panel-header">
        <div>
          <h2 id="trace-title">数据来源</h2>
          <p class="panel-subtitle">查看生成本报告的数据快照、事实、图表作图数据与计算记录</p>
        </div>
      </div>
      <div class="panel-body trace-panel">
        <div class="trace-tabs" role="tablist" aria-label="来源类别"></div>
        <div class="trace-status" data-trace="status" role="status" aria-live="polite"></div>
        <div class="trace-list" data-trace="list"></div>
        <div class="trace-detail" data-trace="detail" hidden></div>
      </div>`,
  })

  const overlay = modal.overlay
  const statusBox = overlay.querySelector<HTMLElement>('[data-trace="status"]')!
  const listBox = overlay.querySelector<HTMLElement>('[data-trace="list"]')!
  const detailBox = overlay.querySelector<HTMLElement>('[data-trace="detail"]')!
  const tabList = overlay.querySelector<HTMLElement>('.trace-tabs')!
  const tabs: HTMLButtonElement[] = []
  const tabButtons = new Map<TraceTab, HTMLButtonElement>()
  for (const tab of Object.keys(TAB_LABELS) as TraceTab[]) {
    const button = document.createElement('button')
    button.type = 'button'
    button.role = 'tab'
    button.className = 'trace-tab'
    button.dataset.traceTab = tab
    button.textContent = TAB_LABELS[tab]
    button.setAttribute('aria-selected', 'false')
    button.addEventListener('click', () => showTab(tab))
    tabList.append(button)
    tabs.push(button)
    tabButtons.set(tab, button)
  }

  let activeTab: TraceTab = 'datasets'
  let controller: AbortController | null = null
  let generation = 0
  let isOpen = false
  let retryAction: (() => void) | null = null
  let downloadEnabled = true

  const beginRequest = (): AbortSignal => {
    controller?.abort()
    controller = new AbortController()
    generation += 1
    return controller.signal
  }

  const isCurrentRequest = (signal: AbortSignal): boolean =>
    isOpen && controller?.signal === signal && !signal.aborted

  // 关闭（按钮/遮罩/Esc 共用）必须作废在途请求并清空内容，否则迟到的
  // 响应或错误会把已隐藏的面板状态改写，甚至触发下载跳转。
  function closePanel() {
    isOpen = false
    controller?.abort()
    controller = null
    clearContent()
    setStatus('')
    modal.close()
  }

  const setStatus = (message: string, kind: 'loading' | 'info' | 'error' = 'info') => {
    statusBox.textContent = message
    statusBox.dataset.state = kind
    statusBox.hidden = !message
  }

  const clearContent = () => {
    listBox.innerHTML = ''
    listBox.hidden = true
    detailBox.innerHTML = ''
    detailBox.hidden = true
    retryAction = null
  }

  const errorLabel = (error: unknown): { message: string; retryable: boolean } => {
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

  const showError = (error: unknown, retry: () => void) => {
    const { message, retryable } = errorLabel(error)
    if (!message) return
    clearContent()
    setStatus(message, 'error')
    if (retryable) {
      const button = document.createElement('button')
      button.type = 'button'
      button.className = 'ui-button trace-retry'
      button.textContent = '重试'
      button.addEventListener('click', retry)
      statusBox.append(' ', button)
      retryAction = retry
    }
  }

  const showTab = (tab: TraceTab) => {
    activeTab = tab
    tabs.forEach((button) => {
      const selected = button.dataset.traceTab === tab
      button.setAttribute('aria-selected', selected ? 'true' : 'false')
      button.classList.toggle('is-active', selected)
    })
    clearContent()
    setStatus('加载中…', 'loading')
    if (tab === 'datasets') void loadDatasets()
    else if (tab === 'facts') void loadFacts()
    else if (tab === 'charts') void loadCharts()
    else if (tab === 'computations') void loadComputations()
    else void loadDrilldowns()
  }

  // ------------------------------------------------------------------
  // 数据快照
  // ------------------------------------------------------------------

  const loadDatasets = async () => {
    const signal = beginRequest()
    try {
      const payload = await client.sources(signal)
      if (!isCurrentRequest(signal)) return
      if (!payload.available) {
        if (payload.reason === 'snapshot_expired') {
          setStatus('数据快照已超过保留期，登记信息仍可查看，明细不可用')
          renderDatasetList(payload.datasets ?? [], false)
          return
        }
        setStatus('当前修订没有来源索引（旧报告或来源未登记）')
        return
      }
      setStatus('')
      renderDatasetList(payload.datasets ?? [])
    } catch (error) {
      if (!isCurrentRequest(signal)) return
      showError(error, loadDatasets)
    }
  }

  const renderDatasetList = (datasets: TraceDatasetInfo[], available = true) => {
    if (!datasets.length) {
      setStatus('当前修订没有登记数据快照')
      return
    }
    listBox.hidden = false
    listBox.innerHTML = ''
    for (const dataset of datasets) {
      const item = document.createElement('div')
      item.className = 'trace-item'
      item.innerHTML = `<div class="trace-item-main">
          <span class="trace-item-title"></span>
          <span class="trace-item-meta"></span>
        </div>
        <div class="trace-item-actions"></div>`
      item.querySelector<HTMLElement>('.trace-item-title')!.textContent =
        dataset.filename ?? dataset.businessLabel ?? dataset.datasetId
      item.querySelector<HTMLElement>('.trace-item-meta')!.textContent =
        `${dataset.rowCount} 行 · ${formatBytes(dataset.size)} · ` +
        `${dataset.materializedAt ?? '物化时间未知'} · ${dataset.periodRoles.join('/')}`
      const actions = item.querySelector<HTMLElement>('.trace-item-actions')!
      const previewButton = document.createElement('button')
      previewButton.type = 'button'
      previewButton.className = 'ui-button'
      previewButton.textContent = '预览'
      previewButton.disabled = !available
      previewButton.addEventListener('click', () => void openDatasetPreview(dataset))
      const downloadButton = document.createElement('button')
      downloadButton.type = 'button'
      downloadButton.className = 'ui-button'
      downloadButton.textContent = '下载原始'
      downloadButton.disabled = !available
      downloadButton.addEventListener('click', () =>
        void downloadDataset(dataset, downloadButton),
      )
      actions.append(previewButton)
      if (downloadEnabled) actions.append(downloadButton)
      listBox.append(item)
    }
  }

  const openDatasetPreview = async (dataset: TraceDatasetInfo, cursor?: string | null) => {
    const signal = beginRequest()
    setStatus('加载预览…', 'loading')
    try {
      const page = await client.datasetPreview(
        dataset.datasetId,
        { limit: 50, cursor: cursor ?? undefined },
        signal,
      )
      if (!isCurrentRequest(signal)) return
      setStatus(
        `共 ${page.rowCountTotal} 行 · 显示第 ${page.offset + 1}–${page.offset + page.rows.length} 行` +
          (page.truncatedByBudget ? ' · 已按响应预算截断' : ''),
      )
      renderPreviewTable(page, {
        onMore: page.nextCursor ? () => void openDatasetPreview(dataset, page.nextCursor) : null,
        onBack: () => void loadDatasets(),
      })
    } catch (error) {
      if (!isCurrentRequest(signal)) return
      showError(error, () => void openDatasetPreview(dataset, cursor))
    }
  }

  const downloadDataset = async (
    dataset: TraceDatasetInfo,
    button: HTMLButtonElement,
  ) => {
    const signal = beginRequest()
    button.disabled = true
    try {
      const response = await fetch(client.datasetDownloadUrl(dataset.datasetId), {
        method: 'HEAD',
        credentials: 'same-origin',
        signal,
      })
      if (!isCurrentRequest(signal)) return
      const url = client.datasetDownloadUrl(dataset.datasetId)
      if (response.ok) {
        window.location.href = url
      } else if (response.status === 403) {
        setStatus('当前会话（分享链接）无权下载原始文件', 'error')
      } else {
        setStatus('下载失败，请稍后重试', 'error')
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return
      if (isCurrentRequest(signal)) setStatus('网络异常，下载失败', 'error')
    } finally {
      button.disabled = false
    }
  }

  // ------------------------------------------------------------------
  // 预览表格（数据集与作图数据共用）
  // ------------------------------------------------------------------

  const renderPreviewTable = (
    page: { columns: string[]; rows: (string | null)[][] },
    options: { onMore: (() => void) | null; onBack?: () => void },
  ) => {
    listBox.hidden = true
    detailBox.hidden = false
    detailBox.innerHTML = ''
    if (options.onBack) {
      const back = document.createElement('button')
      back.type = 'button'
      back.className = 'ui-button trace-back'
      back.textContent = '← 返回'
      back.addEventListener('click', options.onBack)
      detailBox.append(back)
    }
    const scroll = document.createElement('div')
    scroll.className = 'trace-table-wrap'
    const table = document.createElement('table')
    table.className = 'trace-table'
    const header = table.insertRow()
    for (const column of page.columns) {
      const cell = document.createElement('th')
      cell.scope = 'col'
      cell.textContent = column
      header.append(cell)
    }
    for (const row of page.rows) {
      const tr = table.insertRow()
      for (const value of row) {
        const cell = tr.insertCell()
        cell.textContent = text(value)
      }
    }
    scroll.append(table)
    detailBox.append(scroll)
    if (options.onMore) {
      const more = document.createElement('button')
      more.type = 'button'
      more.className = 'ui-button trace-more'
      more.textContent = '加载更多'
      more.addEventListener('click', options.onMore)
      detailBox.append(more)
    }
  }

  // ------------------------------------------------------------------
  // 事实
  // ------------------------------------------------------------------

  const loadFacts = async () => {
    const signal = beginRequest()
    try {
      const payload = await client.facts(signal)
      if (!isCurrentRequest(signal)) return
      if (!payload.available || !payload.analyses?.length) {
        setStatus('当前修订没有登记事实文件')
        return
      }
      setStatus(
        '事实按分析登记；具体数值事实通过正文引用与计算记录定位（后续批次接入正文入口）',
      )
      listBox.hidden = false
      listBox.innerHTML = ''
      for (const analysis of payload.analyses) {
        const item = document.createElement('div')
        item.className = 'trace-item'
        item.innerHTML = `<div class="trace-item-main">
            <span class="trace-item-title"></span>
            <span class="trace-item-meta"></span>
          </div>`
        item.querySelector<HTMLElement>('.trace-item-title')!.textContent = analysis.analysisId
        item.querySelector<HTMLElement>('.trace-item-meta')!.textContent =
          `${analysis.contentKind === 'deterministic_bundle' ? '确定性事实' : '补充分析证据'}` +
          (analysis.fileSize ? ` · ${formatBytes(analysis.fileSize)}` : '')
        listBox.append(item)
      }
    } catch (error) {
      if (!isCurrentRequest(signal)) return
      showError(error, loadFacts)
    }
  }

  const showFactDetail = async (analysisId: string, factId: string) => {
    const signal = beginRequest()
    setStatus('加载事实…', 'loading')
    try {
      const detail = await client.factDetail(analysisId, factId, signal)
      if (!isCurrentRequest(signal)) return
      setStatus('')
      renderFactDetail(detail)
    } catch (error) {
      if (!isCurrentRequest(signal)) return
      showError(error, () => void showFactDetail(analysisId, factId))
    }
  }

  const renderFactDetail = (detail: TraceFactDetail) => {
    listBox.hidden = true
    detailBox.hidden = false
    detailBox.innerHTML = ''
    const back = document.createElement('button')
    back.type = 'button'
    back.className = 'ui-button trace-back'
    back.textContent = '← 返回'
    back.addEventListener('click', () => showTab('computations'))
    detailBox.append(back)
    const section = document.createElement('div')
    section.className = 'trace-fact'
    const entry = detail.entry as Record<string, unknown>
    const formula = typeof entry.formula === 'string' ? entry.formula : ''
    const unit = typeof entry.unit === 'string' ? entry.unit : ''
    section.innerHTML = `<div class="trace-fact-value"></div>
      ${formula ? `<div class="trace-fact-formula"></div>` : ''}
      ${detail.inputFactRefs.length ? '<ul class="trace-fact-inputs"></ul>' : ''}
      ${detail.warnings.length ? '<ul class="trace-fact-warnings"></ul>' : ''}`
    const valueLine = `${detail.factKind} · ${text(detail.displayValue)}${unit ? ` ${unit}` : ''}`
    section.querySelector<HTMLElement>('.trace-fact-value')!.textContent = valueLine
    if (formula) section.querySelector<HTMLElement>('.trace-fact-formula')!.textContent = `公式：${formula}`
    const inputs = section.querySelector<HTMLUListElement>('.trace-fact-inputs')
    if (inputs) {
      for (const ref of detail.inputFactRefs) {
        const li = document.createElement('li')
        li.textContent = `输入事实 ${ref.factId ?? ref.analysisId}`
        if (ref.factId) {
          const jump = document.createElement('button')
          jump.type = 'button'
          jump.className = 'ui-button trace-link'
          jump.textContent = '查看'
          jump.addEventListener('click', () => void showFactDetail(ref.analysisId, ref.factId!))
          li.append(' ', jump)
        }
        inputs.append(li)
      }
    }
    const warnings = section.querySelector<HTMLUListElement>('.trace-fact-warnings')
    if (warnings) {
      for (const warning of detail.warnings) {
        const li = document.createElement('li')
        li.textContent = warning
        warnings.append(li)
      }
    }
    detailBox.append(section)
  }

  // ------------------------------------------------------------------
  // 图表
  // ------------------------------------------------------------------

  const loadCharts = async () => {
    const signal = beginRequest()
    try {
      const payload = await client.charts(signal)
      if (!isCurrentRequest(signal)) return
      if (!payload.available || !payload.charts?.length) {
        setStatus('当前修订没有登记来源的图表（旧图无作图数据登记）')
        return
      }
      setStatus('')
      listBox.hidden = false
      listBox.innerHTML = ''
      for (const chart of payload.charts) {
        const item = document.createElement('div')
        item.className = 'trace-item'
        item.innerHTML = `<div class="trace-item-main">
            <span class="trace-item-title"></span>
            <span class="trace-item-meta"></span>
          </div>
          <div class="trace-item-actions"></div>`
        item.querySelector<HTMLElement>('.trace-item-title')!.textContent = chart.chartId
        item.querySelector<HTMLElement>('.trace-item-meta')!.textContent =
          `${chart.plotDataFileCount} 份作图数据 · ${formatBytes(chart.imageSize)}`
        const button = document.createElement('button')
        button.type = 'button'
        button.className = 'ui-button'
        button.textContent = '查看来源'
        button.addEventListener('click', () => void openChartSource(chart))
        item.querySelector<HTMLElement>('.trace-item-actions')!.append(button)
        listBox.append(item)
      }
    } catch (error) {
      if (!isCurrentRequest(signal)) return
      showError(error, loadCharts)
    }
  }

  const openChartSource = async (chart: Pick<TraceChartInfo, 'chartId'>, offset = 0) => {
    const signal = beginRequest()
    setStatus('加载图表来源…', 'loading')
    try {
      const source = await client.chartSource(
        chart.chartId,
        { limit: 20, offset },
        signal,
      )
      if (!isCurrentRequest(signal)) return
      setStatus('')
      listBox.hidden = true
      detailBox.hidden = false
      detailBox.innerHTML = ''
      const back = document.createElement('button')
      back.type = 'button'
      back.className = 'ui-button trace-back'
      back.textContent = '← 返回'
      back.addEventListener('click', () => void loadCharts())
      detailBox.append(back)
      const info = document.createElement('div')
      info.className = 'trace-chart-info'
      const datasetsLine = document.createElement('p')
      datasetsLine.textContent = `数据集：${source.datasetIds.join('、')}`
      info.append(datasetsLine)
      for (const note of source.transformNotes) {
        const p = document.createElement('p')
        p.textContent = note
        info.append(p)
      }
      detailBox.append(info)
      for (const plot of source.plotData) {
        const heading = document.createElement('h3')
        heading.textContent = plot.role ? `作图数据（${plot.role}）` : '作图数据'
        detailBox.append(heading)
        renderPlotTable(plot.rows as (string | null)[][], plot.columns, {
          onMore: plot.truncated
            ? () => void openChartSource(chart, offset + plot.limit)
            : null,
        })
      }
    } catch (error) {
      if (!isCurrentRequest(signal)) return
      showError(error, () => void openChartSource(chart, offset))
    }
  }

  const renderPlotTable = (
    rows: (string | null)[][],
    columns: string[],
    options: { onMore: (() => void) | null },
  ) => {
    const scroll = document.createElement('div')
    scroll.className = 'trace-table-wrap'
    const table = document.createElement('table')
    table.className = 'trace-table'
    const header = table.insertRow()
    for (const column of columns) {
      const th = document.createElement('th')
      th.scope = 'col'
      th.textContent = column
      header.append(th)
    }
    for (const row of rows) {
      const tr = table.insertRow()
      for (const value of row) {
        const cell = tr.insertCell()
        cell.textContent = text(value)
      }
    }
    scroll.append(table)
    detailBox.append(scroll)
    if (options.onMore) {
      const more = document.createElement('button')
      more.type = 'button'
      more.className = 'ui-button trace-more'
      more.textContent = '加载更多'
      more.addEventListener('click', options.onMore)
      detailBox.append(more)
    }
  }

  // ------------------------------------------------------------------
  // 快照内单维度下钻（B7）
  // ------------------------------------------------------------------

  const loadDrilldowns = async () => {
    const signal = beginRequest()
    try {
      const payload = await client.sources(signal)
      if (!isCurrentRequest(signal)) return
      if (!payload.available) {
        setStatus('当前修订没有来源索引')
        return
      }
      if (!payload.drilldown?.enabled) {
        setStatus('当前会话无权执行快照下钻')
        return
      }
      const metrics = payload.drilldown.metrics ?? []
      if (!metrics.length) {
        setStatus('当前修订没有满足输入条件的下钻指标')
        return
      }
      setStatus('下钻只使用生成报告时登记的快照、范围和聚合规则')
      listBox.hidden = false
      listBox.innerHTML = ''
      for (const metric of metrics) {
        const item = document.createElement('div')
        item.className = 'trace-item'
        const main = document.createElement('div')
        main.className = 'trace-item-main'
        const title = document.createElement('span')
        title.className = 'trace-item-title'
        title.textContent = metric.metricCode
        const meta = document.createElement('span')
        meta.className = 'trace-item-meta'
        meta.textContent = `${metric.aggregation} · ${metric.unit ?? '无单位'} · ${metric.datasetId}`
        main.append(title, meta)
        const actions = document.createElement('div')
        actions.className = 'trace-item-actions'
        for (const dimension of metric.dimensions) {
          const button = document.createElement('button')
          button.type = 'button'
          button.className = 'ui-button'
          button.textContent = `按${dimension.label}下钻`
          button.addEventListener('click', () =>
            void openDrilldown(metric, dimension.code, dimension.label),
          )
          actions.append(button)
        }
        item.append(main, actions)
        listBox.append(item)
      }
    } catch (error) {
      if (!isCurrentRequest(signal)) return
      showError(error, loadDrilldowns)
    }
  }

  const openDrilldown = async (
    metric: TraceDrilldownMetric,
    dimensionCode: string,
    dimensionLabel: string,
    cursor?: string | null,
  ) => {
    const signal = beginRequest()
    setStatus('按冻结快照计算中…', 'loading')
    try {
      const page = await client.drilldownMetric(
        metric,
        dimensionCode,
        { limit: 50, cursor },
        signal,
      )
      if (!isCurrentRequest(signal)) return
      const reconciliation = page.reconciliation
      const state =
        reconciliation.passed === true
          ? '与报告原值核对一致'
          : reconciliation.passed === false
            ? '与报告原值核对不一致'
            : '未登记可核对的报告原值'
      setStatus(
        `${dimensionLabel} · 共 ${page.groupCountTotal} 组 · ${state} · ` +
          `${page.calculation.description} · 快照 ${page.snapshot.sha256.slice(0, 12)}`,
      )
      renderDrilldown(page, {
        onMore: page.nextCursor
          ? () => void openDrilldown(
              metric,
              dimensionCode,
              dimensionLabel,
              page.nextCursor,
            )
          : null,
      })
    } catch (error) {
      if (!isCurrentRequest(signal)) return
      showError(error, () =>
        void openDrilldown(metric, dimensionCode, dimensionLabel, cursor),
      )
    }
  }

  const renderDrilldown = (
    page: TraceDrilldownPage,
    options: { onMore: (() => void) | null },
  ) => {
    listBox.hidden = true
    detailBox.hidden = false
    detailBox.innerHTML = ''
    const back = document.createElement('button')
    back.type = 'button'
    back.className = 'ui-button trace-back'
    back.textContent = '← 返回'
    back.addEventListener('click', () => void loadDrilldowns())
    detailBox.append(back)
    renderPlotTable(
      page.rows.map((row) => [row.group, row.value === null ? null : String(row.value)]),
      ['分组', `值${page.unit ? `（${page.unit}）` : ''}`],
      options,
    )
  }

  // ------------------------------------------------------------------
  // 计算记录
  // ------------------------------------------------------------------

  const loadComputations = async () => {
    const signal = beginRequest()
    try {
      const payload = await client.computations(signal)
      if (!isCurrentRequest(signal)) return
      if (!payload.available || !payload.computations?.length) {
        setStatus('当前修订没有登记补充分析计算记录')
        return
      }
      setStatus('')
      listBox.hidden = false
      listBox.innerHTML = ''
      for (const computation of payload.computations) {
        const item = document.createElement('div')
        item.className = 'trace-item'
        item.innerHTML = `<div class="trace-item-main">
            <span class="trace-item-title"></span>
            <span class="trace-item-meta"></span>
          </div>
          <div class="trace-item-actions"></div>`
        item.querySelector<HTMLElement>('.trace-item-title')!.textContent = computation.method
        item.querySelector<HTMLElement>('.trace-item-meta')!.textContent =
          `${VERIFICATION_LABELS[computation.verification] ?? computation.verification} · ` +
          `${REPRODUCIBILITY_LABELS[computation.reproducibility] ?? computation.reproducibility}`
        const button = document.createElement('button')
        button.type = 'button'
        button.className = 'ui-button'
        button.textContent = '计算说明'
        button.addEventListener('click', () => void openComputation(computation))
        item.querySelector<HTMLElement>('.trace-item-actions')!.append(button)
        listBox.append(item)
      }
    } catch (error) {
      if (!isCurrentRequest(signal)) return
      showError(error, loadComputations)
    }
  }

  const openComputation = async (
    computation: Pick<TraceComputationInfo, 'computationId'>,
    depth = 2,
  ) => {
    const signal = beginRequest()
    setStatus('加载计算记录…', 'loading')
    try {
      const detail = await client.computationDetail(
        computation.computationId,
        depth,
        signal,
      )
      if (!isCurrentRequest(signal)) return
      setStatus('')
      listBox.hidden = true
      detailBox.hidden = false
      detailBox.innerHTML = ''
      const back = document.createElement('button')
      back.type = 'button'
      back.className = 'ui-button trace-back'
      back.textContent = '← 返回'
      back.addEventListener('click', () => void loadComputations())
      detailBox.append(back)
      const section = document.createElement('div')
      section.className = 'trace-computation'
      const env = detail.environment
        ? Object.entries(detail.environment)
            .map(([key, value]) => `${key} ${value}`)
            .join(' · ')
        : '环境信息缺失（复算条件有限）'
      const lines: [string, string][] = [
        ['方法', detail.method],
        ['执行', `${detail.executionId ?? '—'} · ${env}`],
        [
          '核对状态',
          `${VERIFICATION_LABELS[detail.verification] ?? detail.verification} · ` +
            `${REPRODUCIBILITY_LABELS[detail.reproducibility] ?? detail.reproducibility}`,
        ],
      ]
      for (const [label, value] of lines) {
        const p = document.createElement('p')
        p.textContent = `${label}：${value}`
        section.append(p)
      }
      for (const note of detail.limitations) {
        const p = document.createElement('p')
        p.className = 'trace-limitation'
        p.textContent = note
        section.append(p)
      }
      const heading = document.createElement('h3')
      heading.textContent = '输出事实'
      section.append(heading)
      const outputs = document.createElement('ul')
      outputs.className = 'trace-computation-outputs'
      for (const ref of detail.outputFactRefs.slice(0, 20)) {
        const li = document.createElement('li')
        li.textContent = `${ref.analysisId} ${ref.jsonPointer}`
        if (ref.factKey) {
          const jump = document.createElement('button')
          jump.type = 'button'
          jump.className = 'ui-button trace-link'
          jump.textContent = '查看事实'
          jump.addEventListener('click', () =>
            void showFactDetail(ref.analysisId, ref.factKey!),
          )
          li.append(' ', jump)
        }
        outputs.append(li)
      }
      section.append(outputs)
      detailBox.append(section)
    } catch (error) {
      if (!isCurrentRequest(signal)) return
      showError(error, () => void openComputation(computation, depth))
    }
  }

  const openSubject = async (subjectId: string): Promise<void> => {
    isOpen = true
    modal.open()
    clearContent()
    setStatus('定位来源对象…', 'loading')
    const signal = beginRequest()
    try {
      const payload = await client.sources(signal)
      if (!isCurrentRequest(signal)) return
      const subject = payload.subjects?.find((item) => item.subjectId === subjectId)
      if (!subject) {
        showError(new ReportEditorApiError(404, 'source_missing'), () =>
          void openSubject(subjectId),
        )
        return
      }
      if (subject.locator.chartId) {
        activeTab = 'charts'
        void openChartSource({ chartId: subject.locator.chartId })
        return
      }
      const fact = subject.factRefs.find((item) => item.factId)
      if (fact?.factId) {
        activeTab = 'facts'
        void showFactDetail(fact.analysisId, fact.factId)
        return
      }
      if (subject.computationId) {
        activeTab = 'computations'
        void openComputation({ computationId: subject.computationId })
        return
      }
      setStatus('来源对象已登记，但没有可打开的明细')
    } catch (error) {
      if (!isCurrentRequest(signal)) return
      showError(error, () => void openSubject(subjectId))
    }
  }

  return {
    open() {
      isOpen = true
      modal.open()
      showTab(activeTab)
    },
    close() {
      closePanel()
    },
    setDownloadEnabled(enabled: boolean) {
      downloadEnabled = enabled
    },
    setDrilldownEnabled(enabled: boolean) {
      tabButtons.get('drilldowns')!.hidden = !enabled
      if (!enabled && activeTab === 'drilldowns') activeTab = 'datasets'
    },
    openSubject,
  }
}
