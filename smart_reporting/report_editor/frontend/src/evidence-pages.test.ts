import { afterEach, describe, expect, it, vi } from 'vitest'

import { ReportEditorClient } from './api'
import { createEvidenceGraph, mergeEvidenceGraph } from './evidence-graph'
import { formatDifference, graphLabel, groupDigits, renderEvidencePage, snapshotFileName, tsvCell, type EvidencePageContext } from './evidence-pages'
import { createEvidenceState, type EvidenceObjectRef, type EvidencePage } from './evidence-state'
import { markdownSha256 } from './source-validation'

function makeClient(fetcher: typeof fetch) {
  return new ReportEditorClient('/reports/v1/editor/report-1/1', fetcher)
}

const SOURCES_PAYLOAD = {
  available: true,
  datasets: [
    {
      datasetId: 'dataset-url-abc0001',
      sourceType: 'url_csv',
      requirementId: 'attachment-001',
      filename: '收入明细.csv',
      businessLabel: null,
      rowCount: 4,
      size: 125,
      materializedAt: '2026-09-29T08:00:00Z',
      periodRoles: ['current'],
      queryWindowId: 'current',
    },
  ],
  subjects: [
    {
      subjectId: 'sub-cccccccccccccccc',
      subjectKind: 'text_claim',
      locator: { sectionId: 'section_002' },
      factRefs: [{ analysisId: 'analysis_001', factId: 'fact-aaaaaaaaaaaaaaaa' }],
      computationId: 'comp-001',
    },
  ],
  drilldown: {
    enabled: true,
    metrics: [
      {
        metricCode: 'income_total',
        datasetId: 'dataset-url-abc0001',
        aggregation: 'sum',
        unit: '元',
        dimensions: [{ code: 'branch', label: '院区' }],
      },
    ],
    subjects: [
      {
        subjectId: 'sub-cccccccccccccccc',
        metrics: [
          {
            metricCode: 'income_total',
            datasetId: 'dataset-url-abc0001',
            aggregation: 'sum',
            unit: '元',
            dimensions: [],
          },
        ],
      },
    ],
  },
}

const FACT_DETAIL = {
  analysisId: 'analysis_001',
  factId: 'fact-aaaaaaaaaaaaaaaa',
  factKind: 'metric',
  displayValue: 12450,
  entry: { unit: '万元', formula: 'sum(revenue)' },
  inputFactRefs: [{ analysisId: 'analysis_001', factId: 'fact-input' }],
  warnings: [],
}

const COMPUTATION_DETAIL = {
  computationId: 'comp-001',
  method: 'sum',
  parameters: { column: 'revenue' },
  executionId: 'exec-1',
  environment: { python: '3.12' },
  verification: 'verified',
  reproducibility: 'reproducible',
  limitations: [],
  inputDatasetIds: ['dataset-url-abc0001'],
  outputFactRefs: [
    {
      analysisId: 'analysis_001',
      factKey: 'fact-aaaaaaaaaaaaaaaa',
      factKind: 'metric',
      jsonPointer: '/metrics/revenue',
    },
  ],
  scriptFile: null,
  chain: { computationId: 'comp-001', method: 'sum' },
}

const PREVIEW_PAGE_1 = {
  datasetId: 'dataset-url-abc0001',
  columns: ['branch', 'revenue'],
  rows: [
    ['华东', '1000'],
    ['华北', '1200'],
  ],
  rowCountTotal: 4,
  offset: 0,
  limit: 50,
  nextCursor: 'cursor-2',
  truncatedCells: 0,
  truncatedByBudget: false,
  cellTruncationNote: null,
}

const PREVIEW_PAGE_2 = {
  ...PREVIEW_PAGE_1,
  rows: [
    ['华南', '900'],
    ['西南', '800'],
  ],
  offset: 2,
  nextCursor: null,
}

interface PageSetup {
  container: HTMLElement
  ctx: EvidencePageContext
  controller: AbortController
  page: EvidencePage
}

function setupPage(
  fetcher: typeof fetch,
  ref: EvidenceObjectRef,
  overrides: Partial<EvidencePageContext> = {},
): PageSetup {
  const client = makeClient(fetcher)
  const state = createEvidenceState()
  state.openTask(ref)
  const page = state.currentPage()!
  const cache = new WeakMap<EvidencePage, unknown>()
  const controller = new AbortController()
  const container = document.createElement('div')
  const ctx: EvidencePageContext = {
    client,
    page,
    signal: controller.signal,
    isStale: () => controller.signal.aborted,
    revisionLabel: '修订 1',
    downloadEnabled: true,
    drilldownEnabled: true,
    loadSources: () => client.sources(),
    navigate: vi.fn(),
    openBackground: vi.fn(),
    setPreview: vi.fn(),
    updatePage: (patch) => {
      state.updatePage(patch)
    },
    locateSubject: vi.fn(),
    getDraft: () => null,
    pageData: <T,>() => cache.get(page) as T | undefined,
    setPageData: (data: unknown) => cache.set(page, data),
    ...overrides,
  }
  return { container, ctx, controller, page }
}

