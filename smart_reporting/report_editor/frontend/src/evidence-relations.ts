import type {
  TraceChartSource,
  TraceComputationDetail,
  TraceFactDetail,
  TraceSources,
  TraceSubjectInfo,
  TraceDatasetInfo,
} from './api'
import { evidenceRefId, sameEvidenceRef, type EvidenceObjectKind, type EvidenceObjectRef } from './evidence-state'
import { Calculator, ChartColumn, createElement, Database, FileDigit, FileText, type IconNode } from 'lucide'

// 关系图节点、3D 贴图、来源目录与关系列表共用同一套类型图标与类型色。
export const EVIDENCE_KIND_ICONS: Record<EvidenceObjectKind, IconNode> = {
  fact: FileDigit, computation: Calculator, dataset: Database, chart: ChartColumn, subject: FileText,
}
export const EVIDENCE_KIND_COLORS: Record<EvidenceObjectKind, string> = {
  fact: '#2563eb', computation: '#7c3aed', dataset: '#0f766e', chart: '#b45309', subject: '#475569',
}

/** 仅展示登记的期间和角色，不从名称或数据值推断日期。 */
export function factPeriodLabel(entry: { periodStart?: unknown; periodEnd?: unknown; periodRoles?: unknown; periodRole?: unknown; comparisonType?: unknown }): string {
  const roles: Record<string, string> = { current: '本期', yoy: '同比基期', mom: '环比基期' }
  const periods = [...new Set([entry.periodStart, entry.periodEnd].filter(value => typeof value === 'string' && value))]
  const registeredRoles = Array.isArray(entry.periodRoles) ? entry.periodRoles : entry.periodRole ? [entry.periodRole] : []
  const role = registeredRoles.map(value => roles[String(value)] ?? String(value)).join(' / ')
  const comparison = entry.comparisonType === 'yoy' ? '同比' : entry.comparisonType === 'mom' ? '环比' : ''
  return [comparison || role, periods.join(' — ')].filter(Boolean).join(' · ')
}

export function factLabel(fact: NonNullable<TraceSources['facts']>[number]): string {
  return fact.name ? [fact.name, factPeriodLabel(fact)].filter(Boolean).join(' · ') : fact.label
}

export function datasetLabel(dataset: TraceDatasetInfo, datasets: TraceDatasetInfo[] = []): string {
  const name = dataset.businessLabel?.trim() || dataset.filename?.trim()
  if (name) return name
  const roles: Record<string, string> = { current: '本期', yoy: '同比基期', mom: '环比基期' }
  const prefix = dataset.periodRoles.map(role => roles[role] ?? role).join(' / ')
  const label = prefix || dataset.requirementId
  const peers = datasets.filter(item =>
    !item.businessLabel?.trim() && !item.filename?.trim() &&
    item.periodRoles.join('|') === dataset.periodRoles.join('|'),
  )
  return peers.length > 1 ? `${label} ${peers.findIndex(item => item.datasetId === dataset.datasetId) + 1}` : label
}

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
/**
 * 正文引用的短号：“#” + ID 去前缀后的前 6 位；tail > 0 时再接“…” + 末尾 tail 位，
 * 用于区分前缀相同的引用（页签与目录从末尾截断，区分位不能放在长串的中段）。
 */
export function subjectShortId(subjectId: string, tail = 0): string {
  const body = subjectId.replace(/^sub-/, '')
  if (!body) return `#${subjectId}`
  if (tail <= 0) return `#${body.slice(0, 6)}`
  if (body.length <= 6 + tail) return `#${body}`
  return `#${body.slice(0, 6)}…${body.slice(-tail)}`
}

const SUBJECT_LABEL_PREFIX = '正文引用 '

export function subjectLabel(subjectId: string, tail = 0): string {
  return `${SUBJECT_LABEL_PREFIX}${subjectShortId(subjectId, tail)}`
}

/** 从引用显示名取回短号（显示名由 subjectLabel 生成）；不是引用显示名时返回 undefined。 */
export function subjectShortFromLabel(label: string): string | undefined {
  return label.startsWith(`${SUBJECT_LABEL_PREFIX}#`) ? label.slice(SUBJECT_LABEL_PREFIX.length) : undefined
}

/**
 * 同一修订内引用短号互不相同所需的末尾位数（0 表示前 6 位已可区分）：
 * ID 前缀相同的引用若都只取前 6 位会显示成同名，页签、目录与关系中无法区分。
 */
export function subjectShortTail(subjectIds: readonly string[]): number {
  const ids = [...new Set(subjectIds)]
  const longest = Math.max(0, ...ids.map((id) => id.replace(/^sub-/, '').length))
  for (let tail = 0; tail <= longest; tail += 1) {
    if (new Set(ids.map((id) => subjectShortId(id, tail))).size === ids.length) return tail
  }
  return longest
}

