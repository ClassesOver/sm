import { describe, expect, it, vi } from 'vitest'

import { ReportEditorApiError, ReportEditorClient } from './api'
import { createTracePanel } from './trace-panel'

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
      computationId: null,
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
            dimensions: [{ code: 'branch', label: '院区' }],
          },
        ],
      },
    ],
  },
}

const PREVIEW_PAYLOAD = {
  datasetId: 'dataset-url-abc0001',
  columns: ['period', 'revenue'],
  rows: [
    ['2025-08', '1000'],
    ['2025-09', '1200'],
  ],
  rowCountTotal: 4,
  offset: 0,
  limit: 2,
  nextCursor: 'cursor-2',
  truncatedCells: 0,
  truncatedByBudget: false,
  cellTruncationNote: null,
}

function setupPanel(fetcher: typeof fetch) {
  const client = makeClient(fetcher)
  const root = document.createElement('div')
  const panel = createTracePanel(root, client)
  return { root, panel, client }
}

describe('retained source metadata', () => {
  it('shows expired snapshot metadata without enabling file actions', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({
      ...SOURCES_PAYLOAD, available: false, reason: 'snapshot_expired',
    })))
    const { root, panel } = setupPanel(fetcher)
    panel.open()
    await vi.waitFor(() => expect(root.textContent).toContain('明细不可用'))
    expect(root.textContent).toContain('收入明细.csv')
    expect(root.textContent).toContain('4 行')
    for (const button of Array.from(root.querySelectorAll<HTMLButtonElement>('.trace-item-actions button'))) {
      expect(button.disabled).toBe(true)
    }
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
})

describe('ReportEditorClient trace APIs', () => {
  it('loads sources and dataset previews with pagination params', async () => {
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify(SOURCES_PAYLOAD)))
      .mockResolvedValueOnce(new Response(JSON.stringify(PREVIEW_PAYLOAD)))
    const client = makeClient(fetcher as typeof fetch)
    await expect(client.sources()).resolves.toMatchObject({ available: true })
    await expect(
      client.datasetPreview('dataset-url-abc0001', { limit: 2, cursor: 'cursor-2' }),
    ).resolves.toMatchObject({ rowCountTotal: 4 })
    expect(fetcher.mock.calls[0][0]).toBe('/reports/v1/editor/report-1/1/api/sources')
    expect(fetcher.mock.calls[1][0]).toBe(
      '/reports/v1/editor/report-1/1/api/datasets/dataset-url-abc0001/preview?limit=2&cursor=cursor-2',
    )
  })

  it('builds download URLs and surfaces stable trace error codes', async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async () =>
      new Response(JSON.stringify({ detail: { code: 'dataset_access_denied' } }), { status: 403 }),
    )
    const client = makeClient(fetcher as typeof fetch)
    expect(client.datasetDownloadUrl('dataset-url-abc0001')).toBe(
      '/reports/v1/editor/report-1/1/api/datasets/dataset-url-abc0001/download',
    )
    await expect(client.sources()).rejects.toBeInstanceOf(ReportEditorApiError)
    try {
      await client.sources()
    } catch (error) {
      expect(error).toBeInstanceOf(ReportEditorApiError)
      expect((error as ReportEditorApiError).code).toBe('dataset_access_denied')
    }
  })

  it('requests fact and chart sources with encoded ids', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ available: true })),
    )
    const client = makeClient(fetcher as typeof fetch)
    await client.factDetail('analysis_001', 'fact-abc')
    await client.chartSource('chart_001', { limit: 20, offset: 20 })
    expect(fetcher.mock.calls[0][0]).toBe('/reports/v1/editor/report-1/1/api/facts/analysis_001/fact-abc')
    expect(fetcher.mock.calls[1][0]).toBe(
      '/reports/v1/editor/report-1/1/api/charts/chart_001/source?limit=20&offset=20',
    )
  })

  it('posts only registered drilldown selections', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          metricCode: 'income_total',
          datasetId: 'dataset-url-abc0001',
          dimensionCode: 'branch',
          rows: [],
          reconciliation: { passed: true },
        }),
      ),
    )
    const client = makeClient(fetcher as typeof fetch)
    await client.drilldown(
      'sub-cccccccccccccccc',
      { metricCode: 'income_total', datasetId: 'dataset-url-abc0001' },
      'branch',
    )
    expect(fetcher.mock.calls[0][0]).toBe(
      '/reports/v1/editor/report-1/1/api/sources/sub-cccccccccccccccc/drilldown',
    )
    expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({
      metricCode: 'income_total',
      datasetId: 'dataset-url-abc0001',
      dimensionCode: 'branch',
      limit: 50,
    })

    await client.drilldownMetric(
      { metricCode: 'income_total', datasetId: 'dataset-url-abc0001' },
      'branch',
      { limit: 25, cursor: 'next-page' },
    )
    expect(fetcher.mock.calls[1][0]).toBe(
      '/reports/v1/editor/report-1/1/api/drilldowns/income_total',
    )
    expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body))).toEqual({
      metricCode: 'income_total',
      datasetId: 'dataset-url-abc0001',
      dimensionCode: 'branch',
      limit: 25,
      cursor: 'next-page',
    })
  })
})

