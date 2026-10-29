import { Schema } from '@milkdown/kit/prose/model'
import { EditorState, type Transaction } from '@milkdown/kit/prose/state'
import { history, undo } from '@milkdown/kit/prose/history'
import type { EditorView } from '@milkdown/kit/prose/view'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ReportEditorApiError, type ChartAIEditPage, type ChartAIEditSuccess, type ReportEditorClient } from './api'
import { applyChartPagesReplacement, chartResultPages, createChartAIEdit, STANDARD_CHART_PRESETS } from './chart-ai-edit'
import { protocolMarkersUnchanged } from './protocol'

const schema = new Schema({ nodes: {
  doc: { content: 'block+' },
  paragraph: { content: 'inline*', group: 'block' },
  'image-block': { group: 'block', atom: true, attrs: { src: {}, caption: { default: '' } } },
  image: { group: 'inline', inline: true, atom: true, attrs: { src: {}, alt: { default: '' } } },
  citation: { group: 'inline', inline: true, atom: true, attrs: { citationId: {}, label: { default: '' } } },
  unknown_atom: { group: 'inline', inline: true, atom: true, attrs: { id: {} } },
  text: { group: 'inline' },
} })
const paragraph = (value: string) => schema.node('paragraph', null, schema.text(value))
const page = (n: number, count: number, id = 'cedit-old12345'): ChartAIEditPage => ({
  pageNumber: n, pageCount: count,
  imagePath: `reports/revision-1/chart-edits/${id}/${n === 1 ? 'chart.png' : `chart--page-${n}.png`}`,
  imageSrc: `chart-edits/${id}/${n === 1 ? 'chart.png' : `chart--page-${n}.png`}`,
  title: `收入第${n}页`, altText: `第${n}页完整类别`,
})
const old = [page(1, 3), page(2, 3), page(3, 3)]
const next = [page(1, 2, 'cedit-new12345'), page(2, 2, 'cedit-new12345')]
const nodes = (pages: ChartAIEditPage[]) => pages.flatMap(item => [
  schema.node('image-block', { src: item.imageSrc, caption: item.altText }), paragraph(`图表：${item.title}`),
])

function viewFor(doc = schema.node('doc', null, nodes(old)), selected = 1) {
  const positions: number[] = []
  doc.descendants((node, from) => { if (node.type.name === 'image-block' || node.type.name === 'image') positions.push(from) })
  const view = {
    state: EditorState.create({ doc, plugins: [history()] }),
    posAtDOM: () => positions[selected] ?? positions[0] ?? 0,
    dispatch: vi.fn((tr: Transaction) => { view.state = view.state.apply(tr) }),
  }
  return view as unknown as EditorView & { dispatch: ReturnType<typeof vi.fn> }
}

function result(pages = next): ChartAIEditSuccess {
  return { status: 'succeeded', editId: 'cedit-new12345', chartId: 'chart_001',
    imagePath: pages[0]!.imagePath, imageSrc: pages[0]!.imageSrc, pages: pages.map(item => ({ ...item })), level: ['L1'],
    changes: { title: '收入', altText: '收入对照', plotDataUnchanged: true }, warnings: [], skipped: [],
    visualInspection: { reviewed: true } }
}

afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks() })

