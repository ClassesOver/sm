import { Editor, Node } from '@tiptap/core'
import { expect, it, vi } from 'vitest'
import { createDocxSplitPane } from './docx-split-pane'

const Doc = Node.create({ name: 'doc', topNode: true, content: 'paragraph+' })
const Text = Node.create({ name: 'text', group: 'inline' })
const Paragraph = Node.create({ name: 'paragraph', content: 'text*', renderHTML: () => ['p', 0] })

it('shows a read-only snapshot that follows live edits and keeps a separate scroll position', () => {
  vi.useFakeTimers()
  const host = document.body.appendChild(document.createElement('div'))
  const editor = new Editor({
    element: host.appendChild(document.createElement('div')), extensions: [Doc, Text, Paragraph],
    content: { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: '原文' }] }] },
  })
  const onVisibilityChange = vi.fn(), onError = vi.fn()
  const pane = createDocxSplitPane({ host, editor, onVisibilityChange, onError })
  try {
    editor.view.dom.style.width = '960px'
    pane.toggle()
    const preview = host.querySelector<HTMLElement>('.docx-split-content')!
    const scroller = host.querySelector<HTMLElement>('.docx-split-scroll')!
    expect(preview.getAttribute('contenteditable')).toBe('false')
    expect(preview.style.width).toBe('960px')
    expect(preview.textContent).toBe('原文')
    expect(editor.isEditable).toBe(true)
    scroller.scrollTop = 40
    editor.commands.insertContentAt(3, '修改')
    vi.advanceTimersByTime(300)
    expect(preview.textContent).toBe('原文修改')
    expect(scroller.scrollTop).toBe(40)
    host.querySelector<HTMLButtonElement>('[aria-label="取消拆分"]')!.click()
    expect(pane.visible).toBe(false)
    expect(onVisibilityChange.mock.calls).toEqual([[true], [false]])
    expect(onError).not.toHaveBeenCalled()
  } finally {
    pane.dispose()
    editor.destroy()
    host.remove()
    vi.useRealTimers()
  }
})
