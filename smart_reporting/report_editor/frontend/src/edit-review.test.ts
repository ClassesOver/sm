import { expect, it, vi } from 'vitest'
import { commandsCtx, editorViewCtx } from '@milkdown/kit/core'
import { TextSelection } from '@milkdown/kit/prose/state'
import { startStreamingCmd, pushChunkCmd, endStreamingCmd, abortStreamingCmd } from '@milkdown/kit/plugin/streaming'
import { acceptAllDiffsCmd, clearDiffReviewCmd } from '@milkdown/kit/plugin/diff'
import { createReportEditor } from './editor-features'
import { editReviewMode, editReviewObserver, type EditReviewMode } from './edit-review'
import { protocolMarkerPlugin } from './protocol-plugin'

it.each(['accept', 'reject', 'abort'] as const)('observes native AI lifecycle without exposing a handoff as committed: %s', async action => {
  const root = document.createElement('div')
  document.body.append(root)
  const original = '原文[[citation:revenue_001]]'
  const candidate = '改写后[[citation:revenue_001]]'
  const editor = createReportEditor(root, original, { provider: async function* () {} })
  const events: Array<{ mode: EditReviewMode; text: string }> = []
  editor.editor.use(protocolMarkerPlugin)
  editor.editor.use(editReviewObserver((state, mode) => events.push({ mode, text: state.doc.textContent })))
  await editor.create()
  try {
    const view = editor.editor.ctx.get(editorViewCtx)
    const commands = editor.editor.ctx.get(commandsCtx)
    view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc, 1, view.state.doc.content.size - 1)))
    commands.call(startStreamingCmd.key, { insertAt: 'selection' })
    await vi.waitFor(() => expect(events.at(-1)?.mode).toBe('generating'))
    commands.call(pushChunkCmd.key, candidate)
    if (action === 'abort') commands.call(abortStreamingCmd.key, { keep: false })
    else {
      commands.call(endStreamingCmd.key, { diffReview: true })
      await vi.waitFor(() => expect(events.at(-1)?.mode).toBe('reviewing'))
      expect(events.filter(event => event.mode === 'idle')).toEqual([])
      expect(editReviewMode(view.state)).toBe('reviewing')
      commands.call(action === 'accept' ? acceptAllDiffsCmd.key : clearDiffReviewCmd.key)
    }
    await vi.waitFor(() => expect(events.at(-1)?.mode).toBe('idle'))
    expect(events.at(-1)?.text).toBe(action === 'accept' ? candidate : original)
  } finally { await editor.destroy(); root.remove() }
})
