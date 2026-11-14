// 真实 PDF 宿主与产品构造器；文件/来源模型由 smoke 使用真实引擎生成，授权和后端操作为显式夹具。
import { createPdfEditorView } from '../src/pdf-main'
import { createEditorShell } from '../src/shell'
import { NativeDraft } from '../src/native-draft'
import { pdfDrawingOperation } from '../src/pdf-operations'

export async function openPdfHostDialog(root, mode) {
  const source = window.officePdfFixtureContent
  if (!source) throw new Error('缺少 PDF 引擎来源夹具')
  const bytes = Uint8Array.from(atob(source.bytes), value => value.charCodeAt(0))
  const scope = { database: 'fixture', companyId: 'fixture', userId: 'fixture', threadId: 'fixture' }
  const identity = { documentId: 'pdf-dialog-' + mode, revision: 1, sourceSha256: source.model.sourceSha256, scope }
  const draft = new NativeDraft(identity, localStorage)
  const page = source.model.pages[0]
  if (mode === 'note-edit') draft.setOperations([{ kind: 'addTextAnnotation', pageId: page.pageId, rect: [70, 600, 94, 624], text: '年度经营报告的便签正文。'.repeat(20), createdMs: 1794412800000 }])
  if (mode === 'drawing-move' || mode === 'image-resize') {
    const image = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
    draft.setOperations([pdfDrawingOperation(page.pageId, mode === 'image-resize' ? 'image' : 'rect', [[72, 500], [180, 560]], page.cropBox, [1, 0, 0], { image })])
  }
  const shell = createEditorShell(root, 'full', 'pdf')
  const view = await createPdfEditorView(shell, { draft, context: {
    context: { documentId: identity.documentId, revision: 1, parentRevision: null, format: 'pdf', scope, origin: 'upload',
      sourceFile: { path: 'office-ui.pdf', size: bytes.length, sha256: identity.sourceSha256, mediaType: 'application/pdf' } },
    csrfToken: 'fixture', capabilities: { pdf_editor: true }, editingEnabled: true,
  }, api: {
    file: async () => bytes.buffer,
    preview: async request => {
      if (request.operations.length) throw new Error('组件检查不生成服务端预览')
      return { sourceSha256: identity.sourceSha256, draftSha256: identity.sourceSha256, model: structuredClone(source.model), appliedOperationIndices: [], skippedOperations: [] }
    },
  } })
  const click = async selector => {
    const button = root.querySelector(selector)
    if (!button || button.disabled) throw new Error('产品入口不可用：' + selector)
    button.click()
    await Promise.resolve()
  }
  const command = async (tab, id) => { await click(`[data-pdf-ribbon-tab="${tab}"]`); await click(`[data-source-command-id="genoffice.pdf.${id}"]`) }
  if (mode.startsWith('signature')) {
    await command('annotate', 'annotate.signature.sign')
    if (mode === 'signature-type') root.querySelector('.pdf-sign-tabs button:last-child').click()
  } else if (mode === 'stamp') {
    await command('edit', 'edit.objects.watermark')
    window.officeDialogFocusTarget = root.querySelector('[data-source-command-id="genoffice.pdf.edit.objects.watermark"]')
  }
  else if (['crop', 'size', 'merge', 'split'].includes(mode)) {
    await command('page', { crop: 'page.crop', size: 'page.size', merge: 'page.mergePages', split: 'page.splitPages' }[mode])
    if (mode === 'size' || mode === 'split') document.documentElement.dataset.primaryAction = 'none'
  } else if (mode === 'note-edit') await click('.pdf-pending-note button')
  else if (mode === 'drawing-move' || mode === 'image-resize') {
    await click('[data-pdf-ribbon-tab="annotate"]')
    const controls = [...root.querySelectorAll('button')]
    controls.find(button => button.textContent === '待保存绘图').click()
    await Promise.resolve()
    const selection = root.querySelector('.pdf-pending-drawings-panel [data-pdf-pending-drawing] button')
    if (!selection) throw new Error('未找到绘图选择入口：' + root.querySelector('.pdf-pending-drawings-panel')?.textContent)
    selection.click()
    ;[...root.querySelectorAll('.pdf-pending-drawings-panel button')].find(button => button.textContent === (mode === 'drawing-move' ? '移动所选绘图' : '缩放所选图像')).click()
  } else if (mode === 'link' || mode === 'measure') {
    // 交给 Playwright 真鼠标拖动创建区域，避免伪造 pointer capture。
    document.documentElement.dataset.pdfHostDraw = mode
  } else throw new Error('未知 PDF 宿主模式：' + mode)
  document.documentElement.dataset.pdfHostReady = 'true'
  return { view, draft }
}
