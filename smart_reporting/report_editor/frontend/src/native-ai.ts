import type { createNativeApi, NativeAIJob, NativeAISelection } from './native-api'
import type { NativeDraft } from './native-draft'

/** 候选只在显式采纳后进入当前草稿，仍须用户保存为独立修订。 */
export function bindNativeAI(container: HTMLElement, options: {
  api: ReturnType<typeof createNativeApi>; draft: NativeDraft; format?: 'docx' | 'pdf'
  view: { refresh(): Promise<void> }; onDraftChange(): void
}) {
  const panel = document.createElement('section')
  panel.className = 'native-ai'
  panel.setAttribute('aria-label', 'AI 编辑选区')
  const input = document.createElement('textarea')
  input.placeholder = options.format === 'pdf' ? '先在“原位改字”中选择文字对象，再描述修改要求' : '先在正文中选择段落或单元格，再描述修改要求'
  input.setAttribute('aria-label', 'AI 修改要求')
  input.maxLength = 2000
  const status = document.createElement('p')
  status.setAttribute('role', 'status')
  const details = document.createElement('details')
  const summary = document.createElement('summary')
  summary.textContent = '查看建议修改'
  const changes = document.createElement('pre')
  const warnings = document.createElement('ul')
  warnings.setAttribute('aria-label', '建议中的未执行修改')
  details.append(summary, changes, warnings); details.hidden = true
  const button = (name: string, label: string) => {
    const element = document.createElement('button')
    element.type = 'button'; element.dataset.ai = name; element.textContent = label
    return element
  }
  const start = button('start', '生成修改建议'), accept = button('accept', '采纳到草稿'), cancel = button('cancel', '取消建议')
  panel.append(input, start, accept, cancel, status, details); container.append(panel)
  let selection: NativeAISelection[] = []
  let job: NativeAIJob | undefined, busy = false, disposed = false, generation = 0
  let controller: AbortController | undefined
  const editable = () => !disposed && !options.draft.closed && !options.draft.saving
  function update() {
    start.disabled = !editable() || busy || !selection.length
    accept.disabled = !editable() || busy || job?.status !== 'succeeded'
    cancel.disabled = disposed || !job && !busy
  }
  function show(value: NativeAIJob) {
    job = value
    details.hidden = !value.proposal
    const labels: Record<string, string> = {replaceParagraph:'替换段落',insertParagraph:'新增段落',deleteParagraph:'删除段落',formatParagraph:'调整段落格式',replaceCellText:'替换单元格文字',replaceText:'替换 PDF 原文'}
    changes.textContent = value.proposal?.operations.map((operation, index) => {
      const content = operation.kind === 'replaceText' && typeof operation.newText === 'string' ? `\n${operation.newText || '清空原文字'}` : typeof operation.text === 'string' ? `\n${operation.text}` : ''
      const style = operation.style && typeof operation.style === 'object'
        ? Object.entries(operation.style).map(([key, enabled]) => `${({bold:'粗体',italic:'斜体',underline:'下划线'} as Record<string,string>)[key] ?? key}：${enabled ? '启用' : '取消'}`).join('，') : ''
      return `${index + 1}. ${labels[operation.kind] ?? '修改选区'}${content}${style ? `\n${style}` : ''}`
    }).join('\n\n') ?? ''
    warnings.replaceChildren()
    const issues = value.proposal?.issues?.map(issue => issue.message) ?? []
    const skips = value.proposal?.skippedOperations ?? []
    const notices = issues.length ? issues : skips.map(item => `第 ${item.operationIndex + 1} 项未执行，已保留原文：${item.reason}`)
    for (const notice of notices) {
      const warning = document.createElement('li')
      warning.textContent = notice; warnings.append(warning)
    }
    warnings.hidden = !notices.length
    if (options.format === 'pdf' && value.proposal) details.open = true
    status.textContent = value.proposal?.summary ?? value.error?.message ?? ({running:'正在生成并核验建议',succeeded:'建议已核验',failed:'建议生成失败',cancelled:'建议已取消'}[value.status])
    update()
  }
  start.onclick = async () => {
    if (!editable() || busy || !selection.length || !input.value.trim()) return
    const turn = ++generation
    controller = new AbortController(); busy = true; job = undefined; update()
    details.hidden = true
    status.textContent = '正在生成并核验建议'
    try {
      let result = await options.api.aiStart({instruction:input.value.trim(), selection:structuredClone(selection), expectedSha256:options.draft.identity.sourceSha256, operations:options.draft.operations}, controller.signal)
      while (!disposed && turn === generation) {
        show(result)
        if (result.status !== 'running') break
        result = await options.api.aiStatus(result.editId, controller.signal)
      }
    } catch (error) { if (!disposed && turn === generation) status.textContent = error instanceof Error ? error.message : '建议生成失败' }
    finally { if (turn === generation) { busy = false; update() } }
  }
  accept.onclick = async () => {
    if (!editable() || busy || job?.status !== 'succeeded') return
    const turn = generation
    busy = true; update()
    try {
      const operations = options.draft.operations
      const result = await options.api.aiAccept(job.editId, {expectedSha256:options.draft.identity.sourceSha256, operations, snapshotSha256:job.snapshotSha256})
      // 网络等待期间可能发生保存；草稿本身也强制检查修订锁。
      if (turn !== generation || disposed) return
      if (!editable()) throw new Error('当前修订正在保存或已关闭，请重新生成建议')
      if (JSON.stringify(operations) !== JSON.stringify(options.draft.operations)) throw new Error('草稿已变化，请重新生成建议')
      options.draft.setOperations(result.operations)
      options.onDraftChange()
      await options.view.refresh()
      job = undefined; status.textContent = options.format === 'pdf' ? '建议已进入草稿。保存前请核对实际 PDF 预览并确认。' : '建议已进入草稿，内容待重新核验；保存后生成新修订'
      details.hidden = true
    } catch (error) { if (turn === generation && !disposed) status.textContent = error instanceof Error ? error.message : '采纳失败' }
    finally { if (turn === generation) { busy = false; update() } }
  }
  cancel.onclick = async () => {
    ++generation; controller?.abort(); busy = false
    const id = job?.editId; job = undefined; status.textContent = '建议已取消'; update()
    details.hidden = true
    if (id) try { await options.api.aiCancel(id) } catch (error) { if (!disposed) status.textContent = error instanceof Error ? error.message : '服务端取消失败' }
  }
  update()
  return {
    setSelection(value: NativeAISelection[]) {
      if (options.format === 'pdf' && JSON.stringify(selection) !== JSON.stringify(value) && (job || busy)) {
        const id = job?.editId
        ++generation; controller?.abort(); busy = false; job = undefined
        details.hidden = true
        status.textContent = 'PDF 文字选区已变化，请重新生成建议。'
        if (id) void options.api.aiCancel(id).catch(() => {})
      }
      selection = structuredClone(value); update()
    },
    dispose() { disposed = true; ++generation; controller?.abort(); panel.remove() },
  }
}
