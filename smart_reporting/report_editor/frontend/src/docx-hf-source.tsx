import { useEffect, useRef, useState } from 'react'
import { PAGE_MARK, SECTION_PAGES_MARK, TOTAL_PAGES_MARK, type HeaderFooter, type HfParagraph } from '@genoffice/docx-engine'
import { insertHfField, mountHfEditor, type HfEditorHandle, type HfFieldKind } from './vendor/genoffice-docs/apps/docs/src/renderer/editor/hf-editor'
import { docxHfTextOf, type DocxHeadersFootersModel, type DocxHfFlags, type DocxHfPart, type DocxHfPartAnchor, type DocxHfSectionAnchor, type DocxHfVariant } from './docx-hf'

/** 页眉/页脚编辑面板：固定源 hf-editor 交互收敛——进入部件即挂载嵌套 TipTap 编辑器，
 *  PAGE/NUMPAGES 域为原子节点，退出（完成/失焦/Esc）即提交 setHeaderFooter 严格操作。 */

export interface DocxHfPendingEditor {
  flush(): void
  setEditable(editable: boolean): void
}

export interface DocxHeaderFooterController {
  editable: boolean
  registerEditor?: (editor: DocxHfPendingEditor | null) => void
  anchor: DocxHfSectionAnchor
  model: DocxHeadersFootersModel
  valueOf: (part: DocxHfPart, variant: DocxHfVariant) => { value: HeaderFooter; anchor: DocxHfPartAnchor } | null
  onCommit: (part: DocxHfPart, variant: DocxHfVariant, value: HeaderFooter, flags?: DocxHfFlags) => void
}

const stripPageMarks = (value: HeaderFooter): HeaderFooter => {
  const strip = (text: string) => text.split(PAGE_MARK).join('').split(TOTAL_PAGES_MARK).join('').split(SECTION_PAGES_MARK).join('')
  const paras: HfParagraph[] | undefined = value.paras?.map(para => para.cells ? para : {
    ...para,
    runs: para.runs.map(run => ({ ...run, text: strip(run.text) })).filter(run => run.text || run.image),
  })
  return { ...value, ...(paras ? { paras } : {}), text: strip(value.text), pageNumber: false }
}

const group = (label: string, children: React.ReactNode) => <section className="ribbon-group docx-ribbon-group" aria-label={label}><div className="ribbon-group-items">{children}</div><div className="ribbon-group-label">{label}</div></section>

