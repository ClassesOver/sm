import { useState } from 'react'
import { Alert, App, Button, Drawer, Dropdown, Form, Input, InputNumber, Menu, Modal, Select, Space, Switch, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { z } from 'zod'
import { useSession } from '../../app/session'
import { request } from '../../api/http'
import { AsyncState, PageHeader } from '../../components/common'
import { UnsavedChangesGuard } from '../../components/UnsavedChangesGuard'
import { catalogSchema, detailSchema, historySchema, savedSchema, type ConfigurationItem } from './contracts'
import { systemFields } from './system-fields'
import { CredentialReplacement } from './credential-replacement'
import './settings.css'

const sourceLabel: Record<string, string> = { management: '管理配置', deployment: '部署配置', startup: '启动值', default: '内置默认' }
export default function SystemConfiguration() {
  const { state } = useSession()
  const detail = useQuery({ queryKey: ['configuration', 'system'], queryFn: ({ signal }) => request('/configuration/system', detailSchema, { signal }) })
  const catalog = useQuery({ queryKey: ['configuration', 'catalog'], queryFn: ({ signal }) => request('/configuration/system/catalog', catalogSchema, { signal }) })
  return <><PageHeader title="系统配置" description="按分类维护系统参数，保存草稿后应用；需要重启的配置会明确提示。" />
    <AsyncState loading={detail.isPending || catalog.isPending} error={detail.error || catalog.error} retry={() => { void detail.refetch(); void catalog.refetch() }}>
      {detail.data && catalog.data && state.session && <SystemForm key={state.session.username} detail={detail.data} items={catalog.data.items}
        csrf={state.session.csrfToken} refresh={async () => { await detail.refetch(); await catalog.refetch() }} />}
    </AsyncState></>
}
function SystemForm({ detail, items, csrf, refresh }: { detail: z.infer<typeof detailSchema>; items: ConfigurationItem[]; csrf: string; refresh: () => Promise<void> }) {
  const [base, setBase] = useState(detail), [values, setValues] = useState<Record<string, unknown>>(detail.draft.document.values as Record<string, unknown>)
  const [category, setCategory] = useState('模型与服务'), [search, setSearch] = useState(''), [busy, setBusy] = useState(false)
  const [history, setHistory] = useState(false), [confirm, setConfirm] = useState<'apply' | 'reset' | null>(null), [error, setError] = useState('')
  const { message } = App.useApp()
  const dirty = JSON.stringify(values) !== JSON.stringify(base.draft.document.values)
  const versions = useQuery({ queryKey: ['configuration', 'system', 'versions'], enabled: history,
    queryFn: ({ signal }) => request('/configuration/system/versions', historySchema, { signal }) })
  const categories = [...new Set(items.filter(item => systemFields([item], item.category, '').length).map(item => item.category))]
  const filtered = systemFields(items, category, search)
  async function reload() {
    const current = await request('/configuration/system', detailSchema)
    setBase(current); setValues(current.draft.document.values as Record<string, unknown>); await refresh()
  }
  async function submit(action: 'save' | 'apply' | 'reset' | 'restore', revision?: number) {
    setBusy(true); setError('')
    try {
      const path = '/configuration/system' + (action === 'save' ? '/draft' : action === 'apply' ? '/apply' : '/draft/' + action)
      await request(path, z.union([savedSchema, z.object({ revision: z.number().int() }).passthrough()]),
        { method: action === 'save' ? 'PUT' : 'POST', csrf, body: { expectedVersion: base.draft.version,
          ...(action === 'save' ? { document: { ...base.draft.document, schemaVersion: 1, values } } : {}), ...(revision ? { revision } : {}) } })
      await reload(); setConfirm(null); void message.success(action === 'apply' ? '已发布，服务重启后生效。' : '草稿已保存。')
      if (history) void versions.refetch()
    } catch (reason) { setError((reason as Error).message) } finally { setBusy(false) }
  }
  return <section className="global-settings">
    <UnsavedChangesGuard dirty={dirty} />
    <div className="global-settings-toolbar"><Space wrap><Tag>{dirty ? '有未保存修改' : '草稿 v' + base.draft.version}</Tag>
      <Tag color={base.application.requiresRestart ? 'orange' : 'blue'}>{base.application.requiresRestart ? '已发布 · 待重启' : base.application.effectiveRevision ? '运行中 v' + base.application.effectiveRevision : '运行中使用部署值'}</Tag></Space>
      <Space wrap><Dropdown menu={{ items: [{ key: 'history', label: '版本历史' }, { key: 'reload', label: '回读最新状态' }, { key: 'reset', label: '恢复初值', disabled: dirty }], onClick: ({ key }) => {
        if (key === 'history') setHistory(true)
        else if (key === 'reset') setConfirm('reset')
        else if (dirty) Modal.confirm({ title: '回读将替换未保存输入', okText: '替换并回读', cancelText: '继续编辑', onOk: reload })
        else void reload().catch(reason => setError((reason as Error).message))
      } }}><Button disabled={busy}>更多操作</Button></Dropdown><Button loading={busy} disabled={!dirty} onClick={() => void submit('save')}>保存草稿</Button>
        <Button type="primary" disabled={busy || dirty || !base.application.canApply || !base.changes.length} onClick={() => setConfirm('apply')}>应用配置</Button></Space></div>
    {error && <Alert type="error" showIcon title={error} description="输入已保留。并发冲突或提交结果不明时，请先回读最新状态再继续。" />}
    <Alert type={base.application.issue ? 'warning' : 'info'} showIcon title={base.application.issue?.message || base.application.reason} />
    <div className="global-settings-layout"><aside className="global-settings-directory"><Input.Search aria-label="搜索系统配置" placeholder="搜索常用配置" value={search} onChange={event => setSearch(event.target.value)} allowClear />
      <Menu selectedKeys={[category]} items={categories.map(label => ({ key: label, label }))} onClick={({ key }) => { setCategory(key); setSearch('') }} /></aside>
      <div className="global-settings-form"><div className="global-settings-section-heading"><h2>{search ? '搜索结果' : category}</h2></div><Form layout="vertical">
        {filtered.map(item => <div className="global-setting-field" key={item.key}><Form.Item label={<span title={item.key + ' · ' + (sourceLabel[item.source] || item.source)}>{item.label} <small>{item.unit}</small></span>}>
          {item.redacted ? <CredentialReplacement credentialKey={item.key} label={item.label} configured={item.configured || Boolean((base.draft.document.credentials as Record<string, string> | undefined)?.[item.key])}
            version={base.draft.version} csrf={csrf} disabled={busy || dirty} onSaved={reload} /> : !item.editable ? <span>{Array.isArray(item.value) ? item.value.join('、') : String(item.value ?? '未配置')}</span> :
            item.type === 'boolean' ? <Switch aria-label={item.label} checked={Boolean(values[item.key] ?? item.value)} onChange={value => setValues({ ...values, [item.key]: value })} /> :
            item.choices.length ? <Select aria-label={item.label} value={String(values[item.key] ?? item.value ?? '')} options={item.choices.map(value => ({ value, label: value }))} onChange={value => setValues({ ...values, [item.key]: value })} /> :
            item.type === 'integer' || item.type === 'number' ? <InputNumber aria-label={item.label} value={(values[item.key] ?? item.value) as number | null} min={item.minimum ?? undefined} max={item.maximum ?? undefined} precision={item.type === 'integer' ? 0 : undefined} onChange={value => setValues({ ...values, [item.key]: value })} /> :
            <Input aria-label={item.label} value={String(values[item.key] ?? item.value ?? '')} onChange={event => setValues({ ...values, [item.key]: event.target.value })} />}
        </Form.Item></div>)}
      </Form>{!filtered.length && <p>{search.trim() ? '没有匹配配置。' : '本分类暂无常用参数。'}</p>}</div></div>
    <Modal rootClassName="management-overlay" open={!!confirm} title={confirm === 'apply' ? '发布系统配置' : '恢复首次纳管初值'} okText={confirm === 'apply' ? '发布，重启后生效' : '恢复为新草稿'} cancelText="取消" confirmLoading={busy} onCancel={() => setConfirm(null)} onOk={() => void submit(confirm!)}>
      <p>{confirm === 'apply' ? '发布后，新进程在启动时读取该版本。当前进程和运行中任务继续使用原配置。' : '将首次纳管时的配置恢复到新草稿，历史版本继续保留。'}</p>
      {confirm === 'apply' && <ul>{base.changes.map(change => <li key={change.path}>{items.find(item => change.path === 'values.' + item.key || change.path === 'credentials.' + item.key)?.label || change.path}：{change.path.startsWith('credentials.') ? '凭据已替换 · 内容不回显' : String(change.before ?? '未配置') + ' → ' + String(change.after ?? '未配置')}</li>)}</ul>}
    </Modal>
    <Drawer rootClassName="management-overlay" open={history} title="系统配置版本" onClose={() => setHistory(false)} width={520}>
      <AsyncState loading={versions.isPending} error={versions.error} retry={() => void versions.refetch()}>{versions.data?.items.map(version => <div className="global-version" key={version.revision}><div><strong>已发布 v{version.revision}</strong><p>{new Date(version.publishedAt).toLocaleString()}</p></div><Button disabled={busy || dirty} onClick={() => void submit('restore', version.revision)}>恢复到新草稿</Button></div>)}</AsyncState>
      {!versions.data?.items.length && !versions.isPending && <p>尚未发布配置。</p>}
      {versions.data?.nextCursor && <p>当前显示最近 20 个版本。</p>}
    </Drawer>
  </section>
}
