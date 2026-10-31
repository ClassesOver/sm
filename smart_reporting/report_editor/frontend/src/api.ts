/** 与 PDF/Word、静态图共用的服务端主题令牌。 */
export interface ReportVisualTheme {
  ink: string
  muted: string
  grid: string
  gridline: string
  chartPalette: string[]
}

export interface ReportDocument {
  path: string
  markdown: string
  sha256: string
  sourceRevision?: number
  csrfToken?: string
  visualTheme?: ReportVisualTheme
  chartAiEnabled?: boolean
  tableAiEnabled?: boolean
  templatesEnabled?: boolean
  lineageFeatures?: {
    panel: boolean
    download: boolean
    drilldown: boolean
    exportSources: boolean
  }
}

export interface ExportResult {
  reportId?: string
  revision: number
  requestId?: string
  pdf?: { downloadUrl: string; path?: string; size?: number }
  word?: { downloadUrl: string; path?: string; size?: number }
  editor?: { openUrl: string }
  validation?: { ok: boolean; issues: { code?: string; message?: string }[] }
}

export interface ShareResult { openUrl: string; expiresAt: string }

interface ExportJobState {
  exportId: string
  status: 'running' | 'succeeded' | 'failed'
  requestId?: string
  result?: ExportResult
  error?: { code: string; message?: string; status?: number }
}

export interface ReportHistoryItem {
  revision: number
  sha256: string
  markdown?: string
  source?: string
  createdAt?: string | null
  note?: string
}
export interface ReportHistoryPage { items: ReportHistoryItem[]; total: number; hasMore: boolean }

export type SelectionAIAction = 'polish' | 'shorten' | 'expand' | 'professional'

// ---------------------------------------------------------------------------
// 数据追溯（B5）：sources / datasets / facts / charts / computations
// ---------------------------------------------------------------------------

export interface TraceDatasetInfo {
  datasetId: string
  sourceType: string
  requirementId: string
  filename: string | null
  businessLabel: string | null
  sqlHash?: string | null
  querySql?: string | null
  rowCount: number
  size: number
  materializedAt: string | null
  periodRoles: string[]
  queryWindowId: string
}

export interface TraceSources {
  narrativeSections?: {
    sectionCode: string
    findingIds: string[]
    groupingReason: string | null
  }[]
  citations?: { citationId: string; datasetId: string }[]
  facts?: {
    analysisId: string; factId: string; factKind: string; label: string; datasetIds: string[]
    analysisName?: string | null
    name?: string; periodStart?: string | null; periodEnd?: string | null; periodRoles?: string[]
    comparisonType?: string | null; displayValue?: unknown; unit?: string | null
  }[]
  available: boolean
  reason?: string | null
  datasets?: TraceDatasetInfo[]
  subjects?: TraceSubjectInfo[]
  drilldown?: {
    enabled: boolean
    metrics: TraceDrilldownMetric[]
    subjects: TraceDrilldownSubject[]
  }
}

export interface TraceSubjectInfo {
  subjectId: string
  subjectKind: 'text_claim' | 'table_cell' | 'chart' | 'chart_caption'
  locator: {
    sectionId?: string | null
    tableId?: string | null
    rowKey?: string | null
    columnKey?: string | null
    chartId?: string | null
  }
  factRefs: TraceFactRefLite[]
  computationId?: string | null
}

export interface TraceDrilldownMetric {
  metricCode: string
  datasetId: string
  aggregation: string
  unit: string | null
  dimensions: { code: string; label: string }[]
}

export interface TraceDrilldownSubject {
  subjectId: string
  metrics: TraceDrilldownMetric[]
}

