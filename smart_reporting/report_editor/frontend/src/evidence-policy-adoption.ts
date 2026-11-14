import { z } from 'zod'
import { ReportEditorApiError, type DataRefreshTask, type PolicyAdoptionOptions,
  type PolicyAdoptionPreview, type PolicyAdoptionRequest, type ReportEditorClient } from './api'
import { mountPolicyPreparation } from './policy-preparation'
import { deliveryFormats, deliveryLabels, deliveryLayoutDetails, deliveryUrl, deliveryValidation } from './delivery-presentation'

const identity = z.string().min(1).max(128)
const sha = z.string().regex(/^[a-f0-9]{64}$/)
const requestSchema = z.object({
  requestId: z.string().regex(/^[A-Za-z0-9_-]{1,128}$/), parentRevision: z.number().int().positive(),
  expectedSha256: sha, operation: z.literal('adopt_policy'), confirmation: z.object({
    requestId: identity, previewHash: sha,
    targetPolicyVersion: z.object({ policyId: identity, revision: z.number().int().positive() }),
    questionChoices: z.array(z.object({ questionId: identity,
      metricVersion: z.object({ metricId: identity, revision: z.number().int().positive() }).nullable(),
      reason: z.string().trim().min(1).max(2000),
    })).min(1).max(50),
  }),
}).refine(value => value.requestId === value.confirmation.requestId
  && new Set(value.confirmation.questionChoices.map(item => item.questionId)).size === value.confirmation.questionChoices.length)

