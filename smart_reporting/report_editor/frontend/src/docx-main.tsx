import { bytesSha256 } from './source-validation'
import { Editor, Extension, type JSONContent } from '@tiptap/core'
import { Plugin } from '@tiptap/pm/state'
import { createRoot } from 'react-dom/client'
import { readSections, readSectionSettings, type HfPartInfo, type HeaderFooter } from '@genoffice/docx-engine'
import type { EditorShell } from './shell'
import type { createNativeApi, NativeContextResponse } from './native-api'
import type { NativeDraft } from './native-draft'
import { createDocxFindReplace } from './docx-find-replace'
import { docxOperations, replayDocxOperations, restoredDocxSectionOperation, restoredDocxSectionOperations, sectionBreakNode, type DocxAnchor, type DocxPmNode, type DocxSectionAnchor, type SectionBreakType } from './docx-operations'
import { docxHeaderFooterOperation, mergeDocxHeaderFooterOperation, restoredDocxHeaderFooterOperations, type DocxHeadersFootersModel, type DocxHfFlags, type DocxHfPart, type DocxHfVariant } from './docx-hf'
import type { DocxHeaderFooterController, DocxHfPendingEditor } from './docx-hf-source'
import { NativeTableStructure, createDocxTableCommands } from './docx-tables'
import { createDocxRibbon } from './docx-ribbon'
import { createDocxViewCommands } from './docx-view'
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