export interface TraceDrilldownPage {
  metricCode: string
  datasetId: string
  dimensionCode: string
  aggregation: string
  rows: { group: string | null; value: number | null }[]
  groupCountTotal: number
  offset: number
  limit: number
  nextCursor: string | null
  unit: string | null
  reconciliation: {
    expectedValue: number | null
    observedValue: number | null
    difference: number | null
    passed: boolean | null
  }
  snapshot: { datasetId: string; sha256: string }
  scope: {
    kind: 'registered_snapshot'
    fixed: Record<string, string>
    period: { start: string; end: string } | null
  }
  calculation: { aggregation: string; description: string }
}

export interface TracePreviewPage {
  datasetId: string
  columns: string[]
  rows: (string | null)[][]
  rowCountTotal: number
  offset: number
  limit: number
  nextCursor: string | null
  truncatedCells: number
  truncatedByBudget: boolean
  cellTruncationNote: string | null
}

export interface TraceDatasetColumns {
  datasetId: string
  /** 当前会话可预览的列（受限列不回显）。 */
  columns: string[]
  /** 是否存在受限列（不含列名与数量）。 */
  restricted: boolean
  maxColumnsPerPage: number
}

export interface TraceAnalysisInfo {
  analysisId: string
  contentKind: string
  fileSize?: number
}

export interface TraceFactRefLite {
  analysisId: string
  factId: string | null
}

export interface TraceFactDetail {
  analysisId: string
  analysisName?: string | null
  factId: string | null
  factKind: string
  jsonPointer?: string
  displayValue: number | string | null
  displayUnit?: string | null
  entry: Record<string, unknown>
  inputFactRefs: TraceFactRefLite[]
  warnings: string[]
}

export interface TraceChartInfo {
  chartId: string
  datasetIds: string[]
  datasetIdsRegistered: boolean
  plotDataFileCount: number
  plotDataKind: string
  transformNotes: string[]
  /** 工作区相对路径；编辑器据此把正文图片定位到登记图表。 */
  imagePath: string
  imageSize: number
  /** AI 改图后的当前图形形态（未改图或旧图无此信息时为空）。 */
  visualForm?: string | null
  /** 该图成功登记过的 AI 改图次数。 */
  editCount?: number
}

export interface ChartAIAvailability {
  available: boolean
  standardAvailable?: boolean
  standardReason?: string
  codingAvailable?: boolean
  baseImagePath?: string
  expectedSha256?: string
  standardChartCapabilities?: { forms: string[]; families?: Record<string, unknown> }
  /** 服务端按已核验作图数据给出的粗粒度概况，仅用于推荐；读取失败时缺省。 */
  dataProfile?: ChartDataProfile
  /** 服务端按数据概况给出的推荐；编辑器唯一的推荐来源，缺省时只展示按图形的通用建议。 */
  recommendations?: ChartRecommendations | null
  reason?: string
  chartId?: string
}

export interface ChartRecommendations {
  suggestions: { id: string; text: string }[]
  suppress: string[]
  cautions: Record<string, string>
}

export interface ChartDataProfile {
  inputCount: number
  rowCount: number
  categoryCount: number
  textFieldCount: number
  numericFieldCount: number
  unitCount: number
  hasPeriod: boolean
  hasNegative: boolean
  magnitudeRatio: number | null
}

export interface TableAIEditRequest {
  instruction: string
  baseBody?: string
  previousEditId?: string
  expectedSha256?: string
}

export interface TableTemplateApplyRequest {
  templateId: string
  instruction?: string
  baseBody?: string
  previousEditId?: string
  expectedSha256?: string
}

export interface TableAIEditState {
  editId: string
  tableId: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  stage?: string
  markdown?: string
  newTableId?: string
  baseCaption?: string | null
  analysisId?: string
  review?: {
    columns: string[]
    rows: { label: string; cells: { text: string; status: string; column: string; source?: { analysisId: string; factIds: string[]; selector: string | null } }[] }[]
    flagged: { row: string; text: string }[]
  }
  warnings?: string[]
  skipped?: { request: string; reason: string }[]
  error?: { code: string; message: string; status?: number }
}

