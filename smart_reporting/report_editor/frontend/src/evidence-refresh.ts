import { ReportEditorApiError, type DataRefreshRequest, type DataRefreshTask, type ReportEditorClient } from './api'
import { deliveryFormats, deliveryLabels, deliveryLayoutDetails, deliveryUrl, deliveryValidation } from './delivery-presentation'

/** 只缓存请求身份；未知响应先读回，任何页面重开均不重提取数。 */
export function mountDataRefresh(root: HTMLElement, options: {
  client: ReportEditorClient; storageKey: string; getDraft?: () => { markdown: string } | null
  saveMarkdown?: () => Promise<string>
}) {
  const key = options.storageKey + ':data-refresh'
  root.setAttribute('role', 'group')
  root.setAttribute('aria-label', '数据刷新')
  let request: DataRefreshRequest | null = null
  let taskId: string | null = null
  let capability: { available: boolean; parentRevision: number } | undefined
  let confirming = false
  let resume = false
  try {
    const saved = JSON.parse(sessionStorage.getItem(key) ?? 'null')
    if (saved?.operation === 'refresh_data' && /^[A-Za-z0-9_-]{1,128}$/.test(saved.requestId)
      && Number.isInteger(saved.parentRevision) && saved.parentRevision > 0 && /^[a-f0-9]{64}$/.test(saved.expectedSha256)) {
      request = { requestId: saved.requestId, parentRevision: saved.parentRevision,
        expectedSha256: saved.expectedSha256, operation: 'refresh_data' }
    }
  } catch { /* 缓存不可读不影响服务端持久任务。 */ }
  const button = document.createElement('button')
  button.type = 'button'; button.className = 'ui-button'
  const message = document.createElement('p')
  message.setAttribute('role', 'status')
  const deliveryButton = document.createElement('button')
  deliveryButton.type = 'button'; deliveryButton.className = 'ui-button'
  deliveryButton.textContent = '读取已生成文件'; deliveryButton.hidden = true
  const links = document.createElement('div')
  root.append(button, message, deliveryButton, links)
  const update = (value: typeof capability | null = capability ?? null) => {
    capability = value ?? undefined
    root.hidden = !options.getDraft || !(request || capability?.available)
    button.textContent = request ? (resume ? '确认提交原刷新请求' : '读取刷新进度')
      : confirming ? '确认刷新并生成新修订' : '按原口径刷新数据'
  }
  const showTask = (task: DataRefreshTask) => {
    taskId = task.taskId
    deliveryButton.hidden = false
    if (task.status === 'completed') message.textContent = '新修订已生成；尚未进行业务批准。可读取文件及验收告警。'
    else {
      const labels: Record<string, string> = {
        pending: '刷新已排队', running: '正在刷新数据并生成新修订', completed: '后台已结束，完成状态未确认',
        error: '后台执行失败', cancelled: '后台执行已取消', paused: '后台执行已暂停',
        not_dispatched: '请求已登记，尚未确认后台派发', unavailable: '后台状态暂不可读取', unknown: '后台执行状态未知',
      }
      message.textContent = (labels[task.execution?.status] ?? '刷新状态未知')
        + '。请读取进度；不会自动重新取数。已生成文件可单独读取。'
    }
  }
  const busy = (selected: HTMLButtonElement, value: boolean) => {
    selected.disabled = value
    selected.setAttribute('aria-busy', String(value))
  }
  button.addEventListener('click', async () => {
    if (!request && !confirming) {
      confirming = true
      message.textContent = '按本报告原口径和范围重新取数，生成新修订；原报告保持不变。将先保存正文。此操作不采用新口径，也不代表业务批准。'
      update(); return
    }
    busy(button, true)
    try {
      if (request) {
        const submitOriginal = resume
        resume = false
        showTask(await (submitOriginal ? options.client.refreshData(request)
          : options.client.dataRefreshStatus(request.requestId)))
      }
      else {
        const draft = options.getDraft?.()
        if (!draft || !capability?.available) return
        // 保存失败或响应未知时没有可信保存回执，不能登记刷新身份。
        if (!options.saveMarkdown) throw new Error('save unavailable')
        const savedSha256 = await options.saveMarkdown()
        if (!/^[a-f0-9]{64}$/.test(savedSha256)) throw new Error('invalid save receipt')
        request = { requestId: crypto.randomUUID(), parentRevision: capability.parentRevision,
          expectedSha256: savedSha256, operation: 'refresh_data' }
        // 无法保存未知响应的恢复身份时不发起有副作用的请求。
        try { sessionStorage.setItem(key, JSON.stringify(request)) }
        catch { request = null; message.textContent = '无法保存刷新请求身份，请启用会话存储后重试。'; return }
        showTask(await options.client.refreshData(request))
      }
    } catch (error) {
      if (error instanceof ReportEditorApiError && error.status === 409) {
        request = null; confirming = false; sessionStorage.removeItem(key)
        message.textContent = '正文或修订已变化，请先保存并核对后重新发起。'
      } else if (error instanceof ReportEditorApiError && error.status === 404 && error.code === 'source_missing') {
        resume = true
        message.textContent = '服务端未找到原请求。请核对已保存正文，再显式确认提交原请求；不会自动重新取数。'
      } else message.textContent = request ? '刷新结果未知，请读取原请求进度；不会自动重新提交。'
        : '保存尚未确认，未提交刷新请求。请先确认保存成功后重试。'
    } finally { busy(button, false); update() }
  })
  deliveryButton.addEventListener('click', async () => {
    if (!taskId) return
    busy(deliveryButton, true)
    try {
      const { delivery } = await options.client.dataRefreshDelivery(taskId)
      links.replaceChildren()
      let downloadable = false
      for (const format of deliveryFormats) {
        const file = delivery[format]
        const url = deliveryUrl(file?.downloadUrl)
        if (!url) continue
        const link = document.createElement('a')
        link.href = url; link.textContent = `下载 ${deliveryLabels[format]} · 修订 ${delivery.revision}`
        link.className = 'ui-button'; links.append(link); downloadable = true
      }
      if (delivery.editor?.openUrl) {
        const url = deliveryUrl(delivery.editor.openUrl)
        if (url) {
          const link = document.createElement('a')
          link.href = url; link.textContent = '打开新修订'; link.className = 'ui-button'; links.append(link)
        }
      }
      const validation = deliveryValidation(delivery.validation)
      message.textContent = !downloadable ? '未生成可下载文件。' + (validation.reasons || '请核对交付告警。')
        : validation.ok ? '文件已生成，业务批准尚未完成。'
        : '文件可下载，验收尚未通过：' + (validation.reasons || '请核对交付告警。')
      links.append(deliveryLayoutDetails(delivery.validation))
    } catch { message.textContent = '暂未读到可核验文件，请先读取刷新进度；不会重新生成。' }
    finally { busy(deliveryButton, false) }
  })
  update()
  return { update }
}