const json = (payload: unknown) => new Response(JSON.stringify(payload))

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('事实页', () => {
  const FACT_REF: EvidenceObjectRef = {
    kind: 'fact',
    key: 'fact-aaaaaaaaaaaaaaaa',
    analysisId: 'analysis_001',
    label: '华东营收',
  }

  function factFetcher(validation?: unknown): typeof fetch {
    return vi.fn<typeof fetch>().mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.includes('/api/facts/')) return json(FACT_DETAIL)
      if (url.includes('/api/sources/validate')) {
        const result = (
          validation ?? {
            draftSha256: 'x',
            subjects: [
              {
                subjectId: 'sub-cccccccccccccccc',
                claimId: 'claim-1',
                sectionId: 'section_002',
                status: 'stale',
                factValue: 12450,
                unit: '万元',
              },
            ],
            summary: { valid: 0, stale: 1, unbound: 0 },
          }
        ) as Record<string, unknown>
        return json({ ...result, draftSha256: JSON.parse(String(init!.body)).draftSha256 })
      }
      if (url.endsWith('/api/sources')) return json(SOURCES_PAYLOAD)
      if (url.includes('/api/computations/')) return json(COMPUTATION_DETAIL)
      throw new Error(`unexpected ${url}`)
    }) as unknown as typeof fetch
  }

  it('renders three independent status rows and a soft comparability warning', async () => {
    const { container, ctx } = setupPage(factFetcher(), FACT_REF, {
      getDraft: () => ({ markdown: '报告正文', sha256: 'x' }),
    })
    await renderEvidencePage(container, ctx)

    const citation = container.querySelector('[data-status-row="citation"]')!
    expect(citation.textContent).toContain('△ 内容已变更')
    expect(container.querySelector('[data-status-row="verification"]')?.textContent).toContain('数值已核对')
    expect(container.querySelector('[data-status-row="reproducibility"]')?.textContent).toContain('具备复算条件')

    const warning = container.querySelector('.evidence-warning')!
    expect(warning.textContent).toContain('需核对口径')
    expect(warning.textContent).toContain('暂不计算差额')
    expect(warning.textContent).not.toContain('报告当前值')
    const locate = warning.querySelector<HTMLButtonElement>('button')!
    expect(locate.textContent).toBe('定位正文')
    locate.click()
    expect(ctx.locateSubject).toHaveBeenCalledWith('sub-cccccccccccccccc')
    // 软告警不提供「忽略」操作，也不阻塞页面。
    expect(warning.textContent).not.toContain('忽略')
  })

  it('preserves valid citation and verification while showing backend unit and period warnings', async () => {
    const notes = ['单位文本与生成时不一致（生成时 万元）', '期间文本与生成时不一致（生成时 2025-09）']
    const { container, ctx } = setupPage(factFetcher({ draftSha256: 'x',
      subjects: [{ subjectId: 'sub-cccccccccccccccc', status: 'valid', factValue: 12450,
        unit: '万元', periods: ['2025-09'], warnings: notes }],
      summary: { valid: 1, stale: 0, unbound: 0 },
    }), FACT_REF, { getDraft: () => ({ markdown: '2025-10收入12450亿元', sha256: 'x' }) })
    await renderEvidencePage(container, ctx)
    expect(container.querySelector('[data-status-row="citation"]')?.textContent).toContain('引用有效')
    expect(container.querySelector('[data-status-row="verification"]')?.textContent).toContain('数值已核对')
    for (const note of notes) expect(container.querySelector('.evidence-warning')?.textContent).toContain(note)
    expect(container.querySelector('.evidence-warning')?.textContent).not.toContain('差异 +')
  })

  it('shows a soft comparable difference only when the backend provides a trusted draft value', async () => {
    const { container, ctx } = setupPage(factFetcher({
      subjects: [{ subjectId: 'sub-cccccccccccccccc', status: 'stale', factValue: 12450,
        unit: '万元', periods: ['2025-09'], draftValue: 12780, draftUnit: '万元',
        draftPeriods: ['2025-09'], comparable: true }],
      summary: { valid: 0, stale: 1, unbound: 0 },
    }), FACT_REF, { getDraft: () => ({ markdown: '2025-09华东收入12780万元', sha256: 'x' }) })
    await renderEvidencePage(container, ctx)
    const warning = container.querySelector('.evidence-warning')!
    expect(warning.textContent).toContain('正文当前值 12,780 万元')
    expect(warning.textContent).toContain('登记值 12,450 万元')
    expect(warning.textContent).toContain('差异 +330')
    expect(warning.textContent).not.toContain('暂不计算差额')
    expect(container.querySelector('[data-status-row="citation"]')?.textContent).toContain('内容已变更')
    expect(container.querySelector('[data-status-row="verification"]')?.textContent).toContain('数值已核对')
  })

  it.each([
    { name: '完整登记元数据', factValue: 12450, unit: '万元', periods: ['2025-09'], scope: { region: '华东' } },
    { name: '缺少单位', factValue: 12450, unit: null, periods: ['2025-09'], scope: { region: '华东' } },
    { name: '缺少期间', factValue: 12450, unit: '万元', periods: [], scope: { region: '华东' } },
    { name: '缺少口径', factValue: 12450, unit: '万元', periods: ['2025-09'], scope: {} },
    { name: '非数值登记值', factValue: '未提供', unit: '万元', periods: ['2025-09'], scope: { region: '华东' } },
    { name: '登记信息冲突', factValue: 12000, unit: '亿元', periods: ['2025-10'], scope: { region: '华北' } },
  ])('does not treat $name as an extracted current draft value', async ({ name: _name, ...registered }) => {
    const { container, ctx } = setupPage(factFetcher({
      subjects: [{ subjectId: 'sub-cccccccccccccccc', status: 'stale', ...registered }],
      summary: { valid: 0, stale: 1, unbound: 0 },
    }), FACT_REF, { getDraft: () => ({ markdown: '2025-09华东收入12,780万元', sha256: '基准' }) })
    await renderEvidencePage(container, ctx)
    expect(container.querySelector('.evidence-fact-value')?.textContent).toBe('登记值 12,450 万元')
    const warning = container.querySelector('.evidence-warning')!
    expect(warning.textContent).toContain('可比性尚未确认，暂不计算差额')
    expect(warning.textContent).not.toContain('330')
    expect(warning.textContent).not.toContain('报告当前值')
    expect(container.querySelector('[data-status-row="verification"]')?.textContent).toContain('数值已核对')
    warning.querySelector<HTMLButtonElement>('button')!.click()
    expect(ctx.locateSubject).toHaveBeenCalledWith('sub-cccccccccccccccc')
  })

  it('refreshes draft validation after unsaved edits while reusing registered details', async () => {
    const base = factFetcher()
    let draft = { markdown: '初稿', sha256: 'same-base' }
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      if (!String(input).includes('/validate')) return base(input, init)
      const payload = JSON.parse(String(init!.body))
      const changed = payload.markdown === '修改稿'
      expect(payload.draftSha256).toBe(await markdownSha256(payload.markdown))
      return json({
        draftSha256: payload.draftSha256,
        subjects: [{ subjectId: 'sub-cccccccccccccccc', status: changed ? 'stale' : 'valid', factValue: 12450, unit: '万元' }],
        summary: { valid: changed ? 0 : 1, stale: changed ? 1 : 0, unbound: 0 },
      })
    })
    const { container, ctx } = setupPage(fetcher, FACT_REF, { getDraft: () => draft })
    await renderEvidencePage(container, ctx)
    expect(container.querySelector('[data-status-row="citation"]')?.textContent).toContain('引用有效')
    draft = { ...draft, markdown: '修改稿' }
    const changed = document.createElement('div')
    await renderEvidencePage(changed, ctx)
    expect(changed.querySelector('[data-status-row="citation"]')?.textContent).toContain('内容已变更')
    expect(changed.querySelector('.evidence-warning')?.textContent).toContain('需核对口径')
    expect(changed.querySelector('[data-status-row="verification"]')?.textContent).toContain('数值已核对')
    await renderEvidencePage(document.createElement('div'), ctx)
    const urls = fetcher.mock.calls.map(call => String(call[0]))
    expect(urls.filter(url => url.includes('/api/facts/'))).toHaveLength(1)
    expect(urls.filter(url => url.includes('/validate'))).toHaveLength(2)
  })

  it('does not publish an obsolete validation result when the draft changes during the request', async () => {
    const base = factFetcher()
    let draft = { markdown: '初稿', sha256: 'x' }
    let release!: () => void
    let validations = 0
    const fetcher: typeof fetch = async (input, init) => {
      if (!String(input).includes('/validate')) return base(input, init)
      validations += 1
      const first = validations === 1
      if (first) await new Promise<void>(resolve => { release = resolve })
      return json({ draftSha256: JSON.parse(String(init!.body)).draftSha256, subjects: [{ subjectId: 'sub-cccccccccccccccc', status: first ? 'valid' : 'stale', factValue: 12450, unit: '万元' }], summary: { valid: first ? 1 : 0, stale: first ? 0 : 1, unbound: 0 } })
    }
    const { container, ctx } = setupPage(fetcher, FACT_REF, { getDraft: () => draft })
    const rendering = renderEvidencePage(container, ctx)
    await vi.waitFor(() => expect(validations).toBe(1))
    draft = { ...draft, markdown: '修改稿' }
    release()
    await rendering
    expect(validations).toBe(2)
    expect(container.querySelector('[data-status-row="citation"]')?.textContent).not.toContain('引用有效')
    expect(container.querySelector('.evidence-warning')?.textContent).toContain('需核对口径')
  })

  it('rejects a validation response whose digest does not match the current markdown', async () => {
    const base = factFetcher()
    const fetcher: typeof fetch = async (input, init) => {
      if (!String(input).includes('/validate')) return base(input, init)
      return json({ draftSha256: '0'.repeat(64),
        subjects: [{ subjectId: 'sub-cccccccccccccccc', status: 'valid' }],
        summary: { valid: 1, stale: 0, unbound: 0 } })
    }
    const { container, ctx } = setupPage(fetcher, FACT_REF, {
      getDraft: () => ({ markdown: '收入12450万元', sha256: '保存基准' }),
    })
    await renderEvidencePage(container, ctx)
    expect(container.querySelector('[data-status-row="citation"]')?.textContent).toContain('当前草稿引用状态未确认')
    expect(container.querySelector('[data-status-row="citation"]')?.textContent).not.toContain('引用有效')
  })

  it('keeps continuously edited drafts unconfirmed and retries only on the next render', async () => {
    const base = factFetcher()
    let draft = { markdown: '初稿', sha256: '基准' }
    let validations = 0
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      if (!String(input).includes('/validate')) return base(input, init)
      const payload = JSON.parse(String(init!.body))
      validations += 1
      if (validations <= 2) draft = { ...draft, markdown: `请求期间修改${validations}` }
      return json({ draftSha256: payload.draftSha256,
        subjects: [{ subjectId: 'sub-cccccccccccccccc', status: 'valid', factValue: 12450 }],
        summary: { valid: 1, stale: 0, unbound: 0 } })
    })
    const { container, ctx } = setupPage(fetcher, FACT_REF, { getDraft: () => draft })
    await renderEvidencePage(container, ctx)
    expect(validations).toBe(2)
    expect(container.querySelector('[data-status-row="citation"]')?.textContent).toContain('当前草稿引用状态未确认')
    expect(container.querySelector('[data-status-row="citation"]')?.textContent).not.toContain('引用有效')
    expect(container.querySelector('[data-status-row="verification"]')?.textContent).toContain('数值已核对')
    await renderEvidencePage(container, ctx)
    expect(validations).toBe(3)
    expect(container.querySelector('[data-status-row="citation"]')?.textContent).toContain('引用有效')
    expect(fetcher.mock.calls.filter(call => String(call[0]).includes('/api/facts/'))).toHaveLength(1)
    expect(JSON.parse(String(fetcher.mock.calls.filter(call => String(call[0]).includes('/validate')).at(-1)![1]!.body)).markdown).toBe(draft.markdown)
  })

  it('omits the citation row when the draft is unavailable and never guesses', async () => {
    const { container, ctx } = setupPage(factFetcher(), FACT_REF)
    await renderEvidencePage(container, ctx)
    expect(container.querySelector('[data-status-row="citation"]')).toBeNull()
    expect(container.querySelector('[data-status-row="verification"]')?.textContent).toContain('数值已核对')
    expect(container.querySelector('.evidence-fact-value')?.textContent).toContain('登记值 12,450 万元')
    expect(container.querySelector('.evidence-fact-formula')?.textContent).toContain('sum(revenue)')
    // 登记公式与登记值同处摘要区，不再落在关系区之后。
    expect(container.querySelector('.evidence-fact-formula')?.closest('.evidence-detail')).toBeNull()
    expect(container.querySelector('.evidence-fact-formula code')?.textContent).toBe('sum(revenue)')
    // 事实类型以中文显示，不暴露后端枚举值。
    expect(container.querySelector('.evidence-object-note')?.textContent).toContain('指标 · 分析')
    expect(container.querySelector('.evidence-object-note')?.textContent).not.toContain('metric')
  })

  it('marks verification unchecked when no producing computation is registered', async () => {
    const sources = {
      ...SOURCES_PAYLOAD,
      subjects: [
        { ...SOURCES_PAYLOAD.subjects[0], computationId: null },
      ],
    }
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/api/facts/')) return json(FACT_DETAIL)
      if (url.endsWith('/api/sources')) return json(sources)
      throw new Error(`unexpected ${url}`)
    }) as unknown as typeof fetch
    const { container, ctx } = setupPage(fetcher, FACT_REF)
    await renderEvidencePage(container, ctx)
    expect(container.querySelector('[data-status-row="verification"]')?.textContent).toContain('未核对')
    expect(container.querySelector('[data-status-row="reproducibility"]')?.textContent).toContain('不适用')
  })

  it('shows registration warnings as a callout and explains inputs without a fact id', async () => {
    const detail = {
      ...FACT_DETAIL,
      warnings: ['口径与上期不一致'],
      inputFactRefs: [{ analysisId: 'analysis_002', factId: null }],
    }
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/api/facts/')) return json(detail)
      if (url.endsWith('/api/sources')) return json(SOURCES_PAYLOAD)
      throw new Error(`unexpected ${url}`)
    }) as unknown as typeof fetch
    const { container, ctx } = setupPage(fetcher, FACT_REF)
    await renderEvidencePage(container, ctx)
    const callout = container.querySelector('.evidence-fact-warnings')!
    expect(callout.classList.contains('evidence-limitations')).toBe(true)
    expect(callout.querySelector('.evidence-limitations-title')?.textContent).toBe('登记告警')
    expect(callout.textContent).toContain('口径与上期不一致')
    const missing = container.querySelector('.evidence-fact-input-missing')
    expect(missing?.textContent).toBe('分析 analysis_002 的输入未登记事实 ID，无法打开')
    expect(container.querySelectorAll('.evidence-fact-inputs button')).toHaveLength(0)
  })

  it('navigates to an input fact via its icon link', async () => {
    const { container, ctx } = setupPage(factFetcher(), FACT_REF)
    await renderEvidencePage(container, ctx)
    const jump = Array.from(container.querySelectorAll<HTMLButtonElement>('.evidence-fact-inputs button'))
      .find((button) => button.textContent === '事实 fact-input')!
    expect(jump.classList.contains('evidence-related-link')).toBe(true)
    expect(jump.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true')
    jump.click()
    expect(ctx.navigate).toHaveBeenCalledWith({
      kind: 'fact',
      key: 'fact-input',
      analysisId: 'analysis_001',
      label: 'fact-input',
    })
  })

  it('renders server fields as text, never markup', async () => {
    const malicious = '<img src=x onerror="window.__pwned=1">'
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/api/facts/')) {
        return json({ ...FACT_DETAIL, displayValue: malicious, warnings: [malicious] })
      }
      if (url.endsWith('/api/sources')) return json(SOURCES_PAYLOAD)
      if (url.includes('/api/computations/')) return json(COMPUTATION_DETAIL)
      throw new Error(`unexpected ${url}`)
    }) as unknown as typeof fetch
    const { container, ctx } = setupPage(fetcher, FACT_REF)
    await renderEvidencePage(container, ctx)
    expect(container.textContent).toContain('<img src=x')
    expect(container.querySelector('img')).toBeNull()
    expect((window as unknown as Record<string, unknown>).__pwned).toBeUndefined()
  })

  it('does not rewrite the container when a late response arrives after navigation', async () => {
    const release = vi.fn<() => void>()
    const pending = new Promise<Response>((resolve) => {
      release.mockImplementation(() => resolve(json(FACT_DETAIL)))
    })
    const fetcher = vi.fn<typeof fetch>().mockImplementationOnce(() => pending) as unknown as typeof fetch
    const { container, ctx, controller } = setupPage(fetcher, FACT_REF)
    const rendering = renderEvidencePage(container, ctx)
    controller.abort()
    release()
    await rendering
    expect(container.querySelector('.evidence-fact-value')).toBeNull()
    expect(container.querySelector('.evidence-status-row')).toBeNull()
    expect(container.querySelector('.evidence-placeholder')?.textContent).toContain('加载中')
  })

  it('keeps the task graph and positions when a branch fails, then retries only the detail', async () => {
    const graph = createEvidenceGraph()
    const computation: EvidenceObjectRef = { kind: 'computation', key: 'comp-001', label: '汇总' }
    mergeEvidenceGraph(graph, {
      center: FACT_REF, nodes: [computation], loadedNote: '局部关系',
      edges: [{ from: computation, to: FACT_REF, label: '产出' }],
    })
    const before = [...graph.positions.entries()]
    const failing = vi.fn<typeof fetch>()
      .mockImplementationOnce(async () => new Response(JSON.stringify({ detail: { code: 'boom' } }), { status: 502 }))
      .mockImplementation(factFetcher())
    const { container, ctx } = setupPage(failing, FACT_REF, { graph, taskLabel: '核对收入' })
    await renderEvidencePage(container, ctx)
    expect(container.querySelectorAll('.evidence-node')).toHaveLength(2)
    expect(container.querySelector('.evidence-relations-head')?.textContent).toContain('核对收入')
    expect([...graph.positions.entries()]).toEqual(before)
    expect(container.querySelector('.evidence-fact-value')).toBeNull()
    container.querySelector<HTMLButtonElement>('.evidence-retry')!.click()
    await vi.waitFor(() => expect(container.querySelector('.evidence-fact-value')?.textContent).toContain('12,450'))
    for (const [id, position] of before) expect(graph.positions.get(id)).toEqual(position)
  })

  it('offers retry on server failure and reuses cached data on history return', async () => {
    // 第一次请求 502（服务器故障，可重试），重试后走正常分发。
    const failing = vi.fn<typeof fetch>()
      .mockImplementationOnce(async () =>
        new Response(JSON.stringify({ detail: { code: 'boom' } }), { status: 502 }),
      )
      .mockImplementation(async (input) => {
        const url = String(input)
        if (url.includes('/api/facts/')) return json(FACT_DETAIL)
        if (url.endsWith('/api/sources')) return json(SOURCES_PAYLOAD)
        if (url.includes('/api/computations/')) return json(COMPUTATION_DETAIL)
        throw new Error(`unexpected ${url}`)
      })
    const { container, ctx } = setupPage(failing as unknown as typeof fetch, FACT_REF)
    await renderEvidencePage(container, ctx)
    const retry = container.querySelector<HTMLButtonElement>('.evidence-retry')
    expect(retry).not.toBeNull()
    retry!.click()
    await vi.waitFor(() => {
      expect(container.querySelector('.evidence-fact-value')?.textContent).toContain('12,450')
    })
    // 历史返回：pageData 命中缓存，不再发请求。
    const calls = (failing as ReturnType<typeof vi.fn>).mock.calls.length
    const second = document.createElement('div')
    await renderEvidencePage(second, ctx)
    expect(second.querySelector('.evidence-fact-value')?.textContent).toContain('12,450')
    expect((failing as ReturnType<typeof vi.fn>).mock.calls.length).toBe(calls)
  })

  it('renders a self dependency without duplicate nodes or invalid edge coordinates', async () => {
    const base = factFetcher()
    const fetcher: typeof fetch = async (input, init) => String(input).includes('/api/facts/')
      ? json({ ...FACT_DETAIL, inputFactRefs: [{ analysisId: FACT_REF.analysisId, factId: FACT_REF.key }] })
      : base(input, init)
    const { container, ctx } = setupPage(fetcher, FACT_REF)
    await renderEvidencePage(container, ctx)
    const graph = container.querySelector('.evidence-graph')!
    expect(graph.querySelectorAll('.evidence-node')).toHaveLength(3)
    expect(graph.textContent).toContain('已加载 3 个节点')
    const paths = [...graph.querySelectorAll('.evidence-graph-edge')]
    expect(paths).toHaveLength(3)
    for (const path of paths) expect(path.getAttribute('d')).not.toMatch(/NaN|undefined|Infinity/)
    ctx.page.selected = FACT_REF
    const selected = document.createElement('div')
    await renderEvidencePage(selected, ctx)
    const enter = selected.querySelector<HTMLButtonElement>('.evidence-preview-enter')!
    expect(enter.disabled).toBe(true)
    expect(enter.textContent).toBe('已在当前页')
  })

  it('exposes named graph and text relation regions for assistive technology', async () => {
    const { container, ctx } = setupPage(factFetcher(), FACT_REF)
    await renderEvidencePage(container, ctx)
    const section = container.querySelector<HTMLElement>('.evidence-relations')!
    const heading = section.querySelector('h2')!
    const graph = section.querySelector<HTMLElement>('.evidence-graph')!
    const list = section.querySelector<HTMLElement>('.evidence-relation-list')!
    expect(section.getAttribute('aria-labelledby')).toBe(heading.id)
    expect(graph.getAttribute('role')).toBe('region')
    expect(graph.getAttribute('aria-label')).toContain('关系线仅作视觉提示')
    expect(graph.querySelector('.evidence-graph-controls')?.getAttribute('role')).toBe('toolbar')
    expect(graph.querySelector('.evidence-graph-controls')?.getAttribute('aria-label')).toBe('关系图工具')
    expect(list.getAttribute('role')).toBe('region')
    expect(list.getAttribute('aria-label')).toBe('关系列表')
    expect(graph.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true')
    expect(list.querySelectorAll('.evidence-relation-row').length).toBeGreaterThan(0)
  })

  it('defaults to 3D, switches to 2D, and preserves preview state', async () => {
    const { container, ctx, page } = setupPage(factFetcher(), FACT_REF)
    page.selected = { ...FACT_REF, key: 'fact-input', label: '输入事实' }
    await renderEvidencePage(container, ctx)
    expect(page.graphMode).toBe('3d')
    const toggle = container.querySelector<HTMLButtonElement>('.evidence-graph-mode-toggle')!
    expect(toggle.getAttribute('aria-label')).toBe('切换到 2D 关系图')
    expect(toggle.title).toBe('当前为 3D，切换到 2D')
    toggle.click()
    expect(page.graphMode).toBe('2d')
    expect(page.selected?.key).toBe('fact-input')
    expect(container.querySelector('.evidence-node')).not.toBeNull()
    container.querySelector<HTMLButtonElement>('.evidence-graph-mode-toggle')!.click()
    expect(page.graphMode).toBe('3d')
    expect(page.selected?.key).toBe('fact-input')
  })

  it('opens a dedicated graph view from a collapsed detail and restores the detail on return', async () => {
    const { container, ctx, page } = setupPage(factFetcher(), FACT_REF)
    page.collapsed = true
    document.body.append(container)
    await renderEvidencePage(container, ctx)
    const section = container.querySelector<HTMLElement>('.evidence-relations')!
    const open = section.querySelector<HTMLButtonElement>('.evidence-mobile-graph-open')!
    const back = section.querySelector<HTMLButtonElement>('.evidence-mobile-graph-return')!
    const body = section.querySelector<HTMLElement>('.evidence-relations-body')!
    expect(body.hidden).toBe(true)
    open.click()
    expect(page.graphView).toBe(true)
    expect(body.hidden).toBe(false)
    expect(page.collapsed).toBe(true)
    expect(section.classList.contains('is-graph-view')).toBe(true)
    expect(document.activeElement).toBe(back)
    const view = section.querySelector<HTMLButtonElement>('.evidence-view-toggle')!
    view.click()
    expect(page.graphView).toBe(true)
    expect(section.querySelector<HTMLElement>('.evidence-graph')!.hidden).toBe(true)
    expect(section.querySelector<HTMLElement>('.evidence-relation-list')!.hidden).toBe(false)
    view.click()
    expect(section.querySelector<HTMLElement>('.evidence-graph')!.hidden).toBe(false)
    // 节点预览重新渲染也保留图视图。
    const rerendered = document.createElement('div')
    await renderEvidencePage(rerendered, ctx)
    expect(rerendered.querySelector('.is-graph-view')).not.toBeNull()
    page.selected = FACT_REF
    ctx.setPreview = vi.fn((ref) => { page.selected = ref })
    section.querySelector<HTMLElement>('.evidence-node')!.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }),
    )
    expect(page.selected).toBeNull()
    expect(page.graphView).toBe(true) // 关闭预览不会同时退出图视图。
    back.click()
    expect(page.graphView).toBe(false)
    expect(body.hidden).toBe(true)
    expect(document.activeElement).toBe(open)
    open.click()
    back.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(page.graphView).toBe(false)
    container.remove()
  })

  it('traces a preview neighbour on hover or focus without changing page or preview', async () => {
    const { container, ctx, page } = setupPage(factFetcher(), FACT_REF)
    page.selected = FACT_REF
    await renderEvidencePage(container, ctx)
    const graph = container.querySelector('.evidence-graph')!
    const input = graph.querySelector<HTMLButtonElement>('[data-evidence-node="fact:analysis_001/fact-input"]')!
    const computation = graph.querySelector<HTMLButtonElement>('[data-evidence-node="computation:comp-001"]')!
    const geometry = () => [...graph.querySelectorAll<HTMLElement>('.evidence-node')].map(node => [node.style.left, node.style.top])
    const positions = geometry()
    expect(graph.querySelectorAll('.evidence-graph-edge.is-preview')).toHaveLength(3)
    input.dispatchEvent(new FocusEvent('focus'))
    expect(graph.querySelectorAll('.evidence-graph-edge.is-traced')).toHaveLength(1)
    expect(input.classList.contains('is-trace-related')).toBe(true)
    expect(graph.querySelectorAll('.evidence-node.is-trace-dim').length).toBeGreaterThan(0)
    expect(graph.querySelector('.evidence-graph-edge.is-traced')?.getAttribute('data-from')).toBe('fact:analysis_001/fact-input')
    expect(graph.querySelector('.evidence-graph-edge.is-traced')?.getAttribute('marker-end')).toBe('url(#evidence-graph-arrow-selected)')
    computation.dispatchEvent(new Event('pointerenter'))
    expect(graph.querySelectorAll('.evidence-graph-edge.is-traced')).toHaveLength(1)
    expect(graph.querySelector('.evidence-graph-edge.is-traced')?.getAttribute('data-from')).toBe('computation:comp-001')
    expect(graph.querySelector('.evidence-graph-edges')!.lastElementChild).toBe(graph.querySelector('.is-traced'))
    computation.dispatchEvent(new Event('pointerleave'))
    expect(graph.querySelector('.evidence-graph-edge.is-traced')?.getAttribute('data-from')).toBe('fact:analysis_001/fact-input')
    input.dispatchEvent(new FocusEvent('blur'))
    expect(graph.classList.contains('is-tracing')).toBe(false)
    expect(graph.querySelector('.is-traced')).toBeNull()
    expect(graph.querySelectorAll('.evidence-node.is-trace-dim')).toHaveLength(0)
    const touch = new Event('pointerenter')
    Object.defineProperty(touch, 'pointerType', { value: 'touch' })
    computation.dispatchEvent(touch)
    expect(graph.classList.contains('is-tracing')).toBe(false)
    expect(graph.querySelectorAll('.evidence-graph-edge.is-preview')).toHaveLength(3)
    const picker = graph.querySelector<HTMLSelectElement>('.evidence-trace-picker')!
    expect(picker.disabled).toBe(false)
    expect(picker.options).toHaveLength(5)
    picker.value = 'fact:analysis_001/fact-input'
    picker.dispatchEvent(new Event('change'))
    expect(graph.querySelectorAll('.is-traced')).toHaveLength(1)
    expect(input.style.display).toBe('')
    expect(computation.style.display).toBe('none')
    computation.dispatchEvent(new Event('pointerenter'))
    expect(graph.querySelector('.is-traced')?.getAttribute('data-from')).toBe('fact:analysis_001/fact-input')
    computation.dispatchEvent(new Event('pointerleave'))
    const scroll = graph.querySelector('.evidence-graph-scroll')!
    Object.defineProperties(scroll, { clientWidth: { value: 360 }, clientHeight: { value: 300 } })
    graph.querySelector<HTMLButtonElement>('[aria-label="适应追踪关系"]')!.click()
    for (const node of [input, graph.querySelector<HTMLElement>('.evidence-node.is-selected')!]) {
      const left = parseFloat(node.style.left) * page.graphScale + page.graphPan.x
      const top = parseFloat(node.style.top) * page.graphScale + page.graphPan.y
      expect(left).toBeGreaterThanOrEqual(16)
      expect(top).toBeGreaterThanOrEqual(16)
      expect(left + 170 * page.graphScale).toBeLessThanOrEqual(344)
      expect(top + 76 * page.graphScale).toBeLessThanOrEqual(284)
    }
    picker.value = ''
    picker.dispatchEvent(new Event('change'))
    expect(graph.querySelector('.is-traced')).toBeNull()
    expect(computation.style.display).toBe('')
    expect(graph.querySelector('[aria-label="适应关系图"]')).not.toBeNull()
    expect(geometry()).toEqual(positions)
    expect(page.selected).toEqual(FACT_REF)
    expect(ctx.setPreview).not.toHaveBeenCalled()
    expect(ctx.navigate).not.toHaveBeenCalled()
    page.selected = { kind: 'fact', key: 'fact-input', analysisId: 'analysis_001', label: 'fact-input' }
    await renderEvidencePage(container, ctx)
    const updated = container.querySelector('.evidence-graph')!
    updated.querySelector('[data-evidence-node="computation:comp-001"]')!.dispatchEvent(new FocusEvent('focus'))
    expect(updated.querySelector('.is-traced')).toBeNull()
    expect(updated.querySelectorAll('.evidence-graph-edge.is-preview')).toHaveLength(1)
  })

  it.each(['fact:analysis_001/fact-input', 'preview-relations'])('restores 2D trace scope %s only for the same preview', async value => {
    const { container, ctx, page } = setupPage(factFetcher(), FACT_REF)
    page.selected = FACT_REF
    await renderEvidencePage(container, ctx)
    const picker = container.querySelector<HTMLSelectElement>('.evidence-trace-picker')!
    picker.value = value
    picker.dispatchEvent(new Event('change'))
    const visibleIds = () => [...container.querySelectorAll<HTMLElement>('.evidence-node')]
      .filter(node => node.style.display !== 'none').map(node => node.dataset.evidenceNode)
    const before = visibleIds()
    expect(page.graph3dTrace).toEqual({ previewId: `fact:${FACT_REF.analysisId}/${FACT_REF.key}`, value })
    await renderEvidencePage(container, ctx)
    expect(container.querySelector<HTMLSelectElement>('.evidence-trace-picker')!.value).toBe(value)
    expect(visibleIds()).toEqual(before)
    page.selected = { kind: 'fact', key: 'fact-input', analysisId: 'analysis_001', label: 'fact-input' }
    await renderEvidencePage(container, ctx)
    expect(container.querySelector<HTMLSelectElement>('.evidence-trace-picker')!.value).toBe('')
    expect(visibleIds()).toHaveLength(container.querySelectorAll('.evidence-node').length)
  })

  it('previews graph nodes without navigation and keeps the current page distinct', async () => {
    const { container, ctx, page } = setupPage(factFetcher(), FACT_REF)
    await renderEvidencePage(container, ctx)
    const section = container.querySelector('.evidence-relations')!
    expect(section.textContent).toContain('来源与引用')
    expect(section.textContent).toContain('已加载 4 个节点 · 局部关系')
    const graph = section.querySelector('.evidence-graph[data-graph-host]')!
    const nodes = graph.querySelectorAll<HTMLButtonElement>('.evidence-node')
    expect(nodes).toHaveLength(4)
    expect(graph.querySelectorAll('.evidence-node-heading svg[aria-hidden="true"]')).toHaveLength(4)
    expect(graph.querySelector('.evidence-node.is-current .evidence-node-title')?.textContent).toBe(FACT_REF.label)
    expect(graph.querySelector('.evidence-node.is-current .evidence-node-info')?.textContent).toBe('事实 · 已加载 3 条关系')
    expect(graph.querySelector('.evidence-node.is-current .evidence-node-tag')?.textContent).toBe('当前页')
    expect(graph.querySelectorAll('.evidence-graph-edge')).toHaveLength(3)
    expect(graph.querySelector('.evidence-graph-edge.is-muted, .evidence-graph-edge.is-preview')).toBeNull()
    expect(graph.querySelector('.evidence-node.is-related')).toBeNull()
    // 同类型事实依赖按输入→产出布局，而非塞在同一类型列中。
    const currentNode = graph.querySelector<HTMLElement>('.evidence-node.is-current')!
    expect(parseFloat(nodes[1].style.left)).toBeLessThan(parseFloat(currentNode.style.left))
    const positions = [...nodes].map((node) => [node.style.left, node.style.top])
    graph.querySelector<HTMLButtonElement>('[aria-label="放大关系图"]')!.click()
    expect(page.graphScale).toBe(1.1)
    graph.querySelector('.evidence-graph-map')!.dispatchEvent(new WheelEvent('wheel', { deltaY: -100, bubbles: true }))
    expect(page.graphScale).toBe(1.2)
    const graphScroll = graph.querySelector<HTMLElement>('.evidence-graph-scroll')!
    Object.defineProperties(graphScroll, { clientWidth: { value: 300 } })
    graph.querySelector<HTMLButtonElement>('[aria-label="适应关系图"]')!.click()
    const boxes = [...graph.querySelectorAll<HTMLElement>('.evidence-node')].map(node => ({
      left: parseFloat(node.style.left), top: parseFloat(node.style.top), width: 170, height: 76,
    }))
    const left = Math.min(...boxes.map(box => box.left))
    const top = Math.min(...boxes.map(box => box.top))
    const right = Math.max(...boxes.map(box => box.left + box.width))
    const expectedScale = Math.min(1, (300 - 32) / (right - left))
    expect(page.graphScale).toBeCloseTo(expectedScale, 5)
    expect(page.graphPan).toEqual({ x: 16 - left * expectedScale, y: 16 - top * expectedScale })
    expect(page.graphScroll).toEqual({ left: 0, top: 0 })
    graph.querySelector<HTMLButtonElement>('.evidence-view-reset')!.click()
    expect(page.graphScale).toBe(1)
    expect(page.graphPan).toEqual({ x: 0, y: 0 })
    nodes[1].click()
    expect(ctx.setPreview).toHaveBeenCalledWith(expect.objectContaining({ kind: 'fact', key: 'fact-input' }))
    expect(ctx.navigate).not.toHaveBeenCalled()

    const { container: selectedContainer, ctx: selectedCtx } = setupPage(factFetcher(), FACT_REF)
    selectedCtx.page.selected = { kind: 'fact', key: 'fact-input', analysisId: 'analysis_001', label: 'fact-input' }
    await renderEvidencePage(selectedContainer, selectedCtx)
    const selectedGraph = selectedContainer.querySelector('.evidence-graph')!
    expect(selectedGraph.querySelector('.evidence-node.is-current .evidence-node-tag')?.textContent).toBe('当前页')
    expect(selectedGraph.querySelector('.evidence-node.is-selected .evidence-node-tag')?.textContent).toBe('预览')
    expect(selectedGraph.querySelectorAll('.evidence-graph-edge.is-preview')).toHaveLength(1)
    expect(selectedGraph.querySelectorAll('.evidence-graph-edge.is-muted')).toHaveLength(2)
    expect(selectedGraph.querySelector('.evidence-preview-actions')?.getAttribute('role')).toBe('group')
    expect(selectedGraph.querySelector('.evidence-preview-actions')?.getAttribute('aria-label')).toBe('预览操作')
    expect([...selectedGraph.querySelectorAll<HTMLElement>('.evidence-node.is-related')].map(node => node.dataset.evidenceNode)).toEqual(['fact:analysis_001/fact-aaaaaaaaaaaaaaaa'])
    const highlightedEdge = selectedGraph.querySelector('.evidence-graph-edge.is-preview')!
    expect(highlightedEdge.getAttribute('data-from')).toBe('fact:analysis_001/fact-input')
    expect(highlightedEdge.getAttribute('marker-end')).toBe('url(#evidence-graph-arrow-selected)')
    expect(selectedGraph.querySelector('.evidence-graph-edges')!.lastElementChild).toBe(highlightedEdge)
    expect([...selectedGraph.querySelectorAll<HTMLElement>('.evidence-node')].map((node) => [node.style.left, node.style.top])).toEqual(positions)
    const previewButtons = [...selectedGraph.querySelectorAll<HTMLButtonElement>('.evidence-preview button')]
    previewButtons.find((button) => button.textContent === '新页签打开')!.click()
    expect(selectedCtx.openBackground).toHaveBeenCalledWith(selectedCtx.page.selected, true)
    previewButtons.find((button) => button.textContent === '关闭预览')!.click()
    expect(selectedCtx.setPreview).toHaveBeenCalledWith(null)
    const enterButton = selectedGraph.querySelector<HTMLButtonElement>('.evidence-preview-enter')!
    // “进入”与同排按钮一样带图标；文字设置不能覆盖图标。
    expect(enterButton.textContent).toBe('进入')
    expect(enterButton.querySelector('svg')).not.toBeNull()
    enterButton.click()
    expect(selectedCtx.navigate).toHaveBeenCalledWith(selectedCtx.page.selected)
    const selectedNode = selectedGraph.querySelector<HTMLButtonElement>('.evidence-node.is-selected')!
    selectedNode.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    expect(selectedCtx.navigate).toHaveBeenCalledTimes(2)
    selectedNode.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(selectedCtx.setPreview).toHaveBeenCalledWith(null)

    // 事实页默认展开，切换后持久到 page.collapsed。
    const body = section.querySelector<HTMLElement>('.evidence-relations-body')!
    expect(body.hidden).toBe(false)
    // 关系列表保留切换前关系图的高度：页面不收缩，滚动位置与切换按钮位置不跳动。
    const graphBox = section.querySelector<HTMLElement>('.evidence-graph')!
    vi.spyOn(graphBox, 'getBoundingClientRect').mockReturnValue({ height: 521.6 } as DOMRect)
    section.querySelector<HTMLButtonElement>('.evidence-view-toggle')!.click()
    expect(page.showList).toBe(true)
    expect(section.querySelector<HTMLElement>('.evidence-graph')!.hidden).toBe(true)
    const relationList = section.querySelector<HTMLElement>('.evidence-relation-list')!
    expect(relationList.hidden).toBe(false)
    expect(relationList.style.minHeight).toBe('522px')
    section.querySelector<HTMLButtonElement>('.evidence-view-toggle')!.click()
    expect(relationList.style.minHeight).toBe('')
    section.querySelector<HTMLButtonElement>('.evidence-view-toggle')!.click()
    const toggle = section.querySelector<HTMLButtonElement>('.evidence-relations-toggle')!
    toggle.click()
    expect(page.collapsed).toBe(true)
    expect(body.hidden).toBe(true)
  })

  it('locates the current graph node at the current scale without changing preview or navigation', async () => {
    const { container, ctx, page } = setupPage(factFetcher(), FACT_REF)
    document.body.append(container)
    await renderEvidencePage(container, ctx)
    const scroll = container.querySelector<HTMLElement>('.evidence-graph-scroll')!
    Object.defineProperties(scroll, { clientWidth: { value: 300 }, clientHeight: { value: 200 } })
    page.graphScale = 1.2
    page.graphPan = { x: -200, y: -300 }
    scroll.scrollTop = 10000
    const current = container.querySelector<HTMLElement>('.evidence-node.is-current')!
    container.querySelector<HTMLButtonElement>('[aria-label="定位当前对象"]')!.click()
    expect(scroll.scrollLeft).toBeCloseTo(Math.max(0, (parseFloat(current.style.left) + 85) * 1.2 - 150))
    expect(scroll.scrollTop).toBeCloseTo(Math.max(0, (parseFloat(current.style.top) + 38) * 1.2 - 100))
    expect(page.graphScroll).toEqual({ left: scroll.scrollLeft, top: scroll.scrollTop })
    expect(page.graphScale).toBe(1.2)
    expect(page.graphPan).toEqual({ x: 0, y: 0 })
    expect(document.activeElement).toBe(current)
    expect(ctx.navigate).not.toHaveBeenCalled()
    expect(ctx.setPreview).not.toHaveBeenCalled()
    container.querySelector<HTMLButtonElement>('.evidence-view-reset')!.click()
    expect(scroll.scrollLeft).toBe(0)
    expect(scroll.scrollTop).toBe(0)
    expect(page.graphScroll).toEqual({ left: 0, top: 0 })
    container.remove()
  })

  it('pinches around the touch center and continues panning after one finger lifts', async () => {
    const { container, ctx, page } = setupPage(factFetcher(), FACT_REF)
    await renderEvidencePage(container, ctx)
    const map = container.querySelector<HTMLElement>('.evidence-graph-map')!
    map.setPointerCapture = vi.fn()
    const pointer = (type: string, id: number, x: number, y: number) => {
      const event = new MouseEvent(type, { bubbles: true, button: 0, clientX: x, clientY: y })
      Object.defineProperties(event, { pointerId: { value: id }, pointerType: { value: 'touch' } })
      map.dispatchEvent(event)
    }
    pointer('pointerdown', 1, 100, 100)
    pointer('pointerdown', 2, 200, 100)
    pointer('pointermove', 2, 300, 100)
    expect(page.graphScale).toBe(2)
    expect(page.graphPan).toEqual({ x: -100, y: -100 })
    const node = map.querySelector<HTMLButtonElement>('.evidence-node')!
    node.dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 }))
    node.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, detail: 2 }))
    expect(ctx.navigate).not.toHaveBeenCalled()
    expect(ctx.setPreview).not.toHaveBeenCalled()
    pointer('pointermove', 2, 500, 100)
    expect(page.graphScale).toBe(2)
    expect(page.graphPan).toEqual({ x: 0, y: -100 })
    pointer('pointermove', 2, 120, 100)
    expect(page.graphScale).toBe(0.2)
    expect(page.graphPan.x).toBeCloseTo(80)
    const before = { ...page.graphPan }
    pointer('pointerup', 2, 120, 100)
    pointer('pointermove', 1, 110, 120)
    expect(page.graphPan).toEqual({ x: before.x + 10, y: before.y + 20 })
    pointer('pointercancel', 1, 110, 120)
    pointer('pointermove', 1, 150, 150)
    expect(page.graphPan).toEqual({ x: before.x + 10, y: before.y + 20 })
    expect(ctx.navigate).not.toHaveBeenCalled()
    expect(ctx.setPreview).not.toHaveBeenCalled()
    container.remove()
  })

  it('keeps node-origin pinch capture transfers alive and restores mouse clicks', async () => {
    const { container, ctx, page } = setupPage(factFetcher(), FACT_REF)
    await renderEvidencePage(container, ctx)
    const map = container.querySelector<HTMLElement>('.evidence-graph-map')!
    const node = map.querySelector<HTMLButtonElement>('.evidence-node')!
    map.setPointerCapture = vi.fn()
    const pointer = (target: HTMLElement, type: string, id: number, x: number, pointerType = 'touch') => {
      const event = new MouseEvent(type, { bubbles: true, button: 0, clientX: x, clientY: 100 })
      Object.defineProperties(event, { pointerId: { value: id }, pointerType: { value: pointerType } })
      target.dispatchEvent(event)
    }
    pointer(node, 'pointerdown', 1, 100)
    pointer(map, 'pointerdown', 2, 200)
    pointer(node, 'lostpointercapture', 1, 100)
    pointer(map, 'pointermove', 2, 250)
    expect(page.graphScale).toBe(1.5)
    pointer(map, 'pointerup', 1, 100)
    pointer(map, 'pointerup', 2, 250)
    node.dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 }))
    expect(ctx.setPreview).not.toHaveBeenCalled()
    pointer(node, 'pointerdown', 3, 100, 'mouse')
    pointer(node, 'pointerup', 3, 100, 'mouse')
    node.dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 }))
    expect(ctx.setPreview).toHaveBeenCalledTimes(1)
    expect(ctx.navigate).not.toHaveBeenCalled()
    container.remove()
  })

  it('keeps graph panning owned by its starting pointer and stops on capture loss', async () => {
    const { container, ctx, page } = setupPage(factFetcher(), FACT_REF)
    await renderEvidencePage(container, ctx)
    const map = container.querySelector<HTMLElement>('.evidence-graph-map')!
    map.setPointerCapture = vi.fn()
    const pointer = (type: string, id: number, x: number, y: number) => {
      const event = new MouseEvent(type, { bubbles: true, button: 0, clientX: x, clientY: y })
      Object.defineProperty(event, 'pointerId', { value: id })
      map.dispatchEvent(event)
    }
    pointer('pointerdown', 1, 100, 100)
    pointer('pointermove', 1, 120, 130)
    expect(page.graphPan).toEqual({ x: 20, y: 30 })
    pointer('pointerdown', 2, 200, 200)
    pointer('pointermove', 2, 250, 260)
    pointer('pointerup', 2, 250, 260)
    expect(page.graphPan).toEqual({ x: 20, y: 30 })
    pointer('pointermove', 1, 140, 150)
    expect(page.graphPan).toEqual({ x: 40, y: 50 })
    pointer('lostpointercapture', 1, 140, 150)
    pointer('pointermove', 1, 180, 190)
    expect(page.graphPan).toEqual({ x: 40, y: 50 })
    pointer('pointerdown', 3, 200, 200)
    pointer('pointermove', 3, 210, 220)
    expect(page.graphPan).toEqual({ x: 50, y: 70 })
    pointer('pointercancel', 3, 210, 220)
    pointer('pointermove', 3, 230, 240)
    expect(page.graphPan).toEqual({ x: 50, y: 70 })
    expect(ctx.navigate).not.toHaveBeenCalled()
    expect(ctx.setPreview).not.toHaveBeenCalled()
  })
})