/** 按修订内全部引用一次性确定短号尾长，返回各引用的显示名生成器（目录与直接打开引用共用）。 */
export function subjectLabelsFor(subjectIds: readonly string[]): (subjectId: string) => string {
  const tail = subjectShortTail(subjectIds)
  return (subjectId) => subjectLabel(subjectId, tail)
}

export function subjectRef(subjectId: string): EvidenceObjectRef {
  return { kind: 'subject', key: subjectId, label: subjectLabel(subjectId) }
}

function factRef(analysisId: string, factId: string, label?: string): EvidenceObjectRef {
  return { kind: 'fact', key: factId, analysisId, label: label ?? factId }
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
  const registered = sources.facts?.find(item => item.factId === ref.key && item.analysisId === ref.analysisId)
  for (const datasetId of registered?.datasetIds ?? []) {
    const dataset = sources.datasets?.find(item => item.datasetId === datasetId)
    if (!dataset) continue
    const node: EvidenceObjectRef = { kind: 'dataset', key: datasetId, label: datasetLabel(dataset, sources.datasets) }
    add(node)
    relations.edges.push({ from: node, to: ref, label: '输入' })
  }
  for (const input of detail.inputFactRefs) {
    // 没有事实标识的登记无法定位，也没有可显示的名称：缺失不造节点与边。
    if (!input.factId) continue
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
  const labelForDataset = (datasetId: string): string => {
    const dataset = sources.datasets?.find((item) => item.datasetId === datasetId)
    return dataset ? datasetLabel(dataset, sources.datasets) : datasetId
  }
  for (const datasetId of detail.inputDatasetIds) {
    const node: EvidenceObjectRef = { kind: 'dataset', key: datasetId, label: labelForDataset(datasetId) }
    add(node)
    relations.edges.push({ from: node, to: ref, label: '输入' })
  }
  for (const input of detail.inputFactRefs ?? []) {
    // 没有事实标识的登记无法定位，也没有可显示的名称：缺失不造节点与边。
    if (!input.factId) continue
    const node = factRef(input.analysisId, input.factId)
    add(node)
    relations.edges.push({ from: node, to: ref, label: '输入' })
  }
  for (const output of detail.outputFactRefs) {
    // 无 factKey 的输出仍展示（以指针末段命名），但以“分析 + JSON 指针”作身份，
    // 避免同一分析里多个无键输出被当成同一对象去重。
    const node = factRef(
      output.analysisId,
      output.factKey ?? `${output.analysisId}#${output.jsonPointer}`,
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
  for (const fact of sources.facts ?? []) {
    if (!fact.datasetIds.includes(ref.key)) continue
    const node = factRef(fact.analysisId, fact.factId, factLabel(fact))
    add(node)
    relations.edges.push({ from: ref, to: node, label: '产出' })
  }
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

/**
 * 用已登记的显示名统一关系节点名称：各页面装配关系时只能拿到原始 ID（如计算记录 ID、
 * 图表页的数据集 ID），而来源目录与页签使用方法名、文件名。查不到登记名时保留原名，不做推断。
 */
export function relabelRelations(
  relations: EvidenceRelations,
  labelFor: (ref: EvidenceObjectRef) => string | undefined,
): EvidenceRelations {
  const relabel = (ref: EvidenceObjectRef): EvidenceObjectRef => {
    const label = labelFor(ref)
    return label && label !== ref.label ? { ...ref, label } : ref
  }
  return {
    ...relations,
    center: relabel(relations.center),
    nodes: relations.nodes.map(relabel),
    edges: relations.edges.map((edge) => ({ ...edge, from: relabel(edge.from), to: relabel(edge.to) })),
  }
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
    if (!item.factId) continue
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
    const groupName = document.createElement('span')
    groupName.className = 'evidence-relation-group-name'
    groupName.textContent = group
    const count = document.createElement('span')
    count.className = 'evidence-relation-count'
    count.textContent = String(edges.length)
    count.setAttribute('aria-label', `${edges.length} 条`)
    heading.append(groupName, count)
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
        const icon = createElement(EVIDENCE_KIND_ICONS[other.kind], {
          width: 14, height: 14, 'aria-hidden': 'true', color: EVIDENCE_KIND_COLORS[other.kind],
        })
        icon.classList.add('evidence-relation-icon')
        const kind = document.createElement('span')
        kind.className = 'evidence-relation-kind'
        kind.textContent = KIND_LABELS[other.kind]
        const name = document.createElement('span')
        name.className = 'evidence-relation-label'
        name.textContent = other.label
        name.title = other.label
        row.append(icon, kind, name)
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