export interface EditorTemplateInfo {
  templateId: string
  name: string
  available: boolean
  reason?: string
  /** 服务端按该图表/表格绑定的数据源计算的推荐标记，全目录至多一个。 */
  recommended?: boolean
  recommendationReason?: string
}

export interface ChartAIEditRequest {
  instruction: string
  baseImagePath?: string
  baseTitle?: string
  baseAltText?: string
  previousEditId?: string
  expectedSha256?: string
}

export interface ChartStandardEditRequest {
  standard: Record<string, unknown>
  inheritPreviousStandard?: boolean
  baseImagePath: string
  expectedSha256: string
  previousEditId?: string
  baseTitle?: string
  baseAltText?: string
  title?: string
  altText?: string
}

export interface ChartAIEditChanges {
  title?: string | null
  altText?: string | null
  visualForm?: string | null
  plotDataUnchanged: boolean
  /** L2 换绑后新增的数据绑定摘要（analysisId/dataPath/fields）。 */
  dataBindingsAdded?: { analysisId: string; dataPath: string; fields: string[] }[]
}

export interface ChartAIEditSuccess {
  status: 'succeeded'
  editId: string
  chartId: string
  imagePath: string
  /** 新图在正文中的引用形式（相对修订目录）。 */
  imageSrc: string
  /** 完整且有序的分页；包含兼容顶层字段所指的第一页。 */
  pages?: ChartAIEditPage[]
  level: string[]
  changes: ChartAIEditChanges
  warnings: string[]
  skipped: { request: string; reason: string }[]
  visualInspection: { format?: string; width?: number; height?: number; reviewed: boolean }
  planningRoute?: 'direct' | 'ai'
  renderingRoute?: 'standard' | 'mixed' | 'coding'
  stageTimingsMs?: Record<string, number>
}

export interface ChartAIEditPage {
  pageNumber: number
  pageCount: number
  imagePath: string
  imageSrc: string
  title: string | null
  altText: string | null
  sha256?: string
}

export interface ChartAIEditState {
  editId: string
  chartId: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  stage?: string
  stageTimingsMs?: Record<string, number>
  error?: { code: string; message: string; status?: number; skipped?: { request: string; reason: string }[] }
}

export type ChartAIEditResult = ChartAIEditSuccess & { status: 'succeeded' }

export interface TracePlotDataPreview {
  fileResourceId: string
  role: string | null
  columns: string[]
  rowCount: number
  offset: number
  limit: number
  rows: unknown[][]
  truncated: boolean
  source?: Record<string, unknown> | null
}

export interface ChartEditHistoryItem {
  editId: string
  instruction: string
  level: string[]
  createdAt: string
}

export interface TraceChartSource {
  available: boolean
  chartId: string
  datasetIds: string[]
  transformNotes: string[]
  computationId: string | null
  image: { size: number; sha256: string }
  plotData: TracePlotDataPreview[]
  /** AI 改图历史（最新在前）；无改图时为空数组。 */
  editHistory?: ChartEditHistoryItem[]
}