describe('快照复制与下载辅助', () => {
  it('escapes cells that would break tab-separated rows when pasted', () => {
    expect(tsvCell('华东')).toBe('华东')
    expect(tsvCell(null)).toBe('')
    expect(tsvCell(12450)).toBe('12450')
    // 引号内换行、制表符与双引号必须加引号转义，否则粘贴后一行被拆成多行。
    expect(tsvCell('第一行\n第二行')).toBe('"第一行\n第二行"')
    expect(tsvCell('a\tb')).toBe('"a\tb"')
    expect(tsvCell('说"明"')).toBe('"说""明"""')
  })

  it('always downloads snapshots with a csv extension and no path separators', () => {
    expect(snapshotFileName('收入明细.csv')).toBe('收入明细.csv')
    expect(snapshotFileName('季度收入快照')).toBe('季度收入快照.csv')
    expect(snapshotFileName('a/b\\c')).toBe('a_b_c.csv')
    expect(snapshotFileName('  ')).toBe('snapshot.csv')
  })
})

describe('快照页', () => {
  const DATASET_REF: EvidenceObjectRef = {
    kind: 'dataset',
    key: 'dataset-url-abc0001',
    label: '收入明细.csv',
  }

  function datasetFetcher(): typeof fetch {
    return vi.fn<typeof fetch>().mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('cursor=cursor-2')) return json(PREVIEW_PAGE_2)
      if (url.includes('/preview')) return json(PREVIEW_PAGE_1)
      if (url.endsWith('/api/sources')) return json(SOURCES_PAYLOAD)
      throw new Error(`unexpected ${url}`)
    }) as unknown as typeof fetch
  }

  it('switches wide or restricted snapshots to controlled column windows instead of dead-ending', async () => {
    const all = Array.from({ length: 61 }, (_, i) => (i === 0 ? 'row_id' : `c${String(i).padStart(3, '0')}`))
    const previewFor = (columns: string[], offset = 0, nextCursor: string | null = 'cw-2') => ({
      ...PREVIEW_PAGE_1, columns, rows: [columns.map((name) => `${name}-${offset}`)], offset, nextCursor,
    })
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input) => {
      const url = new URL(String(input), 'http://reports.test')
      if (url.pathname.endsWith('/columns')) {
        return json({ datasetId: DATASET_REF.key, columns: all, restricted: true, maxColumnsPerPage: 50 })
      }
      if (url.pathname.endsWith('/preview')) {
        const selected = url.searchParams.getAll('columns')
        if (!selected.length) {
          return new Response(JSON.stringify({ detail: { code: 'resource_limit_exceeded' } }), { status: 422 })
        }
        return json(previewFor(selected, url.searchParams.get('cursor') ? 1 : 0, url.searchParams.get('cursor') ? null : 'cw-2'))
      }
      if (url.pathname.endsWith('/api/sources')) return json(SOURCES_PAYLOAD)
      throw new Error(`unexpected ${url}`)
    }) as unknown as typeof fetch
    const { container, ctx } = setupPage(fetcher, DATASET_REF)
    await renderEvidencePage(container, ctx)

    expect(container.querySelector('.evidence-page-error')).toBeNull()
    expect(ctx.page.datasetColumnWindow).toBe(0)
    const headers = () => [...container.querySelectorAll('.evidence-table th')].map((cell) => cell.textContent)
    expect(headers()).toHaveLength(50)
    expect(headers()[0]).toBe('row_id')
    const select = container.querySelector<HTMLSelectElement>('.evidence-column-window')!
    expect([...select.options].map((option) => option.textContent)).toEqual([
      '第 1–50 列（row_id … c049）',
      '第 51–61 列（c050 … c060）',
    ])
    expect(container.querySelector('.evidence-column-note')?.textContent).toBe(
      '共 61 列，单页最多显示 50 列 · 部分列受访问限制，未在预览中显示',
    )
    expect(container.querySelector('.evidence-dataset-note')?.textContent).toContain('复制仅含当前可见行与当前显示的列')

    // 先翻到第二页，再切换列窗口：游标绑定列选择，切换后从第一页重新开始。
    container.querySelector<HTMLButtonElement>('.evidence-more')!.click()
    await vi.waitFor(() => expect(ctx.page.datasetPageIndex).toBe(1))
    select.value = '1'
    select.dispatchEvent(new Event('change'))
    await vi.waitFor(() => expect(headers()[0]).toBe('c050'))
    expect(headers()).toHaveLength(11)
    expect(ctx.page).toMatchObject({ datasetColumnWindow: 1, datasetPageIndex: 0, datasetCursors: [null] })
    const urls = (fetcher as unknown as ReturnType<typeof vi.fn>).mock.calls.map((call) => String(call[0]))
    expect(urls.filter((url) => url.includes('cursor=cw-2')).every((url) => url.includes('columns=row_id'))).toBe(true)

    // 会话恢复：已保存窗口直接按受控列请求，不再先发整表预览。
    const restored = setupPage(fetcher, DATASET_REF)
    restored.page.datasetColumnWindow = 1
    const before = (fetcher as unknown as ReturnType<typeof vi.fn>).mock.calls.length
    await renderEvidencePage(restored.container, restored.ctx)
    const restoredUrls = (fetcher as unknown as ReturnType<typeof vi.fn>).mock.calls.slice(before).map((call) => String(call[0]))
    expect(restoredUrls.filter((url) => url.includes('/preview')).every((url) => url.includes('columns=c050'))).toBe(true)
    expect(restored.container.querySelector('.evidence-column-window')).not.toBeNull()
  })

  it('keeps reporting a denial when no column is visible to the session', async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/columns')) {
        return json({ datasetId: DATASET_REF.key, columns: [], restricted: true, maxColumnsPerPage: 50 })
      }
      if (url.includes('/preview')) {
        return new Response(JSON.stringify({ detail: { code: 'dataset_access_denied' } }), { status: 403 })
      }
      throw new Error(`unexpected ${url}`)
    }) as unknown as typeof fetch
    const { container, ctx } = setupPage(fetcher, DATASET_REF)
    await renderEvidencePage(container, ctx)
    expect(container.querySelector('.evidence-page-error')?.textContent).toContain('当前会话无权访问该数据')
    expect(ctx.page.datasetColumnWindow).toBeUndefined()
  })

  it('marks a missing materialization time as unknown instead of inferring it', async () => {
    const payload = structuredClone(SOURCES_PAYLOAD)
    payload.datasets[0].materializedAt = null as unknown as string
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/preview')) return json(PREVIEW_PAGE_1)
      if (url.endsWith('/api/sources')) return json(payload)
      throw new Error(`unexpected ${url}`)
    }) as unknown as typeof fetch
    const { container, ctx } = setupPage(fetcher, DATASET_REF)
    await renderEvidencePage(container, ctx)
    expect(container.querySelector('[data-status-row="materialized-at"]')?.textContent).toContain('未知')
  })

  it('replaces the loaded page, preserves its cursor and can return to the previous page', async () => {
    const fetcher = datasetFetcher()
    const { container, ctx } = setupPage(fetcher, DATASET_REF)
    await renderEvidencePage(container, ctx)
    expect(container.querySelector('.evidence-dataset-scope')?.textContent).toContain('完整快照共 4 行')
    expect(container.querySelector('.evidence-dataset-scope')?.textContent).toContain('预览序号 1–2')
    expect(container.querySelectorAll('.evidence-table tbody tr, .evidence-table tr').length).toBe(3)
    // 登记信息取自来源索引，以状态行呈现在关系区之前。
    expect(container.querySelector('[data-status-row="source-type"]')?.textContent).toContain('上传文件')
    expect(container.querySelector('[data-status-row="period-roles"]')?.textContent).toContain('本期')
    expect(container.querySelector('[data-status-row="size"]')?.textContent).toContain('4 行')
    expect(container.querySelector('[data-status-row="business-label"]')).toBeNull()
    // 宽表滚动区可聚焦且具名，键盘用户可横向滚动。
    const region = container.querySelector<HTMLElement>('.evidence-table-wrap')!
    expect(region.tabIndex).toBe(0)
    expect(region.getAttribute('role')).toBe('region')
    expect(region.getAttribute('aria-label')).toContain('数据快照预览表')
    // 数字列右对齐：revenue 全为数字，branch 为文本。
    const header = [...container.querySelectorAll('.evidence-table th')]
    expect(header.map((cell) => cell.classList.contains('is-numeric'))).toEqual([false, true])
    expect(container.querySelector('.evidence-table td.is-numeric')?.textContent).toBe('1000')

    const more = container.querySelector<HTMLButtonElement>('.evidence-more')!
    more.click()
    await vi.waitFor(() => {
      expect(container.querySelector('.evidence-table')?.textContent).toContain('华南')
    })
    expect(container.querySelector('.evidence-table')?.textContent).toContain('华南')
    expect(container.querySelector('.evidence-dataset-scope')?.textContent).toContain('预览序号 3–4')
    expect(container.querySelector('.evidence-table')?.textContent).not.toContain('华东')
    expect(ctx.page.datasetPageIndex).toBe(1)
    expect(ctx.page.datasetCursors).toEqual([null, 'cursor-2'])
    expect(container.querySelector('.evidence-more')).toBeNull()
    const urls = (fetcher as unknown as ReturnType<typeof vi.fn>).mock.calls.map((call) => String(call[0]))
    expect(urls.some((url) => url.includes('cursor=cursor-2'))).toBe(true)
    // 历史返回的数据缓存保持第二页；刷新没有缓存时按保存游标恢复第二页。
    const cached = document.createElement('div')
    await renderEvidencePage(cached, ctx)
    expect(cached.querySelector('.evidence-table')?.textContent).toContain('华南')
    const fresh = setupPage(fetcher, DATASET_REF)
    fresh.page.datasetCursors = [...ctx.page.datasetCursors]
    fresh.page.datasetPageIndex = ctx.page.datasetPageIndex
    await renderEvidencePage(fresh.container, fresh.ctx)
    expect(fresh.container.querySelector('.evidence-table')?.textContent).toContain('华南')
    container.querySelector<HTMLButtonElement>('.evidence-previous')!.click()
    await vi.waitFor(() => expect(container.querySelector('.evidence-table')?.textContent).toContain('华东'))
    expect(ctx.page.datasetPageIndex).toBe(0)
  })

  it('filters only the loaded page and reports 本页匹配 X / Y 行', async () => {
    const { container, ctx, page } = setupPage(datasetFetcher(), DATASET_REF)
    await renderEvidencePage(container, ctx)
    const filter = container.querySelector<HTMLInputElement>('.evidence-filter')!
    expect(container.textContent).toContain('仅筛选本页已加载内容')

    filter.value = '华东'
    filter.dispatchEvent(new Event('input'))
    expect(page.filter).toBe('华东')
    expect(container.querySelector('.evidence-filter-count')?.textContent).toContain('本页匹配 1 / 2 行')
    expect(container.querySelectorAll('.evidence-table tr').length).toBe(2)
    // 命中文字高亮，单元格文本保持原值，未命中的单元格不插入标记。
    const marks = [...container.querySelectorAll('.evidence-table mark.evidence-match')]
    expect(marks.map((mark) => mark.textContent)).toEqual(['华东'])
    expect(marks[0]!.closest('td')?.textContent).toBe('华东')

    filter.value = '00'
    filter.dispatchEvent(new Event('input'))
    // 同一单元格多处命中逐一标记（1000 → 1 + 00 + 0 不应重叠）。
    const numeric = [...container.querySelectorAll('.evidence-table td')].find((cell) => cell.textContent === '1000')!
    expect([...numeric.querySelectorAll('mark')].map((mark) => mark.textContent)).toEqual(['00'])

    filter.value = '不存在的院区'
    filter.dispatchEvent(new Event('input'))
    expect(container.querySelector('.evidence-filter-count')?.textContent).toContain('本页匹配 0 / 2 行')
    expect(container.querySelector('.evidence-filter-count')?.textContent).toContain('未对完整数据集执行搜索')
  })

  it('keeps the filter limited to each page and restores column widths on a new render', async () => {
    const { container, ctx, page } = setupPage(datasetFetcher(), DATASET_REF)
    await renderEvidencePage(container, ctx)
    const handle = container.querySelector<HTMLElement>('.evidence-column-resize')!
    handle.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    expect(page.columnWidths.branch).toBe(154)
    const filter = container.querySelector<HTMLInputElement>('.evidence-filter')!
    filter.value = '华东'
    filter.dispatchEvent(new Event('input'))
    container.querySelector<HTMLButtonElement>('.evidence-more')!.click()
    await vi.waitFor(() => expect(page.datasetPageIndex).toBe(1))
    expect(page.filter).toBe('华东')
    expect(container.querySelector('.evidence-filter-count')?.textContent).toContain('本页匹配 0 / 2 行')
    const restored = document.createElement('div')
    await renderEvidencePage(restored, ctx)
    expect(restored.querySelector<HTMLElement>('col')!.style.width).toBe('154px')
    expect(restored.querySelector<HTMLInputElement>('.evidence-filter')!.value).toBe('华东')
  })

  it('recovers an expired restored cursor by explicitly reopening the first page', async () => {
    const base = datasetFetcher()
    const fetcher: typeof fetch = (input, init) => String(input).includes('cursor=expired')
      ? Promise.resolve(new Response(JSON.stringify({ detail: { code: 'cursor_invalid' } }), { status: 400 })) : base(input, init)
    const { container, ctx, page } = setupPage(fetcher, DATASET_REF)
    page.datasetCursors = [null, 'expired']
    page.datasetPageIndex = 1
    page.filter = '华东'
    await renderEvidencePage(container, ctx)
    expect(container.textContent).toContain('分页游标已失效')
    const reset = [...container.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent === '重新打开第一页')!
    reset.click()
    await vi.waitFor(() => expect(container.querySelector('.evidence-table')?.textContent).toContain('华东'))
    expect(page.datasetCursors).toEqual([null])
    expect(page.datasetPageIndex).toBe(0)
    expect(page.filter).toBe('华东')
  })

  it('does not advance the cursor or discard the current data on a paging failure', async () => {
    const base = datasetFetcher()
    const fetcher: typeof fetch = (input, init) => String(input).includes('cursor=cursor-2')
      ? Promise.resolve(new Response(JSON.stringify({ detail: { code: 'boom' } }), { status: 502 })) : base(input, init)
    const { container, ctx, page } = setupPage(fetcher, DATASET_REF)
    await renderEvidencePage(container, ctx)
    container.querySelector<HTMLButtonElement>('.evidence-more')!.click()
    await vi.waitFor(() => expect(container.querySelector('.evidence-more-error')).not.toBeNull())
    expect(page.datasetPageIndex).toBe(0)
    expect(page.datasetCursors).toEqual([null])
    expect(container.querySelector('.evidence-table')?.textContent).toContain('华东')
    expect(container.querySelector<HTMLButtonElement>('.evidence-more')!.disabled).toBe(false)
  })

  it('keeps one recovery action after repeated expired-cursor paging failures', async () => {
    const base = datasetFetcher()
    const fetcher: typeof fetch = (input, init) => String(input).includes('cursor=cursor-2')
      ? Promise.resolve(new Response(JSON.stringify({ detail: { code: 'cursor_invalid' } }), { status: 400 })) : base(input, init)
    const { container, ctx, page } = setupPage(fetcher, DATASET_REF)
    await renderEvidencePage(container, ctx)
    const next = container.querySelector<HTMLButtonElement>('.evidence-more')!
    for (let attempt = 0; attempt < 2; attempt += 1) {
      next.click()
      await vi.waitFor(() => expect(next.disabled).toBe(false))
    }
    expect(container.querySelectorAll('.evidence-cursor-reset')).toHaveLength(1)
    expect(container.querySelector('.evidence-more-error')?.getAttribute('role')).toBe('status')
    expect(page.datasetPageIndex).toBe(0)
    expect(page.datasetCursors).toEqual([null])
    expect(container.querySelector('.evidence-table')?.textContent).toContain('华东')
    container.querySelector<HTMLButtonElement>('.evidence-cursor-reset')!.click()
    await vi.waitFor(() => expect(container.querySelector('.evidence-more-error')).toBeNull())
    expect(container.querySelectorAll('.evidence-cursor-reset')).toHaveLength(0)
  })

  it('explains 403 on download without navigating away', async () => {
    const headProbe = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 403 }))
    vi.stubGlobal('fetch', headProbe)
    const { container, ctx } = setupPage(datasetFetcher(), DATASET_REF)
    await renderEvidencePage(container, ctx)
    const download = Array.from(container.querySelectorAll<HTMLButtonElement>('button'))
      .find((button) => button.textContent === '下载此快照')!
    download.click()
    await vi.waitFor(() => {
      expect(container.querySelector('.evidence-dataset-note')?.textContent).toContain('无权下载原始文件')
    })
    expect(headProbe).toHaveBeenCalledWith(
      '/reports/v1/editor/report-1/1/api/datasets/dataset-url-abc0001/download',
      expect.objectContaining({ method: 'HEAD' }),
    )
  })

  it('uses a same-origin download link after a successful probe without replacing the editor', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 200 })))
    const links: { href: string; filename: string; connected: boolean }[] = []
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      links.push({ href: this.getAttribute('href')!, filename: this.download, connected: this.isConnected })
    })
    try {
      const { container, ctx } = setupPage(datasetFetcher(), DATASET_REF)
      await renderEvidencePage(container, ctx)
      const download = [...container.querySelectorAll<HTMLButtonElement>('button')]
        .find(button => button.textContent === '下载此快照')!
      download.click()
      await vi.waitFor(() => expect(links).toEqual([{
        href: '/reports/v1/editor/report-1/1/api/datasets/dataset-url-abc0001/download',
        filename: '收入明细.csv', connected: true,
      }]))
      expect(document.querySelector('a[download]')).toBeNull()
      expect(download.disabled).toBe(false)
    } finally {
      click.mockRestore()
    }
  })

  it.each([true, false])('copies only visible rows on the current page (download enabled: %s)', async (downloadEnabled) => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const { container, ctx, page } = setupPage(datasetFetcher(), DATASET_REF, { downloadEnabled })
    await renderEvidencePage(container, ctx)
    const copy = [...container.querySelectorAll<HTMLButtonElement>('button')]
      .find(button => button.textContent === '复制本页')!
    const filter = container.querySelector<HTMLInputElement>('.evidence-filter')!
    const setFilter = (value: string) => {
      filter.value = value
      filter.dispatchEvent(new Event('input'))
    }
    copy.click()
    await vi.waitFor(() => expect(container.querySelector('.evidence-dataset-note')?.textContent).toContain('已复制本页可见 2 行'))
    expect(writeText).toHaveBeenLastCalledWith('branch\trevenue\n华东\t1000\n华北\t1200')
    setFilter('华东')
    copy.click()
    await vi.waitFor(() => expect(container.querySelector('.evidence-dataset-note')?.textContent).toContain('已复制本页可见 1 行'))
    expect(writeText).toHaveBeenLastCalledWith('branch\trevenue\n华东\t1000')
    setFilter('不存在')
    copy.click()
    await vi.waitFor(() => expect(container.querySelector('.evidence-dataset-note')?.textContent).toContain('已复制本页可见 0 行'))
    expect(writeText).toHaveBeenLastCalledWith('branch\trevenue')
    setFilter('南')
    container.querySelector<HTMLButtonElement>('.evidence-more')!.click()
    await vi.waitFor(() => expect(page.datasetPageIndex).toBe(1))
    copy.click()
    await vi.waitFor(() => expect(container.querySelector('.evidence-dataset-note')?.textContent).toContain('已复制本页可见 2 行'))
    expect(writeText).toHaveBeenLastCalledWith('branch\trevenue\n华南\t900\n西南\t800')
    expect(writeText).toHaveBeenCalledTimes(4)
    expect(ctx.navigate).not.toHaveBeenCalled()
    container.remove()
  })

  it('degrades quietly when the clipboard is unavailable', async () => {
    const { container, ctx } = setupPage(datasetFetcher(), DATASET_REF)
    await renderEvidencePage(container, ctx)
    const copy = Array.from(container.querySelectorAll<HTMLButtonElement>('button'))
      .find((button) => button.textContent === '复制本页')!
    copy.click()
    await vi.waitFor(() => {
      expect(container.querySelector('.evidence-dataset-note')?.textContent).toContain('复制不可用')
    })
  })

  it.each([
    [409, '文件完整性校验失败'],
    [410, '编辑会话或数据快照已过期'],
    [404, '来源不存在或不在当前修订中'],
  ])('explains download access failure %i while preserving the preview', async (status, message) => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: Number(status) })))
    const { container, ctx } = setupPage(datasetFetcher(), DATASET_REF)
    await renderEvidencePage(container, ctx)
    const download = [...container.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '下载此快照')!
    download.click()
    await vi.waitFor(() => expect(container.querySelector('.evidence-dataset-note')?.textContent).toContain(message))
    expect(container.querySelector('.evidence-table')?.textContent).toContain('华东')
    expect(download.disabled).toBe(false)
    expect(ctx.navigate).not.toHaveBeenCalled()
  })
})