describe('trace subject links', () => {
  it('opens the exact fact addressed by a subject query link', async () => {
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify(SOURCES_PAYLOAD)))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        analysisId: 'analysis_001',
        factId: 'fact-aaaaaaaaaaaaaaaa',
        factKind: 'metric',
        displayValue: 3600,
        entry: { unit: '万元' },
        inputFactRefs: [],
        warnings: [],
      })))
    const { root, panel } = setupPanel(fetcher as typeof fetch)

    await panel.openSubject('sub-cccccccccccccccc')
    await vi.waitFor(() => {
      expect(root.querySelector('.trace-fact-value')?.textContent).toContain('3600 万元')
    })
    expect(fetcher.mock.calls[1][0]).toBe(
      '/reports/v1/editor/report-1/1/api/facts/analysis_001/fact-aaaaaaaaaaaaaaaa',
    )
  })

  it('does not guess when a subject is absent from the frozen revision', async () => {
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify(SOURCES_PAYLOAD)))
    const { root, panel } = setupPanel(fetcher as typeof fetch)

    await panel.openSubject('sub-missing00000000')

    expect(root.querySelector<HTMLElement>('[data-trace="status"]')?.textContent)
      .toContain('来源不存在')
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('explains that an expired session must be reopened instead of offering retry', async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementationOnce(async () =>
      new Response(
        JSON.stringify({ detail: { code: 'report_editor_session_expired' } }),
        { status: 410 },
      ),
    )
    const { root, panel } = setupPanel(fetcher as typeof fetch)

    await panel.openSubject('sub-cccccccccccccccc')

    await vi.waitFor(() => {
      const status = root.querySelector<HTMLElement>('[data-trace="status"]')!
      expect(status.textContent).toContain('会话已过期')
      expect(status.dataset.state).toBe('error')
    })
    // 410 不是服务器故障：不能给“重试”按钮误导用户刷新过期会话。
    expect(root.querySelector('.trace-retry')).toBeNull()
  })
})

