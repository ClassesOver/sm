import type { AITaskAdapter, AITaskStartRequest } from './ai-task'
import { createAITaskController } from './ai-task-controller'
import type { AskAISession } from './ask-ai-panel'
import { buttonClasses } from './button'
import { createRefinementRow, createStartSection, createSuggestionItem } from './ai-suggestions'

export interface TaskSessionOptions<T> {
  kind: 'document' | 'slides' | 'workbook' | 'chart' | 'table'
  label: string
  adapter: AITaskAdapter<T>
  captureInput: () => Promise<Pick<AITaskStartRequest, 'target' | 'snapshot'>>
  instruction?: string
  placeholder?: string
  suggestions?: readonly { label: string; instruction: string }[]
  refinements?: readonly string[]
  context?: string
}
export function mountTaskSession<T>(session: AskAISession, options: TaskSessionOptions<T>) {
  const form = document.createElement('form'); form.className = 'ai-task-form'
  form.innerHTML = '<label>修改要求<textarea maxlength="2000" rows="3" required></textarea></label><div class="ai-task-compose-footer"><span>Ctrl / ⌘ + Enter 生成候选</span><button type="submit">生成候选</button></div>'
  const instruction = form.querySelector('textarea')!
  instruction.value = options.instruction ?? ''
  instruction.placeholder = options.placeholder ?? '描述要修改的内容，也可以从推荐操作开始'
  const submit = form.querySelector('button')!; submit.className = buttonClasses('primary')
  const counter = document.createElement('span'); counter.className = 'ai-instruction-count'
  counter.id = `ai-instruction-count-${crypto.randomUUID()}`
  instruction.setAttribute('aria-describedby', counter.id)
  form.querySelector('.ai-task-compose-footer')!.prepend(counter)
  const updateCounter = () => {
    const length = instruction.value.length
    counter.textContent = `${length} / 2000`
    counter.dataset.limit = String(length > 2000)
    instruction.setCustomValidity(length > 2000 ? '修改要求最多 2000 个字符，请精简后重试。' : '')
  }
  updateCounter()
  session.mountComposer(form)
  const feedback = session.card.querySelector<HTMLElement>('.ai-task-feedback')!
  const preview = session.card.querySelector<HTMLElement>('.ai-task-preview')!
  const context = document.createElement('section'); context.className = 'ai-task-context'
  const heading = document.createElement('h3'); heading.textContent = options.label
  const details = document.createElement('details')
  const detailLabel = document.createElement('summary'); detailLabel.textContent = '修改范围与说明'
  const note = document.createElement('p'); note.textContent = options.context ?? '生成候选后先预览，采纳进入草稿；保存需单独操作。'
  details.append(detailLabel, note); context.append(heading, details); feedback.before(context)
  const issues = document.createElement('ul'); issues.className = 'ai-task-issues'; issues.hidden = true; issues.setAttribute('aria-label', '候选提示')
  feedback.after(issues)
  const fill = (value: string) => {
    if (value.length > 2000) { feedback.textContent = '修改要求最多 2000 个字符，请精简后再添加微调。'; session.focusComposer(); return }
    instruction.value = value; instruction.dispatchEvent(new Event('input')); session.focusComposer() }
  const start = createStartSection()
  start.section.querySelector('.ask-ai-start-hint')!.textContent = '选择操作填入修改要求，可补充后生成候选。'
  for (const suggestion of options.suggestions ?? []) start.list.append(createSuggestionItem({ kind: 'ai', title: suggestion.label, onClick: () => fill(suggestion.instruction) }))
  start.section.hidden = !options.suggestions?.length; preview.before(start.section)
  const refinements = createRefinementRow(options.refinements ?? [], value => fill(instruction.value.trim() ? `${instruction.value.trim()}；${value}` : value))
  refinements.hidden = true; form.prepend(refinements)
  const actions = document.createElement('div'); actions.className = 'ai-task-actions'
  const labels = { accept: '采纳到草稿', continue: '继续调整', reject: '拒绝', undo: '撤销采纳', cancel: '取消生成', retry: '重试生成', locate: '定位目标', view: '查看新结果' }
  for (const [action, label] of Object.entries(labels)) {
    const control = document.createElement('button'); control.type = 'button'; control.dataset.taskAction = action; control.textContent = label
    control.className = buttonClasses(action === 'accept' ? 'primary' : action === 'reject' ? 'quiet' : 'secondary'); control.hidden = true; actions.append(control)
  }
  const button = (id: string) => actions.querySelector<HTMLButtonElement>(`[data-task-action="${id}"]`)!
  const hints = document.createElement('p'); hints.className = 'ai-task-key-hint'; hints.textContent = '审阅快捷键：A 采纳 · C 继续调整 · X 拒绝（输入时不触发）'; hints.hidden = true; preview.after(hints)
  let rendered: T | undefined
  let announced: T | undefined
  let outcome = ''
  const controller = createAITaskController({ ...options, changed: () => {
    const { task, draft, error, busy } = controller
    const running = task?.state === 'queued' || task?.state === 'running'
    const ready = task?.proposal !== undefined && ['ready', 'accepted'].includes(task.state) && draft === 'unapplied'
    if (task?.proposal !== undefined && task.proposal !== rendered) {
      rendered = task.proposal; options.adapter.renderProposal(rendered, preview)
    } else if (!task || running) { rendered = undefined; preview.replaceChildren() }
    const newResult = ready && task?.proposal !== announced
    if (newResult) { announced = task!.proposal; session.addMessage('assistant', task?.summary || '候选已生成，请检查修改后采纳。') }
    session.setState(error ? 'error' : draft === 'applied' ? 'applied' : ready ? 'ready' : running ? 'running' : 'idle')
    feedback.dataset.tone = error ? 'error' : 'info'
    feedback.textContent = error || (draft === 'applied' ? '已采纳到草稿，可撤销；保存需单独操作。' : draft === 'undone' ? '已撤销采纳。' : ready ? '候选已就绪，尚未改变草稿。' : running ? '正在生成候选，可以收起侧栏继续编辑，完成后会通知你。' : outcome)
    issues.replaceChildren(...(task?.issues ?? []).map(issue => { const row = document.createElement('li'); row.textContent = issue.message; return row }))
    issues.hidden = !issues.childElementCount
    start.section.hidden = !options.suggestions?.length || Boolean(running || task?.proposal || draft === 'applied')
    for (const child of start.list.querySelectorAll('button')) child.disabled = busy || running
    refinements.hidden = !options.refinements?.length || !(ready || draft === 'applied')
    button('locate').hidden = !options.adapter.locateTarget || draft !== 'applied'
    if (!ready) button('view').hidden = true
    if (newResult) button('view').hidden = false
    button('accept').hidden = !ready; button('reject').hidden = !ready || task?.state === 'accepted'
    button('continue').hidden = !(ready || draft === 'applied')
    button('undo').hidden = !controller.canUndo || !options.adapter.undo
    button('cancel').hidden = !running
    button('retry').hidden = !error || ready || draft === 'applied'
    for (const child of actions.querySelectorAll('button')) child.disabled = busy || (running && child !== button('cancel'))
    submit.disabled = busy || running || (!instruction.value.trim() || instruction.value.length > 2000)
    instruction.disabled = busy || running
    submit.textContent = running ? '正在生成…' : ready ? '重新生成候选' : draft === 'applied' ? '基于当前草稿生成' : '生成候选'
    form.setAttribute('aria-busy', String(busy || running))
    hints.hidden = !ready
    session.mountReviewActions([...actions.querySelectorAll('button')].some(child => !child.hidden) ? actions : null)
  } })
  instruction.addEventListener('input', () => { updateCounter(); submit.disabled = (!instruction.value.trim() || instruction.value.length > 2000) || controller.busy || ['queued', 'running'].includes(controller.task?.state ?? '') })
  submit.disabled = (!instruction.value.trim() || instruction.value.length > 2000)
  let generating = false
  let generation = 0
  let cancelling = false
  const generate = async () => {
    if (generating || (!instruction.value.trim() || instruction.value.length > 2000) || controller.busy || ['queued', 'running'].includes(controller.task?.state ?? '')) return
    updateCounter()
    const owner = ++generation
    generating = true
    outcome = ''; session.addMessage('user', instruction.value)
    try { await controller.generate(instruction.value) } finally { if (owner === generation) generating = false }
  }
  form.addEventListener('submit', event => { event.preventDefault(); void generate() })
  instruction.addEventListener('keydown', event => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.isComposing) { event.preventDefault(); void generate() }
  })
  for (const action of ['accept', 'reject', 'cancel', 'undo'] as const) button(action).addEventListener('click', async () => {
    if (action === 'cancel') { if (cancelling) return; cancelling = true; ++generation; generating = false; button('cancel').disabled = true }
    outcome = action === 'cancel' ? '已取消生成，草稿保持原样。' : action === 'reject' ? '已拒绝候选，草稿保持原样。' : ''
    try { await controller[action]() }
    finally {
      if (action === 'cancel') { cancelling = false; button('cancel').disabled = false }
    }
  })
  button('view').addEventListener('click', () => { session.viewResult(); button('view').hidden = true })
  button('locate').addEventListener('click', async () => {
    const control = button('locate'); control.disabled = true
    try {
      if (await options.adapter.locateTarget?.()) { session.close(); outcome = '' }
      else feedback.textContent = '目标已变化或无法定位，请回到编辑区重新选择。'
    } catch (error) { feedback.textContent = error instanceof Error ? error.message : '暂时无法定位目标。' }
    finally { control.disabled = false }
  })
  button('continue').addEventListener('click', () => session.focusComposer())
  button('retry').addEventListener('click', () => { void generate() })
  const onReviewKey = (event: KeyboardEvent) => {
    if (!session.visible || event.defaultPrevented || event.isComposing || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return
    if (event.target instanceof Element && event.target.closest('input, textarea, select, button, [contenteditable]:not([contenteditable="false"])')) return
    const action = ({ a: 'accept', c: 'continue', x: 'reject' } as Record<string, string>)[event.key.toLowerCase()]
    if (!action || button(action).hidden || button(action).disabled) return
    event.preventDefault(); button(action).click()
  }
  document.addEventListener('keydown', onReviewKey)
  const remove = session.remove.bind(session)
  const dispose = () => { document.removeEventListener('keydown', onReviewKey); controller.dispose() }
  session.remove = () => { window.removeEventListener('pagehide', dispose); dispose(); remove() }
  window.addEventListener('pagehide', dispose, { once: true })
  return Object.assign(session, { instruction, generate, controller, undoButton: button('undo') })
}
