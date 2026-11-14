// 仅展示生成回执白名单，不把来源说明提升为完整排版验收。
const contentSources = { frozen_revision_preferences: '沿用冻结偏好', editor_design: '编辑器明确修改', editor_reset: '编辑器重置', unavailable: '待核验' }
const signatureSources = { frozen_revision_preferences: '当前修订冻结偏好', unavailable: '待核验' }
const placements = { declared_template_slot: '模板声明位置', semantic_template_slot: '语义识别位置（模型判断）', body_end: '正文末尾回退', unverified: '待核验' }
const layoutSources = { template: '沿用模板排版', generated_fallback: '生成器回退排版', unverified: '待核验' }
const samples = { replaced: '声明样例已替换', cleared: '声明样例已清除', preserved_for_review: '声明样例保留待复核', no_declared_slot: '无声明位置', not_assessed: '未评估' }
const semanticSamples = { ...samples, replaced: '语义识别样例已替换', cleared: '语义识别样例已清除', preserved_for_review: '语义识别样例保留待复核', no_declared_slot: '无可确认语义样例' }
const signatureReadbacks = { passed: '落款内容回读通过', failed: '落款内容回读未通过', unverified: '落款内容待核验' }
const bodyReadbacks = { structure_verified: '原生结构已核验', sample_only: '文字抽样，未核验完整原生结构', unverified: '正文待核验' }
type ObjectValue = Record<string, unknown>
const object = (value: unknown): value is ObjectValue => value !== null && typeof value === 'object' && !Array.isArray(value)
const digest = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value)
const identity = (value: unknown): value is ObjectValue => object(value) && Number.isSafeInteger(value.size) && (value.size as number) >= 0 && digest(value.sha256)
const known = (value: unknown, labels: object): value is string => typeof value === 'string' && Object.hasOwn(labels, value)
const label = (value: unknown, labels: Record<string, string>) => known(value, labels) ? labels[value] : '待核验'
function date(value: unknown) {
  if (value === null) return true
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}
function validEntry(value: unknown) {
  return object(value) && identity(value.artifact) && value.layoutSource === 'uploaded_template'
    && known(value.signatureSource, signatureSources) && date(value.generatedDate)
    && known(value.dateFormatSource, contentSources) && known(value.descriptionSource, contentSources)
    && known(value.placement, placements) && known(value.signatureLayoutSource, layoutSources)
    && known(value.templateSampleStatus, samples) && known(value.signatureReadback, signatureReadbacks)
    && known(value.bodyReadback, bodyReadbacks)
}
function valid(value: unknown): value is ObjectValue & { template: ObjectValue; formats: ObjectValue } {
  return object(value) && value.version === 1 && identity(value.template)
    && typeof value.template.filename === 'string' && value.template.filename.trim().length > 0
    && !/[/\\\x00-\x1f\x7f]/.test(value.template.filename)
    && digest(value.contentSha256) && value.layoutValidation === 'unverified' && value.undeclaredSamples === 'not_assessed'
    && (value.previewSourceFormat === undefined || value.previewSourceFormat === 'word')
    && object(value.formats) && Object.keys(value.formats).length > 0
    && Object.keys(value.formats).every(format => ['word', 'pdf'].includes(format) && validEntry((value.formats as ObjectValue)[format]))
}
export function renderEditorLayoutProvenance(host: HTMLElement, value: unknown) {
  host.replaceChildren()
  host.hidden = value === undefined
  if (value === undefined) return
  const details = document.createElement('details')
  details.className = 'editor-layout-provenance'
  details.style.overflowWrap = 'anywhere'
  const summary = document.createElement('summary')
  summary.textContent = '排版来源（生成回执）'
  details.append(summary)
  const line = (text: string) => { const paragraph = document.createElement('p'); paragraph.textContent = text; details.append(paragraph) }
  if (!valid(value)) {
    line('来源摘要待复核；不影响已生成文件的预览与下载。')
    host.append(details)
    return
  }
  line('来源说明不代表完整验收通过。署名及生成日期的来源以各格式回执为准；已确认的冻结值不随当前默认变化，未取得的来源标为待核验。日期格式与附加说明的明确修改单独列明。')
  line(`模板：${value.template.filename} · ${value.template.size} B · SHA-256：${value.template.sha256}`)
  line(`正文 SHA-256：${value.contentSha256}`)
  if (value.previewSourceFormat === 'word') line('此 PDF 预览由文字文档转换，不代表 PDF 原生结构已核验。')
  for (const format of ['word', 'pdf']) {
    const entry = value.formats[format]
    if (!object(entry) || !object(entry.artifact)) continue
    const heading = document.createElement('h3')
    heading.textContent = format === 'word' ? '文字文档' : 'PDF'
    details.append(heading)
    line(`文件：${entry.artifact.size} B · SHA-256：${entry.artifact.sha256}`)
    line(`布局来源：上传模板；署名来源：${label(entry.signatureSource, signatureSources)}；冻结生成日期：${entry.generatedDate ?? '待核验'}`)
    line(`日期格式：${label(entry.dateFormatSource, contentSources)}；附加说明：${label(entry.descriptionSource, contentSources)}`)
    line(`生成回执位置：${label(entry.placement, placements)}；落款排版：${label(entry.signatureLayoutSource, layoutSources)}；${label(entry.templateSampleStatus, entry.placement === 'semantic_template_slot' ? semanticSamples : samples)}`)
    line(`${label(entry.signatureReadback, signatureReadbacks)}；正文：${label(entry.bodyReadback, bodyReadbacks)}`)
  }
  line('完整布局未验证；未声明样例未评估。')
  host.append(details)
}
