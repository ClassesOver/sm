import { bytesSha256 } from './source-validation'
import { Editor, Extension, type JSONContent } from '@tiptap/core'
import { Plugin } from '@tiptap/pm/state'
import { createRoot } from 'react-dom/client'
import { readSections, readSectionSettings, type HfPartInfo, type HeaderFooter } from '@genoffice/docx-engine'
import type { EditorShell } from './shell'
import type { createNativeApi, NativeContextResponse } from './native-api'
import type { NativeDraft } from './native-draft'
import { docxOperations, replayDocxOperations, restoredDocxSectionOperation, type DocxAnchor, type DocxPmNode } from './docx-operations'
import { createDocxRibbon } from './docx-ribbon'
import { parseDocxOffThread } from './vendor/genoffice-docs/apps/docs/src/renderer/parse-off-thread'
import { blocksToPmDoc, pmDocOptions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/convert'
import { editorExtensions } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/extensions'
import { PaginationPreview } from './vendor/genoffice-docs/apps/docs/src/renderer/components/PaginationPreview'
import { docStyleCss } from './vendor/genoffice-docs/apps/docs/src/renderer/doc-style-css'
import { adoptEmbeddedFonts } from './vendor/genoffice-docs/apps/docs/src/renderer/embedded-fonts'
import { setResolverFontTable } from './vendor/genoffice-docs/apps/docs/src/renderer/font-resolve'
import { setStaticAsciiResolver } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/protected-render'
import './vendor/genoffice-docs/scoped.css'
import './docx.css'

interface WordModel { sourceSha256: string; blocks: (Omit<DocxAnchor, 'docxIndex'> & { type: string })[]; sections: { sectionId: string; expectedSectionSha256: string; settings: ReturnType<typeof readSectionSettings> }[] }
const sha256 = (bytes: ArrayBuffer | Uint8Array<ArrayBuffer>) => bytesSha256(bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes))

const part = (value: HfPartInfo | null | undefined): HeaderFooter | null => value ? { text: value.text, paras: value.paras, pageNumber: value.hasPageNumber } : null

