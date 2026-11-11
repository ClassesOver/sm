import { z } from 'zod'
import { ReportEditorApiError, type ReportEditorClient, type ReportIssueRecord, type ReportIssueSubmission } from './api'

const submissionSchema = z.object({ issueId: z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/),
  objectRefs: z.array(z.string().min(1).max(128)).min(1).max(50),
  category: z.enum(['calculation', 'policy', 'data', 'citation', 'interpretation']),
  description: z.string().trim().min(1).max(10000) })
const labels = { open: '待处理', needs_evidence: '待补充证据', accepted: '已采纳，待修复', rejected: '未采纳', resolved: '已解决' }

/** 反馈只绑定登记对象；未知提交结果只读原身份，页面重开不自动发送。 */
export function mountReportIssues(root: HTMLElement, options: {
  client: ReportEditorClient; storageKey: string
  loadObjects: () => Promise<{ id: string; label: string }[]>
}) {
  const key = options.storageKey + ':report-issue'
  let cached: ReportIssueSubmission | null = null
  let missing = false
  let busy = false
  let cursor: string | null = null
  let items: ReportIssueRecord[] = []
  let objectLabels = new Map<string, string>()
  const loadObjects = async () => {
    const objects = await options.loadObjects()
    objectLabels = new Map(objects.map(object => [object.id, object.label]))
    return objects
  }
  const labelFor = (id: string) => objectLabels.get(id) ?? '已登记报告对象（名称暂不可读）'
  try { cached = submissionSchema.parse(JSON.parse(sessionStorage.getItem(key) ?? 'null')) }
  catch { /* 不完整缓存不能用于重新提交。 */ }
  root.classList.add('evidence-policy-adoption', 'evidence-report-issues')
  const details = document.createElement('details'); const summary = document.createElement('summary')
  summary.textContent = '反馈报告问题'
  const intro = document.createElement('p'); intro.textContent = '指出计算、口径、数据或引用问题。反馈和采纳不代表报告已修复；已生成文件仍可下载。'
  const message = document.createElement('p'); message.setAttribute('role', 'status')
  const actions = document.createElement('div'); const form = document.createElement('div'); const list = document.createElement('div')
  const button = (label: string, action: string, parent: HTMLElement, run: () => Promise<void>) => {
    const node = document.createElement('button'); node.type = 'button'; node.className = 'ui-button'
    node.textContent = label; node.dataset.action = action; node.disabled = busy
    node.addEventListener('click', () => { void work(run, action) }); parent.append(node); return node
  }
  const work = async (run: () => Promise<void>, action: string) => {
    if (busy) return
    busy = true; root.setAttribute('aria-busy', 'true')
    root.querySelectorAll('button').forEach(node => { node.disabled = true })
    try { await run() }
    catch (error) { message.textContent = error instanceof ReportEditorApiError ? error.message : '读取失败，请显式重试；不会自动提交。' }
    finally {
      busy = false; root.removeAttribute('aria-busy'); renderActions()
      form.querySelectorAll('button').forEach(node => { node.disabled = false })
      const focus = root.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)
        ?? root.querySelector<HTMLButtonElement>('[data-action="issue-read-original"]')
      focus?.focus()
    }
  }
  const renderItems = () => {
    list.replaceChildren()
    for (const item of items) {
      const card = document.createElement('article'); const title = document.createElement('h3')
      title.textContent = labels[item.review.status] ?? '状态未知'
      const description = document.createElement('p'); description.textContent = item.review.description
      const objects = document.createElement('p'); objects.textContent = `关联对象：${item.review.objectRefs.map(labelFor).join('、')}`
      card.append(title, description, objects)
      if (item.review.decisionReason) {
        const reason = document.createElement('p'); reason.textContent = '裁定理由：' + item.review.decisionReason; card.append(reason)
      }
      if (item.proposal) {
        const change = document.createElement('p'); change.textContent = '候选改动：' + item.proposal.changeSummary
        const counterexample = document.createElement('p'); counterexample.textContent = '核对反例：' + item.proposal.counterexample
        card.append(change, counterexample)
      }
      if (item.review.status === 'resolved') {
        const disposition = document.createElement('p')
        disposition.textContent = item.review.notRecalculatedReason
          ? '本次不重算：' + item.review.notRecalculatedReason
          : item.review.newReportRevision ? '已生成新报告并核对纠错事实。' : '请查阅关闭裁定。'
        const original = document.createElement('p')
        original.textContent = '原报告保持不变；问题关闭不代表整份报告验收通过。'
        card.append(disposition, original)
        if (item.review.regressionCaseIds?.length) {
          const cases = document.createElement('p')
          cases.textContent = '回归案例：' + item.review.regressionCaseIds.join('、')
          card.append(cases)
        }
        if (item.review.newReportRevision) {
          const revision = document.createElement('details')
          const label = document.createElement('summary')
          label.textContent = '新报告修订标识'
          revision.append(label, item.review.newReportRevision)
          card.append(revision)
        }
      }
      if (item.review.correctedVersions?.length) {
        const fixes = document.createElement('details'); const heading = document.createElement('summary')
        heading.textContent = item.review.status === 'resolved' ? '关闭关联的正式修复版本' : '已关联正式修复版本，仍待回归与重算核验'; fixes.append(heading)
        const names: Record<string, string> = { metric: '指标', statistical_policy: '统计口径', document: '原件修订', evidence_release: '证据集合' }
        for (const ref of item.review.correctedVersions) {
          const value = document.createElement('p')
          value.textContent = `${names[ref.assetType] ?? '修复对象'} · ${ref.assetId}${ref.revision === null ? '' : ` · 修订 ${ref.revision}`}`
          fixes.append(value)
        }
        card.append(fixes)
      }
      const identity = document.createElement('details'); const heading = document.createElement('summary')
      heading.textContent = '查看问题登记信息'
      const value = document.createElement('p'); value.textContent = `${item.review.issueId} · 记录版本 ${item.version} · ${item.review.objectRefs.join('、')}`
      identity.append(heading, value); card.append(identity)
      list.append(card)
    }
  }
  const submit = async () => {
    if (!cached) return
    missing = false
    try {
      const result = await options.client.submitReportIssue(cached)
      if (result.review.issueId !== cached.issueId) { message.textContent = '反馈返回身份不一致，请查询原问题。'; return }
      items = [result]; cursor = null; renderItems(); form.replaceChildren()
      message.textContent = '问题已登记，请读取原问题查看后续裁定；不会自动更改统计规则。'
    } catch (error) {
      form.replaceChildren()
      message.textContent = error instanceof ReportEditorApiError && [409, 422].includes(error.status)
        ? error.message + ' 原问题身份已保留，请先查询核对。'
        : '提交结果未知，请读取原问题；不会自动重新提交。'
    }
  }
  const readOriginal = async () => {
    if (!cached) return
    missing = false
    const result = await options.client.reportIssues({ issueId: cached.issueId })
    try { await loadObjects() } catch { /* 对象名称不可读不隐藏已登记问题或裁定。 */ }
    if (result.items.some(item => item.review.issueId !== cached!.issueId)) {
      message.textContent = '查询结果身份不一致，请保留原问题供核对。'; return
    }
    items = result.items; cursor = null; renderItems()
    missing = items.length === 0
    message.textContent = missing ? '本修订未找到原问题，核对后可明确重提相同内容。' : '已读取原问题；采纳与修复状态分别记录。'
  }
  const newForm = async () => {
    const objects = await loadObjects()
    form.replaceChildren()
    if (!objects.length) { message.textContent = '当前修订没有可反馈的已登记对象。'; return }
    const label = document.createElement('label'); label.textContent = '问题关联对象'
    const target = document.createElement('select'); target.name = 'object'; target.add(new Option('请选择报告对象', ''))
    for (const object of objects) target.add(new Option(object.label, object.id))
    label.append(target)
    const categoryLabel = document.createElement('label'); categoryLabel.textContent = '问题类型'
    const category = document.createElement('select'); category.name = 'category'
    for (const [value, text] of Object.entries({ calculation: '计算结果', policy: '统计口径', data: '数据完整性', citation: '引用来源', interpretation: '解释与结论' })) category.add(new Option(text, value))
    categoryLabel.append(category)
    const descriptionLabel = document.createElement('label'); descriptionLabel.textContent = '问题描述与核对依据'
    const description = document.createElement('textarea'); description.rows = 4; description.maxLength = 10000
    description.placeholder = '说明哪个结果有问题、预期是什么，以及可核对的数据或材料。'; descriptionLabel.append(description)
    form.append(label, categoryLabel, descriptionLabel)
    button('确认提交问题', 'issue-submit', form, async () => {
      if (!objects.some(object => object.id === target.value) || !description.value.trim()) {
        message.textContent = '请选择关联对象并填写具体问题。'; return
      }
      const value = submissionSchema.parse({ issueId: crypto.randomUUID(), objectRefs: [target.value],
        category: category.value, description: description.value.trim() })
      try { sessionStorage.setItem(key, JSON.stringify(value)) }
      catch { message.textContent = '无法保存问题身份，请启用会话存储后再提交。'; return }
      cached = value; await submit()
    })
    message.textContent = '请明确选择本报告对象；提交不修改原报告。'
  }
  const renderActions = () => {
    actions.replaceChildren()
    if (cached) {
      const original = document.createElement('details'); const title = document.createElement('summary')
      title.textContent = '查看原问题内容'
      const content = document.createElement('p'); content.textContent = cached.description
      const identity = document.createElement('p'); identity.textContent = `${cached.issueId} · ${cached.objectRefs.join('、')}`
      original.append(title, content, identity); actions.append(original)
      button('读取原问题', 'issue-read-original', actions, readOriginal)
      if (missing) button('确认重提原问题', 'issue-resubmit', actions, submit)
      button('另外反馈一个问题', 'issue-another', actions, async () => {
        try { sessionStorage.removeItem(key) }
        catch { message.textContent = '无法清除问题缓存，请检查会话存储。'; return }
        cached = null; missing = false; await newForm()
      })
    } else button('选择对象并反馈', 'issue-new', actions, newForm)
    button('读取本修订问题', 'issue-list', actions, async () => {
      const result = await options.client.reportIssues()
      try { await loadObjects() } catch { /* 名称读取失败不影响问题读回。 */ }
      items = result.items; cursor = result.nextCursor; renderItems()
      message.textContent = items.length ? '已读取本修订问题。' : '本修订尚无问题记录。'
    })
    if (cursor) button('加载更多问题', 'issue-more', actions, async () => {
      const result = await options.client.reportIssues({ after: cursor! })
      items = [...items, ...result.items]; cursor = result.nextCursor; renderItems()
    })
  }
  details.append(summary, intro, actions, form, message, list); root.append(details)
  renderActions()
  if (cached) { details.open = true; message.textContent = '已保留原问题身份，请读取原问题；不会自动提交。' }
}
