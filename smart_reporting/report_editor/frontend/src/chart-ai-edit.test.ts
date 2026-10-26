import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ReportEditorClient, TraceChartInfo } from './api'
import {
  applyChartReplacement,
  assetUrl,
  chartAiUnavailableReason,
  createChartAIEdit,
  matchChartForImage,
} from './chart-ai-edit'

const chart: TraceChartInfo = {
  chartId: 'chart_001',
  datasetIds: ['dataset-1'],
  datasetIdsRegistered: true,
  plotDataFileCount: 1,
  plotDataKind: 'chart_input',
  transformNotes: [],
  imagePath: 'reports/revision-1/chart-001.png',
  imageSize: 10,
}

describe('matchChartForImage', () => {
  it('按后缀唯一匹配正文图片', () => {
    expect(matchChartForImage([chart], 'chart-001.png')).toBe(chart)
    expect(matchChartForImage([chart], 'reports/revision-1/chart-001.png')).toBe(chart)
    expect(matchChartForImage([chart], '/b/asset/reports/revision-1/chart-001.png', '/b')).toBe(chart)
  })

  it('拒绝歧义、目录逃逸与未登记图片', () => {
    const same = { ...chart, chartId: 'chart_002' }
    expect(matchChartForImage([chart, same], 'chart-001.png')).toBeNull()
    expect(matchChartForImage([chart], '../chart-001.png')).toBeNull()
    expect(matchChartForImage([chart], 'other.png')).toBeNull()
    expect(matchChartForImage([], 'chart-001.png')).toBeNull()
  })
})

describe('assetUrl', () => {
  it('逐段编码资源路径', () => {
    expect(assetUrl('/reports/v1/editor/r/1', 'reports/x/chart.png'))
      .toBe('/reports/v1/editor/r/1/asset/reports/x/chart.png')
    expect(assetUrl('/b', '中文 目/chart.png')).toContain(encodeURIComponent('中文 目'))
  })
})

describe('chartAiUnavailableReason', () => {
  it('映射禁用原因文案', () => {
    expect(chartAiUnavailableReason('plot_data_missing')).toContain('没有登记作图数据')
    expect(chartAiUnavailableReason('unknown')).toBe(chartAiUnavailableReason())
  })
})

describe('applyChartReplacement', () => {
  function fakeView(nodeType: string) {
    const node = {
      type: { name: nodeType },
      attrs: { src: 'chart-001.png', caption: '旧图注', alt: '旧 alt' },
      nodeSize: 4,
      isTextblock: false,
    }
    const captionNode = {
      type: { name: 'paragraph' },
      attrs: {},
      nodeSize: 6,
      isTextblock: true,
      textContent: '图表：收入对比',
    }
    const marks: Array<[string, ...unknown[]]> = []
    const tr = {
      setNodeMarkup(pos: number, _type: unknown, attrs: Record<string, unknown>) {
        marks.push(['setNodeMarkup', pos, attrs])
        return tr
      },
      insertText(text: string, from: number, to: number) {
        marks.push(['insertText', text, from, to])
        return tr
      },
    }
    const view = {
      posAtDOM: () => 2,
      state: {
        doc: {
          resolve: () => ({ depth: 1, before: () => 2 }),
          nodeAt: (pos: number) => (pos === 2 ? node : captionNode),
        },
        tr,
      },
      dispatch: vi.fn(),
    }
    return { view, marks }
  }

  it('一次事务替换图片节点并改写图注段落', () => {
    const { view, marks } = fakeView('image-block')
    const ok = applyChartReplacement(
      view as never,
      document.createElement('img'),
      'chart-edits/cedit-1/chart.png',
      '收入横向对比',
    )
    expect(ok).toBe(true)
    expect(view.dispatch).toHaveBeenCalledTimes(1)
    const attrs = (marks[0] as unknown[])[2] as Record<string, unknown>
    expect(attrs.src).toBe('chart-edits/cedit-1/chart.png')
    expect(attrs.caption).toBe('收入横向对比')
    expect(marks[1]![0]).toBe('insertText')
  })

  it('图注为空时只替换图片；非图片节点返回 false', () => {
    const { view, marks } = fakeView('paragraph')
    expect(applyChartReplacement(view as never, document.createElement('img'), 'x.png', null)).toBe(false)
    expect(view.dispatch).not.toHaveBeenCalled()
    const inline = fakeView('image')
    expect(applyChartReplacement(inline.view as never, document.createElement('img'), 'x.png', null)).toBe(true)
    expect(inline.marks[0]![0]).toBe('setNodeMarkup')
  })
})