export interface TraceValidation {
  sourceIssues?: { resourceId: string; code: string }[]
  quality?: { status: 'evaluated' | 'failed'; inputSha256?: string; allKeyFactsEvaluated: false; warningLedger?: { qualityInputSha256: string; originalIssueCount: number; groups: { groupId: string; issueIndices: number[] }[] }; questionCoverage?: { required: number | null; evaluated: number; answered: number; effectiveAnswerRate: number | null; evaluationStatus: string }; issues: { code: string; subjectId?: string | null; reasons?: string[] }[] }
  reviewNotices?: { claimId: string; sectionId: string | null; kind: 'numeric_unverified' | 'source_review'; originalText?: string | null; reason?: string | null; occurrences: number; bound: boolean }[]
  draftSha256: string
  warnings?: string[]
  subjects: {
    subjectId: string
    claimId: string
    sectionId: string | null
    status: 'valid' | 'stale' | 'unbound'
    sourceStatus?: 'available' | 'integrity_failed'
    bindingStatus?: 'bound' | 'invalidated' | 'unbound'
    supportStatus?: 'supported' | 'unknown' | 'conflicting'
    checkStatus?: 'completed' | 'failed'
    sourceIssues?: { resourceId: string; code: string }[]
    /** 当前修订登记值；正文提取值仅在 comparable=true 且字段齐全时提供。 */
    factValue: unknown
    /** 已核验数值引用签发时的精确显示文本；恢复时保留原单位、精度及幅度写法。 */
    restoreText?: string | null
    draftValue?: number
    draftUnit?: string | null
    draftPeriods?: string[]
    /** 服务端确认的百分点幅度方向；用于恢复时保留方向词，避免“下降-1”。 */
    draftDirection?: 'decrease' | 'increase' | null
    comparable?: boolean
    warnings?: string[]
    unit?: string | null
    periods?: unknown
    formula?: string | null
    /** 服务端按导出附录规则转换的中文口径。 */
    formulaText?: string | null
    scope?: unknown
    datasetIds?: string[]
    /** 数值取得方式：直接取登记事实、服务端按登记原值派生，或按运算式由服务端重算。 */
    computation?: 'registered' | 'derived' | 'calc' | null
    /** 模型对当前正文的语义解释，独立于确定性数值和来源核验。 */
    semanticCheck?: {
      method: 'model_context_interpretation_v1'
      status: 'interpreted' | 'invalidated' | 'unavailable'
      interpretation: { claimId: string; scope: { field: string; value: string | null; status: 'resolved' | 'unknown' | 'conflicting'; evidence: string[] }[]; periods: string[]; periodEvidence: string[] }
    } | null
  }[]
  summary: { valid: number; stale: number; unbound: number }
  tables?: {
    tableId: string
    dataCheck?: { status: 'verified' | 'unknown'; scope: 'frozen_cells'; reasons: string[]; checkedCells?: number }
    locations?: TraceTableCellLocation[]
    cells: { valid: number; stale: number; unbound: number }
    copiedCells?: { rowLabel: string; columnKey: string | null; text: string; matches: { rowKey: string; columnKey: string; factKey: string | null }[] }[]
  }[]
  tableSummary?: { valid: number; stale: number; unbound: number; insertedRows: number; copiedCells: number }
  charts?: { chartId: string; editId?: string; imagePath: string | null; status: 'valid' | 'stale' | 'unbound'; semanticCheck?: { status: 'verified' | 'unknown' | 'conflicting'; scope: 'registered_fact_projection'; reasons: string[] }; locationSource?: string | null; dataCheck?: { status: 'verified' | 'unknown'; scope: 'registered_arrays'; reason: string } }[]
}

/** 正文数值与表格单元格共用的冻结数值视图：登记值、单位、期间、口径或可验算算式、取得方式与来源数据集。 */
export interface TraceValueView {
  factValue?: unknown
  unit?: string | null
  periods?: unknown
  formula?: string | null
  formulaText?: string | null
  scope?: unknown
  datasetIds?: string[]
  computation?: 'registered' | 'derived' | 'calc' | null
}

export interface TraceTableCellLocation extends TraceValueView {
  /** 精确位置与业务值状态独立；待复核不阻止查看登记来源。 */
  status?: 'valid' | 'stale'
  rowKey: string
  columnKey: string
  /** 当前草稿的数据行序号（不含表头），列序号包含首列行标签。 */
  rowIndex: number
  columnIndex: number
  rowLabel: string
  text: string
}

export interface TraceComputationInfo {
  computationId: string
  method: string
  methodVersion: string | null
  executionId: string | null
  verification: string
  reproducibility: string
  inputDatasetCount: number
  outputFactCount: number
  scriptSize: number | null
  limitations: string[]
}

