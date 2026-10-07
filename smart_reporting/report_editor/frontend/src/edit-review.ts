import { Plugin, type EditorState } from '@milkdown/kit/prose/state'
import { streamingPluginKey } from '@milkdown/kit/plugin/streaming'
import { diffPluginKey } from '@milkdown/kit/plugin/diff'
import { $prose } from '@milkdown/kit/utils'

export type EditReviewMode = 'idle' | 'generating' | 'reviewing'

export function editReviewMode(state: EditorState): EditReviewMode {
  if (streamingPluginKey.getState(state)?.active) return 'generating'
  if (diffPluginKey.getState(state)?.active) return 'reviewing'
  return 'idle'
}

// 原生流式生成与差异审阅都修改编辑器状态；审阅结束后才交给草稿保存。
export function editReviewObserver(onChange: (state: EditorState, mode: EditReviewMode) => void) {
  return $prose(() => new Plugin({
    view(view) {
      let doc = view.state.doc
      let mode = editReviewMode(view.state)
      let pending = false
      let destroyed = false
      return {
        update() {
          if (pending) return
          pending = true
          // 流式结束与进入审阅是连续两次事务，不能把中间的空闲状态当作完成。
          queueMicrotask(() => {
            pending = false
            if (destroyed) return
            const nextMode = editReviewMode(view.state)
            if (doc === view.state.doc && mode === nextMode) return
            doc = view.state.doc
            mode = nextMode
            onChange(view.state, mode)
          })
        },
        destroy() { destroyed = true },
      }
    },
  }))
}
