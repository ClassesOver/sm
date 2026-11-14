import React from 'react'
import { createRoot } from 'react-dom/client'
import { SlideViewThumbnail } from './slides-view-modes'
import './slides-master-text.css'
import { mountMasterElementControls } from './slides-master-elements'
import type { MasterElementEdit } from './slides-master-elements-model'
import { extractMasterRichText, masterRichTextHtml } from './slides-master-rich-text'

import { validateMasterTextDraft, type MasterTextEdit, type MasterTextPart, type MasterTextRenderPart } from './slides-master-text-model'

/** 固定源 MasterView 的部件选择和文字提交语义；保存与历史仍由宿主负责。 */
export function openSlidesMasterText(host: HTMLElement, options: {
  parts: MasterTextPart[]; edits: MasterTextEdit[]; renders: MasterTextRenderPart[]
  isCurrent(): boolean; onApply(edits: MasterTextEdit[]): void; onClose(): void
  elements?: { edits: MasterElementEdit[]; onApply(edits: MasterElementEdit[]): void }
}) {
  const opener = document.activeElement instanceof HTMLElement ? document.activeElement : undefined
  const dialog = document.createElement('dialog'); dialog.className = 'slides-master-text-dialog'
  dialog.setAttribute('aria-label', '母版和版式文字编辑')
  dialog.innerHTML = '<h2>母版和版式文字</h2><p class="slides-master-text-note">修改当前文件内已有的顶层文字对象，继承该母版或版式的页面会一起刷新。选中文字后可设置粗体、斜体和下划线；未修改的 run 沿用源格式，动态字段可能在 PowerPoint 中重新计算。支持在现有部件中新增文字框、修改待新增框的文字与位置尺寸，以及删除顶层文字对象；组内文字和其他母版结构操作暂不在此入口。</p><div class="slides-master-text-grid"><nav aria-label="母版和版式部件"></nav><section><div class="slides-master-text-preview"></div><label>文字对象<select data-master-element></select></label><div class="slides-master-rich-tools" role="toolbar" aria-label="文字格式"><button type="button" data-master-mark="bold" aria-label="粗体"><strong>B</strong></button><button type="button" data-master-mark="italic" aria-label="斜体"><em>I</em></button><button type="button" data-master-mark="underline" aria-label="下划线"><u>U</u></button></div><div data-master-rich-text role="textbox" aria-label="母版文字" contenteditable="true" spellcheck="false"></div><p data-master-status role="status"></p></section></div><div class="slides-master-text-actions"><button type="button" data-master-close>关闭母版视图</button><button type="button" data-master-apply>应用文字到草稿</button></div>'
  host.append(dialog)
  const nav = dialog.querySelector('nav')!, select = dialog.querySelector<HTMLSelectElement>('[data-master-element]')!, text = dialog.querySelector<HTMLElement>('[data-master-rich-text]')!, status = dialog.querySelector<HTMLElement>('[data-master-status]')!, apply = dialog.querySelector<HTMLButtonElement>('[data-master-apply]')!
  const preview = createRoot(dialog.querySelector('.slides-master-text-preview')!)
  let part = options.parts[0], composing = false, disposed = false
  let elementControls: ReturnType<typeof mountMasterElementControls> | undefined
  const selected = () => part?.elements.find(el => String(el.spid) === select.value)
  const renderText = () => {
    const element = selected()
    const edit = options.edits.find(item => item.partPath === part?.partPath && item.spid === element?.spid)
    const paragraphs = edit?.paragraphs ?? element?.paragraphs ?? [{ runs: [{ srcRun: 0, text: edit?.text ?? element?.text ?? '' }] }]
    text.innerHTML = masterRichTextHtml(paragraphs)
    text.contentEditable = String(!!element?.editable); apply.disabled = !element?.editable || composing
    status.textContent = element?.reason ?? (element ? '采纳后进入同一草稿，可撤销；尚未保存文件。' : '当前部件没有可编辑的顶层文字。')
    elementControls?.update(part, element)
  }
  const renderPart = () => {
    select.replaceChildren(...(part?.elements ?? []).filter(el => !options.elements?.edits.some(edit => edit.kind === 'delete' && edit.partPath === part?.partPath && edit.spid === el.spid)).map(el => { const option = document.createElement('option'); option.value = String(el.spid); option.textContent = `${el.name}${el.editable ? '' : el.fillEditable ? '（文字只读）' : '（只读）'}`; return option }))
    for (const button of nav.querySelectorAll('button')) button.setAttribute('aria-pressed', String(button.dataset.masterPart === part?.partPath))
    const slide = options.renders.find(item => item.partPath === part?.partPath)?.slide
    preview.render(<SlideViewThumbnail slide={slide} width={Math.min(650, Math.max(220, window.innerWidth - 420))} />)
    renderText()
  }
  for (const item of options.parts) {
    const button = document.createElement('button'); button.type = 'button'; button.dataset.masterPart = item.partPath
    button.textContent = `${item.kind === 'master' ? '母版' : '版式'} · ${item.name}`
    button.addEventListener('click', () => { if (!disposed && !composing) { part = item; renderPart() } }); nav.append(button)
  }
  select.addEventListener('change', () => { if (!composing) renderText() })
  text.addEventListener('compositionstart', () => { composing = true; apply.disabled = true })
  text.addEventListener('compositionend', () => { composing = false; apply.disabled = !selected()?.editable })
  for (const button of dialog.querySelectorAll<HTMLButtonElement>('[data-master-mark]')) button.addEventListener('mousedown', event => event.preventDefault())
  for (const button of dialog.querySelectorAll<HTMLButtonElement>('[data-master-mark]')) button.addEventListener('click', () => {
    if (disposed || composing || !selected()?.editable) return
    text.focus()
    document.execCommand(button.dataset.masterMark === 'bold' ? 'bold' : button.dataset.masterMark === 'italic' ? 'italic' : 'underline')
  })
  const close = () => { if (disposed) return; disposed = true; elementControls?.dispose(); preview.unmount(); if (typeof dialog.close === 'function') dialog.close(); dialog.remove(); options.onClose(); opener?.focus({ preventScroll: true }) }
  if (options.elements) elementControls = mountMasterElementControls(dialog.querySelector('section')!, { parts: options.parts, renders: options.renders, edits: options.elements.edits, isCurrent: () => !composing && options.isCurrent(), onApply(items) { options.elements!.onApply(items); close() } })
  apply.addEventListener('click', () => {
    if (disposed || composing || !part || !selected()?.editable) return
    if (!options.isCurrent()) { status.textContent = '来源或草稿已变化，请关闭并重新打开母版视图'; return }
    try {
      const element = selected()!, paragraphs = extractMasterRichText(text)
      const edits = options.edits.filter(edit => edit.partPath !== part!.partPath || edit.spid !== element.spid)
      const baseline = normalizeParagraphs(element.paragraphs ?? [{ runs: [{ srcRun: 0, text: element.text }] }])
      if (JSON.stringify(paragraphs) !== JSON.stringify(baseline)) edits.push({ partPath: part.partPath, spid: element.spid, paragraphs })
      validateMasterTextDraft(edits, options.parts)
      if (JSON.stringify(edits) !== JSON.stringify(options.edits)) options.onApply(edits)
      close()
    } catch (error) { status.textContent = error instanceof Error ? error.message : '母版文字未能加入草稿' }
  })
  dialog.querySelector('[data-master-close]')!.addEventListener('click', close)
  dialog.addEventListener('cancel', event => { event.preventDefault(); close() })
  renderPart(); if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open', '')
  return { dispose: close }
}

function normalizeParagraphs(paragraphs: NonNullable<MasterTextPart['elements'][number]['paragraphs']>) {
  const root = document.createElement('div')
  root.innerHTML = masterRichTextHtml(paragraphs)
  return extractMasterRichText(root)
}
