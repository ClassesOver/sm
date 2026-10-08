import { createElement, ArrowUpRight, Database, Link2, X, CircleCheck, TriangleAlert } from 'lucide'
import type { ReportEditorClient, TraceSources, TraceValidation } from './api'
import { analysisLabel, citationLabel, datasetLabel } from './evidence-relations'
import { sourceSubjectStatus } from './source-status'

type Reference = { kind: 'analysis' | 'citation' | 'chart'; value: string }
type Options = {
  client: ReportEditorClient
  sources: () => Promise<TraceSources>
  validation: () => TraceValidation | null
  open: (reference: Reference) => void
}

// 只读取已登记来源；预览不会写入正文或为缺失的数据补值。
export function createBodySourcePreview(options: Options) {
  let current: { dialog: HTMLDialogElement; marker: HTMLElement } | null = null
  return async (marker: HTMLElement, references: Reference[]) => {
    current?.dialog.close('replaced')
    const dialog = document.createElement('dialog')
    current = { dialog, marker }
    dialog.className = 'report-source-preview'
    dialog.setAttribute('aria-label', '正文来源预览')
    const controller = new AbortController()
    const heading = document.createElement('header')
    const title = document.createElement('h2')
    title.append(createElement(Link2, { width: 18, height: 18 }), '正文来源')
    const close = document.createElement('button')
    close.type = 'button'
    close.className = 'source-preview-close'
    close.setAttribute('aria-label', '关闭来源预览')
    close.append(createElement(X, { width: 18, height: 18 }))
    close.onclick = () => dialog.close()
    heading.append(title, close)
    const subtitle = document.createElement('p')
    subtitle.className = 'source-preview-subtitle'
    subtitle.textContent = `${references.length} 个登记来源 · 正文与来源对照`
    const content = document.createElement('div')
    content.className = 'source-preview-content'
    const context = document.createElement('blockquote')
    context.className = 'source-preview-context'
    // 去掉不可见协议及上角标，只展示用户点击位置附近的正文。
    const nearby = marker.closest('td, th, p, h2, h3, h4, li')?.cloneNode(true) as HTMLElement | undefined
    nearby?.querySelectorAll('.report-protocol-marker').forEach(node => node.remove())
    context.textContent = nearby?.textContent?.trim().slice(0, 260) || `这处正文关联了 ${references.length} 个来源`
    const contextLabel = document.createElement('small')
    contextLabel.className = 'source-preview-context-label'
    contextLabel.textContent = '正在查看的正文引用'
    const loading = document.createElement('p')
    loading.className = 'source-preview-note'
    loading.textContent = '正在读取登记来源…'
    content.append(contextLabel, context, loading)
    dialog.append(heading, subtitle, content)
    marker.classList.add('source-marker-active')
    dialog.addEventListener('close', () => {
      controller.abort()
      if (current?.dialog === dialog) {
        current = null
        document.body.classList.remove('source-preview-is-open')
      }
      dialog.remove()
      // close 事件异步派发：同一标记已打开新预览时，不能撤掉新预览的高亮。
      if (current?.marker !== marker) marker.classList.remove('source-marker-active')
      if (!['selected', 'edited', 'replaced'].includes(dialog.returnValue) && marker.isConnected) marker.focus({ preventScroll: true })
    })
    document.body.append(dialog)
    document.addEventListener('input', event => {
      if ((event.target as HTMLElement)?.closest('.ProseMirror')) dialog.close('edited')
    }, { signal: controller.signal })
    if (window.innerWidth >= 1200) {
      document.body.classList.add('source-preview-is-open')
      dialog.show()
      document.addEventListener('keydown', event => {
        if (event.key === 'Escape') {
          event.preventDefault()
          event.stopPropagation()
          dialog.close()
        }
      }, { capture: true, signal: controller.signal })
    } else dialog.showModal()
    const open = (reference: Reference) => {
      dialog.close('selected')
      options.open(reference)
    }
    try {
      const sources = await options.sources()
      if (controller.signal.aborted) return
      loading.remove()
      for (const [index, reference] of references.entries()) {
        const card = document.createElement('section')
        card.className = 'source-preview-card'
        content.append(card)
        try {
          const label = document.createElement('h3')
          const subject = sources.subjects?.find(item => item.subjectId === reference.value)
          const factRef = subject?.factRefs[0]
          const fact = sources.facts?.find(item => item.analysisId === factRef?.analysisId && item.factId === factRef.factId)
          const citation = sources.citations?.find(item => item.citationId === reference.value)
          const dataset = sources.datasets?.find(item => item.datasetId === citation?.datasetId)
          const metric = sources.facts?.find(item => item.factKind === 'metric' && item.datasetIds.includes(dataset?.datasetId || ''))
          label.textContent = reference.kind === 'analysis' ? analysisLabel(reference.value, sources)
            : reference.kind === 'chart' ? '图表数据来源'
            : subject && subject.factRefs.length > 1 ? `组合事实 · ${subject.factRefs.length} 项依据`
              : fact?.name || metric?.name || citationLabel(reference.value, sources)
          const eyebrow = document.createElement('div')
          eyebrow.className = 'source-preview-eyebrow'
          eyebrow.textContent = `来源 ${String(index + 1).padStart(2, '0')} · ${subject ? '登记事实' : reference.kind === 'chart' ? '图表依据' : reference.kind === 'analysis' ? '分析依据' : '数据快照'}`
          card.append(eyebrow)
          card.append(label)
          if (dataset) {
            const scope = document.createElement('p')
            scope.className = 'source-preview-scope'
            scope.textContent = [dataset.periodRoles.map(role => ({ current: '本期', yoy: '同比基期', mom: '环比基期' }[role] || role)).join(' / '),
              [metric?.periodStart, metric?.periodEnd].filter(Boolean).join(' — '), metric?.unit].filter(Boolean).join(' · ')
            card.append(scope)
          }
          const validation = options.validation()
          const status = subject && validation ? sourceSubjectStatus(validation, subject) : undefined
          if (subject?.subjectKind === 'table_cell' && subject.factRefs.length === 1 && factRef?.factId) {
            const detail = await options.client.factDetail(factRef.analysisId, factRef.factId, controller.signal)
            if (controller.signal.aborted) return
            const entry = detail.entry as Record<string, unknown>
            const rowKey = subject.locator.rowKey || ''
            let value: unknown = fact?.displayValue
            let period = [fact?.periodStart, fact?.periodEnd].filter(Boolean).join(' — ')
            let unit = fact?.unit || ''
            if (rowKey.startsWith('period:')) {
              period = rowKey.slice(7)
              const values = (entry.periodValues as Array<{ period: string; value: unknown }> | undefined)?.filter(item => item.period === period) ?? []
              value = values.length === 1 ? values[0].value : undefined
            } else if (rowKey.startsWith('comparison:')) {
              const field = rowKey.split(':').at(-1)!
              value = ['currentTotal', 'baselineTotal', 'change', 'changeRate'].includes(field) ? entry[field] : undefined
              if (field === 'changeRate') unit = '%'
            }
            const comparison = document.createElement('div')
            comparison.className = 'source-preview-values'
            const currentValue = document.createElement('div')
            const registered = document.createElement('div')
            const valueLabel = document.createElement('small')
            valueLabel.textContent = '正文当前值'
            const currentText = document.createElement('strong')
            currentText.textContent = context.textContent
            currentValue.append(valueLabel, currentText)
            const frozenLabel = document.createElement('small')
            frozenLabel.textContent = '登记值'
            const frozen = document.createElement('strong')
            frozen.textContent = typeof value === 'number' ? `${value.toLocaleString('zh-CN', { maximumFractionDigits: 4 })}${unit}` : '暂无法确认'
            registered.append(frozenLabel, frozen)
            comparison.append(currentValue, registered)
            card.append(comparison)
            const caption = document.createElement('p')
            caption.className = 'source-preview-note'
            caption.textContent = [period, '仅核对登记数值，结论仍需人工确认'].filter(Boolean).join(' · ')
            card.append(caption)
            const badge = document.createElement('div')
            badge.className = `source-preview-status ${status?.status === 'valid' ? 'is-valid' : 'is-warning'}`
            badge.append(createElement(status?.status === 'valid' ? CircleCheck : TriangleAlert, { width: 14, height: 14 }),
              status?.status === 'valid' ? '登记数值一致' : '需复核 · 保留登记来源')
            card.append(badge)
          }
          const datasetIds = reference.kind === 'analysis'
            ? [...new Set(sources.facts?.filter(item => item.analysisId === reference.value).flatMap(item => item.datasetIds))]
            : reference.kind === 'chart'
              ? (await options.client.chartSource(reference.value, { limit: 1 }, controller.signal)).datasetIds
              : subject ? [...new Set(subject.factRefs.flatMap(ref => sources.facts?.find(item => item.analysisId === ref.analysisId && item.factId === ref.factId)?.datasetIds ?? []))]
                : [sources.citations?.find(item => item.citationId === reference.value)?.datasetId].filter((id): id is string => !!id)
          if (controller.signal.aborted) return
          for (const id of datasetIds ?? []) {
            const dataset = sources.datasets?.find(item => item.datasetId === id)
            if (!dataset) continue
            const source = document.createElement('div')
            source.className = 'source-preview-dataset'
            const text = document.createElement('div')
            const name = document.createElement('strong')
            name.textContent = datasetLabel(dataset, sources.datasets)
            name.title = name.textContent
            const metadata = document.createElement('small')
            const roles: Record<string, string> = { current: '本期', yoy: '同比基期', mom: '环比基期' }
            metadata.textContent = `${dataset.periodRoles.map(role => roles[role] || role).join(' / ')} · ${dataset.rowCount.toLocaleString('zh-CN')} 行`
            text.append(name, metadata)
            source.append(createElement(Database, { width: 17, height: 17 }), text)
            card.append(source)
            const details = document.createElement('details')
            details.className = 'source-preview-snapshot'
            const summary = document.createElement('summary')
            summary.textContent = '查看快照信息'
            const info = document.createElement('p')
            info.textContent = [`记录数：${dataset.rowCount.toLocaleString('zh-CN')} 行`, `数据说明：${name.textContent}`,
              `登记时间：${dataset.materializedAt ? new Date(dataset.materializedAt).toLocaleString('zh-CN') : '未登记'}`].join('\n')
            details.append(summary, info)
            card.append(details)
          }
          const button = document.createElement('button')
          button.type = 'button'
          button.className = 'source-preview-open'
          button.append('查看完整溯源', createElement(ArrowUpRight, { width: 15, height: 15 }))
          button.onclick = () => open(reference)
          card.append(button)
        } catch {
          if (controller.signal.aborted) return
          // 单个来源读取失败只降级该卡片，已展示的来源保持不变。
          const note = document.createElement('p')
          note.className = 'source-preview-note'
          note.textContent = '来源预览暂不可用，可以打开完整溯源。'
          const button = document.createElement('button')
          button.type = 'button'
          button.className = 'source-preview-open'
          button.textContent = '查看完整溯源'
          button.onclick = () => open(reference)
          card.replaceChildren(note, button)
        }
      }
    } catch {
      if (controller.signal.aborted) return
      loading.textContent = '来源预览暂不可用，可以打开完整溯源。'
      if (!loading.isConnected) content.append(loading)
      for (const reference of references) {
        const button = document.createElement('button')
        button.type = 'button'
        button.className = 'source-preview-open'
        button.textContent = '查看完整溯源'
        button.onclick = () => open(reference)
        content.append(button)
      }
    }
  }
}
