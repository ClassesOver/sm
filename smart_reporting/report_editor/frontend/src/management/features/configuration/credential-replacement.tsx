import { useState } from 'react'
import { Alert, Button, Input, Modal, Space, Tag } from 'antd'
import { request } from '../../api/http'
import { savedSchema } from './contracts'

export function CredentialReplacement({ credentialKey, label, configured, version, csrf, disabled, onSaved }: {
  credentialKey: string; label: string; configured: boolean; version: number; csrf: string; disabled: boolean; onSaved: () => Promise<void>
}) {
  const [open, setOpen] = useState(false), [secret, setSecret] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('')
  function close() { setOpen(false); setSecret(''); setError('') }
  async function save() {
    setBusy(true); setError('')
    try {
      await request('/configuration/system/credentials/' + credentialKey, savedSchema,
        { method: 'PUT', csrf, body: { expectedVersion: version, secret } })
      setSecret(''); await onSaved(); close()
    } catch (reason) { setSecret(''); setError((reason as Error).message) } finally { setBusy(false) }
  }
  return <><Space wrap><Tag>{configured ? '已配置 · 内容不回显' : '未配置'}</Tag>
    <Button size="small" aria-label={'替换' + label} disabled={disabled} onClick={() => setOpen(true)}>替换</Button></Space>
    <Modal rootClassName="management-overlay" open={open} title={'替换' + label} destroyOnHidden
      okText="保存新凭据到草稿" okButtonProps={{ 'aria-label': '保存新凭据到草稿', disabled: !secret.trim() }}
      cancelText="取消" confirmLoading={busy} closable={!busy} mask={{ closable: !busy }} keyboard={!busy}
      cancelButtonProps={{ disabled: busy }} onCancel={() => { if (!busy) close() }} onOk={() => void save()}>
      <p>新凭据加密保存到草稿，发布并重启服务后生效。原值不回显，历史版本仍可恢复。</p>
      <Input.Password aria-label="新凭据" autoComplete="new-password" visibilityToggle={false} maxLength={8192} value={secret}
        disabled={busy} onChange={event => setSecret(event.target.value)} />
      {error && <Alert type="error" showIcon title={error} description="凭据输入已清空。提交结果不明时先取消并回读最新状态，再决定是否重新替换。" />}
    </Modal></>
}
