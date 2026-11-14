import { createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import type { Editor } from '@tiptap/core'
import { NodeSelection } from '@tiptap/pm/state'
import { closeHistory } from '@tiptap/pm/history'
import { CropDialog, CutoutDialog } from './docx-picture-dialogs-source'
import { projectDocxPicture, projectPendingDocxPicture } from './docx-pictures'
import type { DocxAnchor } from './docx-operations'

export type DocxPictureAction = 'replace' | 'crop' | 'cutout'
export function createDocxPictureControls(editor: Editor, anchors: DocxAnchor[], host: HTMLElement,
  locked: () => string | null, reportError: (error: unknown) => void) {
  let modal: HTMLElement | undefined, root: Root | undefined, active = true, generation = 0
  const selected = () => {
    const selection = editor.state.selection
    if (!(selection instanceof NodeSelection) || selection.node.type.name !== 'docProtected' || selection.node.attrs.blockType !== 'image') return null
    const anchor = anchors.find(item => item.docxIndex === selection.node.attrs.docxIndex)
    return anchor || selection.node.attrs.docxIndex == null && selection.node.attrs.genImage ? { node: selection.node, pos: selection.from, anchor } : null
  }
  const reason = () => locked() ?? (!editor.isEditable ? '当前文档不可编辑' : null) ?? (selected()?.anchor?.imageEditable || selected()?.node.attrs.genImage && selected()?.node.attrs.docxIndex == null ? null : selected()?.anchor?.imageReadOnlyReason ?? '请选择可编辑的整块图片；内联图片与组合对象保持只读')
  const close = () => { generation++; root?.unmount(); root = undefined; modal?.remove(); modal = undefined }
  const open = (action: DocxPictureAction) => {
    try {
      const unavailable = reason(); if (unavailable) throw new Error(unavailable)
      close()
      const target = selected()!, snapshot = editor.state.doc, ticket = generation
      const current = () => active && generation === ticket && !editor.isDestroyed && !locked() && editor.isEditable
        && editor.state.doc === snapshot && selected()?.node === target.node && selected()?.pos === target.pos
      const apply = async (dataUrl: string) => {
        try {
          let match = /^data:(image\/(?:png|jpeg|gif));base64,([A-Za-z0-9+/=]+)$/.exec(dataUrl)
          if (!match) throw new Error('仅支持 PNG、JPEG 或 GIF 图片')
          const image = new Image(); await new Promise<void>((resolve, reject) => { image.onload = () => resolve(); image.onerror = () => reject(new Error('图片无法读取')); image.src = dataUrl })
          if (!current()) throw new Error('文档或图片选择已变化，请重新打开图片工具')
          // 源genImage分支继续复用宿主PNG/JPEG插入协议；GIF在浏览器烘焙为PNG。
          if (!target.anchor && match[1] === 'image/gif') {
            const canvas = document.createElement('canvas'); canvas.width = image.naturalWidth; canvas.height = image.naturalHeight
            canvas.getContext('2d')!.drawImage(image, 0, 0); match = /^data:(image\/(?:png|jpeg|gif));base64,([A-Za-z0-9+/=]+)$/.exec(canvas.toDataURL('image/png'))!
          }
          const operation = { kind: 'replaceImage', blockId: target.anchor?.blockId, expectedObjectSha256: target.anchor?.expectedObjectSha256,
            expectedImageSha256: target.anchor?.imageSha256, image: { mime: match[1], base64: match[2], widthPx: image.naturalWidth, heightPx: image.naturalHeight } }
          const projected = target.anchor ? projectDocxPicture(target.node.toJSON(), target.anchor, operation) : projectPendingDocxPicture(target.node.toJSON(), operation.image)
          editor.view.dispatch(closeHistory(editor.state.tr).setNodeMarkup(target.pos, undefined, projected.attrs))
          close()
        } catch (error) { reportError(error) }
      }
      if (action === 'replace') {
        const input = document.createElement('input'); input.type = 'file'; input.accept = 'image/png,image/jpeg,image/gif'
        input.addEventListener('change', async () => {
          try {
            const file = input.files?.[0]; if (!file) return
            if (file.size > 8 * 1024 * 1024) throw new Error('图片超过 8MB 大小上限')
            const reader = new FileReader(); const dataUrl = await new Promise<string>((resolve, reject) => { reader.onload = () => resolve(String(reader.result)); reader.onerror = () => reject(new Error('图片无法读取')); reader.readAsDataURL(file) })
            await apply(dataUrl)
          } catch (error) { reportError(error) }
        }, { once: true }); input.click(); return
      }
      modal = document.createElement('div'); modal.className = 'docx-picture-dialog-host'; host.append(modal); root = createRoot(modal)
      root.render(createElement(action === 'crop' ? CropDialog : CutoutDialog, { dataUrl: String(target.node.attrs.imageDataUrl), onCancel: close, onApply: (value: string) => { void apply(value) } }))
    } catch (error) { reportError(error) }
  }
  return { reason, open, dispose() { active = false; close() } }
}
