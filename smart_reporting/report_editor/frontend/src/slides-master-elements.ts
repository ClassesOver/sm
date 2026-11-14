import { validateMasterElementDraft, type MasterElementEdit, type MasterTextBoxAddition } from './slides-master-elements-model'
import type { MasterTextPart, MasterTextRenderPart } from './slides-master-text-model'
import { mountMasterFillControls } from './slides-master-fill'
import { mountMasterTransformControls } from './slides-master-transform'
import { mountMasterStrokeControls } from './slides-master-stroke'

/** 源 MasterView 的文字框增删；只把完整候选交回宿主，历史和保存均由NativeDraft管理。 */
export function mountMasterElementControls(host: HTMLElement, options: {
  parts: MasterTextPart[]; renders: MasterTextRenderPart[]; edits: MasterElementEdit[]
  isCurrent(): boolean; onApply(edits: MasterElementEdit[]): void
}) {
  const container = document.createElement('div'); container.className = 'slides-master-elements'
  container.innerHTML = '<div class="slides-master-element-buttons"><button type="button" data-master-add-textbox>新增文字框</button><button type="button" data-master-delete-element>删除所选文字对象</button></div><ul data-master-new-items aria-label="待新增文字框"></ul><p data-master-element-status role="status"></p>'
  host.append(container)
  const list = container.querySelector<HTMLUListElement>('[data-master-new-items]')!, status = container.querySelector<HTMLElement>('[data-master-element-status]')!
  const add = container.querySelector<HTMLButtonElement>('[data-master-add-textbox]')!, remove = container.querySelector<HTMLButtonElement>('[data-master-delete-element]')!
  let part: MasterTextPart | undefined, selected: MasterTextPart['elements'][number] | undefined, editor: HTMLDialogElement | undefined, disposed = false
  const current = () => { if (disposed || !options.isCurrent()) throw Error('来源或草稿已变化，请关闭并重新打开母版视图') }
  const closeEditor = () => { if (!editor) return; if (typeof editor.close === 'function') editor.close(); editor.remove(); editor = undefined }
  const apply = (items: MasterElementEdit[]) => { current(); options.onApply(validateMasterElementDraft(items, options.parts)) }
  const report = (action: () => void) => { try { action() } catch (error) { status.textContent = error instanceof Error ? error.message : '文字对象修改未能加入草稿' } }
  const fillControls = mountMasterFillControls(container, { edits: options.edits, isCurrent: options.isCurrent, onApply: apply })
  const transformControls = mountMasterTransformControls(container, { edits: options.edits, isCurrent: options.isCurrent, onApply: apply })
  const strokeControls = mountMasterStrokeControls(container, { edits: options.edits, isCurrent: options.isCurrent, onApply: apply })
  const openEditor = (original?: MasterTextBoxAddition) => report(() => {
    current(); if (!part?.structureEditable) return
    closeEditor()
    const slide = options.renders.find(render => render.partPath === part!.partPath)?.slide
    const item: MasterTextBoxAddition = original ? structuredClone(original) : { kind: 'addTextBox', partPath: part.partPath, clientId: `master-${crypto.randomUUID()}`, text: '', box: { x: 48, y: 48, width: Math.min(480, Math.max(1, (slide?.widthPx ?? 960) - 96)), height: 96 } }
    editor = document.createElement('dialog'); editor.className = 'slides-master-element-editor'; editor.setAttribute('aria-label', original ? '修改待新增文字框' : '新增母版或版式文字框')
    editor.innerHTML = '<h2>母版/版式文字框</h2><p>位置与尺寸单位为幻灯片96dpi像素，沿用源文字框默认样式。采纳后可撤销，尚未保存文件。</p><label>文字<textarea name="text" rows="4" maxlength="20000"></textarea></label><div class="slides-master-element-box"></div><p role="status"></p><div class="slides-master-text-actions"><button type="button" data-master-element-cancel>取消</button><button type="button" data-master-element-apply>应用文字框到草稿</button></div>'
    host.append(editor)
    const dialog = editor, text = dialog.querySelector<HTMLTextAreaElement>('[name=text]')!, message = dialog.querySelector<HTMLElement>('[role=status]')!, confirm = dialog.querySelector<HTMLButtonElement>('[data-master-element-apply]')!
    text.value = item.text
    for (const [name, label] of [['x', '横向位置'], ['y', '纵向位置'], ['width', '宽度'], ['height', '高度']] as const) {
      const field = document.createElement('label'); field.textContent = label
      const input = document.createElement('input'); input.type = 'number'; input.name = name; input.min = '0'; input.max = '100000'; input.step = 'any'; input.value = String(item.box[name]); field.append(input); dialog.querySelector('.slides-master-element-box')!.append(field)
    }
    let composing = false
    text.addEventListener('compositionstart', () => { composing = true; confirm.disabled = true })
    text.addEventListener('compositionend', () => { composing = false; confirm.disabled = false })
    confirm.addEventListener('click', () => {
      if (composing || disposed || !dialog.isConnected) return
      try {
        const box = Object.fromEntries(['x', 'y', 'width', 'height'].map(name => { const value = dialog.querySelector<HTMLInputElement>(`[name=${name}]`)!.value; return [name, value.trim() ? Number(value) : NaN] })) as MasterTextBoxAddition['box']
        const updated = { ...item, text: text.value.replace(/\r\n?/g, '\n'), box }
        const edits = options.edits.filter(edit => edit.kind !== 'addTextBox' || edit.clientId !== item.clientId)
        if (original && JSON.stringify(updated) === JSON.stringify(original)) { closeEditor(); return }
        // 保持原新框在事务中的顺序，修改不会另建第二个框或改变自动SPID分配。
        if (original) edits.splice(options.edits.indexOf(original), 0, updated); else edits.push(updated)
        apply(edits)
      } catch (error) { message.textContent = error instanceof Error ? error.message : '文字框未能加入草稿' }
    })
    dialog.querySelector('[data-master-element-cancel]')!.addEventListener('click', closeEditor)
    dialog.addEventListener('cancel', event => { event.preventDefault(); closeEditor() })
    if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open', '')
  })
  add.addEventListener('click', () => openEditor())
  remove.addEventListener('click', () => report(() => { if (part && selected?.editable) apply([...options.edits.filter(edit => !('spid' in edit && edit.partPath === part!.partPath && edit.spid === selected!.spid)), { kind: 'delete', partPath: part.partPath, spid: selected.spid }]) }))
  return {
    update(value?: MasterTextPart, element?: MasterTextPart['elements'][number]) {
      part = value; selected = element; add.disabled = !part?.structureEditable; remove.disabled = !part?.structureEditable || !selected?.editable
      fillControls.update(part, selected)
      transformControls.update(part, selected)
      strokeControls.update(part, selected)
      list.replaceChildren()
      for (const item of options.edits) if (item.kind === 'addTextBox' && item.partPath === part?.partPath) {
        const row = document.createElement('li'); row.dataset.masterAdded = item.clientId
        const label = document.createElement('span'); label.textContent = `待新增：${item.text.slice(0, 40) || '空文字框'}`
        const edit = document.createElement('button'); edit.type = 'button'; edit.dataset.masterEditNew = ''; edit.textContent = '修改文字/位置尺寸'; edit.addEventListener('click', () => openEditor(item))
        const discard = document.createElement('button'); discard.type = 'button'; discard.dataset.masterRemoveNew = ''; discard.textContent = '移除此新框'; discard.addEventListener('click', () => report(() => apply(options.edits.filter(entry => entry !== item))))
        row.append(label, edit, discard); list.append(row)
      }
    },
    dispose() { disposed = true; closeEditor(); fillControls.dispose(); transformControls.dispose(); strokeControls.dispose(); container.remove() },
  }
}