interface WordModel { sourceSha256: string; blocks: (Omit<DocxAnchor, 'docxIndex'> & { type: string })[]; sections: { sectionId: string; expectedSectionSha256: string; settings: ReturnType<typeof readSectionSettings>; firstBlockIndex?: number; lastBlockIndex?: number }[]; headersFooters?: DocxHeadersFootersModel }
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
    anchors.push({ ...anchor, docxIndex: block.docxIndex, tableWidthsTwips: block.table?.colWidthsTwips, tableHeaderCount: block.table?.repeatHeaderRows?.findIndex(header => !header) === -1 ? block.table.rows.length : block.table?.repeatHeaderRows?.findIndex(header => !header) ?? 0 })
  }
  setResolverFontTable(parsed.fontTable)
  await adoptEmbeddedFonts(parsed.embeddedFonts)
  const sections = readSections(parsed), section = readSectionSettings(parsed), px = (twips: number) => twips / 15
  // 全部节逐一核验身份（文档顺序，尾节在最后）；页面设置作用于光标所在节。
  if (!sections.length || inspected.model.sections.length !== sections.length) throw new Error('Word 页面设置的节身份校验失败')
  const sectionAnchors: DocxSectionAnchor[] = []
  for (const [index, item] of sections.entries()) {
    const source = inspected.model.sections[index]!
    if (source.sectionId !== await sha256(new TextEncoder().encode(`${expectedSha256}:section:${item.lastBlockIndex}`))
      || source.expectedSectionSha256 !== await sha256(new TextEncoder().encode(item.sectPrXml))) throw new Error('Word 页面设置的节身份校验失败')
    sectionAnchors.push({ sectionId: source.sectionId, expectedSectionSha256: source.expectedSectionSha256, settings: index === sections.length - 1 ? section : item.settings,
      firstBlockIndex: item.firstBlockIndex, lastBlockIndex: item.lastBlockIndex })
  }
  const sectionAnchor = sectionAnchors.at(-1)!
  const sectionOperation = () => restoredDocxSectionOperations(draft.operations, sectionAnchors)
  sectionOperation()
  let activeSection = 0
  const sectionValues = (index: number) => sectionOperation().find(operation => operation.sectionId === sectionAnchors[index]!.sectionId)?.values as Partial<typeof section> | undefined
  const sectionAt = (docxIndex: number) => Math.max(0, sectionAnchors.findIndex(item => (item.firstBlockIndex ?? 0) <= docxIndex && docxIndex <= (item.lastBlockIndex ?? Infinity)))
  /** 本次草稿已在该节插入分节符（保存前该节不能再插入分节符或改页面设置）。 */
  const pendingBreakIn = (index: number) => draft.operations.some(operation => operation.kind === 'insertSectionBreak'
    && sectionAt(anchors.find(anchor => anchor.blockId === operation.blockId)?.docxIndex ?? -1) === index)
  const hfModel = inspected.model.headersFooters as DocxHeadersFootersModel | undefined
  const hfAnchor = { sectionId: sectionAnchor.sectionId, expectedSectionSha256: sectionAnchor.expectedSectionSha256 } as const
  // 恢复的页眉/页脚草稿必须与当前来源的部件身份一致；不一致即拒绝打开并保留草稿。
  const headerFooterOperations = () => restoredDocxHeaderFooterOperations(draft.operations, hfAnchor, hfModel)
  headerFooterOperations()
  const host = document.createElement('div'); host.className = 'docx-native'
  host.innerHTML = '<div class="docx-tools" role="toolbar" aria-label="Word 编辑"></div><p class="docx-notice" role="status">支持正文、基础样式、表格文字及符合条件表格的增删行列。每张表的结构修改需保存并重开后继续；不支持的编辑会提示原因。</p><div class="editor-scroll"><div class="doc-zoom"><div class="docx-canvas"></div></div></div><div class="docx-preview-root"></div>'
  shell.editor.replaceChildren(host)
  const style = document.createElement('style'); style.textContent = docStyleCss(parsed); host.append(style)
  const notice = host.querySelector<HTMLElement>('.docx-notice')!, toolbar = host.querySelector<HTMLElement>('.docx-tools')!
  const previewRoot = createRoot(host.querySelector<HTMLElement>('.docx-preview-root')!)
  let baseline: DocxPmNode, ready = false, refreshing = false, saving = false
  let pendingHfEditor: DocxHfPendingEditor | null = null
  const reportError = (error: unknown) => { notice.textContent = error instanceof Error ? error.message : String(error) }
  const Guard = Extension.create({ name: 'nativeOperationGuard', addProseMirrorPlugins: () => [new Plugin({
    filterTransaction(transaction) {
      if (!ready || refreshing || !transaction.docChanged) return true
      if (saving || draft.saving || draft.closed || !context.editingEnabled) return false
      try { docxOperations(baseline, transaction.doc.toJSON(), anchors, sectionOperation(), editor.schema, parsed.styles, headerFooterOperations()); return true }
      catch (error) { reportError(error); return false }
    },
  })] })
  const editor = new Editor({ element: host.querySelector<HTMLElement>('.docx-canvas')!, extensions: [...editorExtensions, NativeTableStructure, Guard],
    content: blocksToPmDoc(parsed.blocks, sections, pmDocOptions(parsed)) as JSONContent,
    editable: context.editingEnabled,
    editorProps: { attributes: { class: 'doc-page', 'aria-label': 'Word 文档编辑区', role: 'textbox', 'aria-multiline': 'true' } },
    onSelectionUpdate: ({ editor }) => {
      const { $from } = editor.state.selection
      // 当前节：光标所在顶层块（或其前最近的原有块）的 docxIndex 所属节。
      let top = $from.depth > 0 ? $from.index(0) : 0, sectionIndex: number | undefined
      for (; top >= 0 && sectionIndex === undefined; top--) {
        const docxIndex = editor.state.doc.maybeChild(top)?.attrs.docxIndex
        if (docxIndex != null) sectionIndex = sectionAt(Number(docxIndex))
      }
      if ((sectionIndex ?? 0) !== activeSection) { activeSection = sectionIndex ?? 0; syncSection(); editor.commands.setMeta('native-section-layout', true) }
      let anchor: DocxAnchor | undefined
      for (let depth = $from.depth; depth > 0; depth--) {
        const node = $from.node(depth)
        if (node.attrs.docxIndex != null) { anchor = anchors.find(item => item.docxIndex === node.attrs.docxIndex); if (anchor) break }
      }
      if (!anchor) { options.onSelectionChange?.([]); return }
      if (editor.state.doc.content.content.some(node => node.attrs.docxIndex === anchor!.docxIndex && node.attrs.nativeTableStructure)) { options.onSelectionChange?.([{ blockId: anchor.blockId }]); return }
      let cellId: string | undefined
      for (let depth = $from.depth; depth > 1; depth--) if (['docTableCell', 'docTableHeader'].includes($from.node(depth).type.name)) {
        cellId = anchor.cells?.[$from.index(depth - 2)]?.[$from.index(depth - 1)]?.cellId
        break
      }
      options.onSelectionChange?.([{ blockId: anchor.blockId, ...(cellId ? { cellId } : {}) }])
    },
    onUpdate: () => {
      if (!ready || refreshing) return
      try { draft.setOperations(docxOperations(baseline, editor.getJSON(), anchors, sectionOperation(), editor.schema, parsed.styles, headerFooterOperations())); options.onDraftChange?.() }
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
    const settings = { ...sectionAnchors[activeSection]!.settings, ...sectionValues(activeSection) }
    sectionRibbon.settings = settings
    sectionRibbon.label = sections.length > 1 ? `第 ${activeSection + 1} 节，共 ${sections.length} 节` : undefined
    Object.assign(editor.view.dom.style, { width: `${px(settings.pageWidth)}px`, minHeight: `${px(settings.pageHeight)}px`,
      padding: `${px(settings.marginTop)}px ${px(settings.marginRight)}px ${px(settings.marginBottom)}px ${px(settings.marginLeft)}px`, boxSizing: 'border-box' })
  }
  baseline = editor.getJSON(); ready = true
  const refresh = async () => {
    const content = replayDocxOperations(baseline, draft.operations, anchors, sectionAnchors, editor.schema, parsed.styles, { anchor: hfAnchor, model: hfModel })
    refreshing = true
    try { syncSection(); editor.commands.setContent(content as JSONContent, { emitUpdate: false }); editor.setEditable(context.editingEnabled && !saving && !draft.closed, false) }
    finally { refreshing = false }
  }
  const showPaginationPreview = () => {
    const currentSections = sections.map((item, index) => ({ ...item, settings: { ...sectionAnchors[index]!.settings, ...sectionValues(index) } }))
    const currentSection = currentSections[activeSection]!.settings
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
  /** 布局▸分隔符▸分节符（固定源 App.tsx insertSectionBreak）：插在光标所在顶层原有块之后。 */
  const insertSectionBreak = (type: SectionBreakType) => {
    try {
      if (saving || draft.saving || draft.closed || !context.editingEnabled) throw new Error('当前文档不可编辑或正在保存')
      const { $from } = editor.state.selection
      if ($from.depth < 1) throw new Error('请先将光标放在段落中')
      const top = editor.state.doc.child($from.index(0)), docxIndex = top.attrs.docxIndex
      if (docxIndex == null) throw new Error('请将光标放在原有段落或表格中，再插入分节符（新增内容请先保存）')
      const index = sectionAt(Number(docxIndex))
      if (pendingBreakIn(index)) throw new Error('此节已插入分节符，请先保存再继续分节')
      if (sectionOperation().some(operation => operation.sectionId === sectionAnchors[index]!.sectionId)) throw new Error('此节的页面设置修改请先保存，再插入分节符')
      editor.chain().insertContentAt($from.after(1), sectionBreakNode(type) as JSONContent).run()
    } catch (error) { reportError(error) }
  }
  const sectionRibbon = {
    settings: section,
    label: sections.length > 1 ? `第 1 节，共 ${sections.length} 节` : undefined as string | undefined,
    onSectionBreak: insertSectionBreak,
    onChange: (values: Partial<ReturnType<typeof readSectionSettings>>) => {
      if (saving || draft.saving || draft.closed || !context.editingEnabled) return
      try {
        const target = sectionAnchors[activeSection]!
        if (pendingBreakIn(activeSection)) throw new Error('此节已插入分节符，请先保存，再调整页面设置')
        const operation = restoredDocxSectionOperation([{ kind: 'setSectionLayout', sectionId: target.sectionId,
          expectedSectionSha256: target.expectedSectionSha256, values: { ...sectionValues(activeSection), ...values } }], target)
        const others = sectionOperation().filter(item => item.sectionId !== target.sectionId)
        draft.setOperations(docxOperations(baseline, editor.getJSON(), anchors, [...others, ...(operation ? [operation] : [])], editor.schema, parsed.styles, headerFooterOperations())); options.onDraftChange?.()
      } catch (error) { reportError(error) }
      syncSection()
      editor.commands.setMeta('native-section-layout', true)
    },
  }
  const view = createDocxViewCommands({ root: host, scroller: host.querySelector<HTMLElement>('.editor-scroll')!, page: editor.view.dom,
    pageSize: () => { const current = { ...sectionAnchors[activeSection]!.settings, ...sectionValues(activeSection) }; return { width: px(current.pageWidth), height: px(current.pageHeight) } },
    onPaginationPreview: showPaginationPreview })
  const headerFooter: DocxHeaderFooterController | undefined = hfModel ? {
    get editable() { return context.editingEnabled && !saving && !draft.saving && !draft.closed },
    anchor: hfAnchor,
    registerEditor: editor => { pendingHfEditor = editor },
    get model() {
      const current = { ...hfModel }
      for (const operation of headerFooterOperations()) {
        if (typeof operation.titlePg === 'boolean') current.titlePg = operation.titlePg
        if (typeof operation.evenAndOddHeaders === 'boolean') current.evenAndOddHeaders = operation.evenAndOddHeaders
      }
      return current
    },
    valueOf: (part: DocxHfPart, variant: DocxHfVariant) => {
      const partAnchor = hfModel.parts[`${part}.${variant}`]
      if (!partAnchor) return null
      const operation = headerFooterOperations().find(value => value.part === part && value.variant === variant)
      // 草稿重放携带已写入操作的统一对齐，后续再提交（切换选项/变体）不会丢失页码位置。
      const align = operation?.align as 'left' | 'center' | 'right' | undefined
      if (operation) return { value: { text: operation.text as string, paras: (operation.text as string).split('\n').map(text => ({ ...(align ? { align } : {}), runs: [{ text }] })), pageNumber: operation.pageNumber as boolean }, anchor: partAnchor }
      const info = partAnchor.rId ? parsed.hfParts?.[partAnchor.rId] : null
      return { value: { text: partAnchor.text, ...(info?.paras ? { paras: info.paras } : {}), pageNumber: partAnchor.hasPageNumber }, anchor: partAnchor }
    },
    onCommit: (part: DocxHfPart, variant: DocxHfVariant, value, flags?: DocxHfFlags) => {
      if (saving || draft.saving || draft.closed || !context.editingEnabled) return
      try {
        const partAnchor = hfModel.parts[`${part}.${variant}`]
        if (!partAnchor) throw new Error('页眉/页脚部件不受当前保存协议支持')
        const settings: DocxHfFlags = {}
        for (const previous of headerFooterOperations()) {
          for (const key of ['titlePg', 'evenAndOddHeaders', 'pageNumberFmt', 'pageNumberStart'] as const) {
            if (previous[key] !== undefined) Object.assign(settings, { [key]: previous[key] })
          }
        }
        const sourceParas = partAnchor.rId ? parsed.hfParts?.[partAnchor.rId]?.paras : undefined
        const operation = docxHeaderFooterOperation(hfAnchor, partAnchor, part, variant, value, { ...settings, ...flags }, sourceParas)
        draft.setOperations(operation ? mergeDocxHeaderFooterOperation(draft.operations, operation)
          : draft.operations.filter(operation => !(operation.kind === 'setHeaderFooter' && operation.part === part && operation.variant === variant)))
        options.onDraftChange?.()
      } catch (error) { reportError(error) }
    },
  } : undefined
  const findReplace = createDocxFindReplace({ editor, root: host, anchors, getBaseline: () => baseline,
    isLocked: () => saving || draft.saving || draft.closed || !context.editingEnabled,
    getSection: () => sectionAnchors, getSectionOperation: sectionOperation, styles: parsed.styles })
  toolbar.append(createDocxRibbon(editor, context.editingEnabled, showPaginationPreview, paragraphCommand, sectionRibbon, anchors, createDocxTableCommands(editor, baseline, anchors, reportError), view, findReplace.open, reportError, headerFooter))
  editor.on('transaction', view.refresh)
  await refresh()
  return { refresh, flushPendingEdits() { pendingHfEditor?.flush() }, setSaving(value: boolean) { saving = value; pendingHfEditor?.setEditable(!value && context.editingEnabled && !draft.closed); editor.setEditable(context.editingEnabled && !saving && !draft.closed, false); editor.commands.setMeta('native-section-layout', true); findReplace.refreshLock(); toolbar.querySelectorAll<HTMLButtonElement>('[data-mutates=true], [data-editable-action=true]').forEach(control => { control.disabled = !context.editingEnabled || saving || draft.closed }) },
    dispose() { ready = false; editor.off('transaction', view.refresh); findReplace.dispose(); view.dispose(); previewRoot.unmount(); editor.destroy(); void adoptEmbeddedFonts([]); host.remove() } }
}