export interface TraceComputationDetail {
  computationId: string
  method: string
  parameters: Record<string, unknown>
  executionId: string | null
  environment: Record<string, string> | null
  verification: string
  reproducibility: string
  limitations: string[]
  inputDatasetIds: string[]
  inputFactRefs?: { analysisId: string; factKey: string | null; factKind: string }[]
  preprocessing?: unknown
  outputFactRefs: { analysisId: string; factKey: string | null; factKind: string; jsonPointer: string }[]
  scriptFile: { size: number; sha256: string } | null
  chain: { computationId: string; method: string; inputs?: unknown[] } & Record<string, unknown>
}

export class ReportEditorApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly requestId?: string,
  ) {
    super(code)
  }
}

export class ReportEditorClient {
  private csrfToken = ''

  constructor(
    private readonly basePath: string,
    private readonly fetcher: typeof fetch = fetch,
    private readonly exportPollIntervalMs = 2000,
  ) {}

  async load(): Promise<ReportDocument> {
    const document = await this.request<ReportDocument>('/api/document')
    this.csrfToken = document.csrfToken ?? ''
    return document
  }

  async save(markdown: string, expectedSha256: string): Promise<ReportDocument> {
    return this.request<ReportDocument>('/api/document', {
      method: 'PUT',
      body: JSON.stringify({ markdown, expectedSha256 }),
    })
  }

  async share(): Promise<ShareResult> {
    return this.request<ShareResult>('/api/share', { method: 'POST' })
  }

  async historyPage(limit = 20, offset = 0): Promise<ReportHistoryPage> {
    return this.request<ReportHistoryPage>(`/api/history?limit=${limit}&offset=${offset}`)
  }

  async historyRevision(revision: number): Promise<ReportHistoryItem & { markdown: string }> {
    return this.request<ReportHistoryItem & { markdown: string }>(`/api/history/${revision}`)
  }

  async restoreHistory(revision: number, expectedSha256: string, markdown?: string): Promise<ReportDocument> {
    const document = await this.request<ReportDocument>(`/api/history/${revision}/restore`, {
      method: 'POST',
      body: JSON.stringify({ expectedSha256, ...(markdown === undefined ? {} : { markdown }) }),
    })
    this.csrfToken = document.csrfToken ?? this.csrfToken
    return document
  }

  async export(
    expectedSha256: string,
    settings: Record<string, boolean> = {},
    note = '',
  ): Promise<ExportResult> {
    // 渲染与验收可能持续数分钟：服务端立即返回后台任务标识，这里轮询到终态，
    // 避免同步请求被网关读超时切断。
    const started = await this.request<ExportJobState>('/api/export', {
      method: 'POST',
      body: JSON.stringify({ expectedSha256, settings, ...(note ? { note } : {}) }),
    })
    const statusPath = `/api/export/${encodeURIComponent(started.exportId)}`
    let transientFailures = 0
    for (;;) {
      await new Promise((resolve) => setTimeout(resolve, this.exportPollIntervalMs))
      let state: ExportJobState
      try {
        state = await this.request<ExportJobState>(statusPath)
        transientFailures = 0
      } catch (error) {
        // 短暂断网不应让仍在服务端运行的导出失败；连续失败才放弃。
        if (error instanceof TypeError && ++transientFailures < 5) continue
        throw error
      }
      if (state.status === 'succeeded' && state.result) {
        return { ...state.result, requestId: state.requestId }
      }
      if (state.status === 'failed') {
        throw new ReportEditorApiError(
          state.error?.status ?? 500,
          state.error?.code ?? 'report_editor_export_failed',
          state.requestId,
        )
      }
    }
  }

  async validateSources(markdown: string, draftSha256: string, signal?: AbortSignal): Promise<TraceValidation> {
    return this.request<TraceValidation>('/api/sources/validate', {
      method: 'POST',
      body: JSON.stringify({ markdown, draftSha256 }),
      signal,
    })
  }

  async sources(signal?: AbortSignal): Promise<TraceSources> {
    return this.request<TraceSources>('/api/sources', { signal })
  }

