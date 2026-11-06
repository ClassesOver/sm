import { markAIDraft } from './ai-draft'
import { $prose } from '@milkdown/kit/utils'
import { TextSelection, Plugin } from '@milkdown/kit/prose/state'
import { Slice, type Node } from '@milkdown/kit/prose/model'
import type { EditorView } from '@milkdown/kit/prose/view'
import { closeHistory, undo } from '@milkdown/kit/prose/history'
import { askAIPanel } from './ask-ai-panel'
import { createAITaskAdapter, type TaskRequest } from './ai-task'
import { findProtocolMarkers, restoreProtocolMarkers } from './protocol'
import { selectionAIActions, selectionAILabels } from './ai'
import { renderAITextPreview } from './ai-text-preview'

type Anchor = { from: number; to: number; content: Slice; invalid: boolean }
export function createDocumentAI(options: {
  view: () => EditorView
  serialize: (node: Node) => string
  parse: (markdown: string) => Node
  request: TaskRequest
}) {
  const anchors = new Set<Anchor>()
  const plugin = $prose(() => new Plugin({ state: {
    init: () => null,
    apply: tr => {
      if (tr.docChanged) for (const anchor of anchors) {
        const from = tr.mapping.mapResult(anchor.from, 1)
        const to = tr.mapping.mapResult(anchor.to, -1)
        anchor.from = from.pos; anchor.to = to.pos
        anchor.invalid ||= from.deletedAcross || to.deletedAcross || from.pos >= to.pos
      }
      return null
    },
  } }))
  const open = () => {
    const view = options.view()
    const { from, to, empty } = view.state.selection
    if (empty) throw new Error('请先选择要改写的正文。')
    const anchor = { from, to, content: view.state.doc.slice(from, to), invalid: false }
    let original = restoreProtocolMarkers(options.serialize(view.state.doc.cut(from, to)))
    if (findProtocolMarkers(original).some(marker => ['section', 'table', 'table-close'].includes(marker.kind))) throw new Error('请在同一正文段落内选择内容。')
    anchors.add(anchor)
    let appliedDoc: Node | undefined
    let undoAnchor: { from: number; to: number; original: string } | undefined
    const validate = () => {
      if (anchor.invalid || !anchor.content.eq(view.state.doc.slice(anchor.from, anchor.to))) throw new Error('原选区已修改，请重新选择正文生成候选。')
    }
    const session = askAIPanel().createTaskSession({
      kind: 'document', label: view.state.doc.textBetween(from, to).slice(0, 30) || '正文选区',
      suggestions: selectionAIActions.map(action => ({ label: selectionAILabels[action].label, instruction: selectionAILabels[action].label })),
      refinements: ['保留全部数字和事实', '再精简一些', '使用专业报告语气'],
      context: '修改当前正文选区。可对比原文与候选，采纳后继续调整或撤销。',
      placeholder: '例如：精简内容，保留关键数字、事实与引用',
      captureInput: async () => { validate(); return { snapshot: { selection: original } } },
      adapter: createAITaskAdapter<{ markdown: string }>({
        kind: 'document-selection', request: options.request, validateTarget: validate,
        renderProposal: (proposal, target) => {
          renderAITextPreview(original, proposal.markdown, target)
        },
        applyProposal: async proposal => {
          validate()
          const markers = (value: string) => findProtocolMarkers(restoreProtocolMarkers(value)).map(marker => marker.raw).join('\n')
          if (markers(original) !== markers(proposal.markdown)) throw new Error('候选引用标记变化，请重新生成。')
          const parsed = options.parse(proposal.markdown)
          const before = { from: anchor.from, to: anchor.to, original }
          const tr = closeHistory(view.state.tr).replaceRange(anchor.from, anchor.to, Slice.maxOpen(parsed.content))
          markAIDraft()
          view.dispatch(tr.scrollIntoView())
          if (!view.state.doc.eq(tr.doc)) throw new Error('编辑器未应用候选，原稿已保留。')
          appliedDoc = view.state.doc
          undoAnchor = before
          anchor.from = tr.mapping.map(before.from, -1); anchor.to = tr.mapping.map(before.to, 1)
          anchor.content = view.state.doc.slice(anchor.from, anchor.to); anchor.invalid = false
          original = restoreProtocolMarkers(options.serialize(view.state.doc.cut(anchor.from, anchor.to)))
          view.dispatch(closeHistory(view.state.tr))
        },
        undo: async () => {
          if (!appliedDoc?.eq(view.state.doc)) throw new Error('采纳后已有其他修改，请先撤销这些修改。')
          if (!undo(view.state, view.dispatch)) throw new Error('当前没有可撤销的采纳。')
          if (undoAnchor) {
            anchor.from = undoAnchor.from; anchor.to = undoAnchor.to
            anchor.content = view.state.doc.slice(anchor.from, anchor.to); anchor.invalid = false
            original = undoAnchor.original; undoAnchor = undefined; appliedDoc = undefined
          }
        },
        locateTarget: () => {
          try { validate() } catch { return false }
          view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc, anchor.from, anchor.to)).scrollIntoView())
          view.focus(); return true
        },
        dispose: () => { anchors.delete(anchor) },
      }),
    })
    session.open()
    return session
  }
  return { plugin, open }
}
