import { Extension, commands, getSplittedAttributes } from '@tiptap/core'

/** Keep the source Enter/list/heading commands and their marks/history behavior, while
 * fixing raw PM middle splits that bypass Tiptap's keepOnSplit attribute contract.
 * Paragraph/heading start splits retain the original text on the right. Source list
 * continuation retains its left source paragraph and creates a fresh right list item.
 */
export const NativeDocxSplit = Extension.create({
  name: 'nativeDocxSplit',
  // Commands are combined in descending priority order; this override follows core Commands.
  priority: 99,
  addCommands() {
    return {
      splitBlock: options => props => {
        const { tr, editor, dispatch } = props
        const initial = tr.selection.$from
        const source = initial.parent
        if (!['docParagraph', 'docHeading', 'docListItem'].includes(source.type.name)) return commands.splitBlock(options)(props)
        const atStart = initial.parentOffset === 0 && source.content.size > 0
        const stepCount = tr.steps.length
        const result = commands.splitBlock(options)(props)
        if (!result || !dispatch || tr.steps.length === stepCount) return result
        const storedMarks = tr.storedMarks
        const caret = tr.selection.$from
        if (!caret.depth || !caret.parent.isTextblock) return result
        const rightPos = caret.before()
        const left = tr.doc.resolve(rightPos).nodeBefore
        if (!left?.isTextblock) return result
        const leftPos = rightPos - left.nodeSize
        const retainRight = atStart && source.type.name !== 'docListItem'
        const freshPos = retainRight ? leftPos : rightPos, retainedPos = retainRight ? rightPos : leftPos
        const fresh = tr.doc.nodeAt(freshPos)!, retained = tr.doc.nodeAt(retainedPos)!
        tr.setNodeMarkup(freshPos, undefined, getSplittedAttributes(editor.extensionManager.attributes, fresh.type.name, fresh.attrs))
        // Core changes a start-split left heading/list into a paragraph and drops its attrs.
        // Restore source provenance on whichever half this policy retains, across node types.
        const retainedAttrs = { ...retained.attrs }
        for (const attribute of editor.extensionManager.attributes) {
          if (attribute.type === source.type.name && attribute.attribute.keepOnSplit === false && attribute.name in (retained.type.spec.attrs ?? {})) retainedAttrs[attribute.name] = source.attrs[attribute.name]
        }
        tr.setNodeMarkup(retainedPos, undefined, retainedAttrs)
        tr.setStoredMarks(storedMarks)
        return result
      },
    }
  },
})
