import type { Editor } from '@tiptap/core'
import type { Transaction } from '@tiptap/pm/state'
import type { EditorView } from '@tiptap/pm/view'
import { autocorrectKey, parseListPrefix } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/autocorrect'
import { numberPresetLevels } from './vendor/genoffice-docs/apps/docs/src/renderer/list-presets'
import { normalizeDocxCustomList, customListLevel } from '../../../reporting/doc_engine/bridge/docx-custom-list'
import { docxNumberingBindingId, type DocxNumberingBinding } from '../../../reporting/doc_engine/bridge/docx-numbering-value'
import type { DocxAnchor } from './docx-operations'
import { docxCustomListReason } from './docx-custom-list'

/** Adapts the source extension's real allocation hooks to native paragraph-bound numbering.
 * Definitions live on the transaction's list node; NativeDocxCustomList derives its overlay,
 * and existing native operations persist/replay it. No separate pending definitions are stored.
 * Call after creating an editor with AutoCorrectExtension + NativeDocxCustomList; dispose before destroy.
 */
export function installDocxAutocorrect(editor: Editor, anchors: DocxAnchor[]): () => void {
  const plugin = autocorrectKey.get(editor.state), storage = editor.storage.autocorrect
  const original = plugin?.props.handleTextInput
  if (!plugin || !original || !storage) throw new Error('AutoCorrect extension is unavailable')
  const previousHooks = storage.hooks
  let allocation: Record<string, unknown> | null = null
  const hooks = {
    bulletNumId: () => {
      const source = [...editor.storage.listNumbering.defs.values()].find(def => /^[1-9][0-9]*$/.test(def.numId) && def.levels[0]?.numFmt === 'bullet')
      const id = crypto.randomUUID()
      const binding: DocxNumberingBinding = source ? { id, sourceNumId: source.numId, startOverrides: { 0: 1 } } : { id, defaultNumbering: { id, kind: 'bullet' } }
      const numId = docxNumberingBindingId(binding)
      allocation = { numId, ilvl: 0, kind: 'bullet', nativeNumberingBinding: binding, nativeListDefinition: null }
      return numId
    },
    numberedNumId: (numFmt: string, pattern: string, start: number) => {
      const levels = numberPresetLevels(numFmt, pattern)
      if (start > 1) levels[0] = { ...levels[0]!, start }
      const definition = normalizeDocxCustomList({ id: crypto.randomUUID(), levels })
      allocation = { ...customListLevel(definition, 0), nativeListDefinition: definition, nativeNumberingBinding: null }
      return String(allocation.numId)
    },
  }
  storage.hooks = hooks
  const wrapped: NonNullable<typeof original> = function(view, from, to, text, deflt) {
    allocation = null
    const $from = view.state.doc.resolve(from)
    const listPrefix = text === ' ' && $from.parent.type.name === 'docParagraph' && parseListPrefix($from.parent.textBetween(0, $from.parentOffset))
    if (listPrefix && docxCustomListReason(editor, anchors)) return false
    // Delegate every rule to the original plugin, changing only the transaction sent by its list rule.
    const proxy = Object.create(view) as EditorView
    proxy.dispatch = (tr: Transaction) => {
      if (allocation) {
        const pos = tr.mapping.map($from.before(), -1)
        const list = tr.doc.nodeAt(pos)
        if (list?.type.name === 'docListItem') tr.setNodeMarkup(pos, undefined, { ...$from.parent.attrs, ...allocation })
      }
      view.dispatch(tr)
    }
    try { return original.call(plugin, proxy, from, to, text, deflt) }
    finally { allocation = null }
  }
  plugin.props.handleTextInput = wrapped
  let disposed = false
  return () => {
    if (disposed) return
    disposed = true
    if (plugin.props.handleTextInput === wrapped) plugin.props.handleTextInput = original
    if (storage.hooks === hooks) storage.hooks = previousHooks
  }
}