type StatusQueue = Array<Record<string, unknown>>

function fakeClient(overrides: Partial<Record<string, unknown>> = {}) {
  const calls: Record<string, unknown[]> = {}
  const client = {
    charts: vi.fn(async () => ({ available: true, charts: [chart] })),
    chartAiAvailability: vi.fn(async () => ({ available: true, chartId: 'chart_001' })),
    startChartAiEdit: vi.fn(async () => ({ editId: 'cedit-abc12345', status: 'queued' })),
    chartAiEditStatus: vi.fn(async () => ({ editId: 'cedit-abc12345', status: 'succeeded' })),
    cancelChartAiEdit: vi.fn(async () => undefined),
    ...overrides,
  }
  for (const key of Object.keys(client)) {
    calls[key] = []
  }
  return client as unknown as ReportEditorClient & Record<string, ReturnType<typeof vi.fn>>
}

function fakeViewForController() {
  const node = {
    type: { name: 'image-block' },
    attrs: { src: 'chart-001.png', caption: '旧图注' },
    nodeSize: 4,
    isTextblock: false,
  }
  const tr = {
    setNodeMarkup(_pos: number, _t: unknown, _attrs: Record<string, unknown>) {
      return tr
    },
    insertText() {
      return tr
    },
  }
  return {
    posAtDOM: () => 2,
    state: {
      doc: {
        resolve: () => ({ depth: 1, before: () => 2 }),
        nodeAt: () => node,
      },
      tr,
    },
    dispatch: vi.fn(),
  } as unknown as Parameters<typeof createChartAIEdit>[0]['view']
}

const IMG_SRC = 'http://localhost/asset/reports/revision-1/chart-001.png'

function mountEditorWithImage(): HTMLImageElement {
  document.body.innerHTML = '<div id="editor"><img src="/b/asset/reports/revision-1/chart-001.png" alt="收入对比"></div>'
  return document.querySelector('img')!
}

