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

it('highlights through the editor and returns focus to the re-rendered marker after closing', async () => {
  asyncDialogs()
  const client = new ReportEditorClient('/test')
  document.body.innerHTML = '<p>收入<span id="marker" class="report-protocol-marker" tabindex="0"></span></p>'
  const original = document.getElementById('marker')!
  // 编辑器绘制高亮时会重绘标记：模拟原元素被同位置的新元素替换。
  const redrawn = document.createElement('span')
  redrawn.className = 'report-protocol-marker'
  redrawn.tabIndex = 0
  const markers = {
    activate: vi.fn(() => { original.replaceWith(redrawn); return 7 }),
    deactivate: vi.fn(),
    find: vi.fn((position: number) => position === 7 ? redrawn : null),
  }
  const preview = createBodySourcePreview({ client, sources: async () => baseSources(), validation: () => null, open: vi.fn(), markers })
  await preview(original, [{ kind: 'citation', value: 'cite-a' }])
  expect(markers.activate).toHaveBeenCalledWith(original)
  expect(original.classList.contains('source-marker-active')).toBe(false)
  document.querySelector<HTMLDialogElement>('dialog')!.close()
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(markers.deactivate).toHaveBeenCalledTimes(1)
  expect(markers.find).toHaveBeenCalledWith(7)
  expect(document.activeElement).toBe(redrawn)
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

const claimSources = (): TraceSources => ({
  ...baseSources(),
  subjects: [{ subjectId: 'sub-c', subjectKind: 'claim', locator: {}, factRefs: [{ analysisId: 'analysis_001', factId: 'fact-c' }], computationId: null }],
  facts: [{ analysisId: 'analysis_001', factId: 'fact-c', factKind: 'metric', label: '收入', name: '华东营收', unit: '万元', displayValue: 12450, datasetIds: ['data-a'] }],
} as unknown as TraceSources)
const claimValidation = (status: 'valid' | 'stale') => ({
  draftSha256: 'x', summary: { valid: 0, stale: 1, unbound: 0 },
  subjects: [{ subjectId: 'sub-c', claimId: 'c', sectionId: null, status, factValue: 12450, unit: '万元',
    draftValue: status === 'stale' ? 12780 : undefined, periods: ['2025-01', '2025-10'], formula: 'sum(revenue)', formulaText: '营收 求和' }],
})

it('states the verification conclusion and restores the registered value on request', async () => {
  asyncDialogs()
  const client = new ReportEditorClient('/test')
  const open = vi.fn()
  const restore = vi.fn().mockReturnValueOnce(false).mockReturnValue(true)
  const preview = createBodySourcePreview({ client, sources: async () => claimSources(), validation: () => claimValidation('stale'), open, restore })
  document.body.innerHTML = '<p>华东营收为 12,780 万元<span id="marker" class="report-protocol-marker"></span></p>'
  await preview(document.getElementById('marker')!, [{ kind: 'citation', value: 'sub-c' }])
  const verification = document.querySelector('.source-preview-verification')!
  expect(verification.textContent).toContain('正文已改动，需复核')
  expect(verification.textContent).toContain('正文当前值12,780万元')
  expect(verification.textContent).toContain('登记值12,450万元')
  expect(verification.textContent).toContain('期间2025-01 — 2025-10')
  expect(verification.textContent).toContain('口径营收 求和')
  // 找不到唯一位置时保留来源并提示手动修改，不猜测替换。
  ;(document.querySelector('.source-preview-restore') as HTMLButtonElement).click()
  expect(restore).toHaveBeenCalledWith('sub-c')
  expect(verification.textContent).toContain('请手动修改')
  ;(document.querySelector('.source-preview-rows') as HTMLButtonElement).click()
  expect(open).toHaveBeenCalledWith({ kind: 'dataset', value: 'data-a', label: '收入台账' })
})

it('does not offer a restore action when the body already matches', async () => {
  asyncDialogs()
  const client = new ReportEditorClient('/test')
  const preview = createBodySourcePreview({ client, sources: async () => claimSources(), validation: () => claimValidation('valid'), open: vi.fn(), restore: vi.fn() })
  document.body.innerHTML = '<p>华东营收为 12,450 万元<span id="marker" class="report-protocol-marker"></span></p>'
  await preview(document.getElementById('marker')!, [{ kind: 'citation', value: 'sub-c' }])
  expect(document.querySelector('.source-preview-verification')?.textContent).toContain('正文与登记值一致')
  expect(document.querySelector('.source-preview-restore')).toBeNull()
})