describe('详情入口统一导航', () => {
  it.each(['input', 'output', 'subject-fact', 'subject-computation'])('handles modifiers on the %s detail link', async (kind) => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/api/computations/')) return json(COMPUTATION_DETAIL)
      if (url.includes('/api/facts/')) return json(FACT_DETAIL)
      if (url.endsWith('/api/sources')) return json(SOURCES_PAYLOAD)
      throw new Error(`unexpected ${url}`)
    })
    const ref: EvidenceObjectRef = kind === 'input'
      ? { kind: 'fact', key: 'fact-aaaaaaaaaaaaaaaa', analysisId: 'analysis_001', label: '营收' }
      : kind === 'output' ? { kind: 'computation', key: 'comp-001', label: 'sum' }
        : { kind: 'subject', key: 'sub-cccccccccccccccc', label: '正文引用' }
    const { container, ctx } = setupPage(fetcher, ref)
    await renderEvidencePage(container, ctx)
    const selector = kind === 'input' ? '.evidence-fact-inputs button'
      : kind === 'output' ? '.evidence-computation-outputs button'
        : kind === 'subject-fact' ? '.evidence-subject-links li:first-child button' : '.evidence-subject-links li:last-child button'
    const link = container.querySelector<HTMLButtonElement>(selector)!
    const target = kind === 'subject-computation' ? { kind: 'computation', key: 'comp-001', label: 'comp-001' }
      : { kind: 'fact', analysisId: 'analysis_001',
      key: kind === 'input' ? 'fact-input' : 'fact-aaaaaaaaaaaaaaaa',
      label: kind === 'input' ? 'fact-input' : 'fact-aaaaaaaaaaaaaaaa' }
    for (const modifiers of [{ ctrlKey: true }, { metaKey: true }, { ctrlKey: true, shiftKey: true }, { metaKey: true, shiftKey: true }]) {
      link.dispatchEvent(new MouseEvent('click', { bubbles: true, ...modifiers }))
      expect(ctx.openBackground).toHaveBeenLastCalledWith(target, Boolean(modifiers.shiftKey))
    }
    const middle = new MouseEvent('auxclick', { bubbles: true, cancelable: true, button: 1 })
    link.dispatchEvent(middle)
    expect(middle.defaultPrevented).toBe(true)
    expect(ctx.openBackground).toHaveBeenLastCalledWith(target)
    expect(ctx.openBackground).toHaveBeenCalledTimes(5)
    expect(ctx.navigate).not.toHaveBeenCalled()
    link.dispatchEvent(new MouseEvent('auxclick', { bubbles: true, button: 2 }))
    expect(ctx.openBackground).toHaveBeenCalledTimes(5)
    link.click()
    expect(ctx.navigate).toHaveBeenCalledExactlyOnceWith(target)
    container.remove()
  })
})

