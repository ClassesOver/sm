// Adapted from GenOffice SettingsModal.tsx (Apache-2.0); see SOURCE.md.
import React, { useEffect, useRef, useState } from 'react'
import { SectionIcon } from './icons'
import './dialog.css'
export type Theme = 'system' | 'light' | 'dark'
export interface PersonalSettings { theme: Theme; skills: { id: string; name: string; description: string; enabled: boolean }[] }
export function AccountSettingsDialog({ username, settings, onSave, onClose, onLogout, onAssistantPreferences }: {
  username: string; settings: PersonalSettings; onSave(value: PersonalSettings): Promise<PersonalSettings>;
  onClose(): void; onLogout(): Promise<void>; onAssistantPreferences?(): void;
}) {
  const [section, setSection] = useState<'account' | 'general' | 'skills'>('account')
  const [draft, setDraft] = useState(settings), [baseline, setBaseline] = useState(settings)
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [message, setMessage] = useState('')
  const [confirm, setConfirm] = useState<'close' | 'logout' | null>(null)
  const ref = useRef<HTMLDivElement>(null)
  const dirty = JSON.stringify(draft) !== JSON.stringify(baseline)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    ref.current?.querySelector<HTMLButtonElement>('button')?.focus()
    return () => previous?.focus()
  }, [])
  useEffect(() => {
    if (!dirty) return
    const listener = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', listener)
    return () => window.removeEventListener('beforeunload', listener)
  }, [dirty])
  const logout = async () => { setBusy(true); setError(''); try { await onLogout(); onClose() } catch (e) { setError((e as Error).message) } finally { setBusy(false) } }
  const close = () => { if (busy) return; if (dirty) setConfirm('close'); else onClose() }
  const save = async () => {
    setBusy(true); setError(''); setMessage('')
    try { const value = await onSave(draft); setDraft(value); setBaseline(value); setMessage('已保存') }
    catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  return <div className="editor-account-settings"><div className="set-overlay" onMouseDown={event => { if (event.target === event.currentTarget) close() }}>
    <div ref={ref} className="set-dialog" role="dialog" aria-modal="true" aria-label="设置" onKeyDown={event => {
      event.stopPropagation()
      if (event.key === 'Escape') { event.preventDefault(); if (confirm) setConfirm(null); else close() }
      if (event.key === 'Tab') {
        const controls = [...ref.current!.querySelectorAll<HTMLElement>('button:not(:disabled),select:not(:disabled),input:not(:disabled),a[href]')]
        const first = controls[0], last = controls.at(-1)
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
      }
    }}>
      <div className="set-header"><h2 className="set-title">设置</h2><button className="set-close" onClick={close} disabled={busy} aria-label="关闭设置"><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M2 2l10 10M12 2L2 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg></button></div>
      <div className="set-body"><nav className="set-nav" aria-label="个人设置">{([{ id: 'account', label: '账户' }, { id: 'general', label: '偏好' }, { id: 'skills', label: 'Skill' }] as const).map(item => <button key={item.id} className={`set-nav-item${section === item.id ? ' active' : ''}`} aria-current={section === item.id} onClick={() => setSection(item.id)}><SectionIcon id={item.id} />{item.label}</button>)}</nav>
        <div className="set-pane"><h3 className="set-pane-title">{section === 'account' ? '账户' : section === 'general' ? '偏好' : 'Skill'}</h3>
          {section === 'account' && <><div className="set-field"><div className="set-field-text"><span className="set-field-label">账号</span><span className="set-field-value">{username}</span></div></div><div className="set-pane-footer"><button className="set-btn" disabled={busy} onClick={() => dirty ? setConfirm('logout') : void logout()}>退出登录</button></div></>}
          {section === 'general' && <label className="set-field"><span className="set-field-text">外观</span><select aria-label="外观" disabled={busy} value={draft.theme} onChange={e => { setDraft({ ...draft, theme: e.target.value as Theme }); setMessage('') }}><option value="system">跟随系统</option><option value="light">浅色</option><option value="dark">深色</option></select></label>}
          {section === 'general' && onAssistantPreferences && <button className="set-btn" onClick={onAssistantPreferences}>AI 助手界面偏好</button>}
          {section === 'skills' && <>{draft.skills.length === 0 && <p>暂无可用 Skill</p>}{draft.skills.map(skill => <label className="set-field" key={skill.id}><span className="set-field-text"><span><span className="set-field-label">{skill.name}</span><span className="set-field-desc">{skill.description}</span></span></span><input type="checkbox" aria-label={`启用 ${skill.name}`} checked={skill.enabled} disabled={busy} onChange={e => { setDraft({ ...draft, skills: draft.skills.map(x => x.id === skill.id ? { ...x, enabled: e.target.checked } : x) }); setMessage('') }} /></label>)}</>}
          {section !== 'account' && <div className="set-pane-footer"><button className="set-btn primary" disabled={!dirty || busy} onClick={() => void save()}>{busy ? '保存中…' : '保存'}</button></div>}
          {error && <p role="alert">{error}</p>}<p role="status">{message}</p>
          {confirm && <div className="set-confirm" role="alertdialog" aria-label="未保存的修改"><p>有未保存的修改，是否放弃？</p><button className="set-btn" onClick={() => setConfirm(null)}>继续编辑</button><button className="set-btn" disabled={busy} onClick={() => { const action = confirm; setConfirm(null); if (action === 'logout') void logout(); else onClose() }}>放弃修改</button></div>}
        </div>
      </div>
    </div>
  </div></div>
}
