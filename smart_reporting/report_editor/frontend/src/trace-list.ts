import type { TraceSources, TraceValidation } from './api'
import { formatRegisteredValue, periodListText } from './body-value-marks'
import { datasetLabel, subjectBusinessLabel } from './evidence-relations'
import { findProtocolMarkers } from './protocol'
import { sourceSubjectStatus } from './source-status'

/**
 * 溯源清单（CSV）：每个登记来源一行，列出正文位置、正文语句、指标、正文值与登记值、期间、口径、
 * 核对状态和数据快照。只汇总当前修订的登记信息与本次校验结果，不推断未登记的关系。
 */
const HEADERS = ['序号', '章节', '正文语句', '来源', '指标', '正文值', '登记值', '期间', '口径', '核对状态',
  '数据快照', '快照行数', '快照登记时间', '登记编号']

const STATUS_LABELS: Record<string, string> = { valid: '与登记值一致', stale: '需复核', unbound: '未绑定' }
const KIND_LABELS: Record<string, string> = { text_claim: '正文数值', table_cell: '表格单元格', chart: '图表', chart_caption: '图表说明' }

/** CSV 单元格：按 RFC 4180 转义；以公式字符开头的文本前加单引号，避免表格软件执行。 */
export function csvCell(value: unknown): string {
  let text = value === null || value === undefined ? '' : String(value)
  // 只豁免完整负数；数字后接运算符/函数仍是公式。比较完整匹配也排除末尾换行。
  const negativeNumber = /^-(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.exec(text)?.[0] === text
  if (/^[=+@\t\r]/.test(text) || (text.startsWith('-') && !negativeNumber)) text = `'${text}`
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

function stripProtocol(text: string): string {
  return text.replace(/\[\[[a-z/-]+(?::[^\]]*)?\]\]/g, '').replace(/\s+/g, ' ').trim()
}

/** 来源标记所在的句子与最近的上级标题。 */
function bodyContext(markdown: string, subjectId: string): { section: string; sentence: string } {
  const marker = findProtocolMarkers(markdown).find(item => item.kind === 'citation' && item.value === subjectId)
  if (!marker) return { section: '', sentence: '' }
  const before = markdown.slice(0, marker.start)
  const heading = [...before.matchAll(/^#{1,6}\s+(.+)$/gm)].at(-1)?.[1] ?? ''
  const start = Math.max(...['。', '；', '\n'].map(mark => before.lastIndexOf(mark, before.length - 2) + 1))
  return { section: stripProtocol(heading), sentence: stripProtocol(markdown.slice(start, marker.start)) }
}

export function buildTraceListCsv(markdown: string, sources: TraceSources, validation: TraceValidation | null): string {
  const rows: unknown[][] = []
  for (const [index, subject] of (sources.subjects ?? []).entries()) {
    const facts = subject.factRefs.map(ref => sources.facts?.find(fact => fact.analysisId === ref.analysisId && fact.factId === ref.factId))
      .filter((fact): fact is NonNullable<typeof fact> => !!fact)
    const entry = validation?.subjects.find(item => item.subjectId === subject.subjectId)
    const status = validation ? sourceSubjectStatus(validation, subject) : undefined
    const datasets = [...new Set(facts.flatMap(fact => fact.datasetIds))]
      .map(id => sources.datasets?.find(item => item.datasetId === id)).filter((item): item is NonNullable<typeof item> => !!item)
    const { section, sentence } = bodyContext(markdown, subject.subjectId)
    const registered = entry ? formatRegisteredValue(entry.factValue, entry.unit)
      : facts.length === 1 && typeof facts[0].displayValue === 'number' ? formatRegisteredValue(facts[0].displayValue, facts[0].unit) : ''
    const draft = typeof entry?.draftValue === 'number' ? formatRegisteredValue(entry.draftValue, entry.draftUnit ?? entry.unit)
      : entry?.status === 'valid' ? registered : ''
    const factPeriod = [facts[0]?.periodStart, facts[0]?.periodEnd].filter(Boolean).join(' — ')
    rows.push([
      index + 1,
      section,
      sentence || KIND_LABELS[subject.subjectKind] || subject.subjectKind,
      subjectBusinessLabel(subject.subjectId, sources),
      facts.map(fact => fact.name || fact.label).join('、'),
      draft,
      registered,
      periodListText(entry?.periods) || factPeriod,
      entry?.formulaText || entry?.formula || '',
      status ? STATUS_LABELS[status.status] ?? status.status : '未校验',
      datasets.map(dataset => datasetLabel(dataset, sources.datasets)).join('、'),
      datasets.map(dataset => dataset.rowCount).join('、'),
      datasets.map(dataset => dataset.materializedAt ? new Date(dataset.materializedAt).toLocaleString('zh-CN') : '').join('、'),
      subject.subjectId,
    ])
  }
  // 带 BOM 与 CRLF：Excel 直接打开时按 UTF-8 识别中文。
  return `﻿${[HEADERS, ...rows].map(row => row.map(csvCell).join(',')).join('\r\n')}\r\n`
}

export function downloadTraceList(csv: string, fileName: string): void {
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  document.body.append(link)
  link.click()
  link.remove()
  // 浏览器在 click 之后才异步读取 blob 与文件名，立即撤销会让下载退化为无名文件。
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