/** 每次选择须明确确认；未知响应只读原请求，页面重开不自动提交。 */
export function mountPolicyAdoption(root: HTMLElement, options: {
  client: ReportEditorClient; storageKey: string; getDraft?: () => { markdown: string } | null
  saveMarkdown?: () => Promise<string>
}) {
  const key = options.storageKey + ':policy-adoption'
  let request: PolicyAdoptionRequest | null = null
  let choices: PolicyAdoptionOptions | null = null
  let preview: PolicyAdoptionPreview | null = null
  let draftHash = ''
  let selectionVersion = 0
  let taskId: string | null = null
  let resume = false
  try { request = requestSchema.parse(JSON.parse(sessionStorage.getItem(key) ?? 'null')) }
  catch { /* 不完整缓存不能触发提交。 */ }
  root.classList.add('evidence-policy-adoption')
  root.hidden = !options.getDraft
  const details = document.createElement('details')
  const summary = document.createElement('summary'); summary.textContent = '采用新业务口径'
  const intro = document.createElement('p')
  intro.textContent = '核对差异并逐题确认后，重新取数生成独立新报告。原报告保留；生成不代表业务批准。请先保存正文。'
  const message = document.createElement('p'); message.setAttribute('role', 'status')
  const selection = document.createElement('div')
  const confirmation = document.createElement('div')
  const links = document.createElement('div')
  const preparation = document.createElement('div')
  const recoveryKey = key + ':preparation-recovery'
  const preparationPanel = mountPolicyPreparation(preparation, options.client, recoveryKey)
  const button = (label: string, action: string) => {
    const node = document.createElement('button'); node.type = 'button'; node.className = 'ui-button'
    node.textContent = label; node.dataset.action = action; return node
  }
  const load = button('选择已发布口径', 'load')
  const next = button('加载更多口径', 'more'); next.hidden = true
  const status = button('读取新口径任务进度', 'status'); status.hidden = !request
  const delivery = button('读取已生成文件', 'delivery'); delivery.hidden = true
  const reset = button('重新核对新口径', 'reset'); reset.hidden = true
  details.append(summary, intro, load, selection, next, confirmation, status, delivery, reset, message, preparation, links)
  root.append(details)
  if (request) { load.hidden = true; details.open = true; message.textContent = '已保留原确认请求，请读取进度；不会自动提交。' }
  const work = async (selected: HTMLButtonElement, action: () => Promise<void>) => {
    selected.disabled = true; selected.setAttribute('aria-busy', 'true')
    try { await action() }
    catch (error) { message.textContent = error instanceof ReportEditorApiError ? error.message : '读取失败，请稍后显式重试。' }
    finally { selected.disabled = false; selected.removeAttribute('aria-busy') }
  }
  const save = async () => {
    try {
      if (!options.saveMarkdown) throw new Error('save unavailable')
      return sha.parse(await options.saveMarkdown())
    } catch {
      message.textContent = '保存尚未确认，未提交新口径请求。请先确认保存成功后重新预检。'
      return null
    }
  }
  const showTask = (task: DataRefreshTask) => {
    taskId = task.taskId; delivery.hidden = false
    preparationPanel.update(task)
    const labels: Record<string, string> = { pending: '任务已排队', running: '正在按新口径生成报告',
      completed: '后台已结束，完成状态未确认', error: '后台执行失败', cancelled: '后台执行已取消',
      paused: '后台执行已暂停', not_dispatched: '请求已登记，尚未确认派发' }
    message.textContent = task.status === 'completed' ? '新报告已生成；可读取文件和验收告警，业务批准尚未完成。'
      : (labels[task.execution?.status] ?? '执行状态未知') + '。不会自动重新取数；已生成文件可单独读取。'
    reset.hidden = task.status !== 'completed' && !['error', 'cancelled', 'paused'].includes(task.execution?.status)
  }
  const read = async () => {
    if (!request) return
    try {
      const current = resume ? await options.client.adoptPolicy(request)
        : await options.client.dataRefreshStatus(request.requestId)
      resume = false; status.textContent = '读取新口径任务进度'; showTask(current)
    } catch (error) {
      resume = false
      if (error instanceof ReportEditorApiError && error.status === 404 && error.code === 'source_missing') {
        resume = true; status.textContent = '确认提交原口径请求'
        message.textContent = '服务端未找到原请求。核对后可显式提交同一确认；不会自动提交。'
      } else if (error instanceof ReportEditorApiError && [409, 422].includes(error.status)) {
        message.textContent = error.message + ' 请重新核对口径和正文。'; reset.hidden = false
      } else message.textContent = '结果未知，请读取原请求进度；不会自动重新提交。'
    }
  }
  status.addEventListener('click', () => { void work(status, read) })
  const renderPreview = () => {
    if (!preview) return
    confirmation.replaceChildren()
    const frozen = preview
    const fields: Record<string, string> = { name: '名称', metric_versions: '指标版本', filters: '过滤范围',
      joins: '关联规则', valid_from: '生效日期', valid_to: '结束日期', evidence_release_id: '制度依据',
      readiness_policy: '数据充分性规则', decision_notes: '决策说明' }
    const heading = document.createElement('p')
    heading.textContent = `口径 ${frozen.preview.originalPolicyVersion.revision} → ${frozen.preview.targetPolicyVersion.revision}；变更：`
      + (frozen.preview.changedFields.map(field => fields[field] ?? field).join('、') || '无字段差异')
    confirmation.append(heading)
    for (const change of frozen.preview.changes) {
      const comparison = document.createElement('details')
      const title = document.createElement('summary'); title.textContent = fields[change.field] ?? change.field
      const before = document.createElement('p'); before.textContent = '原口径：' + change.before
      const after = document.createElement('p'); after.textContent = '新口径：' + change.after
      comparison.append(title, before, after); confirmation.append(comparison)
    }
    for (const issue of frozen.preview.issues) {
      const warning = document.createElement('p'); warning.textContent = issue.message; confirmation.append(warning)
    }
    const rows = frozen.preview.questions.map(question => {
      const fieldset = document.createElement('fieldset')
      const legend = document.createElement('legend'); legend.textContent = question.text
      const select = document.createElement('select'); select.setAttribute('aria-label', question.text + '：选择指标')
      select.add(new Option('请明确选择指标', ''))
      frozen.preview.metricOptions.forEach((metric, index) => select.add(new Option(
        `${metric.name} · v${metric.metricVersion.revision} · ${metric.unit}`, String(index))))
      select.add(new Option('暂无可用指标（保留未回答）', 'unavailable'))
      const reason = document.createElement('textarea'); reason.maxLength = 2000; reason.rows = 2
      reason.setAttribute('aria-label', question.text + '：选择原因'); reason.placeholder = '说明选择原因或缺项'
      fieldset.append(legend, select, reason); confirmation.append(fieldset)
      return { question, select, reason }
    })
    const submit = button('确认采用并生成新报告', 'submit'); submit.disabled = true
    const valid = () => { submit.disabled = rows.some(row => !row.select.value || !row.reason.value.trim()) || !rows.length }
    rows.forEach(row => { row.select.addEventListener('change', valid); row.reason.addEventListener('input', valid) })
    confirmation.append(submit)
    submit.addEventListener('click', () => { void work(submit, async () => {
      if (!choices || !options.getDraft) return
      const savedSha256 = await save()
      if (savedSha256 === null) return
      if (savedSha256 !== draftHash) {
        message.textContent = '正文已变化，请保存并重新预检。'; confirmation.replaceChildren(); return
      }
      if (preview !== frozen) return
      const requestId = crypto.randomUUID()
      const value: PolicyAdoptionRequest = { requestId, parentRevision: choices.parentRevision,
        expectedSha256: draftHash, operation: 'adopt_policy', confirmation: { requestId,
          targetPolicyVersion: frozen.preview.targetPolicyVersion, previewHash: frozen.previewHash,
          questionChoices: rows.map(row => ({ questionId: row.question.id, reason: row.reason.value.trim(),
            metricVersion: row.select.value === 'unavailable' ? null : frozen.preview.metricOptions[Number(row.select.value)]!.metricVersion })) } }
      try { sessionStorage.setItem(key, JSON.stringify(requestSchema.parse(value))) }
      catch { message.textContent = '无法保存请求身份，请启用会话存储后再提交。'; return }
      request = value; load.hidden = true; next.hidden = true; selection.replaceChildren(); confirmation.replaceChildren()
      status.hidden = false
      try { showTask(await options.client.adoptPolicy(value)) }
      catch (error) {
        message.textContent = error instanceof ReportEditorApiError && [409, 422].includes(error.status)
          ? error.message + ' 请重新核对。' : '结果未知，请读取原请求进度；不会自动重新提交。'
        reset.hidden = !(error instanceof ReportEditorApiError && [409, 422].includes(error.status))
      }
    }) })
  }
  const renderPolicies = () => {
    selectionVersion += 1
    selection.replaceChildren(); confirmation.replaceChildren(); preview = null
    const label = document.createElement('label'); label.textContent = '目标口径（最新发布版本）'
    const select = document.createElement('select'); select.add(new Option('请选择口径', ''))
    choices?.items.forEach((item, index) => select.add(new Option(`${item.name} · v${item.policyVersion.revision}`, String(index))))
    label.append(select)
    const inspect = button('核对变更与问题', 'preview'); inspect.disabled = true
    select.addEventListener('change', () => {
      selectionVersion += 1; preview = null
      inspect.disabled = select.value === ''; confirmation.replaceChildren()
    })
    inspect.addEventListener('click', () => { void work(inspect, async () => {
      const draft = options.getDraft?.(); const target = choices?.items[Number(select.value)]
      if (!draft || !target || !choices || select.value === '') return
      const version = selectionVersion
      confirmation.replaceChildren(); preview = null
      const savedSha256 = await save()
      if (savedSha256 === null || selectionVersion !== version || request) return
      draftHash = savedSha256
      const result = await options.client.previewPolicyAdoption({ parentRevision: choices.parentRevision,
        expectedSha256: draftHash, policyVersion: target.policyVersion })
      if (selectionVersion !== version || request) return
      preview = result; renderPreview(); message.textContent = '请逐题选择并说明原因；暂无可用指标会保留未回答状态。'
    }) })
    selection.append(label, inspect)
  }
  const loadChoices = async (more: boolean) => {
    const result = await options.client.policyAdoptionOptions(more ? choices?.nextCursor ?? undefined : undefined)
    choices = more && choices ? { ...result, items: [...choices.items, ...result.items] } : result
    renderPolicies(); next.hidden = !choices.nextCursor
    message.textContent = choices.items.length ? '请选择目标口径并核对差异。' : '当前没有同场景的其他可采用发布口径。'
  }
  load.addEventListener('click', () => { void work(load, () => loadChoices(false)) })
  next.addEventListener('click', () => { void work(next, () => loadChoices(true)) })
  reset.addEventListener('click', () => {
    try { sessionStorage.removeItem(recoveryKey); sessionStorage.removeItem(key) }
    catch { message.textContent = '无法清除请求缓存，请检查会话存储。'; return }
    request = null; taskId = null; resume = false; preview = null
    status.hidden = delivery.hidden = reset.hidden = true; load.hidden = false
    preparationPanel.reset()
    status.textContent = '读取新口径任务进度'; links.replaceChildren(); message.textContent = '请重新选择并核对，原任务及报告不会删除。'
  })
  delivery.addEventListener('click', () => { void work(delivery, async () => {
    if (!taskId) return
    const { delivery: output } = await options.client.dataRefreshDelivery(taskId)
    links.replaceChildren()
    let downloadable = false
    for (const format of [...deliveryFormats, 'editor'] as const) {
      const file = output[format]
      const value = format === 'editor' ? output.editor?.openUrl
        : file && typeof file === 'object' && 'downloadUrl' in file ? file.downloadUrl : null
      const url = deliveryUrl(value)
      if (!url) continue
      const link = document.createElement('a'); link.href = url; link.className = 'ui-button'
      if (format !== 'editor') downloadable = true
      link.textContent = format === 'editor' ? '打开新报告' : `下载 ${deliveryLabels[format]} · 修订 ${output.revision}`; links.append(link)
    }
    const validation = deliveryValidation(output.validation)
    message.textContent = !downloadable ? '未生成可下载文件。' + (validation.reasons || '请核对交付告警。')
      : validation.ok ? '文件已生成，尚未进行业务批准。'
      : '文件可下载，验收尚未通过：' + (validation.reasons || '请核对告警。')
    links.append(deliveryLayoutDetails(output.validation))
  }) })
}
