import type { DeliveryFormat, ExportResult } from './api'

export const exportFormats = ['pdf', 'word', 'md', 'xlsx', 'pptx'] as const
export type ExportFormat = typeof exportFormats[number]
export const exportLabels: Record<ExportFormat, string> = {
  pdf: 'PDF', word: 'Word', md: 'MD', xlsx: 'XLSX', pptx: 'PPTX',
}

export function configureExportButtons(
  primary: HTMLButtonElement, secondary: HTMLButtonElement, target: DeliveryFormat = 'document',
): ExportFormat {
  const format = target === 'document' ? 'pdf' : target === 'docx' ? 'word' : target
  for (const [button, key] of [[primary, format], [secondary, 'word']] as const) {
    const label = `导出 ${exportLabels[key]}`
    const span = button.querySelector('span')
    if (span) span.textContent = label
    else button.textContent = label
    button.setAttribute('aria-label', label)
    button.title = label
  }
  primary.hidden = false
  secondary.hidden = target !== 'document'
  return format
}

/** 仅要求本次目标格式；没有目标字段的旧回执按实际可下载格式展示。 */
export function exportOutcome(result: ExportResult, target?: DeliveryFormat, preferred: ExportFormat = 'pdf') {
  const available = exportFormats.filter(format => Boolean(result[format]?.downloadUrl))
  const delivery = result.deliveryFormat ?? target
  const expected = delivery === 'document' ? ['pdf', 'word']
    : delivery ? [delivery === 'docx' ? 'word' : delivery] : available
  const partial = expected.some(format => !available.includes(format as ExportFormat))
  const format = available.includes(preferred) ? preferred : available[0] ?? preferred
  const failed = !available.length || result.validation?.ok === false || partial
  return {
    available: available.length > 0, failed, format,
    title: !available.length ? '未生成可下载文件'
      : partial ? '部分格式已生成 · 验收未通过'
      : `${exportLabels[format]} ${failed ? '已生成 · 验收未通过' : '导出完成'}`,
  }
}
