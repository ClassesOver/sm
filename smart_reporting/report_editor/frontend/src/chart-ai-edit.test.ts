import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ReportEditorClient, TraceChartInfo } from './api'
import {
  applyChartReplacement,
  assetUrl,
  chartAiUnavailableReason,
  chartEditIdFromSrc,
  createChartAIEdit,
  matchChartForImage,
  quickCommandsForForm,
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

describe('quickCommandsForForm', () => {
  it('按当前图形形态优先推荐对应快捷指令，未知形态回落默认集', () => {
    const bar = quickCommandsForForm('横向条形图')
    expect(bar[0]).toBe('在图上显示数值标签')
    expect(bar).toContain('改成横向条形图')
    const line = quickCommandsForForm('月度趋势折线图')
    expect(line[0]).toBe('标注最高和最低的月份')
    const fallback = quickCommandsForForm(null)
    expect(fallback).toEqual(quickCommandsForForm())
    expect(fallback[0]).toContain('条形图')
  })
})

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
  function fakeView(nodeType: string, { inline = false, captionText = '图表：收入对比' } = {}) {
    const node = {
      type: { name: nodeType },
      attrs: { src: 'chart-001.png', caption: '旧图注', alt: '旧 alt' },
      nodeSize: inline ? 1 : 4,
      isTextblock: false,
      isInline: inline,
    }
    const captionNode = {
      type: { name: 'paragraph' },
      attrs: {},
      nodeSize: 6,
      isTextblock: true,
      textContent: captionText,
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
          // 行内图片位于段落内（段落结束于 10），图注段落在段落之后。
          resolve: () => ({ depth: 1, before: () => 2, after: () => 10 }),
          nodeAt: (pos: number) => (pos === 2 ? node : pos === (inline ? 10 : 6) ? captionNode : null),
        },
        tr,
      },
      dispatch: vi.fn(),
    }
    return { view, marks }
  }

  it('一次事务替换图片节点：“图表：”段落写标题，替代文本写图注', () => {
    const { view, marks } = fakeView('image-block')
    const ok = applyChartReplacement(
      view as never,
      document.createElement('img'),
      'chart-edits/cedit-1/chart.png',
      { title: '收入（横向）', altText: '收入横向对比' },
    )
    expect(ok).toBe(true)
    expect(view.dispatch).toHaveBeenCalledTimes(1)
    const attrs = (marks[0] as unknown[])[2] as Record<string, unknown>
    expect(attrs.src).toBe('chart-edits/cedit-1/chart.png')
    expect(attrs.caption).toBe('收入横向对比')
    expect(marks[1]).toEqual(['insertText', '图表：收入（横向）', 7, 11])
  })

  it('“图注：”段落写图注；标题未变时不改“图表：”段落', () => {
    const captioned = fakeView('image-block', { captionText: '图注：旧说明' })
    applyChartReplacement(captioned.view as never, document.createElement('img'), 'x.png',
      { title: '新标题', altText: '新说明' })
    expect(captioned.marks[1]).toEqual(['insertText', '图注：新说明', 7, 11])
    const titled = fakeView('image-block')
    applyChartReplacement(titled.view as never, document.createElement('img'), 'x.png',
      { title: null, altText: '新说明' })
    expect(titled.marks).toHaveLength(1)
  })

  it('行内图片按图片节点替换，图注段落取所在段落之后；非图片节点返回 false', () => {
    const { view } = fakeView('paragraph')
    expect(applyChartReplacement(view as never, document.createElement('img'), 'x.png',
      { title: null, altText: null })).toBe(false)
    expect(view.dispatch).not.toHaveBeenCalled()
    const inline = fakeView('image', { inline: true })
    expect(applyChartReplacement(inline.view as never, document.createElement('img'), 'x.png',
      { title: '新标题', altText: null })).toBe(true)
    expect(inline.marks[0]).toEqual(['setNodeMarkup', 2, expect.objectContaining({ src: 'x.png', alt: '旧 alt' })])
    expect(inline.marks[1]).toEqual(['insertText', '图表：新标题', 11, 15])
  })
})