describe('createTracePanel', () => {
  it('renders dataset snapshots with preview and download actions', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(SOURCES_PAYLOAD)),
    )
    const { root, panel } = setupPanel(fetcher as typeof fetch)
    panel.open()
    await vi.waitFor(() => {
      expect(root.querySelector('.trace-item-title')?.textContent).toBe('收入明细.csv')
    })
    expect(root.querySelector('.trace-item-meta')?.textContent).toContain('4 行')
    const buttons = Array.from(root.querySelectorAll<HTMLButtonElement>('.trace-item-actions button'))
    expect(buttons.map((button) => button.textContent)).toEqual(['预览', '下载原始'])
  })

  it('keeps preview but omits download when the rollout feature is disabled', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(SOURCES_PAYLOAD)),
    )
    const { root, panel } = setupPanel(fetcher as typeof fetch)
    panel.setDownloadEnabled(false)
    panel.setDrilldownEnabled(false)

    panel.open()

    await vi.waitFor(() => expect(root.textContent).toContain('收入明细.csv'))
    const buttons = Array.from(
      root.querySelectorAll<HTMLButtonElement>('.trace-item-actions button'),
    )
    expect(buttons.map((button) => button.textContent)).toEqual(['预览'])
    expect(
      Array.from(root.querySelectorAll<HTMLButtonElement>('[data-trace-tab]'))
        .find((button) => button.textContent === '下钻')?.hidden,
    ).toBe(true)
  })

  it('shows honest empty state when the revision has no trace index', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ available: false, reason: 'source_index_missing', datasets: [] })),
    )
    const { root, panel } = setupPanel(fetcher as typeof fetch)
    panel.open()
    await vi.waitFor(() => {
      expect(root.querySelector<HTMLElement>('[data-trace="status"]')?.textContent).toContain(
        '没有来源索引',
      )
    })
  })

  it('maps 403 to a clear no-permission message without retry', async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async () =>
      new Response(JSON.stringify({ detail: { code: 'dataset_access_denied' } }), { status: 403 }),
    )
    const { root, panel } = setupPanel(fetcher as typeof fetch)
    panel.open()
    await vi.waitFor(() => {
      const status = root.querySelector<HTMLElement>('[data-trace="status"]')!
      expect(status.textContent).toContain('无权访问')
      expect(status.dataset.state).toBe('error')
    })
    expect(root.querySelector('.trace-retry')).toBeNull()
  })

  it('offers retry for server failures', async () => {
    const fetcher = vi.fn<typeof fetch>()
      .mockImplementationOnce(async () => new Response('boom', { status: 502 }))
      .mockImplementationOnce(async () => new Response(JSON.stringify(SOURCES_PAYLOAD)))
    const { root, panel } = setupPanel(fetcher as typeof fetch)
    panel.open()
    await vi.waitFor(() => {
      expect(root.querySelector('.trace-retry')).not.toBeNull()
    })
    ;(root.querySelector('.trace-retry') as HTMLButtonElement).click()
    await vi.waitFor(() => {
      expect(root.querySelector('.trace-item-title')?.textContent).toBe('收入明细.csv')
    })
  })

  it('renders paginated preview tables with a load-more control', async () => {
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify(SOURCES_PAYLOAD)))
      .mockResolvedValueOnce(new Response(JSON.stringify(PREVIEW_PAYLOAD)))
    const { root, panel } = setupPanel(fetcher as typeof fetch)
    panel.open()
    await vi.waitFor(() => {
      expect(root.querySelector('.trace-item-title')).not.toBeNull()
    })
    ;(root.querySelector<HTMLButtonElement>('.trace-item-actions button') as HTMLButtonElement).click()
    await vi.waitFor(() => {
      expect(root.querySelectorAll('.trace-table th').length).toBe(2)
      expect(root.querySelector('.trace-table')?.textContent).toContain('1200')
      expect(root.querySelector('.trace-more')?.textContent).toBe('加载更多')
    })
  })

  it('shows registered dimensions and renders reconciled drilldown rows', async () => {
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify(SOURCES_PAYLOAD)))
      .mockResolvedValueOnce(new Response(JSON.stringify(SOURCES_PAYLOAD)))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            metricCode: 'income_total',
            datasetId: 'dataset-url-abc0001',
            dimensionCode: 'branch',
            aggregation: 'sum',
            rows: [
              { group: 'A院区', value: 1200 },
              { group: 'B院区', value: 2400 },
            ],
            groupCountTotal: 2,
            offset: 0,
            limit: 50,
            nextCursor: null,
            unit: '元',
            reconciliation: {
              expectedValue: 3600,
              observedValue: 3600,
              difference: 0,
              passed: true,
            },
            snapshot: {
              datasetId: 'dataset-url-abc0001',
              sha256: 'a'.repeat(64),
            },
            scope: {
              kind: 'registered_snapshot',
              fixed: { scope: 'current' },
              period: null,
            },
            calculation: {
              aggregation: 'sum',
              description: '按登记范围对数值求和',
            },
          }),
        ),
      )
    const { root, panel } = setupPanel(fetcher as typeof fetch)
    panel.open()
    const tabs = root.querySelectorAll<HTMLButtonElement>('.trace-tab')
    tabs[tabs.length - 1]!.click()
    await vi.waitFor(() => {
      expect(root.querySelector('.trace-item-actions button')?.textContent).toBe('按院区下钻')
    })
    ;(root.querySelector('.trace-item-actions button') as HTMLButtonElement).click()
    await vi.waitFor(() => {
      expect(root.querySelector('.trace-table')?.textContent).toContain('B院区')
      expect(root.querySelector<HTMLElement>('[data-trace="status"]')?.textContent).toContain(
        '核对一致',
      )
      expect(root.querySelector<HTMLElement>('[data-trace="status"]')?.textContent).toContain(
        '快照 aaaaaaaaaaaa',
      )
    })
    expect(fetcher.mock.calls[2][0]).toBe(
      '/reports/v1/editor/report-1/1/api/drilldowns/income_total',
    )
  })

  it('switches tabs and aborts in-flight requests', async () => {
    const releaseSources = vi.fn<() => void>()
    const sourcesPromise = new Promise<Response>((resolve) => {
      releaseSources.mockImplementation(() =>
        resolve(new Response(JSON.stringify(SOURCES_PAYLOAD))),
      )
    })
    const fetcher = vi.fn<typeof fetch>()
      .mockImplementationOnce(() => sourcesPromise)
      .mockImplementationOnce(
        async () =>
          new Response(
            JSON.stringify({
              available: true,
              analyses: [{ analysisId: 'analysis_001', contentKind: 'deterministic_bundle' }],
            }),
          ),
      )
    const { root, panel } = setupPanel(fetcher as typeof fetch)
    panel.open()
    // 切到事实 tab：数据 tab 的挂起请求应被 abort，不再渲染其结果。
    ;(root.querySelectorAll<HTMLButtonElement>('.trace-tab')[1] as HTMLButtonElement).click()
    await vi.waitFor(() => {
      expect(root.querySelector('.trace-item-title')?.textContent).toBe('analysis_001')
    })
    releaseSources()
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(root.querySelectorAll('.trace-item').length).toBe(1)
  })

  it('does not render stale success, stale error, or content after closing the panel', async () => {
    const releaseSources = vi.fn<() => void>()
    const sourcesPromise = new Promise<Response>((resolve) => {
      releaseSources.mockImplementation(() =>
        resolve(new Response(JSON.stringify(SOURCES_PAYLOAD))),
      )
    })
    const fetcher = vi.fn<typeof fetch>().mockImplementationOnce(() => sourcesPromise)
    const { root, panel } = setupPanel(fetcher as typeof fetch)
    panel.open()
    const chartsTab = root.querySelectorAll<HTMLButtonElement>('.trace-tab')[2]!
    chartsTab.click()
    panel.close()
    expect(root.querySelector<HTMLElement>('.modal-overlay')!.hidden).toBe(true)
    releaseSources()
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(root.querySelector('.trace-item-title')).toBeNull()
    const status = root.querySelector<HTMLElement>('[data-trace="status"]')!
    expect(status.textContent).toBe('')
    expect(status.dataset.state).not.toBe('error')
    expect(root.querySelector('.trace-retry')).toBeNull()
  })

  it('closes via Escape and drops an in-flight preview response', async () => {
    const releasePreview = vi.fn<() => void>()
    const previewPromise = new Promise<Response>((resolve) => {
      releasePreview.mockImplementation(() => resolve(new Response(JSON.stringify(PREVIEW_PAYLOAD))))
    })
    const fetcher = vi.fn<typeof fetch>()
      .mockImplementationOnce(async () => new Response(JSON.stringify(SOURCES_PAYLOAD)))
      .mockImplementationOnce(() => previewPromise)
    const { root, panel } = setupPanel(fetcher as typeof fetch)
    panel.open()
    await vi.waitFor(() => {
      expect(root.querySelector('.trace-item-title')?.textContent).toBe('收入明细.csv')
    })
    ;(root.querySelector<HTMLButtonElement>('.trace-item-actions button') as HTMLButtonElement).click()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    const overlay = root.querySelector<HTMLElement>('.modal-overlay')!
    expect(overlay.hidden).toBe(true)
    releasePreview()
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(root.querySelector('.trace-table')).toBeNull()
  })

  it('renders server-provided chart and computation fields as text, never markup', async () => {
    const malicious = '<img src=x onerror="window.__tracePwned=1"><p>evil</p>'
    const chartPayload = {
      available: true,
      chartId: 'chart_001',
      datasetIds: ['d<script>1</script>'],
      transformNotes: [malicious],
      computationId: null,
      image: { size: 10, sha256: 'a'.repeat(64) },
      plotData: [],
    }
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify(SOURCES_PAYLOAD)))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ available: true, charts: [{ chartId: 'chart_001', datasetIds: ['d1'], plotDataFileCount: 1, imageSize: 10 }] })),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify(chartPayload)))
    const { root, panel } = setupPanel(fetcher as typeof fetch)
    panel.open()
    ;(root.querySelectorAll<HTMLButtonElement>('.trace-tab')[2] as HTMLButtonElement).click()
    await vi.waitFor(() => {
      expect(root.querySelector('.trace-item-title')?.textContent).toBe('chart_001')
    })
    ;(root.querySelector<HTMLButtonElement>('.trace-item-actions button') as HTMLButtonElement).click()
    await vi.waitFor(() => {
      expect(root.querySelector('.trace-chart-info')?.textContent).toContain('<img src=x')
    })
    expect(root.querySelector('.trace-chart-info img')).toBeNull()
    expect((window as unknown as Record<string, unknown>).__tracePwned).toBeUndefined()
  })
})