describe('完整多页接受', () => {
  it('真实图片与引用文本同段时完整展开，引用不复制不丢失，撤销恢复原节点', () => {
    const sourceText = '  [[citation:citation_001]] [[citation:citation_002]]  '
    const doc = schema.node('doc', null, [schema.node('paragraph', null, [schema.node('image', { src: 'original.png' }), schema.text(sourceText)]), paragraph('正文')])
    const view = viewFor(doc, 0)
    expect(applyChartPagesReplacement(view, document.createElement('img'), next, { basePath: '/b' })).toBe(true)
    expect(view.dispatch).toHaveBeenCalledTimes(1)
    expect(protocolMarkersUnchanged(doc.textContent, view.state.doc.textContent)).toBe(true)
    expect(view.state.doc.firstChild!.lastChild!.text).toBe(sourceText)
    expect(view.state.doc.textContent.match(/\[\[citation:/g)).toHaveLength(2)
    expect(undo(view.state, tr => view.dispatch(tr))).toBe(true)
    expect(view.state.doc.eq(doc)).toBe(true)
  })

  it('原子引用节点及其属性原样保留在新图段落，不复制到其他页', () => {
    const citation = schema.node('citation', { citationId: 'citation_001', label: '登记来源' })
    const doc = schema.node('doc', null, schema.node('paragraph', null, [schema.text(' '), citation, schema.node('image', { src: 'original.png' }), schema.text(' ')]))
    const view = viewFor(doc, 0)
    expect(applyChartPagesReplacement(view, document.createElement('img'), next, { basePath: '/b' })).toBe(true)
    const found: unknown[] = []
    view.state.doc.descendants(node => { if (node.type.name === 'citation') found.push(node.toJSON()) })
    expect(found).toEqual([citation.toJSON()])
    expect(view.state.doc.firstChild!.child(2).eq(citation)).toBe(true)
    expect(undo(view.state, tr => view.dispatch(tr))).toBe(true)
    expect(view.state.doc.eq(doc)).toBe(true)
  })

  it('从旧分页第二页重画时保存各页原有文本及原子引用，再次改图也不残留或复制', () => {
    const citation = schema.node('citation', { citationId: 'citation_003', label: '第三页来源' })
    const content = old.flatMap((item, index) => [schema.node('paragraph', null, [schema.node('image', { src: item.imageSrc }),
      index === 2 ? citation : schema.text(` [[citation:citation_00${index + 1}]]`)]), paragraph(`图表：${item.title}`)])
    const doc = schema.node('doc', null, content)
    const view = viewFor(doc, 1)
    expect(applyChartPagesReplacement(view, document.createElement('img'), next, { basePath: '/b', previousEditId: 'cedit-old12345', previousPages: old })).toBe(true)
    expect(protocolMarkersUnchanged(doc.textContent, view.state.doc.textContent)).toBe(true)
    let atomCount = 0
    view.state.doc.descendants(node => { if (node.type.name === 'citation') atomCount++ })
    expect(atomCount).toBe(1)
    const latest = viewFor(view.state.doc, 0)
    const replacement = [page(1, 1, 'cedit-final1234')]
    expect(applyChartPagesReplacement(latest, document.createElement('img'), replacement, { basePath: '/b', previousEditId: 'cedit-new12345', previousPages: next })).toBe(true)
    expect(protocolMarkersUnchanged(doc.textContent, latest.state.doc.textContent)).toBe(true)
    let finalAtoms = 0
    latest.state.doc.descendants(node => { if (node.type.name === 'citation') finalAtoms++ })
    expect(finalAtoms).toBe(1)
  })

  it.each(['[[citation:citation_001]]还有正文', '[[citation:broken id]]', '[[analysis:analysis_001]]', '[[citation:citation_001]] [[unfinished'])('图片旁不是完整引用时仍拒绝：%s', (text) => {
    const doc = schema.node('doc', null, schema.node('paragraph', null, [schema.node('image', { src: 'original.png' }), schema.text(text)]))
    const view = viewFor(doc, 0)
    expect(applyChartPagesReplacement(view, document.createElement('img'), next, { basePath: '/b' })).toBe(false)
    expect(view.dispatch).not.toHaveBeenCalled()
  })

  it('未知原子节点不能冒充引用被移动', () => {
    const doc = schema.node('doc', null, schema.node('paragraph', null, [schema.node('image', { src: 'original.png' }), schema.node('unknown_atom', { id: 'citation_001' })]))
    const view = viewFor(doc, 0)
    expect(applyChartPagesReplacement(view, document.createElement('img'), next, { basePath: '/b' })).toBe(false)
    expect(view.dispatch).not.toHaveBeenCalled()
  })

  it('引用文本不能跨过图片拼接成一个原本不存在的完整标记', () => {
    const doc = schema.node('doc', null, schema.node('paragraph', null, [schema.text('[[citation:'), schema.node('image', { src: 'original.png' }), schema.text('citation_001]]')]))
    const view = viewFor(doc, 0)
    expect(applyChartPagesReplacement(view, document.createElement('img'), next, { basePath: '/b' })).toBe(false)
    expect(view.dispatch).not.toHaveBeenCalled()
  })

  it('图题中还有协议引用时，不因重画图题静默丢掉该引用', () => {
    const previous = old.map((item, index) => index === 0 ? { ...item, title: `${item.title} [[citation:caption_001]]` } : item)
    const doc = schema.node('doc', null, nodes(previous))
    const view = viewFor(doc, 1)
    expect(applyChartPagesReplacement(view, document.createElement('img'), next, { basePath: '/b', previousEditId: 'cedit-old12345', previousPages: previous })).toBe(false)
    expect(view.dispatch).not.toHaveBeenCalled()
    expect(view.state.doc.eq(doc)).toBe(true)
  })
  it('从第二页接受会原子替换整组，保留无关正文，撤销一次恢复全部旧页', () => {
    const doc = schema.node('doc', null, [paragraph('前置正文'), ...nodes(old), paragraph('后置正文')])
    const view = viewFor(doc)
    expect(applyChartPagesReplacement(view, document.createElement('img'), next, {
      basePath: '/b', previousEditId: 'cedit-old12345', previousPages: old,
    })).toBe(true)
    expect(view.dispatch).toHaveBeenCalledTimes(1)
    const images: string[] = []
    view.state.doc.descendants(node => { if (node.type.name === 'image-block') images.push(String(node.attrs.src)) })
    expect(images).toEqual(next.map(item => item.imageSrc))
    expect(view.state.doc.textContent).toContain('前置正文')
    expect(view.state.doc.textContent).toContain('后置正文')
    expect(undo(view.state, tr => view.dispatch(tr))).toBe(true)
    expect(view.state.doc.eq(doc)).toBe(true)
  })

  it.each(['missing', 'duplicate', 'reordered', 'separated', 'changed-caption'])('旧组%s时不进行部分替换或删除其他正文', (fault) => {
    let pages = [...old]
    if (fault === 'missing') pages = pages.slice(0, 2)
    if (fault === 'duplicate') pages.push(old[0]!)
    if (fault === 'reordered') pages.reverse()
    const content = nodes(pages)
    if (fault === 'separated') content.splice(2, 0, paragraph('这段正文不能被删除'))
    if (fault === 'changed-caption') content[1] = paragraph('图表：用户刚修改的图题')
    const doc = schema.node('doc', null, content)
    const view = viewFor(doc)
    expect(applyChartPagesReplacement(view, document.createElement('img'), next, {
      basePath: '/b', previousEditId: 'cedit-old12345', previousPages: old,
    })).toBe(false)
    expect(view.dispatch).not.toHaveBeenCalled()
    expect(view.state.doc.eq(doc)).toBe(true)
  })

  it('新结果缩为一页时也删除整组旧页，不留旧末页', () => {
    const view = viewFor()
    expect(applyChartPagesReplacement(view, document.createElement('img'), next.slice(0, 1), {
      basePath: '/b', previousEditId: 'cedit-old12345', previousPages: old,
    })).toBe(true)
    let count = 0
    view.state.doc.descendants(node => { if (node.type.name === 'image-block') count++ })
    expect(count).toBe(1)
  })

  it('从一张图完整展开为多页，沿用原图节点类型并保持一个事务', () => {
    const doc = schema.node('doc', null, [schema.node('paragraph', null, schema.node('image', { src: 'original.png' })), paragraph('图注：原图注'), paragraph('正文')])
    const view = viewFor(doc, 0)
    expect(applyChartPagesReplacement(view, document.createElement('img'), next, { basePath: '/b' })).toBe(true)
    expect(view.dispatch).toHaveBeenCalledTimes(1)
    expect(view.state.doc.textContent).toContain('正文')
    expect(view.state.doc.textContent).toContain(`图注：${next[1]!.altText}`)
    expect(undo(view.state, tr => view.dispatch(tr))).toBe(true)
    expect(view.state.doc.eq(doc)).toBe(true)
  })

  it('原图段落包含其他正文时安全拒绝多页替换', () => {
    const doc = schema.node('doc', null, schema.node('paragraph', null, [schema.text('引用正文'), schema.node('image', { src: 'original.png' })]))
    const view = viewFor(doc, 0)
    expect(applyChartPagesReplacement(view, document.createElement('img'), next, { basePath: '/b' })).toBe(false)
    expect(view.dispatch).not.toHaveBeenCalled()
  })

  it('缺失旧分页元数据时不把同组多页当单图覆盖', () => {
    const view = viewFor()
    expect(applyChartPagesReplacement(view, document.createElement('img'), [next[0]!], { basePath: '/b', previousEditId: 'cedit-old12345' })).toBe(false)
    expect(view.dispatch).not.toHaveBeenCalled()
  })

  it('底图节点已变化或原DOM已脱离时不覆盖别的图片', () => {
    const view = viewFor()
    expect(applyChartPagesReplacement(view, document.createElement('img'), next, {
      basePath: '/b', previousEditId: 'cedit-old12345', previousPages: old, expectedImageSrc: 'another-chart.png',
    })).toBe(false)
    expect(view.dispatch).not.toHaveBeenCalled()
    view.posAtDOM = () => { throw new RangeError('DOM no longer in editor') }
    expect(applyChartPagesReplacement(view, document.createElement('img'), next, { basePath: '/b' })).toBe(false)
    expect(view.dispatch).not.toHaveBeenCalled()
  })
})

describe('页响应完整性', () => {
  it.each(['empty', 'missing', 'duplicate', 'unordered', 'canonical'])('拒绝%s页列表，不回落为仅首页', (fault) => {
    const response = result()
    if (fault === 'empty') response.pages = []
    if (fault === 'missing') response.pages = response.pages!.slice(0, 1)
    if (fault === 'duplicate') response.pages![1] = { ...response.pages![0]!, pageNumber: 2 }
    if (fault === 'unordered') response.pages!.reverse()
    if (fault === 'canonical') response.imagePath = 'unexpected.png'
    expect(chartResultPages(response)).toBeNull()
  })
  it('旧单图响应继续可用，多页按原始顺序完整保留', () => {
    const response = result()
    expect(chartResultPages(response)).toEqual(next)
    delete response.pages
    expect(chartResultPages(response)).toHaveLength(1)
  })
})

function client(overrides: Record<string, unknown> = {}) {
  return { charts: vi.fn(async () => ({ charts: [{ chartId: 'chart_001', imagePath: 'reports/revision-1/original.png' }] })),
    chartAiAvailability: vi.fn(async () => ({ available: true })),
    cancelChartAiEdit: vi.fn(async () => ({ status: 'cancelled' })),
    startChartAiEdit: vi.fn(async () => ({ editId: 'cedit-new12345' })), chartAiEditStatus: vi.fn(async () => result()),
    chartEditRecord: vi.fn(async () => ({ editId: 'cedit-old12345', chartId: 'chart_001', imagePath: old[0]!.imagePath, pages: old })),
    ...overrides } as unknown as ReportEditorClient
}
function mount(src = '/b/asset/reports/revision-1/original.png') {
  const img = document.createElement('img')
  img.src = src
  document.body.append(img)
  return img
}

describe('模板选择与完整预览', () => {
  it.each(['ai', 'standard', 'template'])('关闭再打开后丢弃%s旧状态，且仍能取消新任务', async (route) => {
    let finishOld: (value: unknown) => void = () => undefined
    let oldWaiting = false
    const start = vi.fn().mockResolvedValueOnce({ editId: 'cedit-old12345' }).mockResolvedValueOnce({ editId: 'cedit-new12345' })
    const api = client({
      chartAiAvailability: vi.fn(async () => ({ available: true, standardAvailable: true, standard: { standardForm: 'bar' }, expectedSha256: 'a'.repeat(64), baseImagePath: 'reports/revision-1/original.png' })),
      startChartAiEdit: start, startChartStandardEdit: start, startChartTemplateEdit: start,
      chartTemplates: vi.fn(async () => ({ templates: [{ templateId: 'one', name: '预制一', available: true }] })),
      cancelChartAiEdit: vi.fn(async () => ({ status: 'cancelled' })),
      chartAiEditStatus: vi.fn((_chart, editId) => editId === 'cedit-old12345'
        ? new Promise(resolve => { oldWaiting = true; finishOld = resolve })
        : new Promise(() => undefined)),
    })
    const controller = createChartAIEdit({ view: viewFor(), client: api, basePath: '/b' })
    const img = mount()
    const startRoute = async () => {
      await vi.waitFor(() => expect(document.querySelector('#chart-ai-instruction')).not.toBeNull())
      if (route === 'template') {
        await vi.waitFor(() => expect(document.querySelector('.chart-ai-template')).not.toBeNull())
        ;(document.querySelector('.chart-ai-template') as HTMLButtonElement).click()
      } else if (route === 'standard') {
        const select = document.querySelector<HTMLSelectElement>('#chart-ai-standard-preset')!
        select.value = 'pie'
        select.dispatchEvent(new Event('change'))
        ;(document.querySelector('[data-action="apply-standard"]') as HTMLButtonElement).click()
      } else {
        document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!.value = '调整颜色'
        ;(document.querySelector('[data-action="submit"]') as HTMLButtonElement).click()
      }
    }
    try {
      controller.open(img)
      await startRoute()
      await vi.waitFor(() => expect(oldWaiting).toBe(true))
      ;(document.querySelector('.chart-ai-edit-close') as HTMLButtonElement).click()
      controller.open(img)
      // 新任务走AI，确保旧任务收尾不会清掉其取消身份。
      await vi.waitFor(() => expect(document.querySelector('#chart-ai-instruction')).not.toBeNull())
      document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!.value = '新任务颜色'
      ;(document.querySelector('[data-action="submit"]') as HTMLButtonElement).click()
      await vi.waitFor(() => expect(api.chartAiEditStatus).toHaveBeenCalledWith('chart_001', 'cedit-new12345'))
      finishOld(result())
      await new Promise(resolve => setTimeout(resolve, 0))
      expect(document.querySelector('[data-action="accept"]')).toBeNull()
      expect(document.querySelector('.chart-ai-progress')).not.toBeNull()
      ;(document.querySelector('.chart-ai-edit-close') as HTMLButtonElement).click()
      expect(api.cancelChartAiEdit).toHaveBeenLastCalledWith('chart_001', 'cedit-new12345')
    } finally { controller.dispose() }
  })

  it.each(['ai', 'template'])('关闭后%s启动回执晚到时补发取消，不查询或重开预览', async (route) => {
    let finishStart: (value: unknown) => void = () => undefined
    const start = vi.fn(() => new Promise(resolve => { finishStart = resolve }))
    const api = client({ startChartAiEdit: start, startChartTemplateEdit: start,
      chartTemplates: vi.fn(async () => ({ templates: [{ templateId: 'one', name: '预制一', available: true }] })),
      cancelChartAiEdit: vi.fn(async () => ({ status: 'cancelled' })),
    })
    const controller = createChartAIEdit({ view: viewFor(), client: api, basePath: '/b' })
    try {
      controller.open(mount())
      await vi.waitFor(() => expect(document.querySelector('#chart-ai-instruction')).not.toBeNull())
      if (route === 'template') {
        await vi.waitFor(() => expect(document.querySelector('.chart-ai-template')).not.toBeNull())
        ;(document.querySelector('.chart-ai-template') as HTMLButtonElement).click()
      } else {
        document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!.value = '调整颜色'
        ;(document.querySelector('[data-action="submit"]') as HTMLButtonElement).click()
      }
      expect(start).toHaveBeenCalledTimes(1)
      ;(document.querySelector('.chart-ai-edit-close') as HTMLButtonElement).click()
      finishStart({ editId: 'cedit-old12345' })
      await vi.waitFor(() => expect(api.cancelChartAiEdit).toHaveBeenCalledWith('chart_001', 'cedit-old12345'))
      expect(api.chartAiEditStatus).not.toHaveBeenCalled()
      expect(document.querySelector<HTMLDivElement>('.chart-ai-edit')!.hidden).toBe(true)
    } finally { controller.dispose() }
  })

  it('乱序目标解析不让旧图覆盖新打开的图', async () => {
    let finishOld: (value: unknown) => void = () => undefined
    const api = client({ charts: vi.fn().mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
      .mockResolvedValueOnce({ charts: [{ chartId: 'chart_002', imagePath: 'new.png' }] }) })
    const controller = createChartAIEdit({ view: viewFor(), client: api, basePath: '/b' })
    try {
      controller.open(mount())
      controller.open(mount('/b/asset/new.png'))
      await vi.waitFor(() => expect(document.querySelector('#chart-ai-instruction')).not.toBeNull())
      finishOld({ charts: [{ chartId: 'chart_001', imagePath: 'reports/revision-1/original.png' }] })
      await new Promise(resolve => setTimeout(resolve, 0))
      document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!.value = '调整颜色'
      ;(document.querySelector('[data-action="submit"]') as HTMLButtonElement).click()
      await vi.waitFor(() => expect(api.startChartAiEdit).toHaveBeenCalledWith('chart_002', expect.objectContaining({ baseImagePath: 'new.png' })))
    } finally { controller.dispose() }
  })

  it('临时网络错误退避后立即探测一次，不叠加服务端长等待', async () => {
    const api = client({ chartAiEditStatus: vi.fn()
      .mockResolvedValueOnce({ status: 'running' })
      .mockRejectedValueOnce(new TypeError('network down'))
      .mockResolvedValueOnce(result()) })
    const controller = createChartAIEdit({ view: viewFor(), client: api, basePath: '/b' })
    controller.open(mount())
    await vi.waitFor(() => expect(document.querySelector('#chart-ai-instruction')).not.toBeNull())
    document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!.value = '调整颜色'
    ;(document.querySelector('[data-action="submit"]') as HTMLButtonElement).click()
    try {
      await vi.waitFor(() => expect(document.querySelector('[data-action="accept"]')).not.toBeNull(), { timeout: 2200 })
      expect(vi.mocked(api.chartAiEditStatus).mock.calls).toEqual([
        ['chart_001', 'cedit-new12345'],
        ['chart_001', 'cedit-new12345', 1500],
        ['chart_001', 'cedit-new12345'],
      ])
    } finally { controller.dispose() }
  })

  it('长轮询中取消后不呈现随后到达的成功预览', async () => {
    let complete: (value: unknown) => void = () => undefined
    let waiting = false
    const api = client({
      cancelChartAiEdit: vi.fn(async () => ({ status: 'cancelled' })),
      chartAiEditStatus: vi.fn().mockResolvedValueOnce({ status: 'running' })
        .mockImplementationOnce(() => new Promise(resolve => { waiting = true; complete = resolve })),
    })
    const controller = createChartAIEdit({ view: viewFor(), client: api, basePath: '/b' })
    controller.open(mount())
    await vi.waitFor(() => expect(document.querySelector('#chart-ai-instruction')).not.toBeNull())
    document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!.value = '调整颜色'
    ;(document.querySelector('[data-action="submit"]') as HTMLButtonElement).click()
    try {
      await vi.waitFor(() => expect(waiting).toBe(true))
      ;(document.querySelector('[data-action="cancel"]') as HTMLButtonElement).click()
      complete(result())
      await vi.waitFor(() => expect(document.querySelector('#chart-ai-instruction')).not.toBeNull(), { timeout: 250 })
      expect(document.querySelector('[data-action="accept"]')).toBeNull()
      expect(document.querySelector('.chart-ai-note')!.textContent).toContain('已取消')
    } finally { controller.dispose() }
  })

  it('生产状态等待返回后立即呈现结果，不再叠加固定轮询间隔', async () => {
    const api = client({ chartAiEditStatus: vi.fn().mockResolvedValueOnce({ status: 'running' }).mockResolvedValueOnce(result()) })
    const controller = createChartAIEdit({ view: viewFor(), client: api, basePath: '/b' })
    controller.open(mount())
    await vi.waitFor(() => expect(document.querySelector('#chart-ai-instruction')).not.toBeNull())
    document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!.value = '调整颜色'
    ;(document.querySelector('[data-action="submit"]') as HTMLButtonElement).click()
    try {
      await vi.waitFor(() => expect(document.querySelector('[data-action="accept"]')).not.toBeNull(), { timeout: 250 })
      expect(api.chartAiEditStatus).toHaveBeenLastCalledWith('chart_001', 'cedit-new12345', 1500)
    } finally { controller.dispose() }
  })

  it('未配置AI仍可直达结构化预设，且启动后立即查询首个状态', async () => {
    const api = client({ chartAiAvailability: vi.fn(async () => ({ available: false, reason: 'unconfigured', standardAvailable: true,
      standard: { standardForm: 'bar' }, baseImagePath: 'reports/revision-1/original.png', expectedSha256: 'a'.repeat(64) })),
      startChartStandardEdit: vi.fn(async () => ({ editId: 'cedit-new12345' })),
    })
    const controller = createChartAIEdit({ view: viewFor(), client: api, basePath: '/b', pollIntervalMs: 60000 })
    controller.open(mount())
    await vi.waitFor(() => expect(document.querySelector('#chart-ai-standard-preset')).not.toBeNull())
    const select = document.querySelector<HTMLSelectElement>('#chart-ai-standard-preset')!
    select.value = 'donut'
    select.dispatchEvent(new Event('change'))
    ;(document.querySelector('[data-action="apply-standard"]') as HTMLButtonElement).click()
    await vi.waitFor(() => expect(document.querySelector('[data-action="accept"]')).not.toBeNull())
    expect(api.startChartStandardEdit).toHaveBeenCalledWith('chart_001', expect.objectContaining({
      standard: { standardForm: 'donut' }, expectedSha256: 'a'.repeat(64), baseImagePath: 'reports/revision-1/original.png',
    }))
    expect(api.startChartAiEdit).not.toHaveBeenCalled()
    expect(api.chartAiEditStatus).toHaveBeenCalledTimes(1)
    controller.dispose()
  })

  it('选择堆叠双轴保留补充要求，通过现有改图请求实际提交，切换预设不累积冲突', async () => {
    const api = client()
    const controller = createChartAIEdit({ view: viewFor(), client: api, basePath: '/b', pollIntervalMs: 1 })
    controller.open(mount())
    await vi.waitFor(() => expect(document.querySelector('#chart-ai-instruction')).not.toBeNull())
    const text = document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!
    text.value = '收入用万元，蓝绿色'
    const select = document.querySelector<HTMLSelectElement>('#chart-ai-standard-preset')!
    expect(select.options.length).toBe(STANDARD_CHART_PRESETS.length + 1)
    select.value = 'dual'
    select.dispatchEvent(new Event('change'))
    ;(document.querySelector('[data-action="apply-standard"]') as HTMLButtonElement).click()
    select.value = 'dual-stack'
    select.dispatchEvent(new Event('change'))
    ;(document.querySelector('[data-action="apply-standard"]') as HTMLButtonElement).click()
    expect(text.value).toContain('收入用万元，蓝绿色')
    expect(text.value).toContain('正负分开累计')
    expect(text.value).not.toContain('根据已登记系列改成双坐标轴')
    ;(document.querySelector('[data-action="submit"]') as HTMLButtonElement).click()
    await vi.waitFor(() => expect(api.startChartAiEdit).toHaveBeenCalledWith('chart_001', expect.objectContaining({ instruction: expect.stringContaining('正负分开累计') })))
    await vi.waitFor(() => expect(document.querySelectorAll('.chart-ai-pages img')).toHaveLength(2))
    expect(document.querySelector('.chart-ai-changes')!.textContent).toContain('完整生成 2 页')
    controller.dispose()
  })

  it('字数不足时不截断模板要求或覆盖用户文本', async () => {
    const controller = createChartAIEdit({ view: viewFor(), client: client(), basePath: '/b' })
    controller.open(mount())
    await vi.waitFor(() => expect(document.querySelector('#chart-ai-instruction')).not.toBeNull())
    const text = document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!
    text.value = '字'.repeat(2000)
    const select = document.querySelector<HTMLSelectElement>('#chart-ai-standard-preset')!
    select.value = 'boxplot'
    select.dispatchEvent(new Event('change'))
    ;(document.querySelector('[data-action="apply-standard"]') as HTMLButtonElement).click()
    expect(text.value).toBe('字'.repeat(2000))
    expect(document.querySelector('#chart-ai-standard-help')!.textContent).toContain('不能超过2000字')
    controller.dispose()
  })

  it('从第二页继续改图传实际页路径，不误用首页', async () => {
    const api = client()
    const controller = createChartAIEdit({ view: viewFor(), client: api, basePath: '/b', pollIntervalMs: 1 })
    controller.open(mount(`/b/asset/${old[1]!.imagePath}`))
    await vi.waitFor(() => expect(document.querySelector('#chart-ai-instruction')).not.toBeNull())
    document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!.value = '调整颜色'
    ;(document.querySelector('[data-action="submit"]') as HTMLButtonElement).click()
    await vi.waitFor(() => expect(api.startChartAiEdit).toHaveBeenCalledWith('chart_001', expect.objectContaining({ baseImagePath: old[1]!.imagePath, previousEditId: 'cedit-old12345' })))
    controller.dispose()
  })

  it('多轮未接受的预览最终接受时仍替换正文旧组，不寻找尚未插入的新预览页', async () => {
    const second = [page(1, 2, 'cedit-final1234'), page(2, 2, 'cedit-final1234')]
    const api = client({ chartAiEditStatus: vi.fn().mockResolvedValueOnce(result()).mockResolvedValueOnce({ ...result(second), editId: 'cedit-final1234' }) })
    const view = viewFor()
    const controller = createChartAIEdit({ view, client: api, basePath: '/b', pollIntervalMs: 1 })
    controller.open(mount(`/b/asset/${old[1]!.imagePath}`))
    await vi.waitFor(() => expect(document.querySelector('#chart-ai-instruction')).not.toBeNull())
    document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!.value = '第一次'
    ;(document.querySelector('[data-action="submit"]') as HTMLButtonElement).click()
    await vi.waitFor(() => expect(document.querySelector('[data-action="continue"]')).not.toBeNull())
    ;(document.querySelector('[data-action="continue"]') as HTMLButtonElement).click()
    document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!.value = '第二次'
    ;(document.querySelector('[data-action="submit"]') as HTMLButtonElement).click()
    await vi.waitFor(() => expect(document.querySelector('[data-action="accept"]')).not.toBeNull())
    ;(document.querySelector('[data-action="accept"]') as HTMLButtonElement).click()
    expect(view.dispatch).toHaveBeenCalledTimes(1)
    const sources: string[] = []
    view.state.doc.descendants(node => { if (node.type.name === 'image-block') sources.push(String(node.attrs.src)) })
    expect(sources).toEqual(second.map(item => item.imageSrc))
    expect(api.startChartAiEdit).toHaveBeenLastCalledWith('chart_001', expect.objectContaining({ baseImagePath: next[0]!.imagePath, previousEditId: 'cedit-new12345' }))
    controller.dispose()
  })

  it('新修订缺少旧草稿记录时仅404允许回退正式登记图匹配', async () => {
    const api = client({ chartEditRecord: vi.fn(async () => { throw new ReportEditorApiError(404, 'missing') }),
      charts: vi.fn(async () => ({ charts: [{ chartId: 'published', imagePath: old[1]!.imagePath }] })) })
    const controller = createChartAIEdit({ view: viewFor(), client: api, basePath: '/b', pollIntervalMs: 1 })
    controller.open(mount(`/b/asset/${old[1]!.imagePath}`))
    await vi.waitFor(() => expect(document.querySelector('#chart-ai-instruction')).not.toBeNull())
    document.querySelector<HTMLTextAreaElement>('#chart-ai-instruction')!.value = '调整颜色'
    ;(document.querySelector('[data-action="submit"]') as HTMLButtonElement).click()
    await vi.waitFor(() => expect(api.startChartAiEdit).toHaveBeenCalledWith('published', expect.not.objectContaining({ previousEditId: expect.anything() })))
    controller.dispose()
  })

  it('读取草稿记录失败时不吞掉服务器错误改绑其他图', async () => {
    const api = client({ chartEditRecord: vi.fn(async () => { throw new ReportEditorApiError(500, 'server_error') }) })
    const controller = createChartAIEdit({ view: viewFor(), client: api, basePath: '/b' })
    controller.open(mount(`/b/asset/${old[1]!.imagePath}`))
    await vi.waitFor(() => expect(document.querySelector('.chart-ai-unavailable')).not.toBeNull())
    expect(api.charts).not.toHaveBeenCalled()
    controller.dispose()
  })
})