describe('graphLabel', () => {
  it('keeps the citation short id instead of cutting it in the middle', () => {
    const subject: EvidenceObjectRef = { kind: 'subject', key: 'sub-fixture-001', label: '正文引用 #fixtur' }
    expect(graphLabel(subject, 14, 9, 4)).toBe('正文引用 #fixtur')
    expect(graphLabel(subject, 10, 5, 4)).toBe('引用 #fixtur')
    expect(graphLabel(subject, 4, 1, 2)).toBe('#fixtur')
    const dataset: EvidenceObjectRef = { kind: 'dataset', key: 'd', label: '门急诊收入明细快照.csv' }
    expect(graphLabel(dataset, 10, 5, 4)).toBe('门急诊收入….csv')
    expect(graphLabel({ ...dataset, label: '短名' }, 4, 1, 2)).toBe('短名')
  })
})

describe('groupDigits', () => {
  it('groups integer digits without rounding or touching decimals', () => {
    expect(groupDigits(12450)).toBe('12,450')
    expect(groupDigits(-1234567.0891)).toBe('-1,234,567.0891')
    expect(groupDigits('+330.25')).toBe('+330.25')
    expect(groupDigits('+3300')).toBe('+3,300')
    expect(groupDigits(999)).toBe('999')
    expect(groupDigits(1e21)).toBe('1e+21')
    expect(groupDigits('12,450')).toBe('12,450')
    expect(groupDigits('未提供')).toBe('未提供')
    expect(groupDigits(null)).toBe('—')
  })
})