  async drilldown(
    subjectId: string,
    metric: Pick<TraceDrilldownMetric, 'metricCode' | 'datasetId'>,
    dimensionCode: string,
    options: { limit?: number; cursor?: string | null } = {},
    signal?: AbortSignal,
  ): Promise<TraceDrilldownPage> {
    return this.request<TraceDrilldownPage>(
      `/api/sources/${encodeURIComponent(subjectId)}/drilldown`,
      {
        method: 'POST',
        body: JSON.stringify({
          metricCode: metric.metricCode,
          datasetId: metric.datasetId,
          dimensionCode,
          limit: options.limit ?? 50,
          ...(options.cursor ? { cursor: options.cursor } : {}),
        }),
        signal,
      },
    )
  }

  async drilldownMetric(
    metric: Pick<TraceDrilldownMetric, 'metricCode' | 'datasetId'>,
    dimensionCode: string,
    options: { limit?: number; cursor?: string | null } = {},
    signal?: AbortSignal,
  ): Promise<TraceDrilldownPage> {
    return this.request<TraceDrilldownPage>(
      `/api/drilldowns/${encodeURIComponent(metric.metricCode)}`,
      {
        method: 'POST',
        body: JSON.stringify({
          metricCode: metric.metricCode,
          datasetId: metric.datasetId,
          dimensionCode,
          limit: options.limit ?? 50,
          ...(options.cursor ? { cursor: options.cursor } : {}),
        }),
        signal,
      },
    )
  }

  async datasetPreview(
    datasetId: string,
    options: { limit?: number; cursor?: string | null; columns?: string[] } = {},
    signal?: AbortSignal,
  ): Promise<TracePreviewPage> {
    const params = new URLSearchParams()
    if (options.limit) params.set('limit', String(options.limit))
    if (options.cursor) params.set('cursor', options.cursor)
    // 每列一个 columns 参数：列名可含逗号，不能拼接后由服务端拆分。
    for (const column of options.columns ?? []) params.append('columns', column)
    const query = params.toString()
    return this.request<TracePreviewPage>(
      `/api/datasets/${encodeURIComponent(datasetId)}/preview${query ? `?${query}` : ''}`,
      { signal },
    )
  }

  async datasetColumns(datasetId: string, signal?: AbortSignal): Promise<TraceDatasetColumns> {
    return this.request<TraceDatasetColumns>(
      `/api/datasets/${encodeURIComponent(datasetId)}/columns`,
      { signal },
    )
  }

  datasetDownloadUrl(datasetId: string): string {
    return `${this.basePath}/api/datasets/${encodeURIComponent(datasetId)}/download`
  }

  async facts(signal?: AbortSignal): Promise<{ available: boolean; analyses?: TraceAnalysisInfo[] }> {
    return this.request('/api/facts', { signal })
  }

  async factDetail(
    analysisId: string,
    factId: string,
    signal?: AbortSignal,
  ): Promise<TraceFactDetail> {
    return this.request<TraceFactDetail>(
      `/api/facts/${encodeURIComponent(analysisId)}/${encodeURIComponent(factId)}`,
      { signal },
    )
  }

  async charts(signal?: AbortSignal): Promise<{ available: boolean; charts?: TraceChartInfo[] }> {
    return this.request('/api/charts', { signal })
  }

  async chartSource(
    chartId: string,
    options: { limit?: number; offset?: number; editId?: string } = {},
    signal?: AbortSignal,
  ): Promise<TraceChartSource> {
    const params = new URLSearchParams()
    if (options.limit) params.set('limit', String(options.limit))
    if (options.offset) params.set('offset', String(options.offset))
    if (options.editId) params.set('edit_id', options.editId)
    const query = params.toString()
    return this.request<TraceChartSource>(
      `/api/charts/${encodeURIComponent(chartId)}/source${query ? `?${query}` : ''}`,
      { signal },
    )
  }

