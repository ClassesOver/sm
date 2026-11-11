import { z } from 'zod'
import { ReportEditorApiError, type DataRefreshTask, type PolicyPreparation,
  type PolicyRecovery, type ReportEditorClient } from './api'

const cachedSchema = z.object({
  taskId: z.string().min(1), recoveryId: z.string().min(1),
  confirmation: z.object({ kind: z.enum(['analysis', 'document']), expectedStateVersion: z.number().int().nonnegative(),
    identity: z.object({ path: z.string().min(1), size: z.number().int().nonnegative(), sha256: z.string().regex(/^[a-f0-9]{64}$/) }) }),
})

/** 只读核对与明确续跑分开；缓存固定身份后才允许提交，未知结果不自动重发。 */
export function mountPolicyPreparation(root: HTMLElement, client: ReportEditorClient, storageKey: string) {
  let task: DataRefreshTask | null = null
  let cached: z.infer<typeof cachedSchema> | null = null
  let inspected: PolicyPreparation | null = null
  let busy = false
  let missingRecovery = false
  try { cached = cachedSchema.parse(JSON.parse(sessionStorage.getItem(storageKey) ?? 'null')) }
  catch { /* 损坏缓存不能授权继续执行。 */ }
  const message = document.createElement('p'); message.setAttribute('role', 'status')
  const stages = document.createElement('div')
  const actions = document.createElement('div')
  const button = (label: string, action: string, run: () => Promise<void>) => {
    const node = document.createElement('button'); node.type = 'button'; node.className = 'ui-button'
    node.textContent = label; node.dataset.action = action
    node.addEventListener('click', () => { void work(run, action) }); actions.append(node); return node
  }
  const work = async (run: () => Promise<void>, action: string) => {
    if (busy) return
    busy = true; root.setAttribute('aria-busy', 'true'); renderActions()
    try { await run() }
    catch (error) { message.textContent = error instanceof ReportEditorApiError ? error.message : '读取失败，请显式重试；不会自动提交。' }
    finally {
      busy = false; root.removeAttribute('aria-busy'); renderActions()
      const target = actions.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)
        ?? actions.querySelector<HTMLButtonElement>('[data-action="recovery-read"]')
        ?? actions.querySelector<HTMLButtonElement>('button')
      target?.focus()
    }
  }
  const showRecovery = (result: PolicyRecovery) => {
    if (result.taskId !== task?.taskId || result.recoveryId !== cached?.recoveryId) {
      message.textContent = '续跑身份不一致，请保留原任务供核对。'; return
    }
    const labels: Record<string, string> = { pending: '续跑已排队', running: '正在继续生成报告',
      error: '续跑执行失败', cancelled: '续跑已取消', paused: '续跑已暂停' }
    message.textContent = task.status === 'completed' || result.deliveryStatus === 'completed'
      ? '新报告已生成，请读取已生成文件及验收告警；尚未进行业务批准。'
      : result.status === 'completed' ? '后台已结束，报告交付尚未确认。请读取已生成文件及原任务状态；不会自动重跑。'
        : (labels[result.status] ?? '续跑状态未知') + '。已生成文件可单独读取；不会自动重复取数。'
  }
  const readRecovery = async () => {
    if (!task || !cached) return
    missingRecovery = false
    try { showRecovery(await client.policyRecovery(task.taskId, cached.recoveryId)) }
    catch (error) {
      missingRecovery = error instanceof ReportEditorApiError && error.status === 404 && error.code === 'source_missing'
      message.textContent = missingRecovery
        ? '未找到原续跑票据。核对后可明确提交原确认；不会自动创建执行。'
        : '续跑结果未知，请继续读取同一票据；不会自动重新提交。'
    }
  }
  const submitCached = async () => {
    if (!cached) return
    missingRecovery = false; inspected = null
    try { showRecovery(await client.resumePolicyPreparation(cached.taskId, cached.confirmation)) }
    catch (error) {
      message.textContent = error instanceof ReportEditorApiError && [409, 422].includes(error.status)
        ? error.message + ' 请重新读取准备状态核对，原确认身份已保留。'
        : '续跑结果未知，请读取同一票据与准备状态；不会自动重新提交。'
    }
  }
  const renderActions = () => {
    actions.replaceChildren()
    button('读取准备状态', 'preparation-read', async () => {
      if (!task) return
      inspected = null
      const result = await client.policyPreparation(task.taskId)
      if (result.taskId !== task.taskId) { message.textContent = '准备状态与原任务不一致。'; return }
      inspected = result; stages.replaceChildren()
      const labels = { not_generated: '尚未生成', registered: '已登记', awaiting_confirmation: '文件已生成，等待确认',
        unverifiable: '无法核验', not_applicable: '本报告不适用' }
      for (const kind of ['analysis', 'document'] as const) {
        const stage = result[kind]; const row = document.createElement('p')
        row.textContent = `${kind === 'analysis' ? '分析准备' : '文档准备'}：${labels[stage.status]}`
          + (stage.message ? `；${stage.message}` : '')
        stages.append(row)
        if (stage.identity) {
          const details = document.createElement('details'); const summary = document.createElement('summary')
          summary.textContent = '查看文件核对信息'
          const identity = document.createElement('p')
          identity.textContent = `${stage.identity.path} · ${stage.identity.size} 字节 · SHA-256 ${stage.identity.sha256}`
          details.append(summary, identity); stages.append(details)
        }
      }
      message.textContent = canResume() ? '请核对已生成的准备文件。明确确认后继续生成独立新报告，原报告保留。'
        : '原任务尚未确认结束或已有交付终态；当前只读取准备状态。'
    })
    if (cached) button('读取续跑进度', 'recovery-read', readRecovery)
    if (cached && missingRecovery && canResume()) button('确认提交原续跑', 'recovery-resubmit', submitCached)
    if (cached) {
      const previous = document.createElement('details'); const title = document.createElement('summary')
      title.textContent = '上次确认的文件'
      const info = document.createElement('p'); const { identity, expectedStateVersion } = cached.confirmation
      info.textContent = `${identity.path} · ${identity.size} 字节 · SHA-256 ${identity.sha256} · 状态版本 ${expectedStateVersion}`
      previous.append(title, info); actions.append(previous)
    }
    if (cached && missingRecovery && inspected && canResume()) {
      button('按当前核对结果重新确认', 'recovery-recheck', async () => {
        try { sessionStorage.removeItem(storageKey) }
        catch { message.textContent = '无法更新恢复缓存，请检查会话存储。'; return }
        cached = null; missingRecovery = false
        message.textContent = '已清除旧确认，请核对当前准备文件，再明确确认继续；本操作未派发。'
      })
    }
    if (inspected && !cached && canResume()) {
      // 优先确认尚未登记的阶段；已登记文件可显式继续，服务端仍核对独立队列终态。
      const kind = (['document', 'analysis'] as const).find(value => inspected![value].status === 'awaiting_confirmation')
        ?? (['document', 'analysis'] as const).find(value => inspected![value].status === 'registered')
      const stage = kind && inspected[kind]
      if (kind && stage?.identity && stage.recoveryId) {
        const confirmation = { kind, identity: stage.identity, expectedStateVersion: inspected.stateVersion }
        const value = { taskId: task!.taskId, recoveryId: stage.recoveryId, confirmation }
        button(`确认${kind === 'analysis' ? '分析' : '文档'}准备并继续`, 'preparation-resume', async () => {
          try { sessionStorage.setItem(storageKey, JSON.stringify(cachedSchema.parse(value))) }
          catch { message.textContent = '无法保存恢复身份，请启用会话存储后再继续。'; return }
          cached = value
          await submitCached()
        })
      }
    }
    actions.querySelectorAll('button').forEach(node => { node.disabled = busy })
  }
  const canResume = () => task?.status === 'pending' && ['completed', 'error', 'cancelled'].includes(task.execution.status)
  root.classList.add('evidence-policy-preparation')
  root.append(stages, message, actions); root.hidden = true
  const update = (current: DataRefreshTask) => {
    if (task?.taskId !== current.taskId) inspected = null
    task = current; root.hidden = false
    if (current.status === 'completed') message.textContent = '新报告已生成，请读取已生成文件及验收告警；尚未进行业务批准。'
    if (cached && cached.taskId !== current.taskId) {
      message.textContent = '恢复缓存属于其他任务，请保留原请求供核对。'; actions.replaceChildren(); return
    }
    renderActions()
  }
  return { update, reset: () => {
    cached = null; task = null; inspected = null; missingRecovery = false
    root.hidden = true; stages.replaceChildren(); actions.replaceChildren(); message.textContent = ''
  } }
}