describe('formatDifference', () => {
  it('rounds away floating-point noise and keeps the sign', () => {
    expect(formatDifference(12780.1, 12450.3)).toBe('+329.8')
    expect(formatDifference('12,780', '12,450')).toBe('+330')
    expect(formatDifference(0.3, 0.1)).toBe('+0.2')
    expect(formatDifference(100, 100.5)).toBe('-0.5')
    expect(formatDifference(1, 1)).toBe('+0')
    expect(formatDifference('abc', 1)).toBeNull()
  })
})

describe('错误重试与会话文案', () => {
  it.each([
    [429, 'resource_limit_exceeded', true],
    [408, 'request_timeout', true],
    [404, 'source_missing', false],
    [401, 'report_editor_session_invalid', false],
  ])('status %s / %s retryable=%s', async (status, code, retryable) => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async () =>
      new Response(JSON.stringify({ detail: { code } }), { status })) as unknown as typeof fetch
    const ref: EvidenceObjectRef = { kind: 'computation', key: 'comp-001', label: 'sum' }
    const { container, ctx } = setupPage(fetcher, ref)
    await renderEvidencePage(container, ctx)
    expect(container.querySelector('.evidence-retry') !== null).toBe(retryable)
    if (code === 'report_editor_session_invalid') {
      expect(container.querySelector('.evidence-status')?.textContent).toContain('重新打开此报告')
    }
  })
})

