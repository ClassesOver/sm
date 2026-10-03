import { afterEach, describe, expect, it, vi } from 'vitest'

import { ReportEditorClient } from './api'
import { createEvidenceGraph, mergeEvidenceGraph } from './evidence-graph'
import { renderEvidencePage, type EvidencePageContext } from './evidence-pages'
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
    expect(warning.textContent).toContain('正文当前值 12780 万元')
    expect(warning.textContent).toContain('登记值 12450 万元')
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
    expect(container.querySelector('.evidence-fact-value')?.textContent).toBe('登记值 12450 万元')
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
    expect(container.querySelector('.evidence-fact-value')?.textContent).toContain('登记值 12450 万元')
    expect(container.querySelector('.evidence-fact-formula')?.textContent).toContain('sum(revenue)')
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

  it('navigates to an input fact via the 查看 button', async () => {
    const { container, ctx } = setupPage(factFetcher(), FACT_REF)
    await renderEvidencePage(container, ctx)
    const jump = Array.from(container.querySelectorAll<HTMLButtonElement>('.evidence-fact-inputs button'))
      .find((button) => button.textContent === '查看')!
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
    await vi.waitFor(() => expect(container.querySelector('.evidence-fact-value')?.textContent).toContain('12450'))
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
      expect(container.querySelector('.evidence-fact-value')?.textContent).toContain('12450')
    })
    // 历史返回：pageData 命中缓存，不再发请求。
    const calls = (failing as ReturnType<typeof vi.fn>).mock.calls.length
    const second = document.createElement('div')
    await renderEvidencePage(second, ctx)
    expect(second.querySelector('.evidence-fact-value')?.textContent).toContain('12450')
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
    expect(toggle.textContent).toBe('切换 2D')
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
    expect(picker.options).toHaveLength(4)
    picker.value = 'fact:analysis_001/fact-input'
    picker.dispatchEvent(new Event('change'))
    expect(graph.querySelectorAll('.is-traced')).toHaveLength(1)
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
    const mapWidth = parseFloat(graph.querySelector<HTMLElement>('.evidence-graph-map')!.style.width)
    expect(page.graphScale).toBeCloseTo(Math.min(1, (300 - 32) / mapWidth), 5)
    expect(page.graphPan).toEqual({ x: 0, y: 0 })
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
    selectedGraph.querySelector<HTMLButtonElement>('.evidence-preview-enter')!.click()
    expect(selectedCtx.navigate).toHaveBeenCalledWith(selectedCtx.page.selected)
    const selectedNode = selectedGraph.querySelector<HTMLButtonElement>('.evidence-node.is-selected')!
    selectedNode.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    expect(selectedCtx.navigate).toHaveBeenCalledTimes(2)
    selectedNode.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(selectedCtx.setPreview).toHaveBeenCalledWith(null)

    // 事实页默认展开，切换后持久到 page.collapsed。
    const body = section.querySelector<HTMLElement>('.evidence-relations-body')!
    expect(body.hidden).toBe(false)
    section.querySelector<HTMLButtonElement>('.evidence-view-toggle')!.click()
    expect(page.showList).toBe(true)
    expect(section.querySelector<HTMLElement>('.evidence-graph')!.hidden).toBe(true)
    expect(section.querySelector<HTMLElement>('.evidence-relation-list')!.hidden).toBe(false)
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

  it('replaces the loaded page, preserves its cursor and can return to the previous page', async () => {
    const fetcher = datasetFetcher()
    const { container, ctx } = setupPage(fetcher, DATASET_REF)
    await renderEvidencePage(container, ctx)
    expect(container.querySelector('.evidence-dataset-scope')?.textContent).toContain('完整快照共 4 行')
    expect(container.querySelector('.evidence-dataset-scope')?.textContent).toContain('预览序号 1–2')
    expect(container.querySelectorAll('.evidence-table tbody tr, .evidence-table tr').length).toBe(3)

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

describe('计算页', () => {
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
    expect(container.textContent).toContain('方法：sum')
    expect(container.querySelector('.evidence-computation-parameters')?.textContent).toContain('"column": "revenue"')
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
    expect(container.textContent).toContain('数据集：dataset-url-abc0001')
    expect(container.textContent).toContain('按院区聚合')
    expect(container.textContent).toContain('作图数据（main）')
    const more = container.querySelector<HTMLButtonElement>('.evidence-more')!
    more.click()
    await vi.waitFor(() => {
      expect(container.querySelector('.evidence-table')?.textContent).toContain('华北')
    })
    expect(container.querySelector('.evidence-table')?.textContent).not.toContain('华东')
    expect(ctx.page.chartOffset).toBe(20)
    expect(container.textContent).toContain('预览序号 21–21')
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
    label: '正文引用 sub-cccc',
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
    expect(container.textContent).toContain('章节 section_002')
    const locate = Array.from(container.querySelectorAll<HTMLButtonElement>('button'))
      .find((button) => button.textContent === '定位正文')!
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
      label: '正文引用 sub-miss',
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