describe('chartEditIdFromSrc', () => {
  it('识别正文中的改图结果引用', () => {
    expect(chartEditIdFromSrc('chart-edits/cedit-abc12345/chart.png')).toBe('cedit-abc12345')
    expect(chartEditIdFromSrc('/b/asset/chart-edits/cedit-abc12345/chart.png', '/b')).toBe('cedit-abc12345')
    expect(chartEditIdFromSrc('chart-001.png')).toBeNull()
  })
})

function fakeClient(overrides: Partial<Record<string, unknown>> = {}) {
  const calls: Record<string, unknown[]> = {}
  const client = {
    charts: vi.fn(async () => ({ available: true, charts: [chart] })),
    chartAiAvailability: vi.fn(async () => ({ available: true, chartId: 'chart_001' })),
    startChartAiEdit: vi.fn(async () => ({ editId: 'cedit-abc12345', status: 'queued' })),
    chartAiEditStatus: vi.fn(async () => ({ editId: 'cedit-abc12345', status: 'succeeded' })),
    cancelChartAiEdit: vi.fn(async () => undefined),
    chartEditRecord: vi.fn(async () => ({
      editId: 'cedit-prev1234', chartId: 'chart_001',
      imagePath: 'reports/revision-1/chart-edits/cedit-prev1234/chart.png',
    })),
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

  it('已接受的改图按登记找回图表并作为底图继续调整', async () => {
    const client = fakeClient()
    const controller = createChartAIEdit({ view: fakeViewForController(), client, basePath: '/b', pollIntervalMs: 1 })
    document.body.innerHTML = '<div><img src="/b/asset/chart-edits/cedit-prev1234/chart.png" alt="收入对比"></div>'
    controller.open(document.querySelector('img')!)
    await vi.waitFor(() => {
      expect(document.querySelector('#chart-ai-instruction')).not.toBeNull()
    })
    expect(client.chartEditRecord).toHaveBeenCalledWith('cedit-prev1234')
    expect(client.charts).not.toHaveBeenCalled()
    document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!.value = '再加数值标签'
    ;(document.querySelector('[data-action="submit"]') as HTMLButtonElement).click()
    await vi.waitFor(() => {
      expect(client.startChartAiEdit).toHaveBeenCalledWith('chart_001', expect.objectContaining({
        previousEditId: 'cedit-prev1234',
        baseImagePath: 'reports/revision-1/chart-edits/cedit-prev1234/chart.png',
      }))
    })
    controller.dispose()
  })

  it('关闭窗口后不再被后台结果重新打开；编号返回前取消也会通知服务端', async () => {
    let releaseStart: (value: { editId: string; status: string }) => void = () => undefined
    const client = fakeClient({
      startChartAiEdit: vi.fn(() => new Promise((resolve) => { releaseStart = resolve })),
      chartAiEditStatus: vi.fn(async () => ({ editId: 'cedit-abc12345', chartId: 'chart_001', status: 'cancelled' })),
    })
    const controller = createChartAIEdit({ view: fakeViewForController(), client, basePath: '/b', pollIntervalMs: 1 })
    controller.open(mountEditorWithImage())
    await vi.waitFor(() => {
      expect(document.querySelector('#chart-ai-instruction')).not.toBeNull()
    })
    document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!.value = '改成折线图'
    ;(document.querySelector('[data-action="submit"]') as HTMLButtonElement).click()
    await vi.waitFor(() => {
      expect(document.querySelector('[data-action="cancel"]')).not.toBeNull()
    })
    const overlay = document.querySelector<HTMLElement>('.chart-ai-edit')!
    ;(document.querySelector('.chart-ai-edit-close') as HTMLButtonElement).click()
    releaseStart({ editId: 'cedit-abc12345', status: 'queued' })
    await vi.waitFor(() => {
      expect(client.cancelChartAiEdit).toHaveBeenCalledWith('chart_001', 'cedit-abc12345')
    })
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(overlay.hidden || !overlay.isConnected || !overlay.classList.contains('is-open')).toBe(true)
    expect(document.activeElement?.id).not.toBe('chart-ai-instruction')
    controller.dispose()
  })
})
