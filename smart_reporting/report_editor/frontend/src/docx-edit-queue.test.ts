import { Editor, Node } from '@tiptap/core'
import { expect, it, vi } from 'vitest'
import { createDocxEditQueue } from './docx-edit-queue'
import { bindNativeAI } from './native-ai'
import { NativeDraft } from './native-draft'
import { AiQueueAnchorsExtension } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/ai-queue-anchors'

it('maps anchored passages through transactions, orders one trusted batch, and rejects orphaned passages', () => {
  const editor = new Editor({
    extensions: [
      Node.create({ name: 'doc', topNode: true, content: 'paragraph+' }),
      Node.create({ name: 'paragraph', content: 'text*', parseHTML: () => [{ tag: 'p' }], renderHTML: () => ['p', 0] }),
      Node.create({ name: 'text' }), AiQueueAnchorsExtension,
    ],
    content: '<p>Alpha</p><p>Beta</p>',
  })
  try {
    const queue = createDocxEditQueue(editor, selection => selection.$from.sameParent(selection.$to)
      ? [{ blockId: selection.$from.index(0) === 0 ? 'a' : 'b' }] : [])
    editor.commands.setTextSelection({ from: 2, to: 4 })
    queue.add('polish first')
    expect(queue.items()[0]?.excerpt).toBe('lp')
    expect(() => queue.add('duplicate')).toThrow('已有排队要求')
    editor.commands.setTextSelection({ from: 8, to: 10 })
    queue.add('polish second')
    editor.view.dispatch(editor.state.tr.insertText('!', 1))
    expect(queue.items().map(item => item.excerpt)).toEqual(['lp', 'Be'])
    const batch = queue.resolve()
    expect(batch.targets).toEqual([{ blockId: 'b' }, { blockId: 'a' }])
    expect(batch.instruction).toContain('1. blockId=b：polish second')
    expect(editor.getHTML()).toBe('<p>!Alpha</p><p>Beta</p>')
    editor.view.dispatch(editor.state.tr.delete(3, 5))
    expect(queue.items()[0]?.stale).toBe(true)
    expect(() => queue.resolve()).toThrow('选区已失效')
    queue.remove([batch.ids[1]!])
    expect(queue.resolve().targets).toEqual([{ blockId: 'b' }])
  } finally { editor.destroy() }
})

it('submits the anchored batch as one candidate and writes only after explicit adoption', async () => {
  const draft = new NativeDraft({documentId:'batch-word',revision:1,sourceSha256:'a'.repeat(64),
    scope:{database:'d',companyId:'c',userId:'u',threadId:'t'}}, sessionStorage)
  const operations = [{kind:'replaceParagraph',blockId:'a',text:'candidate'}]
  const api = {
    aiStart: vi.fn().mockResolvedValue({editId:'batch',status:'succeeded',snapshotSha256:'snap',proposal:{summary:'candidate',operations}}),
    aiAccept: vi.fn().mockResolvedValue({operations}),
  }
  const batch = { instruction:'batch instruction', targets:[{blockId:'b'},{blockId:'a'}], ids:['q2','q1'] }
  const wordEditQueue = { items: () => batch.ids.map((id, index) => ({
    id, instruction:'polish', targets:[batch.targets[index]!], excerpt:'text', stale:false,
  })), listen: () => () => {}, add: vi.fn(), resolve: vi.fn(() => batch), remove: vi.fn(),
    update: vi.fn(), focus: vi.fn(), canAnnotate: () => true }
  const root = document.createElement('div'), flushPendingEdits = vi.fn()
  const binding = bindNativeAI(root,{api:api as never,draft,format:'docx',wordEditQueue,view:{refresh:vi.fn(),flushPendingEdits},onDraftChange:vi.fn()})
  try {
    binding.open()
    const submit = [...root.querySelectorAll('button')].find(control => control.textContent === '生成排队编辑建议')!
    expect(submit.hidden).toBe(false)
    submit.click()
    expect(flushPendingEdits).toHaveBeenCalledBefore(wordEditQueue.resolve)
    expect(api.aiStart).toHaveBeenCalledOnce()
    expect(api.aiStart.mock.calls[0]?.[0]).toMatchObject({instruction:batch.instruction,selection:batch.targets,operations:[],expectedSha256:'a'.repeat(64)})
    expect(wordEditQueue.remove).toHaveBeenCalledWith(batch.ids)
    binding.setSelection([{blockId:'unrelated'}])
    const accept = root.querySelector<HTMLButtonElement>('[data-ai=accept]')!
    await vi.waitFor(() => expect(accept.disabled).toBe(false))
    expect(draft.operations).toEqual([])
    expect(api.aiAccept).not.toHaveBeenCalled()
    accept.click()
    await vi.waitFor(() => expect(draft.operations).toEqual(operations))
  } finally { binding.dispose() }
})

