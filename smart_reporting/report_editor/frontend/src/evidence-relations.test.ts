import { describe, expect, it, vi } from 'vitest'

import type { TraceSources } from './api'
import {
  assembleChartRelations,
  assembleComputationRelations,
  assembleDatasetRelations,
  assembleFactRelations,
  assembleSubjectRelations,
  renderRelationList,
  relabelRelations,
  subjectLabel,
} from './evidence-relations'
import type { EvidenceObjectRef } from './evidence-state'

const FACT_REF: EvidenceObjectRef = {
  kind: 'fact',
  key: 'fact-aaaaaaaaaaaaaaaa',
  analysisId: 'analysis_001',
  label: '华东营收',
}

const SOURCES: TraceSources = {
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
      materializedAt: null,
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
    {
      subjectId: 'sub-dddddddddddddddd',
      subjectKind: 'text_claim',
      locator: { sectionId: 'section_003' },
      factRefs: [{ analysisId: 'analysis_001', factId: 'fact-other' }],
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
        dimensions: [],
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

describe('subjectLabel', () => {
  it('drops the fixed prefix so the short id stays distinguishable', () => {
    expect(subjectLabel('sub-a1b2c3d4e5f60718')).toBe('正文引用 #a1b2c3')
    // 旧实现只保留 4 位有效字符，以下两个引用会显示成同一个名称。
    expect(subjectLabel('sub-a1b2c3000000000')).not.toBe(subjectLabel('sub-a1b2ff000000000'))
    expect(subjectLabel('legacy-id')).toBe('正文引用 #legacy')
  })
})

describe('relabelRelations', () => {
  it('replaces raw ids with registered labels on nodes and edge endpoints only when known', () => {
    const center: EvidenceObjectRef = { kind: 'chart', key: 'chart-1', label: 'chart-1' }
    const dataset: EvidenceObjectRef = { kind: 'dataset', key: 'ds-1', label: 'ds-1' }
    const computation: EvidenceObjectRef = { kind: 'computation', key: 'comp-1', label: 'comp-1' }
    const relations = {
      center, nodes: [dataset, computation],
      edges: [{ from: dataset, to: center, label: '输入' as const }, { from: computation, to: center, label: '输入' as const }],
      loadedNote: '',
    }
    const labels: Record<string, string> = { 'ds-1': '收入明细.csv', 'comp-1': '渠道收入汇总' }
    const next = relabelRelations(relations as never, (ref) => labels[ref.key])
    expect(next.nodes.map((node) => node.label)).toEqual(['收入明细.csv', '渠道收入汇总'])
    expect(next.edges.map((edge) => edge.from.label)).toEqual(['收入明细.csv', '渠道收入汇总'])
    // 未登记的对象保留原名，不推断。
    expect(next.center.label).toBe('chart-1')
    expect(next.edges[0]!.from.key).toBe('ds-1')
  })
})

describe('assembleFactRelations', () => {
  it('links input facts, citing subjects and producing computations', () => {
    const relations = assembleFactRelations(
      FACT_REF,
      {
        analysisId: 'analysis_001',
        factId: 'fact-aaaaaaaaaaaaaaaa',
        factKind: 'metric',
        displayValue: 12450,
        entry: { unit: '万元' },
        inputFactRefs: [{ analysisId: 'analysis_001', factId: 'fact-input' }],
        warnings: [],
      },
      SOURCES,
    )
    expect(relations.center).toBe(FACT_REF)
    expect(relations.loadedNote).toBe('已加载 4 个节点 · 局部关系')
    expect(relations.edges).toEqual([
      {
        from: { kind: 'fact', key: 'fact-input', analysisId: 'analysis_001', label: 'fact-input' },
        to: FACT_REF,
        label: '输入',
      },
      {
        from: FACT_REF,
        to: { kind: 'subject', key: 'sub-cccccccccccccccc', label: '正文引用 #cccccc' },
        label: '引用',
      },
      {
        from: { kind: 'computation', key: 'comp-001', label: 'comp-001' },
        to: FACT_REF,
        label: '产出',
      },
    ])
    // 只匹配引用此事实的 subject，其他 subject 不进入关系。
    expect(relations.nodes.some((node) => node.key === 'sub-dddddddddddddddd')).toBe(false)
  })
})

describe('assembleComputationRelations', () => {
  it('resolves dataset labels from sources and fact labels from factKey or pointer tail', () => {
    const ref: EvidenceObjectRef = { kind: 'computation', key: 'comp-001', label: 'sum' }
    const relations = assembleComputationRelations(
      ref,
      {
        computationId: 'comp-001',
        method: 'sum',
        parameters: {},
        executionId: null,
        environment: null,
        verification: 'verified',
        reproducibility: 'reproducible',
        limitations: [],
        inputDatasetIds: ['dataset-url-abc0001', 'dataset-missing'],
        inputFactRefs: [{ analysisId: 'analysis_001', factId: 'fact-input' }],
        outputFactRefs: [
          { analysisId: 'analysis_001', factKey: 'fact-out', factKind: 'metric', jsonPointer: '/a/b' },
          { analysisId: 'analysis_001', factKey: null, factKind: 'metric', jsonPointer: '/metrics/revenue' },
        ],
        scriptFile: null,
        chain: { computationId: 'comp-001', method: 'sum' },
      },
      SOURCES,
    )
    const labels = relations.nodes.map((node) => node.label)
    expect(labels).toEqual(['收入明细.csv', 'dataset-missing', 'fact-input', 'fact-out', 'revenue'])
    expect(relations.edges.filter((edge) => edge.label === '输入')).toHaveLength(3)
    expect(relations.edges.filter((edge) => edge.label === '产出')).toHaveLength(2)
    expect(relations.loadedNote).toBe('已加载 6 个节点 · 局部关系')
  })

  it('keeps keyless outputs distinct and skips inputs without a fact id', () => {
    const ref: EvidenceObjectRef = { kind: 'computation', key: 'comp-001', label: 'sum' }
    const relations = assembleComputationRelations(ref, {
      computationId: 'comp-001', method: 'sum', parameters: {}, executionId: null, environment: null,
      verification: 'verified', reproducibility: 'reproducible', limitations: [], inputDatasetIds: [],
      inputFactRefs: [{ analysisId: 'analysis_001', factId: null }],
      outputFactRefs: [
        { analysisId: 'analysis_001', factKey: null, factKind: 'metric', jsonPointer: '/metrics/revenue' },
        { analysisId: 'analysis_001', factKey: null, factKind: 'metric', jsonPointer: '/metrics/cost' },
      ],
      scriptFile: null, chain: { computationId: 'comp-001', method: 'sum' },
    }, SOURCES)
    // 两个无键输出各自成为节点；缺 factId 的输入不造节点。
    expect(relations.nodes.map((node) => node.label)).toEqual(['revenue', 'cost'])
    expect(relations.edges.filter((edge) => edge.label === '输入')).toHaveLength(0)
  })
})

describe('assembleDatasetRelations', () => {
  it('links only registered drilldown subjects', () => {
    const ref: EvidenceObjectRef = { kind: 'dataset', key: 'dataset-url-abc0001', label: '收入明细.csv' }
    const relations = assembleDatasetRelations(ref, SOURCES)
    expect(relations.nodes).toEqual([
      { kind: 'subject', key: 'sub-cccccccccccccccc', label: '正文引用 #cccccc' },
    ])
    expect(relations.edges[0]).toMatchObject({ from: ref, label: '引用' })
    expect(relations.loadedNote).toContain('局部关系')
    expect(relations.loadedNote).toContain('仅含已登记关系')
  })
})

describe('assembleChartRelations', () => {
  it('links plot datasets and the producing computation as inputs', () => {
    const ref: EvidenceObjectRef = { kind: 'chart', key: 'chart_001', label: 'chart_001' }
    const relations = assembleChartRelations(ref, {
      available: true,
      chartId: 'chart_001',
      datasetIds: ['d1', 'd2'],
      transformNotes: [],
      computationId: 'comp-001',
      image: { size: 10, sha256: 'a'.repeat(64) },
      plotData: [],
    })
    expect(relations.edges.map((edge) => edge.label)).toEqual(['输入', '输入', '输入'])
    expect(relations.nodes.map((node) => node.kind)).toEqual(['dataset', 'dataset', 'computation'])
  })
})

describe('assembleSubjectRelations', () => {
  it('keeps citation edges pointing from facts to the subject on every page', () => {
    const ref: EvidenceObjectRef = { kind: 'subject', key: 'sub-cccccccccccccccc', label: '正文引用 #cccccc' }
    const relations = assembleSubjectRelations(ref, SOURCES.subjects![0]!)
    expect(relations.edges).toEqual([
      {
        to: ref,
        from: { kind: 'fact', key: 'fact-aaaaaaaaaaaaaaaa', analysisId: 'analysis_001', label: 'fact-aaaaaaaaaaaaaaaa' },
        label: '引用',
      },
      { from: { kind: 'computation', key: 'comp-001', label: 'comp-001' }, to: ref, label: '产出' },
    ])
  })
})

describe('renderRelationList', () => {
  function setup() {
    const container = document.createElement('div')
    const navigate = vi.fn()
    const openBackground = vi.fn()
    return { container, navigate, openBackground }
  }

  it('groups rows by edge label and navigates on plain click', () => {
    const { container, navigate, openBackground } = setup()
    const relations = assembleFactRelations(
      FACT_REF,
      {
        analysisId: 'analysis_001',
        factId: 'fact-aaaaaaaaaaaaaaaa',
        factKind: 'metric',
        displayValue: 1,
        entry: {},
        inputFactRefs: [{ analysisId: 'analysis_001', factId: 'fact-input' }],
        warnings: [],
      },
      SOURCES,
    )
    renderRelationList(container, relations, { navigate, openBackground })
    const groups = Array.from(container.querySelectorAll('.evidence-relation-group')).map(
      (item) => item.textContent,
    )
    expect(groups).toEqual(['输入', '产出', '引用'])
    expect(container.querySelectorAll('h3.evidence-relation-group')).toHaveLength(3)
    const rows = container.querySelectorAll<HTMLButtonElement>('.evidence-relation-row')
    expect(rows).toHaveLength(3)
    expect(rows[0]!.textContent).toContain('事实')
    expect(rows[0]!.textContent).toContain('fact-input')
    // 每行带装饰性类型图标，读屏仍读类型文字与名称。
    expect(rows[0]!.querySelector('.evidence-relation-icon')?.getAttribute('aria-hidden')).toBe('true')
    expect(rows[0]!.querySelector('.evidence-relation-label')?.getAttribute('title')).toBe('fact-input')
    rows[0]!.click()
    expect(navigate).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'fact', key: 'fact-input' }),
    )
    expect(openBackground).not.toHaveBeenCalled()
  })

  it('exposes both endpoints of a loaded edge outside the current object', () => {
    const { container, navigate, openBackground } = setup()
    const input: EvidenceObjectRef = { kind: 'dataset', key: 'rows', label: '明细' }
    const output: EvidenceObjectRef = { kind: 'computation', key: 'sum', label: '汇总' }
    renderRelationList(container, {
      center: FACT_REF, nodes: [input, output], loadedNote: '局部关系',
      edges: [{ from: input, to: output, label: '输入' }],
    }, { navigate, openBackground })
    const rows = container.querySelectorAll<HTMLButtonElement>('.evidence-relation-row')
    expect(rows).toHaveLength(2)
    expect(container.textContent).toContain('→')
    rows[0].click()
    expect(navigate).toHaveBeenCalledWith(input)
    rows[1].dispatchEvent(new MouseEvent('click', { ctrlKey: true, bubbles: true }))
    expect(openBackground).toHaveBeenCalledWith(output, false)
  })

  it('opens in background on ctrl/meta click and middle auxclick', () => {
    const { container, navigate, openBackground } = setup()
    const relations = assembleChartRelations(
      { kind: 'chart', key: 'chart_001', label: 'chart_001' },
      {
        available: true,
        chartId: 'chart_001',
        datasetIds: ['d1'],
        transformNotes: [],
        computationId: null,
        image: { size: 1, sha256: 'a'.repeat(64) },
        plotData: [],
      },
    )
    renderRelationList(container, relations, { navigate, openBackground })
    const row = container.querySelector<HTMLButtonElement>('.evidence-relation-row')!
    row.dispatchEvent(new MouseEvent('click', { bubbles: true, ctrlKey: true }))
    expect(openBackground).toHaveBeenCalledTimes(1)
    expect(navigate).not.toHaveBeenCalled()
    row.dispatchEvent(new MouseEvent('click', { bubbles: true, ctrlKey: true, shiftKey: true }))
    expect(openBackground).toHaveBeenLastCalledWith(expect.anything(), true)
    row.dispatchEvent(new MouseEvent('auxclick', { bubbles: true, button: 1 }))
    expect(openBackground).toHaveBeenCalledTimes(3)
    expect(navigate).not.toHaveBeenCalled()
  })

  it('renders labels as text, never markup', () => {
    const { container, navigate, openBackground } = setup()
    const relations = assembleComputationRelations(
      { kind: 'computation', key: 'c', label: 'c' },
      {
        computationId: 'c',
        method: 'm',
        parameters: {},
        executionId: null,
        environment: null,
        verification: 'not_checked',
        reproducibility: 'unavailable',
        limitations: [],
        inputDatasetIds: [],
        outputFactRefs: [
          {
            analysisId: 'a',
            factKey: '<img src=x onerror="window.__pwned=1">',
            factKind: 'metric',
            jsonPointer: '/x',
          },
        ],
        scriptFile: null,
        chain: { computationId: 'c', method: 'm' },
      },
      { available: true },
    )
    renderRelationList(container, relations, { navigate, openBackground })
    expect(container.textContent).toContain('<img src=x')
    expect(container.querySelector('img')).toBeNull()
    expect((window as unknown as Record<string, unknown>).__pwned).toBeUndefined()
  })

  it('announces an empty relation state', () => {
    const { container, navigate, openBackground } = setup()
    renderRelationList(container, {
      center: { kind: 'fact', key: 'f', label: 'f' },
      nodes: [],
      edges: [],
      loadedNote: '局部关系',
    }, { navigate, openBackground })
    const empty = container.querySelector('.evidence-relation-empty')!
    expect(empty.getAttribute('role')).toBe('status')
    expect(empty.getAttribute('aria-live')).toBe('polite')
  })
})