describe('createChartAIEdit', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('输入阶段展示当前图与快捷指令', async () => {
    const client = fakeClient()
    const controller = createChartAIEdit({
      view: fakeViewForController(),
      client,
      basePath: '/b',
      pollIntervalMs: 1,
    })
    controller.open(mountEditorWithImage())
    await vi.waitFor(() => {
      expect(document.querySelector('#chart-ai-instruction')).not.toBeNull()
    })
    expect(document.querySelectorAll('.chart-ai-chip').length).toBeGreaterThan(0)
    expect(document.querySelector('.chart-ai-current img')!.getAttribute('src')).toContain(
      'asset/reports/revision-1/chart-001.png',
    )
    controller.dispose()
  })

  it('禁用时展示原因并触发 onError', async () => {
    const client = fakeClient({
      chartAiAvailability: vi.fn(async () => ({ available: false, reason: 'plot_data_missing' })),
    })
    const onError = vi.fn()
    const controller = createChartAIEdit({
      view: fakeViewForController(),
      client,
      basePath: '/b',
      pollIntervalMs: 1,
      hooks: { onError },
    })
    controller.open(mountEditorWithImage())
    await vi.waitFor(() => {
      expect(document.querySelector('.chart-ai-unavailable')).not.toBeNull()
    })
    expect(document.querySelector('.chart-ai-unavailable p')!.textContent).toContain('没有登记作图数据')
    expect(onError).toHaveBeenCalledWith('report_editor_chart_ai_unavailable')
    controller.dispose()
  })

  it('成功后进入审阅卡，接受替换写回正文并回调 onReplaced', async () => {
    const client = fakeClient({
      chartAiEditStatus: vi.fn()
        .mockResolvedValueOnce({
          editId: 'cedit-abc12345', chartId: 'chart_001', status: 'running', stage: 'draw',
        })
        .mockResolvedValueOnce({
          editId: 'cedit-abc12345', chartId: 'chart_001', status: 'succeeded',
          imagePath: 'reports/revision-1/chart-edits/cedit-abc12345/chart.png',
          imageSrc: 'chart-edits/cedit-abc12345/chart.png',
          level: ['L1'],
          changes: { title: '收入（横向）', altText: '收入横向对比', visualForm: '横向条形图', plotDataUnchanged: true },
          warnings: ['视觉审查提示：图例遮挡'],
          skipped: [],
          visualInspection: { format: 'PNG', width: 64, height: 48, reviewed: true },
        }),
    })
    const onReplaced = vi.fn()
    const view = fakeViewForController()
    const controller = createChartAIEdit({
      view,
      client,
      basePath: '/b',
      pollIntervalMs: 1,
      hooks: { onReplaced },
    })
    controller.open(mountEditorWithImage())
    await vi.waitFor(() => {
      expect(document.querySelector('#chart-ai-instruction')).not.toBeNull()
    })
    const textarea = document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!
    textarea.value = '改成横向条形图并按金额降序'
    ;(document.querySelector('[data-action="submit"]') as HTMLButtonElement).click()
    await vi.waitFor(() => {
      expect(document.querySelector('.chart-ai-compare')).not.toBeNull()
    })
    expect(client.startChartAiEdit).toHaveBeenCalledWith('chart_001', expect.objectContaining({
      instruction: '改成横向条形图并按金额降序',
      baseImagePath: 'reports/revision-1/chart-001.png',
      baseAltText: '收入对比',
    }))
    const compareImages = [...document.querySelectorAll('.chart-ai-compare img')]
    expect(compareImages).toHaveLength(2)
    expect(compareImages[1]!.getAttribute('src')).toContain('chart-edits/cedit-abc12345/chart.png')
    expect(document.querySelector('.chart-ai-warnings')!.textContent).toContain('图例遮挡')
    ;(document.querySelector('[data-action="accept"]') as HTMLButtonElement).click()
    expect(view.dispatch).toHaveBeenCalledTimes(1)
    expect(onReplaced).toHaveBeenCalledWith('cedit-abc12345')
    controller.dispose()
  })

  it('失败时回到输入阶段并展示服务端原因', async () => {
    const client = fakeClient({
      chartAiEditStatus: vi.fn(async () => ({
        editId: 'cedit-abc12345', chartId: 'chart_001', status: 'failed',
        error: { code: 'report_editor_chart_ai_skipped', message: '改图要求全部超出当前可用数据范围', skipped: [{ request: '加预测', reason: '预测数据未登记' }] },
      })),
    })
    const controller = createChartAIEdit({
      view: fakeViewForController(),
      client,
      basePath: '/b',
      pollIntervalMs: 1,
    })
    controller.open(mountEditorWithImage())
    await vi.waitFor(() => {
      expect(document.querySelector('#chart-ai-instruction')).not.toBeNull()
    })
    const textarea = document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!
    textarea.value = '加预测'
    ;(document.querySelector('[data-action="submit"]') as HTMLButtonElement).click()
    await vi.waitFor(() => {
      expect(document.querySelector('.chart-ai-note')).not.toBeNull()
    })
    expect(document.querySelector('.chart-ai-note')!.textContent).toContain('预测数据未登记')
    controller.dispose()
  })
})