  async computations(
    signal?: AbortSignal,
  ): Promise<{ available: boolean; computations?: TraceComputationInfo[] }> {
    return this.request('/api/computations', { signal })
  }

  async chartAiAvailability(chartId: string, signal?: AbortSignal): Promise<ChartAIAvailability> {
    return this.request<ChartAIAvailability>(
      `/api/charts/${encodeURIComponent(chartId)}/ai-edits/availability`,
      { signal },
    )
  }

  async chartTemplates(chartId: string, signal?: AbortSignal): Promise<{ chartId: string; templates: EditorTemplateInfo[] }> {
    return this.request(`/api/charts/${encodeURIComponent(chartId)}/templates`, { signal })
  }

  async startChartTemplateEdit(chartId: string, payload: { templateId: string; instruction?: string; baseImagePath?: string; baseTitle?: string; baseAltText?: string; previousEditId?: string; expectedSha256?: string }): Promise<{ editId: string; status: string }> {
    return this.request(`/api/charts/${encodeURIComponent(chartId)}/template-edits`, { method: 'POST', body: JSON.stringify(payload) })
  }

  async tableAiAvailability(tableId: string, signal?: AbortSignal): Promise<{ available: boolean; reason?: string; tableId?: string }> {
    return this.request(`/api/tables/${encodeURIComponent(tableId)}/ai-edits/availability`, { signal })
  }

  async tableTemplates(tableId: string, signal?: AbortSignal): Promise<{ tableId: string; templates: EditorTemplateInfo[] }> {
    return this.request(`/api/tables/${encodeURIComponent(tableId)}/templates`, { signal })
  }

  async startTableAiEdit(tableId: string, payload: TableAIEditRequest): Promise<{ editId: string; status: string }> {
    return this.request(`/api/tables/${encodeURIComponent(tableId)}/ai-edits`, { method: 'POST', body: JSON.stringify(payload) })
  }

  async startTableTemplateEdit(tableId: string, payload: TableTemplateApplyRequest): Promise<{ editId: string; status: string }> {
    return this.request(`/api/tables/${encodeURIComponent(tableId)}/template-edits`, { method: 'POST', body: JSON.stringify(payload) })
  }

  async tableAiEditStatus(tableId: string, editId: string): Promise<TableAIEditState> {
    return this.request(`/api/tables/${encodeURIComponent(tableId)}/ai-edits/${encodeURIComponent(editId)}`)
  }

  async cancelTableAiEdit(tableId: string, editId: string): Promise<void> {
    await this.request(`/api/tables/${encodeURIComponent(tableId)}/ai-edits/${encodeURIComponent(editId)}/cancel`, { method: 'POST' })
  }

  tableEditRecord(editId: string): Promise<{ editId: string; tableId: string; newTableId: string; markdown: string }> {
    return this.request(`/api/table-edits/${encodeURIComponent(editId)}`)
  }

  tableEditRecordByTableId(tableId: string): Promise<{ editId: string; tableId: string; newTableId: string; markdown: string }> {
    return this.request(`/api/table-edits/by-table/${encodeURIComponent(tableId)}`)
  }