it('adds a floating cross-paragraph annotation and reopens it for editing', async () => {
  const { mountDocxAskPopover } = await import('./docx-ask-popover')
  const { AI_QUEUE_ANCHOR_CLICK } = await import('./vendor/genoffice-docs/apps/docs/src/renderer/editor/ai-queue-anchors')
  const { InactiveSelectionExtension } = await import('./vendor/genoffice-docs/apps/docs/src/renderer/editor/inactive-selection')
  const host = document.body.appendChild(document.createElement('div'))
  const editor = new Editor({element: host, extensions: [
    Node.create({name:'doc',topNode:true,content:'paragraph+'}),
    Node.create({name:'paragraph',content:'text*',parseHTML:()=>[{tag:'p'}],renderHTML:()=>['p',0]}),
    Node.create({name:'text'}), AiQueueAnchorsExtension, InactiveSelectionExtension,
  ], content:'<p>Alpha</p><p>Beta</p>'})
  editor.view.coordsAtPos = () => ({left:10,right:20,top:30,bottom:40})
  let editable = true
  const queue = createDocxEditQueue(editor, selection => [{blockId:'a'}, {blockId:'b'}].slice(selection.$from.index(0), selection.$to.index(0) + 1))
  const dispose = mountDocxAskPopover(editor, queue, host, () => editable)
  try {
    editor.view.focus()
    editor.commands.setTextSelection({from:3,to:10})
    const trigger = host.querySelector<HTMLButtonElement>('[data-action="word-ai-annotation"]')!
    expect(trigger.hidden).toBe(false)
    trigger.click()
    const input = host.querySelector<HTMLInputElement>('[role=dialog] input')!
    expect(document.activeElement).toBe(input)
    input.value = 'rewrite both'
    input.dispatchEvent(new KeyboardEvent('keydown', {bubbles:true,key:'Enter',isComposing:true}))
    expect(queue.items()).toHaveLength(0)
    input.dispatchEvent(new KeyboardEvent('keydown', {bubbles:true,key:'Enter'}))
    const entry = queue.items()[0]!
    expect(entry.targets).toEqual([{blockId:'a'},{blockId:'b'}])
    expect(queue.resolve().instruction).toContain('blockId=a, blockId=b：rewrite both')
    window.dispatchEvent(new CustomEvent(AI_QUEUE_ANCHOR_CLICK, {detail:{qid:entry.id}}))
    expect(input.value).toBe('rewrite both')
    input.value = 'update both'
    document.body.dispatchEvent(new Event('pointerdown',{bubbles:true,composed:true}))
    expect(queue.resolve().instruction).toContain('update both')
    editor.view.dispatch(editor.state.tr.insertText('!',1))
    expect(queue.items()[0]?.stale).toBe(false)
    editable = false
    editor.view.dispatch(editor.state.tr.setMeta('saving', true))
    expect(trigger.hidden).toBe(true)
    expect(editor.getHTML()).toBe('<p>!Alpha</p><p>Beta</p>')
  } finally { dispose(); editor.destroy(); host.remove() }
})
