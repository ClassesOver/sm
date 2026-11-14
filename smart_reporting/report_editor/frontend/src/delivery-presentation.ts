import type { ExportResult } from './api'

/** 交付区使用业务名称；扩展名只在需要时作为格式帮助。 */
export const deliveryLabels = {
  pdf: 'PDF', word: '文字文档', pptx: '演示文稿', xlsx: '电子表格', md: '文本报告',
} as const

export const deliveryFormats = ['pdf', 'word', 'pptx', 'xlsx', 'md'] as const

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : {}
}

/** 来源或告警损坏不能中断其他已生成文件的展示。 */
export function deliveryValidation(value: unknown) {
  const raw = record(value)
  const issues = Array.isArray(raw.issues) ? raw.issues : []
  return {
    ok: raw.ok === true && Array.isArray(raw.issues),
    reasons: issues.map(issue => {
      const item = record(issue)
      return typeof item.message === 'string' && item.message.trim() ? item.message
        : typeof item.code === 'string' ? item.code : ''
    }).filter(Boolean).join('；'),
  }
}

export function deliveryUrl(value: unknown): string | null {
  if (typeof value !== 'string' || !value.trim()) return null
  try {
    const url = new URL(value, location.href)
    return ['http:', 'https:'].includes(url.protocol) ? url.href : null
  } catch { return null }
}

/** 只翻译后端已返回的来源枚举；未知值不推断为模板或全局偏好。 */
export function deliveryLayoutDetails(validation: ExportResult['validation']): HTMLDetailsElement {
  const readback = record(record(validation).readback)
  const template = record(readback.templateLayout)
  const signature = record(readback.signature)
  const details = document.createElement('details')
  details.className = 'delivery-layout-provenance'
  const summary = document.createElement('summary')
  summary.textContent = '排版来源'; details.append(summary)
  const line = (text: string) => {
    const paragraph = document.createElement('p')
    paragraph.textContent = text; details.append(paragraph)
  }
  const unknown = '未知或未核验'
  line('模板布局：' + (template.source === 'uploaded_template' ? '上传模板' : unknown)
    + (template.source === 'uploaded_template' && readback.ok !== true ? '（来源回读未核验）' : '') + '。')
  if (template.source === 'uploaded_template') {
    line(template.scope === 'outside_declared_binding_targets'
      ? '声明绑定目标之外保留模板布局。' : '模板布局范围：' + unknown + '。')
    line(template.globalDefaults === 'not_applied'
      ? '全局排版默认未套用到模板布局。' : '全局排版默认套用状态：' + unknown + '。')
    line(template.layoutValidation === 'unverified' ? '模板布局尚未核验。' : '模板布局核验状态：' + unknown + '。')
  }
  const frozen = signature.source === 'frozen_run_preferences'
  const complete = typeof signature.configurationHash === 'string' && /^[a-f0-9]{64}$/.test(signature.configurationHash)
    && typeof signature.generatedDate === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(signature.generatedDate)
  const recorded = frozen && complete && readback.ok === true && signature.bindingStatus === 'recorded'
  line('落款内容：' + (frozen ? '本次运行冻结偏好' + (recorded ? '' : '（来源回执未核验）') : unknown) + '。')
  const placements: Record<string, string> = {
    declared_template_slot: '模板声明的落款槽', semantic_template_slot: '语义识别位置（模型判断）', body_end: '正文末尾',
    declared_named_range: '模板声明的命名区域', signature_sheet: '独立说明页',
    declared_textbox: '模板声明的文本框', ending_slide: '结尾落款页',
  }
  const position = recorded && typeof signature.placement === 'string' && Object.hasOwn(placements, signature.placement)
    ? placements[signature.placement] : undefined
  line('落款位置：' + (position || unknown) + '。')
  if (position) {
    line('落款布局：' + (signature.layoutSource === 'template' ? '模板原有布局'
      : signature.layoutSource === 'generated_fallback' ? '生成的回退布局' : unknown) + '。')
    if (typeof signature.sheetName === 'string' && signature.sheetName) {
      line('工作表：' + signature.sheetName + (typeof signature.cellRange === 'string' && signature.cellRange
        ? ' · 区域：' + signature.cellRange : '') + '。')
    }
    if (typeof signature.slideNumber === 'number' && Number.isInteger(signature.slideNumber) && signature.slideNumber > 0) {
      line('演示文稿第 ' + signature.slideNumber + ' 页。')
    }
    const samples: Record<string, string> = {
      replaced: '声明样例已替换', cleared: '声明样例已清除',
      preserved_for_review: '声明样例保留待核对', no_declared_slot: '未声明落款槽',
    }
    const sampleLabels = signature.placement === 'semantic_template_slot'
      ? { ...samples, replaced: '语义识别样例已替换', cleared: '语义识别样例已清除', preserved_for_review: '语义识别样例保留待核对', no_declared_slot: '无可确认语义样例' } : samples
    line('模板样例：' + (typeof signature.templateSampleStatus === 'string' && Object.hasOwn(sampleLabels, signature.templateSampleStatus)
      ? sampleLabels[signature.templateSampleStatus] : unknown) + '。')
  }
  if (signature.undeclaredSamples === 'not_assessed') line('未声明样例尚未评估。')
  line('来源记录不代表验收通过；请同时核对交付告警及实际文件。')
  return details
}
