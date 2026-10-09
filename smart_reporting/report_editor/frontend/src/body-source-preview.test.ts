import { afterEach, expect, it, vi } from 'vitest'
import { ReportEditorClient, type TraceSources } from './api'
import { createBodySourcePreview } from './body-source-preview'

afterEach(() => {
  vi.restoreAllMocks(); document.body.replaceChildren()
  Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal')
  Reflect.deleteProperty(HTMLDialogElement.prototype, 'close')
})

it('previews the exact frozen month and retains the complete provenance link', async () => {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function (this: HTMLDialogElement) { this.open = true } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: function (this: HTMLDialogElement, value?: string) {
    this.returnValue = value || ''; this.open = false; this.dispatchEvent(new Event('close'))
  } })
  const client = new ReportEditorClient('/test')
  vi.spyOn(client, 'factDetail').mockResolvedValue({
    analysisId: 'analysis_001', factId: 'fact-a', factKind: 'metric',
    entry: { total: 9000, periodValues: [{ period: '2025-01', value: 1200 }, { period: '2025-02', value: 7800 }] }, displayValue: 9000, inputFactRefs: [], warnings: [],
  })
  const sources: TraceSources = {
    available: true,
    subjects: [{ subjectId: 'sub-a', subjectKind: 'table_cell', locator: { tableId: 'table-a', rowKey: 'period:2025-01', columnKey: '收入' }, factRefs: [{ analysisId: 'analysis_001', factId: 'fact-a' }], computationId: null }],
    facts: [{ analysisId: 'analysis_001', factId: 'fact-a', factKind: 'metric', label: '收入', name: '医疗收入', unit: '元', displayValue: 9000, datasetIds: ['data-a'] }],
    datasets: [{ datasetId: 'data-a', sourceType: 'csv', requirementId: 'income', filename: '收入.csv', businessLabel: '收入台账', rowCount: 3, size: 10, materializedAt: null, periodRoles: ['current'], queryWindowId: 'current' }],
  }
  const open = vi.fn()
  const preview = createBodySourcePreview({ client, sources: async () => sources, validation: () => null, open })
  document.body.innerHTML = '<table><tbody><tr><td>1,200元<span id="marker" class="report-protocol-marker"></span></td></tr></tbody></table>'
  const marker = document.getElementById('marker')!
  await preview(marker, [{ kind: 'citation', value: 'sub-a' }])
  expect(document.querySelector('.source-preview-values')?.textContent).toContain('登记值1,200元')
  expect(document.querySelector('.source-preview-values')?.textContent).not.toContain('9,000')
  expect(document.querySelector('.source-preview-note')?.textContent).toContain('2025-01')
  expect(document.querySelector('.source-preview-dataset')?.textContent).toContain('收入台账')
  ;(document.querySelector('.source-preview-open') as HTMLButtonElement).click()
  expect(open).toHaveBeenCalledWith({ kind: 'citation', value: 'sub-a' })
  expect(document.querySelector('dialog')).toBeNull()
  sources.subjects![0].factRefs.push({ analysisId: 'analysis_002', factId: 'fact-b' })
  await preview(marker, [{ kind: 'citation', value: 'sub-a' }])
  expect(document.querySelector('.source-preview-card h3')?.textContent).toBe('组合事实 · 2 项依据')
  expect(document.querySelector('.source-preview-values')).toBeNull()
  expect(client.factDetail).toHaveBeenCalledTimes(1)
})

const asyncDialogs = () => {
  // 规范中 close 事件是排队任务（异步），不是在 close() 内同步派发。
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: function (this: HTMLDialogElement) { this.open = true } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: function (this: HTMLDialogElement, value?: string) {
    if (!this.open) return
    this.returnValue = value || ''; this.open = false
    setTimeout(() => this.dispatchEvent(new Event('close')))
  } })
}

const baseSources = (): TraceSources => ({
  available: true,
  citations: [{ citationId: 'cite-a', datasetId: 'data-a' }, { citationId: 'cite-b', datasetId: 'data-a' }] as TraceSources['citations'],
  datasets: [{ datasetId: 'data-a', sourceType: 'csv', requirementId: 'income', filename: '收入.csv', businessLabel: '收入台账', rowCount: 3, size: 10, materializedAt: null, periodRoles: ['current'], queryWindowId: 'current' }],
})

it('keeps the marker highlighted when the same marker reopens its preview', async () => {
  asyncDialogs()
  const client = new ReportEditorClient('/test')
  const preview = createBodySourcePreview({ client, sources: async () => baseSources(), validation: () => null, open: vi.fn() })
  document.body.innerHTML = '<p>收入<span id="marker" class="report-protocol-marker"></span></p>'
  const marker = document.getElementById('marker')!
  await preview(marker, [{ kind: 'citation', value: 'cite-a' }])
  await preview(marker, [{ kind: 'citation', value: 'cite-a' }])
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(document.querySelectorAll('dialog')).toHaveLength(1)
  expect(marker.classList.contains('source-marker-active')).toBe(true)
})

it('falls back per reference instead of duplicating every link after a partial failure', async () => {
  asyncDialogs()
  const client = new ReportEditorClient('/test')
  vi.spyOn(client, 'chartSource').mockRejectedValue(new TypeError('offline'))
  const preview = createBodySourcePreview({ client, sources: async () => baseSources(), validation: () => null, open: vi.fn() })
  document.body.innerHTML = '<p>收入<span id="marker" class="report-protocol-marker"></span></p>'
  await preview(document.getElementById('marker')!, [{ kind: 'citation', value: 'cite-a' }, { kind: 'chart', value: 'chart-1' }])
  // 第一项已正常展示；只有失败的第二项降级，每个来源恰好一个“查看完整溯源”。
  expect(document.querySelectorAll('.source-preview-card')).toHaveLength(2)
  expect(document.querySelectorAll('.source-preview-open')).toHaveLength(2)
  expect(document.querySelectorAll('.source-preview-card')[1].textContent).toContain('来源预览暂不可用')
})
