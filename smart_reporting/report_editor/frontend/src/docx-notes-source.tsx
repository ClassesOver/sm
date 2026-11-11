import { IconFootnote, IconEndnote, IconPencil, IconTrash, IconAiPanel } from './vendor/genoffice-docs/apps/docs/src/renderer/components/icons'
import { useState } from 'react'
import { createModal } from './modal'

export type DocxNoteKind = 'footnote' | 'endnote'
export interface DocxNotesController {
  readonly editable: boolean
  readonly insertReason?: string
  readonly entries: readonly { kind: DocxNoteKind; id: string; text: string; editable: boolean; pending?:boolean; readOnlyReason?: string; canDelete?: boolean; deleteReason?: string }[]
  aiInsert?(): void
  aiEdit?(kind:DocxNoteKind,id:string): void
  insert(kind: DocxNoteKind): void
  edit(kind: DocxNoteKind, id: string): void
  remove(kind: DocxNoteKind, id: string): void
}

/** 固定源 References 的脚注/尾注入口；编辑使用来源部件身份，列表不改变引用顺序。 */
export function DocxNotesSource({ controller }: { controller: DocxNotesController }) {
  const [selected, setSelected] = useState('')
  const entry = controller.entries.find(note => JSON.stringify([note.kind, note.id]) === selected)
  const reason = !controller.editable ? '当前文档不可编辑或正在保存' : entry?.readOnlyReason
  return <section className="ribbon-group docx-ribbon-group" aria-label="脚注和尾注">
    <div className="ribbon-group-items">
      {(['footnote', 'endnote'] as const).map(kind => <button key={kind} type="button" className="rb-icon docx-source-command" data-note-action={`insert-${kind}`}
        disabled={!controller.editable || !!controller.insertReason} title={controller.insertReason ?? (kind === 'footnote' ? '插入脚注' : '插入尾注')}
        onMouseDown={event => event.preventDefault()} onClick={() => controller.insert(kind)}>{kind === 'footnote' ? <IconFootnote size={16} /> : <IconEndnote size={16} />}{kind === 'footnote' ? '插入脚注' : '插入尾注'}</button>)}
      {controller.aiInsert && <button type="button" className="rb-icon docx-source-command" data-note-action="ai-insert" disabled={!controller.editable || !!controller.insertReason}
        title={controller.insertReason ?? '仅授权当前段落插入脚注或尾注'} onMouseDown={event=>event.preventDefault()} onClick={()=>controller.aiInsert?.()}><IconAiPanel size={16}/>AI 新增注释</button>}
      <label>已有注释<select aria-label="已有脚注和尾注" value={entry ? selected : ''} onChange={event => setSelected(event.currentTarget.value)}>
        <option value="">选择脚注或尾注</option>
        {controller.entries.map(note => <option key={JSON.stringify([note.kind, note.id])} value={JSON.stringify([note.kind, note.id])}>
          {note.kind === 'footnote' ? '脚注' : '尾注'} {note.id}：{note.text.slice(0, 40)}
        </option>)}
      </select></label>
      <button type="button" className="rb-icon docx-source-command" data-note-action="edit" disabled={!entry || !entry.editable || !controller.editable}
        title={reason ?? '编辑注释'} onClick={() => entry && controller.edit(entry.kind, entry.id)}><IconPencil size={16} />编辑注释</button>
      <button type="button" className="rb-icon docx-source-command" data-note-action="delete" disabled={!entry || !(entry.canDelete ?? entry.editable) || !controller.editable}
        title={!controller.editable ? '当前文档不可编辑或正在保存' : entry && !(entry.canDelete ?? entry.editable) ? entry.deleteReason ?? '此注释的正文引用暂不能安全修改' : '删除注释及其正文引用'} onClick={() => entry && controller.remove(entry.kind, entry.id)}><IconTrash size={16} />删除注释</button>
      {controller.aiEdit && <button type="button" className="rb-icon docx-source-command" data-note-action="ai-edit" disabled={!entry || !entry.editable || !controller.editable}
        title={reason ?? '仅授权当前脚注或尾注，核对候选后采纳'} onClick={()=>entry&&controller.aiEdit?.(entry.kind,entry.id)}><IconAiPanel size={16}/>AI 处理注释</button>}
    </div>
    <div className="ribbon-group-label">脚注和尾注</div>
  </section>
}

/** 模态框只保存打开时捕获的提交目标，光标移动不改变插入位置。 */
export function createDocxNoteDialog(root: HTMLElement) {
  const modal = createModal({ root, label: '脚注和尾注', closeLabel: '关闭注释', cardClass: 'workbook-ribbon-note-dialog', content: `
    <h2></h2><form class="workbook-ribbon-note-form">
      <label>注释内容<textarea aria-label="注释内容" rows="6" maxlength="20000"></textarea></label>
      <p role="alert"></p><div class="workbook-ribbon-note-actions">
        <button type="button" data-action="cancel">取消</button><button type="submit">确定</button>
      </div>
    </form>` })
  const input = modal.card.querySelector<HTMLTextAreaElement>('textarea')!
  const error = modal.card.querySelector<HTMLElement>('[role="alert"]')!
  let commit: ((text: string) => void) | undefined
  modal.card.querySelector('[data-action="cancel"]')!.addEventListener('click', modal.close)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    try {
      if (!commit) throw new Error('请重新打开注释')
      commit(input.value)
      modal.close()
    } catch (cause) { error.textContent = (cause as Error).message }
  })
  return {
    open(title: string, text: string, apply: (text: string) => void) {
      commit = apply; input.value = text; error.textContent = ''
      modal.card.querySelector('h2')!.textContent = title
      modal.open(input)
    },
    dispose: modal.remove,
  }
}