describe('无事实标识的输出', () => {
  it('explains the missing fact binding without requesting fact details', async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => {
      throw new Error('should not request')
    }) as unknown as typeof fetch
    const ref: EvidenceObjectRef = {
      kind: 'fact', key: 'analysis_001#/metrics/revenue', analysisId: 'analysis_001', label: 'revenue',
    }
    const { container, ctx } = setupPage(fetcher, ref)
    await renderEvidencePage(container, ctx)
    expect(fetcher).not.toHaveBeenCalled()
    expect(container.querySelector('.evidence-status')?.textContent).toContain('事实引用暂不可用')
  })
})

describe('计算页', () => {
  it('says how many outputs are hidden and keeps nested environment values readable', async () => {
    const detail = {
      ...COMPUTATION_DETAIL,
      environment: { python: '3.12', packages: { polars: '1.3' } },
      outputFactRefs: Array.from({ length: 23 }, (_, i) => ({
        analysisId: 'analysis_001', factKey: `fact-${String(i).padStart(16, '0')}`,
        factKind: 'metric', jsonPointer: `/metrics/m${i}`,
      })),
    }
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/api/computations/')) return json(detail)
      if (url.endsWith('/api/sources')) return json(SOURCES_PAYLOAD)
      throw new Error(`unexpected ${url}`)
    }) as unknown as typeof fetch
    const { container, ctx } = setupPage(fetcher, { kind: 'computation', key: 'comp-001', label: 'sum' })
    await renderEvidencePage(container, ctx)
    expect(container.querySelectorAll('.evidence-computation-outputs li')).toHaveLength(20)
    expect(container.querySelector('.evidence-outputs-more')?.textContent).toContain('共 23 项输出事实')
    const execution = container.querySelector('[data-status-row="execution"]')?.textContent ?? ''
    expect(execution).toContain('packages {"polars":"1.3"}')
    expect(execution).not.toContain('[object Object]')
  })

  it('renders method, parameters, verification labels and output facts', async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('/api/computations/')) return json(COMPUTATION_DETAIL)
      if (url.endsWith('/api/sources')) return json(SOURCES_PAYLOAD)
      throw new Error(`unexpected ${url}`)
    }) as unknown as typeof fetch
    const ref: EvidenceObjectRef = { kind: 'computation', key: 'comp-001', label: 'sum' }
    const { container, ctx } = setupPage(fetcher, ref)
    await renderEvidencePage(container, ctx)
    expect(container.querySelector('[data-status-row="method"]')?.textContent).toContain('sum')
    const verification = container.querySelector<HTMLElement>('[data-status-row="verification"] .evidence-status-value')
    expect(verification?.textContent).toContain('数值已核对')
    expect(verification?.dataset.tone).toBe('verified')
    expect(container.querySelector('[data-status-row="execution"]')?.textContent).toContain('python 3.12')
    expect(container.querySelector('.evidence-computation-parameters')?.textContent).toContain('"column": "revenue"')
    // 参数块是纯 JSON，标题在代码块之外。
    expect(JSON.parse(container.querySelector('.evidence-computation-parameters')!.textContent!)).toEqual({ column: 'revenue' })
    expect(container.querySelector('.evidence-computation-subhead')?.textContent).toBe('计算参数')
    expect(container.textContent).toContain('python 3.12')
    expect(container.textContent).toContain('数值已核对')
    expect(container.textContent).toContain('具备复算条件')
    const jump = Array.from(container.querySelectorAll<HTMLButtonElement>('button'))
      .find((button) => button.textContent === '查看事实')!
    jump.click()
    expect(ctx.navigate).toHaveBeenCalledWith({
      kind: 'fact',
      key: 'fact-aaaaaaaaaaaaaaaa',
      analysisId: 'analysis_001',
      label: 'fact-aaaaaaaaaaaaaaaa',
    })
    // 关系区包含输入快照（标签取自 sources 文件名）与输出事实。
    expect(container.querySelector('.evidence-relation-list')?.textContent).toContain('收入明细.csv')
  })
})