export function DocxHeaderFooterSource({ controller }: { controller: DocxHeaderFooterController }) {
  const model = controller.model
  const [locked, setLocked] = useState(!controller.editable)
  const editable = controller.editable && !locked
  const [part, setPart] = useState<DocxHfPart>('header')
  const [variant, setVariant] = useState<DocxHfVariant>('default')
  const [editorReady, setEditorReady] = useState(false)
  const [, refresh] = useState(0)
  const effectiveVariant = variant === 'first' && !model.titlePg ? 'default' : variant === 'even' && !model.evenAndOddHeaders ? 'default' : variant
  const found = controller.valueOf(part, effectiveVariant)
  const host = useRef<HTMLDivElement | null>(null)
  const handle = useRef<HfEditorHandle | null>(null)
  const valueKey = found ? `${found.value.paras ? docxHfTextOf(found.value) : found.value.text}\u0000${found.value.pageNumber ?? false}\u0000${found.value.paras?.length ?? 0}` : 'missing'
  useEffect(() => {
    controller.registerEditor?.({
      flush: () => { const pending = handle.current?.changed(); if (pending) commit(pending) },
      setEditable: value => { handle.current?.editor.setEditable(value); setLocked(!value) },
    })
    return () => controller.registerEditor?.(null)
  }, [controller, part, effectiveVariant])
  useEffect(() => {
    const container = host.current
    if (!container || !found || !editable) { setEditorReady(false); return }
    const editorHost = document.createElement('div')
    container.replaceChildren(editorHost)
    const mounted = mountHfEditor(editorHost, {
      value: found.value, pageNo: '1', pageTotal: '1', spellcheck: false,
      onCommit: next => commit(next),
      onExit: () => { handle.current = null; setEditorReady(false) },
    })
    handle.current = mounted
    setEditorReady(true)
    return () => { mounted.discard(); if (handle.current === mounted) handle.current = null }
    // valueKey 只作挂载依据：提交后的新值重新挂载，未变化的值不重挂。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [part, effectiveVariant, valueKey, editable])
  const commit = (value: HeaderFooter, flags?: DocxHfFlags) => {
    if (!controller.editable) return
    controller.onCommit(part, effectiveVariant, value, flags)
    refresh(value => value + 1)
  }
  const insertField = (kind: HfFieldKind) => { if (handle.current) insertHfField(handle.current.editor, kind) }
  const pageNumberOnly = (align: 'left' | 'center' | 'right') => commit({ text: PAGE_MARK, pageNumber: true, paras: [{ align, runs: [{ text: PAGE_MARK }] }] })
  // 切换部件/变体先提交未退出的编辑（固定源"离开页眉条即提交"的收敛）。
  const currentValue = () => handle.current?.changed() ?? found?.value ?? { text: '' }
  const commitPending = () => { const pending = handle.current?.changed(); if (pending) commit(pending) }
  const variantTab = (id: DocxHfVariant, label: string, enabled: boolean) => (
    <button type="button" key={id} className={`rb-icon docx-ribbon-command${effectiveVariant === id ? ' active' : ''}`} disabled={!enabled || !editable}
      onClick={() => { commitPending(); setVariant(id) }} aria-pressed={effectiveVariant === id}>{label}</button>
  )
  return <div className="ribbon-content docx-source-headerfooter">
    {group('部件', <>
      <div className="docx-hf-tabs" role="group" aria-label="页眉页脚部件">
        <button type="button" className={`rb-icon docx-ribbon-command${part === 'header' ? ' active' : ''}`} disabled={!editable} onClick={() => { commitPending(); setPart('header') }} aria-pressed={part === 'header'}>页眉</button>
        <button type="button" className={`rb-icon docx-ribbon-command${part === 'footer' ? ' active' : ''}`} disabled={!editable} onClick={() => { commitPending(); setPart('footer') }} aria-pressed={part === 'footer'}>页脚</button>
      </div>
      <div className="docx-hf-tabs" role="group" aria-label="页眉页脚变体">
        {variantTab('default', '默认', true)}
        {variantTab('first', '首页', model.titlePg)}
        {variantTab('even', '偶数页', model.evenAndOddHeaders)}
      </div>
    </>)}
    {group('选项', <>
      <label className="docx-hf-option"><input type="checkbox" data-source-action="hf-title-page" aria-label="首页不同" checked={model.titlePg} disabled={!editable}
        onChange={event => commit(currentValue(), { titlePg: event.currentTarget.checked })} /><span>首页不同</span></label>
      <label className="docx-hf-option"><input type="checkbox" data-source-action="hf-even-odd" aria-label="奇偶页不同" checked={model.evenAndOddHeaders} disabled={!editable}
        onChange={event => commit(currentValue(), { evenAndOddHeaders: event.currentTarget.checked })} /><span>奇偶页不同</span></label>
    </>)}
    {group('页码', <>
      <button type="button" className="rb-icon docx-ribbon-command" data-source-action="hf-insert-page" disabled={!editable || !editorReady} onClick={() => insertField('PAGE')}>页码</button>
      <button type="button" className="rb-icon docx-ribbon-command" data-source-action="hf-insert-total" disabled={!editable || !editorReady} onClick={() => insertField('NUMPAGES')}>总页数</button>
      <button type="button" className="rb-icon docx-ribbon-command" data-source-action="hf-insert-section-pages" disabled={!editable || !editorReady} onClick={() => insertField('SECTIONPAGES')}>节页数</button>
      <label className="layout-num"><span>位置</span><select data-source-action="hf-page-number-position" aria-label="页码位置" defaultValue="" disabled={!editable}
        onChange={event => { const value = event.currentTarget.value as 'left' | 'center' | 'right' | ''; if (value) pageNumberOnly(value); event.currentTarget.value = '' }}>
        <option value="" disabled>选择位置</option><option value="left">左</option><option value="center">居中</option><option value="right">右</option>
      </select></label>
      <button type="button" className="rb-icon docx-ribbon-command" data-source-action="hf-remove-page-number" disabled={!editable || !found?.value} onClick={() => found && commit(stripPageMarks(found.value))}>删除页码</button>
    </>)}
    {group('编辑', <div className="docx-hf-editor-host" data-testid="docx-hf-editor-host" ref={host} />)}
    {!editable && <p className="docx-notice" role="status">当前文档不可编辑或正在保存。</p>}
  </div>
}
