import type {
  TraceChartSource,
  TraceComputationDetail,
  TraceFactDetail,
  TraceSources,
  TraceSubjectInfo,
} from './api'
import { evidenceRefId, sameEvidenceRef, type EvidenceObjectKind, type EvidenceObjectRef } from './evidence-state'

/**
 * 证据浏览器局部关系装配（证据浏览器 v6，M2）。
 *
 * 只组装接口真实返回的一跳关系，不补造不存在的边，不声称完整血缘；
 * loadedNote 统一标注「局部关系」，未知总量不写百分比。边方向固定从
 * 输入指向产出；引用边始终从被引用对象指向正文引用，与当前页面无关。
 */

export interface EvidenceRelationEdge {
  from: EvidenceObjectRef
  to: EvidenceObjectRef
  label: '输入' | '产出' | '引用'
}

export interface EvidenceRelations {
  center: EvidenceObjectRef
  nodes: EvidenceObjectRef[]
  edges: EvidenceRelationEdge[]
  loadedNote: string
}

export interface EvidenceRelationHandlers {
  navigate: (ref: EvidenceObjectRef) => void
  openBackground: (ref: EvidenceObjectRef, foreground?: boolean) => void
}

const KIND_LABELS: Record<EvidenceObjectKind, string> = {
  fact: '事实',
  computation: '计算',
  dataset: '快照',
  chart: '图表',
  subject: '引用',
}

/**
 * 正文引用的统一显示名。subjectId 为 `sub-` + 16 位摘要；旧实现截前 8 位只剩 4 位有效字符，
 * 名称既无可读信息又容易在大报告中重名。这里去掉固定前缀后取 6 位短号，各入口共用。
 */
export function subjectLabel(subjectId: string): string {
  const short = subjectId.replace(/^sub-/, '').slice(0, 6)
  return `正文引用 #${short || subjectId}`
}

function subjectRef(subjectId: string): EvidenceObjectRef {
  return { kind: 'subject', key: subjectId, label: subjectLabel(subjectId) }
}

function factRef(analysisId: string, factId: string | null, label?: string): EvidenceObjectRef {
  return {
    kind: 'fact',
    key: factId ?? analysisId,
    analysisId,
    label: label ?? factId ?? analysisId,
  }
}

function pointerTail(jsonPointer: string): string {
  const segments = jsonPointer.split('/').filter(Boolean)
  return segments[segments.length - 1] ?? jsonPointer
}

function makeRelations(center: EvidenceObjectRef): { relations: EvidenceRelations; add: (node: EvidenceObjectRef) => void } {
  const nodes: EvidenceObjectRef[] = []
  const seen = new Set<string>([evidenceRefId(center)])
  return {
    relations: { center, nodes, edges: [], loadedNote: '' },
    add(node) {
      const id = evidenceRefId(node)
      if (seen.has(id)) return
      seen.add(id)
      nodes.push(node)
    },
  }
}

function finish(relations: EvidenceRelations, suffix = ''): EvidenceRelations {
  relations.loadedNote = `已加载 ${relations.nodes.length + 1} 个节点 · 局部关系${suffix}`
  return relations
}

/** 事实页：输入事实、产出它的计算记录、引用它的正文引用。 */
export function assembleFactRelations(
  ref: EvidenceObjectRef,
  detail: TraceFactDetail,
  sources: TraceSources,
): EvidenceRelations {
  const { relations, add } = makeRelations(ref)
  for (const input of detail.inputFactRefs) {
    const node = factRef(input.analysisId, input.factId)
    add(node)
    relations.edges.push({ from: node, to: ref, label: '输入' })
  }
  const subjects = (sources.subjects ?? []).filter((subject) =>
    subject.factRefs.some(
      (item) => item.factId === ref.key && (!ref.analysisId || item.analysisId === ref.analysisId),
    ),
  )
  const computationIds = new Set<string>()
  for (const subject of subjects) {
    const node = subjectRef(subject.subjectId)
    add(node)
    relations.edges.push({ from: ref, to: node, label: '引用' })
    if (subject.computationId) computationIds.add(subject.computationId)
  }
  for (const computationId of computationIds) {
    const node: EvidenceObjectRef = { kind: 'computation', key: computationId, label: computationId }
    add(node)
    relations.edges.push({ from: node, to: ref, label: '产出' })
  }
  return finish(relations)
}

/** 计算页：输入快照、输入事实、输出事实。 */
export function assembleComputationRelations(
  ref: EvidenceObjectRef,
  detail: TraceComputationDetail,
  sources: TraceSources,
): EvidenceRelations {
  const { relations, add } = makeRelations(ref)
  const datasetLabel = (datasetId: string): string => {
    const dataset = sources.datasets?.find((item) => item.datasetId === datasetId)
    return dataset?.filename ?? dataset?.businessLabel ?? datasetId
  }
  for (const datasetId of detail.inputDatasetIds) {
    const node: EvidenceObjectRef = { kind: 'dataset', key: datasetId, label: datasetLabel(datasetId) }
    add(node)
    relations.edges.push({ from: node, to: ref, label: '输入' })
  }
  for (const input of detail.inputFactRefs ?? []) {
    const node = factRef(input.analysisId, input.factId)
    add(node)
    relations.edges.push({ from: node, to: ref, label: '输入' })
  }
  for (const output of detail.outputFactRefs) {
    const node = factRef(
      output.analysisId,
      output.factKey,
      output.factKey ?? pointerTail(output.jsonPointer),
    )
    add(node)
    relations.edges.push({ from: ref, to: node, label: '产出' })
  }
  return finish(relations)
}