/** GenOffice Docs 的真实 ProseMirror 画布；保存仅提交服务端允许的原文件操作。 */
export async function createDocxEditorView(shell: EditorShell, options: {
  api: ReturnType<typeof createNativeApi>; context: NativeContextResponse; draft: NativeDraft; onDraftChange?: () => void; onSelectionChange?: (selection: { blockId: string; cellId?: string }[]) => void
}) {
  const { api, context, draft } = options
  const expectedSha256 = context.context.sourceFile.sha256
  const [buffer, inspected] = await Promise.all([api.file(), api.preview<WordModel>({ expectedSha256, operations: [] })])
  if (await sha256(buffer) !== expectedSha256 || inspected.model.sourceSha256 !== expectedSha256) throw new Error('Word 来源文件身份发生变化，请重新打开')
  const parsed = await parseDocxOffThread(new Uint8Array(buffer))
  const visible = parsed.blocks.filter(block => !block.hidden)
  if (visible.length !== inspected.model.blocks.length) throw new Error('Word 解析对象与服务端不一致')
  const anchors: DocxAnchor[] = []
  for (let index = 0; index < visible.length; index++) {
    const block = visible[index], anchor = inspected.model.blocks[index]
    if (block.docxIndex == null || block.type !== anchor.type || await sha256(new TextEncoder().encode(block.originalXml ?? '')) !== anchor.expectedObjectSha256
      || await sha256(new TextEncoder().encode(`${expectedSha256}:block:${block.docxIndex}`)) !== anchor.blockId) throw new Error('Word 对象身份校验失败')
    anchors.push({ ...anchor, docxIndex: block.docxIndex })
  }
  setResolverFontTable(parsed.fontTable)
  await adoptEmbeddedFonts(parsed.embeddedFonts)
  const sections = readSections(parsed), section = readSectionSettings(parsed), px = (twips: number) => twips / 15
  const sourceSection = inspected.model.sections.at(-1), trailingSection = sections.at(-1)
  if (!sourceSection || !trailingSection
    || sourceSection.sectionId !== await sha256(new TextEncoder().encode(`${expectedSha256}:section:${trailingSection.lastBlockIndex}`))
    || sourceSection.expectedSectionSha256 !== await sha256(new TextEncoder().encode(trailingSection.sectPrXml))) throw new Error('Word 页面设置的节身份校验失败')
  const sectionAnchor = { ...sourceSection, settings: section }
  const sectionOperation = () => restoredDocxSectionOperation(draft.operations, sectionAnchor)
  sectionOperation()
  const host = document.createElement('div'); host.className = 'docx-native'
  host.innerHTML = '<div class="docx-tools" role="toolbar" aria-label="Word 编辑"></div><p class="docx-notice" role="status">支持正文、整段基础样式和简单表格文字。复杂对象保留原样；不支持的编辑会提示原因。</p><div class="editor-scroll"><div class="doc-zoom"><div class="docx-canvas"></div></div></div><div class="docx-preview-root"></div>'
  shell.editor.replaceChildren(host)
  const style = document.createElement('style'); style.textContent = docStyleCss(parsed); host.append(style)
  const notice = host.querySelector<HTMLElement>('.docx-notice')!, toolbar = host.querySelector<HTMLElement>('.docx-tools')!
  const previewRoot = createRoot(host.querySelector<HTMLElement>('.docx-preview-root')!)
  let baseline: DocxPmNode, ready = false, refreshing = false, saving = false
  const reportError = (error: unknown) => { notice.textContent = error instanceof Error ? error.message : String(error) }
  const Guard = Extension.create({ name: 'nativeOperationGuard', addProseMirrorPlugins: () => [new Plugin({
    filterTransaction(transaction) {
      if (!ready || refreshing || !transaction.docChanged) return true
      if (saving || draft.saving || draft.closed || !context.editingEnabled) return false
      try { docxOperations(baseline, transaction.doc.toJSON(), anchors, sectionOperation()); return true }
      catch (error) { reportError(error); return false }
    },
  })] })
  const editor = new Editor({ element: host.querySelector<HTMLElement>('.docx-canvas')!, extensions: [...editorExtensions, Guard],
    content: blocksToPmDoc(parsed.blocks, sections, pmDocOptions(parsed)) as JSONContent,
    editable: context.editingEnabled,
    editorProps: { attributes: { class: 'doc-page', 'aria-label': 'Word 文档编辑区', role: 'textbox', 'aria-multiline': 'true' } },
    onSelectionUpdate: ({ editor }) => {
      const { $from } = editor.state.selection
      let anchor: DocxAnchor | undefined
      for (let depth = $from.depth; depth > 0; depth--) {
        const node = $from.node(depth)
        if (node.attrs.docxIndex != null) { anchor = anchors.find(item => item.docxIndex === node.attrs.docxIndex); if (anchor) break }
      }
      if (!anchor) { options.onSelectionChange?.([]); return }
      let cellId: string | undefined
      for (let depth = $from.depth; depth > 1; depth--) if (['docTableCell', 'docTableHeader'].includes($from.node(depth).type.name)) {
        cellId = anchor.cells?.[$from.index(depth - 2)]?.[$from.index(depth - 1)]?.cellId
        break
      }
      options.onSelectionChange?.([{ blockId: anchor.blockId, ...(cellId ? { cellId } : {}) }])
    },
    onUpdate: () => {
      if (!ready || refreshing) return
      try { draft.setOperations(docxOperations(baseline, editor.getJSON(), anchors, sectionOperation())); options.onDraftChange?.() }
      catch (error) { reportError(error) }
    },
  })
  editor.storage.listNumbering.styles = parsed.styles
  editor.storage.listNumbering.docDefaults = parsed.docDefaults
  editor.storage.listNumbering.defs = parsed.numbering
  editor.storage.listNumbering.defaultTabTwips = parsed.defaultTabStopTwips ?? 720
  editor.storage.listNumbering.indentNotTabStop = parsed.indentNotNumberingTabStop === true
  editor.storage.tabStops.defaultTabStopTwips = parsed.defaultTabStopTwips ?? null
  setStaticAsciiResolver(() => editor.storage.listNumbering)
  const syncSection = () => {
    const settings = { ...section, ...sectionOperation()?.values }
    sectionRibbon.settings = settings
    Object.assign(editor.view.dom.style, { width: `${px(settings.pageWidth)}px`, minHeight: `${px(settings.pageHeight)}px`,
      padding: `${px(settings.marginTop)}px ${px(settings.marginRight)}px ${px(settings.marginBottom)}px ${px(settings.marginLeft)}px`, boxSizing: 'border-box' })
  }
  baseline = editor.getJSON(); ready = true
  const refresh = async () => {
    const content = replayDocxOperations(baseline, draft.operations, anchors, sectionAnchor)
    refreshing = true
    try { syncSection(); editor.commands.setContent(content as JSONContent, { emitUpdate: false }); editor.setEditable(context.editingEnabled && !saving && !draft.closed, false) }
    finally { refreshing = false }
  }
  const showPaginationPreview = () => {
    const currentSection = { ...section, ...sectionOperation()?.values }
    const currentSections = sections.map((item, index) => index === sections.length - 1 ? { ...item, settings: currentSection } : item)
    previewRoot.render(<PaginationPreview section={currentSection} sections={currentSections} canvasTop={px(currentSection.marginTop)} hfParts={parsed.hfParts ?? {}}
    colFlow={null} colMode="none" mirrorMargins={parsed.mirrorMargins} comments={parsed.comments} anchorBlocks={parsed.blocks}
    hf={{ header: { text: parsed.headerText ?? '', paras: parsed.headerParas ?? undefined, pageNumber: parsed.headerHasPageNumber },
      footer: { text: parsed.footerText ?? '', paras: parsed.footerParas ?? undefined, pageNumber: parsed.footerHasPageNumber },
      headerFirst: part(parsed.headerFirst), footerFirst: part(parsed.footerFirst), headerEven: part(parsed.headerEven), footerEven: part(parsed.footerEven),
      titlePg: parsed.titlePg ?? false, evenOddHf: parsed.evenAndOddHeaders ?? false,
      images: { header: parsed.headerImages ?? undefined, footer: parsed.footerImages ?? undefined,
        headerFirst: parsed.headerFirst?.images, footerFirst: parsed.footerFirst?.images, headerEven: parsed.headerEven?.images, footerEven: parsed.footerEven?.images } }}
    onExportPdf={() => shell.exportPdf.click()} onClose={() => previewRoot.render(null)} />)
  }
  const selectParagraph = () => {
    const { $from } = editor.state.selection
    for (let depth = $from.depth; depth > 0; depth--) if (['docParagraph', 'docHeading', 'docListItem'].includes($from.node(depth).type.name)) {
      return editor.chain().focus().setTextSelection({ from: $from.start(depth), to: $from.end(depth) })
    }
    throw new Error('请先选择正文段落')
  }
  const paragraphCommand = (command: 'add' | 'delete') => {
    try {
      if (command === 'add') {
        const { $from } = editor.state.selection
        const position = $from.depth ? $from.after(1) : editor.state.doc.content.size
        editor.chain().focus().insertContentAt(position, { type: 'docParagraph', attrs: { docxIndex: null }, content: [{ type: 'text', text: '新段落' }] }).run()
      } else selectParagraph().deleteNode(editor.state.selection.$from.parent.type.name).run()
    } catch (error) { reportError(error) }
  }
  const sectionRibbon = {
    settings: section,
    onChange: (values: Partial<ReturnType<typeof readSectionSettings>>) => {
      if (saving || draft.saving || draft.closed || !context.editingEnabled) return
      try {
        const operation = restoredDocxSectionOperation([{ kind: 'setSectionLayout', sectionId: sectionAnchor.sectionId,
          expectedSectionSha256: sectionAnchor.expectedSectionSha256, values: { ...sectionOperation()?.values, ...values } }], sectionAnchor)
        draft.setOperations(docxOperations(baseline, editor.getJSON(), anchors, operation)); options.onDraftChange?.()
      } catch (error) { reportError(error) }
      syncSection()
      editor.commands.setMeta('native-section-layout', true)
    },
  }
  toolbar.append(createDocxRibbon(editor, context.editingEnabled, showPaginationPreview, paragraphCommand, sectionRibbon, anchors))
  await refresh()
  return { refresh, setSaving(value: boolean) { saving = value; editor.setEditable(context.editingEnabled && !saving && !draft.closed, false); editor.commands.setMeta('native-section-layout', true); toolbar.querySelectorAll<HTMLButtonElement>('[data-mutates=true], [data-editable-action=true]').forEach(control => { control.disabled = !context.editingEnabled || saving || draft.closed }) },
    dispose() { ready = false; previewRoot.unmount(); editor.destroy(); void adoptEmbeddedFonts([]); host.remove() } }
}
