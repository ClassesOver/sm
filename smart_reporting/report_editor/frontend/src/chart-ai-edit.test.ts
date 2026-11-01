import { afterEach, describe, expect, it, vi } from 'vitest'
import { Schema } from '@milkdown/kit/prose/model'
import { EditorState, type Transaction } from '@milkdown/kit/prose/state'
import { EditorView } from '@milkdown/kit/prose/view'
import { history, undo } from '@milkdown/kit/prose/history'

import type { ReportEditorClient, TraceChartInfo } from './api'
import { createEvidenceLocationPlugin } from './evidence-location'
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

const replacementSchema = new Schema({ nodes: {
  doc: { content: 'block+' }, paragraph: { content: 'inline*', group: 'block', toDOM: () => ['p', 0] },
  'image-block': { group: 'block', atom: true, attrs: { src: {}, caption: { default: '' } }, toDOM: node => ['img', { src: node.attrs.src, alt: node.attrs.caption }] },
  image: { group: 'inline', inline: true, atom: true, attrs: { src: {}, alt: { default: '' } } },
  text: { group: 'inline' },
} })

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
    const node = replacementSchema.node(nodeType, { src: 'chart-001.png', caption: '旧图注', alt: '旧 alt' })
    const captionNode = replacementSchema.node('paragraph', null, replacementSchema.text(captionText))
    const block = inline ? replacementSchema.node('paragraph', null, [replacementSchema.text('x'), node]) : node
    const content = inline ? [block, captionNode] : [replacementSchema.node('paragraph'), block, captionNode]
    let state = EditorState.create({ doc: replacementSchema.node('doc', null, content) })
    const captionFrom = inline ? block.nodeSize : 2 + block.nodeSize
    const marks: Array<[string, ...unknown[]]> = []
    const tr = state.tr
    const setMarkup = tr.setNodeMarkup.bind(tr)
    const insertText = tr.insertText.bind(tr)
    tr.setNodeMarkup = (pos, type, attrs) => { marks.push(['setNodeMarkup', pos, attrs]); return setMarkup(pos, type, attrs) }
    tr.insertText = (text, from, to) => { marks.push(['insertText', text, from, to]); return insertText(text, from, to) }
    Object.defineProperty(state, 'tr', { get: () => tr })
    const view = {
      posAtDOM: () => 2,
      state,
      dispatch: vi.fn((change: Transaction) => { state = state.apply(change); view.state = state }),
    }
    return { view, marks, captionRange: [captionFrom + 1, captionFrom + captionNode.nodeSize - 1] }
  }

  it('一次事务替换图片节点：“图表：”段落写标题，替代文本写图注', () => {
    const { view, marks, captionRange } = fakeView('image-block')
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
    expect(marks[1]).toEqual(['insertText', '图表：收入（横向）', ...captionRange])
  })

  it('“图注：”段落写图注；标题未变时不改“图表：”段落', () => {
    const captioned = fakeView('image-block', { captionText: '图注：旧说明' })
    applyChartReplacement(captioned.view as never, document.createElement('img'), 'x.png',
      { title: '新标题', altText: '新说明' })
    expect(captioned.marks[1]).toEqual(['insertText', '图注：新说明', ...captioned.captionRange])
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
    expect(inline.marks[1]).toEqual(['insertText', '图表：新标题', ...inline.captionRange])
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
  const view = {
    posAtDOM: () => 0,
    state: EditorState.create({ doc: replacementSchema.node('doc', null,
      replacementSchema.node('image-block', { src: 'chart-001.png', caption: '旧图注' })) }),
    dispatch: vi.fn((tr: Transaction) => { view.state = view.state.apply(tr) }),
  }
  return view as unknown as Parameters<typeof createChartAIEdit>[0]['view']
}

function mountEditorWithImage(): HTMLImageElement {
  document.body.innerHTML = '<div id="editor"><img src="/b/asset/reports/revision-1/chart-001.png" alt="收入对比"></div>'
  return document.querySelector('img')!
}

describe('createChartAIEdit', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it.each([false, true])('采用后可继续修改当前新图，撤销后拒绝旧回执定位（撤销=%s）', async (reverted) => {
    const client = fakeClient({
      chartAiEditStatus: vi.fn(async () => ({
        editId: 'cedit-prev1234', chartId: 'chart_001', status: 'succeeded',
        imagePath: 'reports/revision-1/chart-edits/cedit-prev1234/chart.png', imageSrc: 'chart-edits/cedit-prev1234/chart.png',
        changes: { title: '收入', altText: '新图', plotDataUnchanged: true }, warnings: [], skipped: [],
        visualInspection: { format: 'PNG', width: 64, height: 48, reviewed: true },
      })),
    })
    const host = document.createElement('div'); document.body.append(host)
    const view = new EditorView(host, { state: EditorState.create({
      doc: replacementSchema.node('doc', null, replacementSchema.node('image-block', { src: 'chart-001.png' })), plugins: [history(), createEvidenceLocationPlugin()],
    }) })
    const controller = createChartAIEdit({ view, client, basePath: '/b', pollIntervalMs: 1 })
    controller.open(view.dom.querySelector('img')!)
    await vi.waitFor(() => expect(document.querySelector('#chart-ai-instruction')).not.toBeNull())
    const input = document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!
    input.value = '改配色'; input.dispatchEvent(new Event('input'))
    document.querySelector<HTMLButtonElement>('[data-action="submit"]')!.click()
    await vi.waitFor(() => expect(document.querySelector('[data-action="accept"]')).not.toBeNull())
    expect(document.querySelector('[data-action="accept"]')?.textContent).toBe('采用到正文')
    document.querySelector<HTMLButtonElement>('[data-action="accept"]')!.click()
    expect(document.querySelector<HTMLElement>('.ask-ai-panel')!.hidden).toBe(false)
    const receipt = document.querySelector<HTMLElement>('.ask-ai-receipt')!
    expect(receipt).not.toBeNull()
    expect(view.state.doc.firstChild?.attrs.src).toContain('cedit-prev1234')
    if (reverted) {
      undo(view.state, view.dispatch)
      receipt.querySelector<HTMLButtonElement>('[data-action="continue-editing"]')!.click()
      expect(receipt.textContent).toContain('已变化或无法唯一定位')
      expect(view.state.doc.firstChild?.attrs.src).toBe('chart-001.png')
      expect(document.querySelector('#chart-ai-instruction')).toBeNull()
    } else {
      receipt.querySelector<HTMLButtonElement>('[data-action="locate-body"]')!.click()
      const located = view.dom.querySelectorAll('.report-located-subject')
      expect(located).toHaveLength(1)
      expect(located[0]!.getAttribute('src')).toContain('cedit-prev1234')
      receipt.querySelector<HTMLButtonElement>('[data-action="continue-editing"]')!.click()
      await vi.waitFor(() => expect(document.querySelector('#chart-ai-instruction')).not.toBeNull())
      const next = document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!
      next.value = '加标签'; next.dispatchEvent(new Event('input'))
      document.querySelector<HTMLButtonElement>('[data-action="submit"]')!.click()
      await vi.waitFor(() => expect(client.startChartAiEdit).toHaveBeenLastCalledWith('chart_001', expect.objectContaining({ previousEditId: 'cedit-prev1234' })))
    }
    controller.dispose(); view.destroy()
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
    expect(document.querySelector('.ask-ai-composers #chart-ai-instruction')).not.toBeNull()
    expect(document.querySelector('.ask-ai-content textarea')).toBeNull()
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

  it('AI 不可用但标准预设可用时保留输入区，并在提交按钮下方常显原因', async () => {
    const client = fakeClient({
      chartAiAvailability: vi.fn(async () => ({ available: false, standardAvailable: true, reason: 'vision_missing' })),
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
    const note = document.querySelector('[data-role="ai-unavailable-note"]')
    expect(note).not.toBeNull()
    expect(note!.textContent).toContain('未配置视觉审查模型')
    expect(note!.textContent).toContain('一键调整')
    const textarea = document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!
    textarea.value = '改成折线图'; textarea.dispatchEvent(new Event('input'))
    expect(document.querySelector<HTMLButtonElement>('[data-action="submit"]')!.disabled).toBe(true)
    controller.dispose()
  })

  it('标准预设通道不可用时置灰确定性预设并常显说明，AI 预设不受影响', async () => {
    const client = fakeClient({
      chartAiAvailability: vi.fn(async () => ({ available: true, standardAvailable: false, standardReason: 'unconfigured' })),
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
    const pie = document.querySelector<HTMLButtonElement>('[data-preset="pie"]')!
    const dual = document.querySelector<HTMLButtonElement>('[data-preset="dual"]')!
    expect(pie.disabled).toBe(true)
    expect(dual.disabled).toBe(false)
    expect(document.querySelector('[id$="chart-ai-standard-help"]')!.textContent).toContain('暂不可用')
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
        })
        .mockResolvedValueOnce({
          editId: 'cedit-abc12345', chartId: 'chart_001', status: 'succeeded',
          imagePath: 'reports/revision-1/chart-edits/cedit-abc12345/chart.png',
          imageSrc: 'chart-edits/cedit-abc12345/chart.png',
          changes: { plotDataUnchanged: true }, warnings: [], skipped: [],
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
    document.querySelector("#chart-ai-instruction")?.dispatchEvent(new Event("input"))
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
    const original = document.querySelector<HTMLElement>('[data-compare-view="original"]')!
    const generated = document.querySelector<HTMLElement>('.chart-ai-pages')!
    expect(original).not.toBeNull()
    expect(original.hidden).toBe(true)
    expect(generated.hidden).toBe(false)
    document.querySelector<HTMLButtonElement>('[data-action="view-original"]')!.click()
    expect(original.hidden).toBe(false)
    expect(generated.hidden).toBe(true)
    expect(document.querySelector('.chart-ai-warnings')!.textContent).toContain('图例遮挡')
    document.querySelector<HTMLButtonElement>('[data-action="view-new"]')!.click()
    expect(generated.hidden).toBe(false)
    const followUp = document.querySelector<HTMLTextAreaElement>('.ask-ai-composers textarea')!
    expect(followUp).not.toBeNull()
    followUp.value = '图例移到底部'; followUp.dispatchEvent(new Event('input'))
    document.querySelector<HTMLButtonElement>('[data-action="submit"]')!.click()
    await vi.waitFor(() => expect(client.startChartAiEdit).toHaveBeenCalledWith('chart_001', expect.objectContaining({
      instruction: '图例移到底部', previousEditId: 'cedit-abc12345',
    })))
    await vi.waitFor(() => expect(document.querySelector('[data-action="accept"]')).not.toBeNull())
    ;(document.querySelector('[data-action="accept"]') as HTMLButtonElement).click()
    expect(view.dispatch).toHaveBeenCalledTimes(1)
    expect(onReplaced).toHaveBeenCalledWith('cedit-abc12345')
    const receipt = document.querySelector<HTMLElement>('.ask-ai-receipt')
    expect(receipt).not.toBeNull()
    expect(receipt!.textContent).toContain('已替换到正文')
    expect(receipt!.textContent).toContain('撤销')
    expect(receipt!.textContent).not.toContain('已保存')
    expect(document.querySelector<HTMLElement>('.ask-ai-panel')!.hidden).toBe(false)
    expect(document.querySelector('[data-action="accept"]')).toBeNull()
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
    document.querySelector("#chart-ai-instruction")?.dispatchEvent(new Event("input"))
    ;(document.querySelector('[data-action="submit"]') as HTMLButtonElement).click()
    await vi.waitFor(() => {
      expect(document.querySelector('.chart-ai-note')).not.toBeNull()
    })
    expect(document.querySelector('.chart-ai-note')!.textContent).toContain('预测数据未登记')
    expect(document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!.value).toBe('加预测')
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
    document.querySelector("#chart-ai-instruction")?.dispatchEvent(new Event("input"))
    ;(document.querySelector('[data-action="submit"]') as HTMLButtonElement).click()
    await vi.waitFor(() => {
      expect(client.startChartAiEdit).toHaveBeenCalledWith('chart_001', expect.objectContaining({
        previousEditId: 'cedit-prev1234',
        baseImagePath: 'reports/revision-1/chart-edits/cedit-prev1234/chart.png',
      }))
    })
    controller.dispose()
  })

  it('收起后任务继续，重新打开同一张图恢复结果而不重复提交', async () => {
    let releaseStart: (value: { editId: string; status: string }) => void = () => undefined
    const client = fakeClient({
      startChartAiEdit: vi.fn(() => new Promise((resolve) => { releaseStart = resolve })),
      chartAiEditStatus: vi.fn(async () => ({
        editId: 'cedit-abc12345', chartId: 'chart_001', status: 'succeeded',
        imagePath: 'chart-edits/cedit-abc12345/chart.png', imageSrc: 'chart-edits/cedit-abc12345/chart.png',
        changes: { title: null, altText: null, visualForm: '折线图', plotDataUnchanged: true },
        warnings: [], skipped: [], visualInspection: { reviewed: true, format: 'PNG', width: 64, height: 48 },
      })),
    })
    const controller = createChartAIEdit({ view: fakeViewForController(), client, basePath: '/b', pollIntervalMs: 1 })
    const image = mountEditorWithImage()
    controller.open(image)
    await vi.waitFor(() => {
      expect(document.querySelector('#chart-ai-instruction')).not.toBeNull()
    })
    document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!.value = '改成折线图'
    document.querySelector("#chart-ai-instruction")?.dispatchEvent(new Event("input"))
    ;(document.querySelector('[data-action="submit"]') as HTMLButtonElement).click()
    await vi.waitFor(() => {
      expect(document.querySelector('[data-action="cancel"]')).not.toBeNull()
    })
    ;(document.querySelector('.chart-ai-edit-close') as HTMLButtonElement).click()
    releaseStart({ editId: 'cedit-abc12345', status: 'queued' })
    await vi.waitFor(() => {
      expect(document.querySelector('.chart-ai-compare')).not.toBeNull()
    })
    expect(client.cancelChartAiEdit).not.toHaveBeenCalled()
    expect(document.querySelector<HTMLElement>('.ask-ai-panel')!.hidden).toBe(true)
    expect(document.activeElement?.id).not.toBe('chart-ai-instruction')
    controller.open(image)
    expect(document.querySelector<HTMLElement>('.ask-ai-panel')!.hidden).toBe(false)
    expect(document.querySelector('[data-action="accept"]')).not.toBeNull()
    expect(client.startChartAiEdit).toHaveBeenCalledTimes(1)
    controller.dispose()
  })

  it('空输入不提交，Ctrl+Enter 提交已输入的要求', async () => {
    const client = fakeClient({ chartAiEditStatus: vi.fn(async () => ({ status: 'failed', error: { message: '稍后重试' } })) })
    const controller = createChartAIEdit({ view: fakeViewForController(), client, basePath: '/b', pollIntervalMs: 1 })
    controller.open(mountEditorWithImage())
    await vi.waitFor(() => expect(document.querySelector('#chart-ai-instruction')).not.toBeNull())
    const area = document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!
    expect(document.querySelector<HTMLButtonElement>('[data-action="submit"]')!.disabled).toBe(true)
    area.value = '显示数值标签'
    area.dispatchEvent(new Event('input', { bubbles: true }))
    area.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, bubbles: true }))
    await vi.waitFor(() => expect(client.startChartAiEdit).toHaveBeenCalledWith('chart_001', expect.objectContaining({ instruction: '显示数值标签' })))
    controller.dispose()
  })

  it('多个图表会话字段身份唯一，切换后分别保留输入', async () => {
    const image = mountEditorWithImage()
    const secondImage = document.createElement('img'); secondImage.src = image.src; document.querySelector('#editor')!.append(secondImage)
    const first = createChartAIEdit({ view: fakeViewForController(), client: fakeClient(), basePath: '/b', pollIntervalMs: 1 })
    const second = createChartAIEdit({ view: fakeViewForController(), client: fakeClient(), basePath: '/b', pollIntervalMs: 1 })
    first.open(image)
    await vi.waitFor(() => expect(document.querySelector('#chart-ai-instruction')).not.toBeNull())
    document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!.value = '第一张图要求'
    document.querySelector('#chart-ai-instruction')!.dispatchEvent(new Event('input'))
    second.open(secondImage)
    await vi.waitFor(() => expect(document.querySelectorAll('.ask-ai-composers textarea')).toHaveLength(2))
    const fields = [...document.querySelectorAll<HTMLTextAreaElement>('.ask-ai-composers textarea')]
    expect(new Set(fields.map(field => field.id)).size).toBe(2)
    fields[1].value = '第二张图要求'
    fields[1].dispatchEvent(new Event('input'))
    first.open(image)
    expect(fields[0].value).toBe('第一张图要求')
    expect(fields[1].value).toBe('第二张图要求')
    expect(document.querySelectorAll('.ask-ai-panel')).toHaveLength(1)
    first.dispose(); second.dispose()
  })

  it('后台失败不打断用户在正文之外的输入', async () => {
    let complete: (value: unknown) => void = () => undefined
    const client = fakeClient({ chartAiEditStatus: vi.fn(() => new Promise(resolve => { complete = resolve })) })
    const controller = createChartAIEdit({ view: fakeViewForController(), client, basePath: '/b', pollIntervalMs: 1 })
    controller.open(mountEditorWithImage())
    await vi.waitFor(() => expect(document.querySelector('#chart-ai-instruction')).not.toBeNull())
    const area = document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!
    area.value = '优化配色'; area.dispatchEvent(new Event('input'))
    document.querySelector<HTMLButtonElement>('[data-action="submit"]')!.click()
    await vi.waitFor(() => expect(client.chartAiEditStatus).toHaveBeenCalled())
    const search = document.createElement('input'); document.body.append(search); search.focus()
    complete({ status: 'failed', error: { message: '暂时失败' } })
    await vi.waitFor(() => expect(document.querySelector('.chart-ai-note')).not.toBeNull())
    expect(document.activeElement).toBe(search)
    controller.dispose()
  })

  it.each(['登记读取', '审阅结果', '通知恢复', '通知恢复有重复资源'])('%s期间同一图片DOM重建后，安全定位当前图片', async phase => {
    let ready: (value: unknown) => void = () => undefined
    const client = fakeClient({
      charts: vi.fn(() => new Promise(resolve => { ready = resolve })),
      chartAiEditStatus: vi.fn(async () => ({
        editId: 'cedit-abc12345', chartId: 'chart_001', status: 'succeeded',
        imagePath: 'chart-edits/cedit-abc12345/chart.png', imageSrc: 'chart-edits/cedit-abc12345/chart.png',
        changes: { title: null, altText: null, visualForm: null, plotDataUnchanged: true },
        warnings: [], skipped: [], visualInspection: { reviewed: true, format: 'PNG', width: 64, height: 48 },
      })),
    })
    const view = fakeViewForController()
    view.posAtDOM = node => { if (!node.isConnected) throw new RangeError('detached'); return 0 }
    const controller = createChartAIEdit({ view, client, basePath: '/b', pollIntervalMs: 1 })
    const old = mountEditorWithImage()
    Object.assign(view, { dom: old.parentElement })
    controller.open(old)
    const rebuildImage = (reopen = true) => {
      const current = old.cloneNode() as HTMLImageElement
      old.replaceWith(current)
      if (phase === '通知恢复有重复资源') current.parentElement!.append(current.cloneNode())
      if (reopen) controller.open(current)
    }
    if (phase === '登记读取') rebuildImage()
    ready({ charts: [chart] })
    await vi.waitFor(() => expect(document.querySelector('#chart-ai-instruction')).not.toBeNull())
    const area = document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!
    area.value = '优化配色'; area.dispatchEvent(new Event('input'))
    document.querySelector<HTMLButtonElement>('[data-action="submit"]')!.click()
    await vi.waitFor(() => expect(document.querySelector('[data-action="accept"]')).not.toBeNull())
    if (phase === '审阅结果') rebuildImage()
    if (phase.startsWith('通知恢复')) {
      controller.open(old)
      document.querySelector<HTMLButtonElement>('.chart-ai-edit-close')!.click()
      rebuildImage(false)
      document.querySelector<HTMLButtonElement>('.ask-ai-launcher')!.click()
    }
    document.querySelector<HTMLButtonElement>('[data-action="accept"]')!.click()
    expect(view.dispatch).toHaveBeenCalledTimes(phase === '通知恢复有重复资源' ? 0 : 1)
    controller.dispose()
  })
})
