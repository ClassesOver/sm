import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { ConfigProvider, Form, Input, Select, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { officeRequest } from './office-client'
import { CommonStyleFields } from './management/features/configuration/common-style'
import { SignatureStyleFields } from './management/features/configuration/signature-style'
import { PagePreferenceFields, HeaderFooterFields } from './management/features/configuration/document-fields'
import { WorkbookLayoutFields } from './management/features/configuration/workbook-layout'
import { TypographyFields } from './management/features/configuration/typography'
import { TablePreferenceFields } from './management/features/configuration/table-editor'
import { getPreferenceValue, setPreferenceValue, validateSignatureDraft } from './management/features/configuration/preference-draft'
import './office-document-preferences.css'
type Value = { version: number; document: Record<string, unknown> }
const formats = [{ value: 'common', label: '通用' }, { value: 'word', label: '文档' }, { value: 'xlsx', label: '表格' }, { value: 'pptx', label: '演示' }, { value: 'pdf', label: 'PDF' }]
export function DocumentPreferencesPanel({ initial, save, close }: { initial: Value; save(value: Value): Promise<Value>; close(): void }) {
  const [draft, setDraft] = useState(initial), [baseline, setBaseline] = useState(initial)
  const [format, setFormat] = useState('common'), [section, setSection] = useState('style')
  const [busy, setBusy] = useState(false), [message, setMessage] = useState(''), [error, setError] = useState('')
  const [confirm, setConfirm] = useState(false)
  const dirty = JSON.stringify(draft.document) !== JSON.stringify(baseline.document)
  const errors = validateSignatureDraft(draft.document)
  useEffect(() => {
    if (!dirty) return
    const listener = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', listener)
    return () => window.removeEventListener('beforeunload', listener)
  }, [dirty])
  const change = (path: string[], value: unknown) => { setDraft(previous => ({ ...previous, document: setPreferenceValue(previous.document, path, value) })); setMessage('') }
  const props = { document: draft.document, format, onChange: change, disabled: busy, errors }
  const prefix = format === 'common' ? ['common'] : [format, 'common']
  const requestClose = () => { if (!busy) { if (dirty) setConfirm(true); else close() } }
  const active = format === 'common' ? 'style' : section
  return <div className="office-document-preferences" onKeyDown={event => { event.stopPropagation(); if (event.key === 'Escape') { event.preventDefault(); requestClose() } }}>
    <header><h2>文档偏好</h2><button data-preferences-close disabled={busy} onClick={requestClose}>关闭</button></header>
    <p>仅对你的后续 AI 排版生效，不改写现有文档。</p>
    <nav className="office-format-tabs" role="tablist" aria-label="文档类型" onKeyDown={event => {
      const index = formats.findIndex(item => item.value === format)
      const next = event.key === 'ArrowRight' ? (index + 1) % formats.length : event.key === 'ArrowLeft' ? (index + formats.length - 1) % formats.length : event.key === 'Home' ? 0 : event.key === 'End' ? formats.length - 1 : -1
      if (next >= 0 && !busy) { event.preventDefault(); setFormat(formats[next].value); event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus() }
    }}>{formats.map(item => <button key={item.value} id={'preference-tab-' + item.value} role="tab" aria-selected={format === item.value} aria-controls="office-document-panel" tabIndex={format === item.value ? 0 : -1} disabled={busy} onClick={() => setFormat(item.value)}>{item.label}</button>)}</nav>
    <nav className="office-section-tabs" aria-label="文档偏好分类">{(format === 'common' ? [['style', '字体与落款']] : [['style', '字体与落款'], ['page', '页面与排版'], ['headerFooter', '页眉页脚'], ['tables', '表格']]).map(([key, label]) => <button key={key} aria-current={active === key} onClick={() => setSection(key)}>{label}</button>)}</nav>
    <div className="office-document-fields" role="tabpanel" id="office-document-panel" aria-labelledby={'preference-tab-' + format} key={format + active}>
      {active === 'style' && <><Form layout="vertical" disabled={busy}><CommonStyleFields {...props} />
        <Form.Item label="署名"><Input aria-label="署名" maxLength={200} value={String(getPreferenceValue(draft.document, [...prefix, 'signer']) ?? '')} onChange={e => change([...prefix, 'signer'], e.target.value)} /></Form.Item>
        <Form.Item label="日期格式"><Select aria-label="日期格式" value={getPreferenceValue(draft.document, [...prefix, 'dateFormat']) as string} options={[{ value: 'chinese', label: '中文日期' }, { value: 'iso', label: 'YYYY-MM-DD' }, { value: 'slash', label: 'YYYY/MM/DD' }]} onChange={value => change([...prefix, 'dateFormat'], value)} /></Form.Item>
        {format !== 'common' && <><button type="button" disabled={busy} onClick={() => { change([...prefix, 'signer'], null); change([...prefix, 'dateFormat'], null) }}>署名和日期沿用通用偏好</button><Form.Item label="落款说明"><Input.TextArea aria-label="落款说明" maxLength={600} value={String(getPreferenceValue(draft.document, [format, 'signature', 'description']) ?? '')} onChange={e => change([format, 'signature', 'description'], e.target.value)} /></Form.Item></>}
      {format !== 'common' && <SignatureStyleFields {...props} />}</Form></>}
      {active === 'page' && <><PagePreferenceFields {...props} /><details className="office-preferences-details"><summary>文字排版</summary><TypographyFields {...props} /></details>{format === 'xlsx' && <details className="office-preferences-details"><summary>行列布局</summary><WorkbookLayoutFields {...props} /></details>}</>}
      {active === 'headerFooter' && <HeaderFooterFields {...props} />}
      {active === 'tables' && <TablePreferenceFields {...props} />}
    </div>
    {errors.length > 0 && <p role="alert">{errors[0].message}</p>}{error && <p role="alert">{error}</p>}<p role="status">{message}</p>
    <footer><button disabled={busy || !dirty || errors.length > 0} onClick={async () => {
      setBusy(true); setError(''); setMessage('')
      try { const result = await save(draft); setDraft(result); setBaseline(result); setMessage('已保存') }
      catch (e) { setError((e as Error).message) } finally { setBusy(false) }
    }}>{busy ? '保存中…' : '保存文档偏好'}</button></footer>
    {confirm && <div role="alertdialog" aria-label="未保存的文档偏好"><p>有未保存的修改，是否放弃？</p><button onClick={() => setConfirm(false)}>继续编辑</button><button onClick={close}>放弃修改</button></div>}
  </div>
}
export async function showOfficeDocumentPreferences(isCurrent: () => boolean) {
  const initial = await officeRequest<Value>('/settings/document-preferences')
  if (!isCurrent()) return
  const opener = document.activeElement as HTMLElement | null
  const dialog = document.createElement('dialog'); dialog.className = 'office-document-preferences-host'
  dialog.setAttribute('aria-label', '文档偏好')
  document.body.append(dialog)
  const root = createRoot(dialog)
  const expired = () => dialog.close()
  window.addEventListener('genoffice-session-expired', expired)
  dialog.oncancel = event => { event.preventDefault(); dialog.querySelector<HTMLButtonElement>('[data-preferences-close]')?.click() }
  dialog.onclose = () => { window.removeEventListener('genoffice-session-expired', expired); root.unmount(); dialog.remove(); opener?.focus() }
  dialog.showModal()
  root.render(<ConfigProvider locale={zhCN} getPopupContainer={trigger => trigger?.closest('dialog') || dialog} theme={{ algorithm: document.documentElement.dataset.officeTheme === 'dark' ? theme.darkAlgorithm : theme.defaultAlgorithm }}><DocumentPreferencesPanel initial={initial} close={() => dialog.close()} save={async value => {
    if (!isCurrent()) throw new Error('账户已变化，请重新打开设置。')
    const saved = await officeRequest<Value>('/settings/document-preferences', 'PUT', { document: value.document, expectedVersion: value.version })
    if (!isCurrent()) throw new Error('账户已变化，请重新打开设置。')
    return saved
  }} /></ConfigProvider>)
}
