import type { Editor } from '@tiptap/core'
import { history, redoDepth, undoDepth } from '@tiptap/pm/history'

const historyKey = history().spec.key!

/** 仅在外部草稿完整安装并核验成功后调用；失败/锁定刷新不能清除原历史。 */
export function resetDocxHistory(editor: Editor): boolean {
  if (editor.isDestroyed) return false
  const state = editor.state
  if (!undoDepth(state) && !redoDepth(state)) return false
  const plugin = state.plugins.find(value => value.spec.key === historyKey)
  if (!plugin) return false
  // 官方 reconfigure 保留其余 state field；同一历史插件移除再加回才会重新 init。
  const withoutHistory = state.reconfigure({ plugins: state.plugins.filter(value => value !== plugin) })
  editor.view.updateState(withoutHistory.reconfigure({ plugins: state.plugins }))
  return true
}