  startChartAiEdit(
    chartId: string,
    payload: ChartAIEditRequest,
  ): Promise<{ editId: string; status: string; requestId?: string }> {
    return this.request(`/api/charts/${encodeURIComponent(chartId)}/ai-edits`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  }

  startChartStandardEdit(chartId: string, payload: ChartStandardEditRequest): Promise<{ editId: string; status: string }> {
    return this.request(`/api/charts/${encodeURIComponent(chartId)}/standard-edits`, {
      method: 'POST', body: JSON.stringify(payload),
    })
  }

  chartAiEditStatus(chartId: string, editId: string, waitMs = 0): Promise<ChartAIEditState> {
    return this.request<ChartAIEditState>(
      `/api/charts/${encodeURIComponent(chartId)}/ai-edits/${encodeURIComponent(editId)}${waitMs ? `?waitMs=${waitMs}` : ''}`,
    )
  }

  /** 已登记改图的图表归属：正文图片已替换为改图结果时据此继续改图。 */
  chartEditRecord(editId: string): Promise<{ editId: string; chartId: string; imagePath: string; visualForm?: string; pages?: ChartAIEditPage[] }> {
    return this.request(`/api/chart-edits/${encodeURIComponent(editId)}`)
  }

  async cancelChartAiEdit(chartId: string, editId: string): Promise<void> {
    await this.request(
      `/api/charts/${encodeURIComponent(chartId)}/ai-edits/${encodeURIComponent(editId)}/cancel`,
      { method: 'POST' },
    )
  }

  async computationDetail(
    computationId: string,
    depth = 2,
    signal?: AbortSignal,
  ): Promise<TraceComputationDetail> {
    return this.request<TraceComputationDetail>(
      `/api/computations/${encodeURIComponent(computationId)}?depth=${depth}`,
      { signal },
    )
  }

  async reportEvent(payload: {
    event: string
    durationMs?: number
    format?: 'pdf' | 'word'
    errorCode?: string
    surface?: 'chart' | 'table'
    source?: 'start' | 'dialog' | 'refine' | 'free'
    kind?: 'oneclick' | 'ai'
    suggestionId?: string
    outcome?: 'succeeded' | 'failed' | 'cancelled' | 'accepted' | 'discarded'
  }): Promise<void> {
    const response = await this.fetcher.call(window, `${this.basePath}/api/events`, {
      body: JSON.stringify(payload),
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        ...(this.csrfToken ? { 'X-CSRF-Token': this.csrfToken } : {}),
      },
      method: 'POST',
    })
    if (!response.ok) throw new ReportEditorApiError(response.status, 'report_editor_event_failed')
  }

  async *streamRewrite(
    selection: string,
    action: SelectionAIAction,
    signal: AbortSignal,
  ): AsyncIterable<string> {
    const response = await this.fetcher.call(window, `${this.basePath}/api/ai/rewrite`, {
      body: JSON.stringify({ selection, action }),
      credentials: 'same-origin',
      headers: {
        Accept: 'text/markdown',
        'Content-Type': 'application/json',
        ...(this.csrfToken ? { 'X-CSRF-Token': this.csrfToken } : {}),
      },
      method: 'POST',
      signal,
    })
    if (!response.ok) {
      const payload = await parseErrorBody(response)
      throw new ReportEditorApiError(
        response.status,
        payload.detail?.code ?? 'report_editor_ai_failed',
      )
    }
    if (!response.body) throw new ReportEditorApiError(502, 'report_editor_ai_empty_stream')

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      const chunk = decoder.decode(value, { stream: true })
      if (chunk) yield chunk
    }
    const remaining = decoder.decode()
    if (remaining) yield remaining
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await this.fetcher.call(window, `${this.basePath}${path}`, {
      ...init,
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...(this.csrfToken ? { 'X-CSRF-Token': this.csrfToken } : {}),
        ...init.headers,
      },
    })
    const parsed: unknown = await response.json().catch(() => undefined)
    // 成功状态却不是 JSON 对象（网关/登录页 HTML、截断响应）：按上游异常处理，
    // 不把空对象当作合法数据交给页面渲染。
    if (response.ok && (parsed === null || typeof parsed !== 'object')) {
      throw new ReportEditorApiError(502, 'report_editor_response_invalid')
    }
    const payload = (parsed ?? {}) as {
      detail?: { code?: string; requestId?: string }
    }
    if (!response.ok) {
      throw new ReportEditorApiError(
        response.status,
        payload.detail?.code ?? 'report_editor_request_failed',
        payload.detail?.requestId,
      )
    }
    return payload as T
  }
}

async function parseErrorBody(
  response: Response,
): Promise<{ detail?: { code?: string } }> {
  try {
    return (await response.json()) as { detail?: { code?: string } }
  } catch {
    return {}
  }
}