/** 快照页：仅登记了下钻指标与引用的使用方，不声称完整下游。 */
export function assembleDatasetRelations(ref: EvidenceObjectRef, sources: TraceSources): EvidenceRelations {
  const { relations, add } = makeRelations(ref)
  const drilldown = sources.drilldown
  if (drilldown) {
    const metricCodes = new Set(
      (drilldown.metrics ?? [])
        .filter((metric) => metric.datasetId === ref.key)
        .map((metric) => metric.metricCode),
    )
    for (const subject of drilldown.subjects ?? []) {
      if (!subject.metrics.some((metric) => metric.datasetId === ref.key && metricCodes.has(metric.metricCode))) {
        continue
      }
      const node = subjectRef(subject.subjectId)
      add(node)
      relations.edges.push({ from: ref, to: node, label: '引用' })
    }
  }
  return finish(relations, '（仅含已登记关系）')
}

/** 图表页：作图数据集与产出侧计算记录。 */
export function assembleChartRelations(ref: EvidenceObjectRef, source: TraceChartSource): EvidenceRelations {
  const { relations, add } = makeRelations(ref)
  for (const datasetId of source.datasetIds) {
    const node: EvidenceObjectRef = { kind: 'dataset', key: datasetId, label: datasetId }
    add(node)
    relations.edges.push({ from: node, to: ref, label: '输入' })
  }
  if (source.computationId) {
    const node: EvidenceObjectRef = {
      kind: 'computation',
      key: source.computationId,
      label: source.computationId,
    }
    add(node)
    relations.edges.push({ from: node, to: ref, label: '输入' })
  }
  return finish(relations)
}

/** 引用页：引用的事实与产出侧计算记录。 */
export function assembleSubjectRelations(ref: EvidenceObjectRef, subject: TraceSubjectInfo): EvidenceRelations {
  const { relations, add } = makeRelations(ref)
  for (const item of subject.factRefs) {
    const node = factRef(item.analysisId, item.factId)
    add(node)
    relations.edges.push({ from: node, to: ref, label: '引用' })
  }
  if (subject.computationId) {
    const node: EvidenceObjectRef = {
      kind: 'computation',
      key: subject.computationId,
      label: subject.computationId,
    }
    add(node)
    relations.edges.push({ from: node, to: ref, label: '产出' })
  }
  return finish(relations)
}

const GROUP_ORDER: EvidenceRelationEdge['label'][] = ['输入', '产出', '引用']

export function bindEvidenceNavigation(
  button: HTMLButtonElement, ref: EvidenceObjectRef, handlers: EvidenceRelationHandlers,
): void {
  button.addEventListener('click', (event) => {
    if (event.ctrlKey || event.metaKey) handlers.openBackground(ref, event.shiftKey)
    else handlers.navigate(ref)
  })
  button.addEventListener('auxclick', (event) => {
    if (event.button !== 1) return
    event.preventDefault()
    handlers.openBackground(ref)
  })
}

/**
 * 关系列表：图视图（M3）接入前的等价文字入口，按输入/产出/引用分组。
 * 普通点击进入当前任务导航；Ctrl/⌘ + 单击与中键后台开启独立任务。
 */
export function renderRelationList(
  container: HTMLElement,
  relations: EvidenceRelations,
  handlers: EvidenceRelationHandlers,
): void {
  container.innerHTML = ''
  for (const group of GROUP_ORDER) {
    const edges = relations.edges.filter((edge) => edge.label === group)
    if (!edges.length) continue
    const heading = document.createElement('h3')
    heading.className = 'evidence-relation-group'
    heading.textContent = group
    container.append(heading)
    for (const edge of edges) {
      const endpoints = sameEvidenceRef(edge.from, relations.center) ? [edge.to]
        : sameEvidenceRef(edge.to, relations.center) ? [edge.from] : [edge.from, edge.to]
      const pair = document.createElement('div')
      pair.className = 'evidence-relation-pair'
      for (const [index, other] of endpoints.entries()) {
        if (index) {
          const arrow = document.createElement('span')
          arrow.className = 'evidence-relation-arrow'
          arrow.textContent = ' → '
          arrow.setAttribute('aria-hidden', 'true')
          pair.append(arrow)
        }
        const row = document.createElement('button')
        row.type = 'button'
        row.className = 'evidence-relation-row'
        const kind = document.createElement('span')
        kind.className = 'evidence-relation-kind'
        kind.textContent = KIND_LABELS[other.kind]
        const name = document.createElement('span')
        name.className = 'evidence-relation-label'
        name.textContent = other.label
        name.title = other.label
        row.append(kind, name)
        bindEvidenceNavigation(row, other, handlers)
        pair.append(row)
      }
      container.append(pair)
    }
  }
  if (!relations.edges.length) {
    const empty = document.createElement('p')
    empty.className = 'evidence-relation-empty'
    empty.setAttribute('role', 'status')
    empty.setAttribute('aria-live', 'polite')
    empty.textContent = '没有已加载的关系'
    container.append(empty)
  }
}
