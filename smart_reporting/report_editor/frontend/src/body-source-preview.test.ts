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