describe('图表页', () => {
  const CHART_REF: EvidenceObjectRef = { kind: 'chart', key: 'chart_001', label: 'chart_001' }

  it('pages plot data and restores cached and refreshed page positions', async () => {
    const source1 = {
      available: true,
      chartId: 'chart_001',
      datasetIds: ['dataset-url-abc0001'],
      transformNotes: ['按院区聚合'],
      computationId: 'comp-001',
      image: { size: 2048, sha256: 'a'.repeat(64) },
      plotData: [
        {
          fileResourceId: 'plot-1',
          role: 'main',
          columns: ['branch', 'value'],
          rowCount: 21,
          offset: 0,
          limit: 20,
          rows: Array.from({ length: 20 }, () => ['华东', 1000]),
          truncated: true,
        },
      ],
    }
    const source2 = {
      ...source1,
      plotData: [
        { ...source1.plotData[0], offset: 20, rows: [['华北', 1200]], truncated: false },
      ],
    }
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input) => {
      const url = String(input)
      if (url.includes('offset=20')) return json(source2)
      if (url.includes('/api/charts/')) return json(source1)
      throw new Error(`unexpected ${url}`)
    }) as unknown as typeof fetch
    const { container, ctx } = setupPage(fetcher, CHART_REF)
    await renderEvidencePage(container, ctx)
    expect(container.querySelector('[data-status-row="datasets"]')?.textContent).toContain('dataset-url-abc0001')
    // 来源数据集可直接打开快照页。
    container.querySelector<HTMLButtonElement>('[data-status-row="datasets"] button')!.click()
    expect(ctx.navigate).toHaveBeenCalledWith({ kind: 'dataset', key: 'dataset-url-abc0001', label: 'dataset-url-abc0001' })
    expect(container.textContent).toContain('按院区聚合')
    expect(container.textContent).toContain('作图数据（主序列）')
    expect(container.querySelector('.evidence-page-number')?.textContent).toBe('第 1 / 2 页')
    const more = container.querySelector<HTMLButtonElement>('.evidence-more')!
    more.click()
    await vi.waitFor(() => {
      expect(container.querySelector('.evidence-table')?.textContent).toContain('华北')
    })
    expect(container.querySelector('.evidence-table')?.textContent).not.toContain('华东')
    expect(ctx.page.chartOffset).toBe(20)
    expect(container.textContent).toContain('预览序号 21–21')
    expect(container.querySelector('.evidence-page-number')?.textContent).toBe('第 2 / 2 页')
    await renderEvidencePage(container, ctx)
    expect(container.textContent).toContain('华北')
    expect(fetcher).toHaveBeenCalledTimes(2)
    const fresh = setupPage(fetcher, CHART_REF)
    fresh.page.chartOffset = ctx.page.chartOffset
    await renderEvidencePage(fresh.container, fresh.ctx)
    expect(fresh.container.textContent).toContain('华北')
    fresh.container.querySelector<HTMLButtonElement>('.evidence-previous')!.click()
    await vi.waitFor(() => expect(fresh.page.chartOffset).toBe(0))
    expect(fresh.container.textContent).toContain('华东')
    expect(fresh.container.textContent).not.toContain('华北')
  })

  it('hides single-page pagination and explains charts without plot data', async () => {
    const base = {
      available: true, chartId: 'chart_001', datasetIds: [], transformNotes: [],
      computationId: null, image: { size: 1, sha256: 'a' },
    }
    const single = { ...base, plotData: [{ fileResourceId: 'plot-1', columns: ['value'], rowCount: 2,
      offset: 0, limit: 20, rows: [[1], [2]], truncated: false }] }
    const first = setupPage(vi.fn<typeof fetch>().mockImplementation(async () => json(single)) as unknown as typeof fetch, CHART_REF)
    await renderEvidencePage(first.container, first.ctx)
    expect(first.container.querySelector<HTMLElement>('.evidence-pagination')?.hidden).toBe(true)
    expect(first.container.querySelector('.evidence-plot-empty')).toBeNull()

    const empty = setupPage(vi.fn<typeof fetch>().mockImplementation(async () => json({ ...base, plotData: [] })) as unknown as typeof fetch, CHART_REF)
    await renderEvidencePage(empty.container, empty.ctx)
    expect(empty.container.querySelector('.evidence-plot-empty')?.textContent).toContain('未登记作图数据')
    expect(empty.container.querySelector<HTMLElement>('.evidence-pagination')?.hidden).toBe(true)
  })

  it('keeps current rows and offset on failure and offers retry', async () => {
    const source = {
      available: true, chartId: 'chart_001', datasetIds: [], transformNotes: [],
      computationId: null, image: { size: 1, sha256: 'a' },
      plotData: [{ fileResourceId: 'plot-1', columns: ['value'], rowCount: 21,
        offset: 0, limit: 20, rows: Array.from({ length: 20 }, () => [1000]), truncated: true }],
    }
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(json(source))
      .mockResolvedValueOnce(new Response(JSON.stringify({ code: 'snapshot_integrity_failed' }), { status: 409 }))
      .mockResolvedValueOnce(json({ ...source, plotData: [{ ...source.plotData[0], offset: 20,
        rows: [[1200]], truncated: false }] }))
    const { container, ctx, page } = setupPage(fetcher, CHART_REF)
    await renderEvidencePage(container, ctx)
    container.querySelector<HTMLButtonElement>('.evidence-more')!.click()
    await vi.waitFor(() => expect(container.querySelector('.evidence-more-error')).not.toBeNull())
    expect(page.chartOffset).toBe(0)
    expect(container.querySelector('.evidence-table')?.textContent).toContain('1000')
    expect(container.querySelector<HTMLButtonElement>('.evidence-more')!.disabled).toBe(false)
    container.querySelector<HTMLButtonElement>('.evidence-more')!.click()
    await vi.waitFor(() => expect(page.chartOffset).toBe(20))
    expect(container.querySelector('.evidence-table')?.textContent).toContain('1200')
    expect(container.querySelector('.evidence-more-error')).toBeNull()
  })

  it('ignores a pagination response after leaving the page', async () => {
    const source = {
      available: true, chartId: 'chart_001', datasetIds: [], transformNotes: [],
      computationId: null, image: { size: 1, sha256: 'a' },
      plotData: [{ fileResourceId: 'plot-1', columns: ['value'], rowCount: 21, offset: 0,
        limit: 20, rows: Array.from({ length: 20 }, () => [1000]), truncated: true }],
    }
    let finish!: (response: Response) => void
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(json(source))
      .mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const { container, ctx, controller, page } = setupPage(fetcher, CHART_REF)
    await renderEvidencePage(container, ctx)
    container.querySelector<HTMLButtonElement>('.evidence-more')!.click()
    controller.abort()
    finish(json({ ...source, plotData: [{ ...source.plotData[0], offset: 20,
      rows: [[1200]], truncated: false }] }))
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(page.chartOffset).toBe(0)
    expect(container.querySelector('.evidence-table')?.textContent).not.toContain('1200')
  })

  it('shows empty short plot tables without an inverted preview range', async () => {
    const source = {
      available: true, chartId: 'chart_001', datasetIds: [], transformNotes: [],
      computationId: null, image: { size: 1, sha256: 'a' },
      plotData: [
        { fileResourceId: 'long', columns: ['value'], rowCount: 21, offset: 20,
          limit: 20, rows: [[21]], truncated: false },
        { fileResourceId: 'short', columns: ['value'], rowCount: 2, offset: 20,
          limit: 20, rows: [], truncated: false },
      ],
    }
    const { container, ctx, page } = setupPage(vi.fn().mockResolvedValue(json(source)), CHART_REF)
    page.chartOffset = 20
    await renderEvidencePage(container, ctx)
    expect(container.textContent).toContain('当前页无预览记录')
    expect(container.textContent).not.toContain('21–20')
    expect(container.querySelectorAll('.evidence-table')).toHaveLength(2)
    expect(container.querySelector('.evidence-more')).toBeNull()
    expect(container.querySelector('.evidence-previous')).not.toBeNull()
  })

})

describe('引用页', () => {
  const SUBJECT_REF: EvidenceObjectRef = {
    kind: 'subject',
    key: 'sub-cccccccccccccccc',
    label: '正文引用 #cccccc',
  }

  it('displays backend semantic warnings without invalidating the citation', async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input, init) => {
      if (String(input).includes('/validate')) return json({ draftSha256: JSON.parse(String(init!.body)).draftSha256,
        subjects: [{ subjectId: SUBJECT_REF.key, status: 'valid', factValue: 12450,
          warnings: ['单位文本与生成时不一致（生成时 万元）'] }],
        summary: { valid: 1, stale: 0, unbound: 0 } })
      return json(SOURCES_PAYLOAD)
    })
    const { container, ctx } = setupPage(fetcher, SUBJECT_REF,
      { getDraft: () => ({ markdown: '收入12450亿元', sha256: 'x' }) })
    await renderEvidencePage(container, ctx)
    expect(container.querySelector('[data-status-row="citation"]')?.textContent).toContain('引用有效')
    expect(container.querySelector('.evidence-warning')?.textContent).toContain('单位文本与生成时不一致')
    expect(container.querySelector('.evidence-locate')).not.toBeNull()
    // 软告警排在全部状态行之后，状态行不被拆开。
    const area = container.querySelector('[data-status-row="locator"]')!.parentElement!
    expect([...area.children].filter((node) => !node.classList.contains('evidence-status'))
      .map((node) => (node as HTMLElement).dataset.statusRow ?? node.className))
      .toEqual(['citation', 'kind', 'locator', 'evidence-warning'])
  })

  it('renders identity, related objects and the locate action', async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.includes('/api/sources/validate')) {
        return json({
          draftSha256: JSON.parse(String(init!.body)).draftSha256,
          subjects: [
            {
              subjectId: 'sub-cccccccccccccccc',
              claimId: 'claim-1',
              sectionId: 'section_002',
              status: 'valid',
              factValue: 12450,
              unit: '万元',
            },
          ],
          summary: { valid: 1, stale: 0, unbound: 0 },
        })
      }
      if (url.endsWith('/api/sources')) return json(SOURCES_PAYLOAD)
      throw new Error(`unexpected ${url}`)
    }) as unknown as typeof fetch
    const { container, ctx } = setupPage(fetcher, SUBJECT_REF, {
      getDraft: () => ({ markdown: '报告正文', sha256: 'x' }),
    })
    await renderEvidencePage(container, ctx)
    expect(container.querySelector('[data-status-row="citation"]')?.textContent).toContain('✓ 引用有效')
    expect(container.querySelector('[data-status-row="locator"]')?.textContent).toContain('章节 section_002')
    const locate = Array.from(container.querySelectorAll<HTMLButtonElement>('button'))
      .find((button) => button.textContent === '定位正文')!
    // 定位操作紧挨正文位置，而不是游离在页面底部。
    expect(locate.closest('[data-status-row="locator"]')).not.toBeNull()
    locate.click()
    expect(ctx.locateSubject).toHaveBeenCalledWith('sub-cccccccccccccccc')
    const factLink = Array.from(container.querySelectorAll<HTMLButtonElement>('.evidence-subject-links button'))
      .find((button) => button.textContent?.startsWith('事实'))!
    factLink.click()
    expect(ctx.navigate).toHaveBeenCalledWith({
      kind: 'fact',
      key: 'fact-aaaaaaaaaaaaaaaa',
      analysisId: 'analysis_001',
      label: 'fact-aaaaaaaaaaaaaaaa',
    })
  })

  it('shows the stable error label when the subject is absent', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(json(SOURCES_PAYLOAD)) as unknown as typeof fetch
    const { container, ctx } = setupPage(fetcher, {
      kind: 'subject',
      key: 'sub-missing00000000',
      label: '正文引用 #miss',
    })
    await renderEvidencePage(container, ctx)
    expect(container.querySelector('.evidence-status')?.textContent).toContain('来源不存在')
    expect(container.querySelector('.evidence-retry')).toBeNull()
  })
})

describe('节点分支加载', () => {
  const ref: EvidenceObjectRef = { kind: 'subject', key: 'sub-cccccccccccccccc', label: '正文引用' }
  const computation: EvidenceObjectRef = { kind: 'computation', key: 'comp-001', label: 'comp-001' }

  it('loads one branch without navigating or moving known nodes and retries a failed branch', async () => {
    let attempts = 0
    let finish!: (response: Response) => void
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async input => {
      const url = String(input)
      if (url.endsWith('/api/sources')) return json(SOURCES_PAYLOAD)
      if (url.includes('/api/computations/')) {
        attempts += 1
        if (attempts === 1) return new Response(JSON.stringify({ detail: { code: 'snapshot_integrity_failed' } }), { status: 409 })
        return new Promise(resolve => { finish = resolve })
      }
      throw new Error(url)
    })
    const graph = createEvidenceGraph()
    const { container, ctx, page } = setupPage(fetcher, ref, { graph })
    await renderEvidencePage(container, ctx)
    page.selected = computation
    await renderEvidencePage(container, ctx)
    const original = [...graph.positions].map(([id, position]) => [id, { ...position }])
    const click = () => container.querySelector<HTMLButtonElement>('.evidence-branch-load')!.click()
    click()
    await vi.waitFor(() => expect(container.textContent).toContain('重试加载关系'))
    expect(graph.nodes.size).toBe(3)
    expect(container.textContent).toContain('关系加载失败')
    click()
    expect(container.querySelector<HTMLButtonElement>('.evidence-branch-load')!.disabled).toBe(true)
    expect(container.textContent).toContain('关系加载中')
    finish(json(COMPUTATION_DETAIL))
    await vi.waitFor(() => expect(container.textContent).toContain('已加载登记关系'))
    expect(graph.nodes.has('dataset:dataset-url-abc0001')).toBe(true)
    for (const [id, position] of original) expect(graph.positions.get(id as string)).toEqual(position)
    expect(ctx.navigate).not.toHaveBeenCalled()
    expect(page.ref).toEqual(ref)
    expect(page.selected).toEqual(computation)
    click()
    expect(attempts).toBe(2)
  })

  it('ignores branch results after the page is left', async () => {
    let finish!: (response: Response) => void
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async input => {
      if (String(input).endsWith('/api/sources')) return json(SOURCES_PAYLOAD)
      return new Promise(resolve => { finish = resolve })
    })
    const graph = createEvidenceGraph()
    const { container, ctx, controller, page } = setupPage(fetcher, ref, { graph })
    await renderEvidencePage(container, ctx)
    page.selected = computation
    await renderEvidencePage(container, ctx)
    container.querySelector<HTMLButtonElement>('.evidence-branch-load')!.click()
    controller.abort()
    finish(json(COMPUTATION_DETAIL))
    await vi.waitFor(() => expect(graph.branches.has('computation:comp-001')).toBe(false))
    expect(graph.nodes.has('dataset:dataset-url-abc0001')).toBe(false)
    expect(ctx.navigate).not.toHaveBeenCalled()
  })
})
