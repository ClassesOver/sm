import type { Editor } from '@tiptap/core'
import { TextSelection } from '@tiptap/pm/state'
import type { DocxAIReadSelection } from './docx-ai-read-selection'
import { addQueueAnchor, queueAnchorRange, removeQueueAnchors } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/ai-queue-anchors'

const MAX_ITEMS = 10
const MAX_INSTRUCTION = 500
const REQUEST_LIMIT = 2000
type Target = DocxAIReadSelection[number]
type Entry = { id: string; instruction: string; target: Target; excerpt: string }
const sameTarget = (a: Target, b: Target) => a.blockId === b.blockId && a.cellId === b.cellId

/** GenOffice selection-scoped queue. Decorations track positions; Word edit requests use trusted source IDs. */
export function createDocxEditQueue(editor: Editor, resolve: (selection: TextSelection) => DocxAIReadSelection) {
  let entries: Entry[] = []
  function targetOf(id: string) {
    const range = queueAnchorRange(editor.state, id)
    if (!range) return undefined
    const selection = TextSelection.between(editor.state.doc.resolve(range.from), editor.state.doc.resolve(range.to))
    const targets = selection instanceof TextSelection && !selection.empty ? resolve(selection) : []
    return targets.length === 1 ? { range, target: targets[0]! } : undefined
  }
  return {
    items: () => entries.map(entry => {
      const current = targetOf(entry.id)
      return { ...entry, stale: !current || !sameTarget(current.target, entry.target),
        excerpt: current && sameTarget(current.target, entry.target)
          ? editor.state.doc.textBetween(current.range.from, current.range.to, ' ').slice(0, 80)
          : entry.excerpt }
    }),
    add(instruction: string) {
      const text = instruction.trim(), selection = editor.state.selection
      if (!text || text.length > MAX_INSTRUCTION) throw new Error('请输入 1–500 字的选区修改要求。')
      if (entries.length >= MAX_ITEMS) throw new Error('最多可排队 10 项修改。')
      const targets = selection instanceof TextSelection && !selection.empty ? resolve(selection) : []
      if (targets.length !== 1) throw new Error('请选择一个可定位到来源的正文段落或表格单元格中的文字。')
      const target = targets[0]!
      if (entries.some(entry => sameTarget(entry.target, target))) throw new Error('此段落或单元格已有排队要求，请编辑原有要求。')
      const id = crypto.randomUUID()
      entries = [...entries, { id, instruction: text, target, excerpt: editor.state.doc.textBetween(selection.from, selection.to, ' ').slice(0, 80) }]
      addQueueAnchor(editor, id, selection.from, selection.to)
    },
    update(id: string, instruction: string) {
      const value = instruction.trim()
      if (value && value.length <= MAX_INSTRUCTION) entries = entries.map(entry => entry.id === id ? { ...entry, instruction: value } : entry)
    },
    focus(id: string) {
      const current = targetOf(id)
      if (current) editor.chain().focus().setTextSelection(current.range).scrollIntoView().run()
    },
    remove(ids: string[]) {
      entries = entries.filter(entry => !ids.includes(entry.id))
      if (!editor.isDestroyed) removeQueueAnchors(editor, ids)
    },
    resolve() {
      const live = entries.map(entry => ({ entry, current: targetOf(entry.id) }))
      if (live.some(({ entry, current }) => !current || !sameTarget(entry.target, current.target))) {
        throw new Error('排队选区已失效。移除失效项后再生成候选。')
      }
      live.sort((a, b) => b.current!.range.from - a.current!.range.from)
      const instruction = ['按以下顺序仅修改列出的段落或单元格，每条要求仅适用于该行目标：',
        ...live.map(({ entry }, index) => `${index + 1}. blockId=${entry.target.blockId}${entry.target.cellId ? ' cellId=' + entry.target.cellId : ''}：${entry.instruction}`)].join('\n')
      if (instruction.length > REQUEST_LIMIT) throw new Error('排队要求合计超过候选请求上限，请缩短要求或分批提交。')
      return { instruction, targets: live.map(({ entry }) => entry.target), ids: live.map(({ entry }) => entry.id) }
    },
    listen(render: () => void) { editor.on('transaction', render); return () => { editor.off('transaction', render) } },
  }
}

export type DocxEditQueue = ReturnType<typeof createDocxEditQueue>

type Batch = ReturnType<DocxEditQueue['resolve']>
export function mountDocxEditQueue(queue: DocxEditQueue, input: HTMLTextAreaElement, status: HTMLElement,
  submit: (resolve: () => Batch) => Batch | undefined) {
  const element = document.createElement('section')
  element.className = 'docx-anchored-queue'
  element.setAttribute('aria-label', '排队编辑选区')
  const hint = document.createElement('p')
  hint.textContent = '选中文字后加入队列。候选按整段或整格授权。'
  const button = (label: string, run: () => void) => {
    const control = document.createElement('button')
    control.type = 'button'; control.textContent = label; control.onclick = run
    return control
  }
  const list = document.createElement('ol')
  let blocked = false
  const showError = (error: unknown) => { status.textContent = error instanceof Error ? error.message : String(error) }
  const add = button('将选区加入编辑队列', () => {
    try { queue.add(input.value); input.value = ''; input.dispatchEvent(new Event('input')); render() }
    catch (error) { showError(error) }
  })
  const send = button('生成排队编辑建议', () => {
    if (blocked || send.hidden) return
    try { const batch = submit(queue.resolve); if (batch) queue.remove(batch.ids) }
    catch (error) { showError(error) }
  })
  const clear = button('清空编辑队列', () => queue.remove(queue.items().map(item => item.id)))
  element.append(hint, add, list, send, clear)
  function render() {
    const items = queue.items()
    // Keep a focused instruction field mounted while it is being edited.
    if (!(document.activeElement instanceof HTMLInputElement && list.contains(document.activeElement))) list.replaceChildren(...items.map(item => {
      const row = document.createElement('li')
      const label = button(item.stale ? '选区已失效' : item.excerpt, () => queue.focus(item.id))
      label.disabled = item.stale
      const instruction = document.createElement('input')
      instruction.maxLength = MAX_INSTRUCTION; instruction.value = item.instruction
      instruction.setAttribute('aria-label', '排队修改要求')
      instruction.onchange = () => {
        queue.update(item.id, instruction.value)
        if (!instruction.value.trim()) instruction.value = item.instruction
      }
      row.append(label, instruction, button('移除此项', () => { list.focus(); queue.remove([item.id]); render() }))
      return row
    }))
    add.disabled = blocked || items.length >= MAX_ITEMS
    send.hidden = clear.hidden = !items.length
    send.disabled = blocked || items.some(item => item.stale)
    clear.disabled = blocked
  }
  list.tabIndex = -1
  const unlisten = queue.listen(render)
  render()
  return { element, setBlocked(value: boolean) { if (blocked !== value) { blocked = value; render() } },
    dispose() { unlisten(); queue.remove(queue.items().map(item => item.id)); element.remove() } }
}
