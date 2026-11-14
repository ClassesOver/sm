import { useEffect, useState } from 'react'
import { Alert, App, Button, Drawer, Dropdown, Form, Input, Modal, Select, Space, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { z } from 'zod'
import { request } from '../../api/http'
import { UnsavedChangesGuard } from '../../components/UnsavedChangesGuard'
import { type ConfigurationDetail, detailSchema, historySchema, savedSchema } from './contracts'
import { HeaderFooterFields, PagePreferenceFields, documentFieldLabels, documentValueLabels, marginSideLabels } from './document-fields'
import { PreferencePreview } from './preference-preview'
import { PreferenceReportVerification } from './preference-report-verification'
import { SignatureStyleFields, signatureStyleLabels } from './signature-style'
import { headerFooterLayoutLabels } from './header-footer-style'
import { CommonStyleFields, commonStyleLabels } from './common-style'
import { TypographyFields, typographyLabels, typographyRoles } from './typography'
import { WorkbookLayoutFields, workbookLayoutLabels } from './workbook-layout'
import { WorkbookPrintFields, workbookPrintLabels } from './workbook-print'
import { PdfOutputFields, pdfOutputLabels } from './pdf-output'
import { TablePreferenceFields, tableFieldLabels, borderOptions } from './table-editor'
import { getPreferenceValue, setPreferenceValue, preferenceChanges, validateSignatureDraft } from './preference-draft'
import { formatLabels } from './format-labels'
import { DocumentStructureFields } from './document-output'

type Doc = Record<string, unknown>
const formats: Record<string, string> = { common: '通用偏好', ...formatLabels }
const dates = [{ value: 'chinese', label: '中文日期' }, { value: 'iso', label: 'YYYY-MM-DD' }, { value: 'slash', label: 'YYYY/MM/DD' }]
const valueLabel = (value: unknown): string => {
  if (typeof value === 'boolean') return value ? '开启' : '关闭'
  if (value === null) return '沿用通用'
  if (value === '') return '未填写'
  if (value === 'backticks') return '反引号'
  if (value === 'pipe') return '标准 Markdown 表格'
  if (value === 'html') return 'HTML 表格'
  if (value === 'tildes') return '波浪号'
  if (value === '-') return '短横线（-）'
  if (value === '*') return '星号（*）'
  if (value === 'minus') return '负号'
  if (value === 'parentheses') return '括号'
  if (value === 'red') return '红色负号'
  if (value === 'sans') return '无衬线'
  if (value === 'serif') return '衬线'
  if (value === 'left') return '左对齐'
  if (value === 'center') return '居中'
  if (value === 'right') return '右对齐'
  return documentValueLabels[String(value)] || borderOptions.find(item => item.value === value)?.label || dates.find(item => item.value === value)?.label || String(value ?? '未填写')
}

export function SignatureEditor({ detail, format, common, csrf, onNavigate, children, active, readonlyContent, section }: { detail: ConfigurationDetail; format: string; common: boolean; csrf: string; onNavigate: (format: string, section?: string) => void; children?: React.ReactNode; active: boolean; readonlyContent: React.ReactNode; section: string }) {
  const [base, setBase] = useState(detail), [document, setDocument] = useState<Doc>(detail.draft.document)
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [confirm, setConfirm] = useState(false), [history, setHistory] = useState(false)
  const [errors, setErrors] = useState<{ path: string; message: string }[]>([])
  const [typographyOpen, setTypographyOpen] = useState(false)
  useEffect(() => { setTypographyOpen(false) }, [format])
  useEffect(() => {
    if (errors.some(error => error.path.startsWith(format + '.typography.') || format === 'xlsx' && /^xlsx\.(body|header)\./.test(error.path))) setTypographyOpen(true)
  }, [errors, format])
  const { message } = App.useApp()
  const changes = preferenceChanges(base.draft.document, document), dirty = changes.length > 0
  const versions = useQuery({ queryKey: ['configuration', 'preferences', 'versions'], enabled: history,
    queryFn: ({ signal }) => request('/configuration/preferences/versions', historySchema, { signal }) })
  useEffect(() => {
    if (errors.length) globalThis.document.getElementById('preference-' + errors[0].path)?.focus()
  }, [errors, format, common, section])
  function update(path: string[], value: unknown) { setDocument(current => setPreferenceValue(current, path, value)); setErrors([]) }
  async function reload() {
    const current = await request('/configuration/preferences', detailSchema)
    setBase(current); setDocument(current.draft.document); setError(''); setErrors([])
  }
  async function save() {
    setBusy(true); setError('')
    try {
      await request('/configuration/preferences/draft', savedSchema, { method: 'PUT', csrf,
        body: { expectedVersion: base.draft.version, document } })
      await reload(); setConfirm(false); void message.success('偏好草稿已保存，尚未应用。')
    } catch (reason) { setError((reason as Error).message); setConfirm(false) } finally { setBusy(false) }
  }
  async function restore(revision?: number) {
    setBusy(true); setError('')
    try {
      await request('/configuration/preferences/draft/' + (revision ? 'restore' : 'reset'), z.object({ version: z.number() }).passthrough(),
        { method: 'POST', csrf, body: { expectedVersion: base.draft.version, ...(revision ? { revision } : {}) } })
      await reload(); void message.success('已恢复为新草稿，尚未应用。')
    } catch (reason) { setError((reason as Error).message) } finally { setBusy(false) }
  }
  function review() {
    const found = validateSignatureDraft(document); setErrors(found)
    if (found.length) { onNavigate(found[0].path.split('.')[0], found[0].path === 'md.sectionHeadingLevel' || found[0].path.includes('.numbers.') || found[0].path.includes('.tables.') ? 'tables' : found[0].path.endsWith('accentColor') ? 'page' : found[0].path === 'pdf.imageQuality' ? 'export' : (found[0].path.includes('.page.') || found[0].path.includes('.typography.') || /^xlsx\.(body\.|header\.|rowHeight$|columnWidth$)/.test(found[0].path)) ? 'page' : found[0].path.includes('headerFooter') || found[0].path.includes('.footer.') || found[0].path.startsWith('pptx.footerStyle.') ? 'headerFooter' : 'signature'); return }
    setError(''); setConfirm(true)
  }
  const documentActive = ['page', 'headerFooter'].includes(section) && format !== 'md'
  const tableActive = section === 'tables' && ['word', 'pdf', 'xlsx', 'md', 'pptx'].includes(format)
  const descriptionIssue = errors.find(item => item.path === format + '.signature.description')
  const prefix = common ? ['common'] : [format, 'common']
  return <>
    <UnsavedChangesGuard dirty={dirty} />
    <div className="global-settings-toolbar"><Space wrap><Tag>{dirty ? '有未保存修改' : '偏好草稿 v' + base.draft.version}</Tag><span>草稿不影响新任务和已有报告。</span></Space>
      <Space wrap><PreferenceReportVerification format={format} version={base.draft.version} contentHash={base.draft.contentHash} csrf={csrf} disabled={dirty || busy} effectiveRevision={base.effective?.revision || 0} onApplied={reload} /><Dropdown menu={{ items: [{ key: 'history', label: '版本历史' }, { key: 'reload', label: '回读最新状态' }, { key: 'reset', label: '恢复初值', disabled: dirty }], onClick: ({ key }) => {
        if (key === 'history') setHistory(true)
        else if (key === 'reset') Modal.confirm({ title: '恢复首次纳管初值？', content: '生成新草稿，历史版本继续保留。', okText: '恢复为新草稿', cancelText: '取消', onOk: () => restore() })
        else if (dirty) Modal.confirm({ title: '回读将替换未保存输入', okText: '替换并回读', cancelText: '继续编辑', onOk: reload })
        else void reload().catch(reason => setError((reason as Error).message))
      } }}><Button disabled={busy}>更多操作</Button></Dropdown>        <Button type="primary" loading={busy} disabled={!dirty} onClick={review}>保存偏好草稿</Button></Space></div>
    <p className="global-settings-notice">已接通的落款、页面、页眉页脚及表格设置可保存草稿；应用功能待执行适配与预览验收完成后开放。</p>
    {error && <Alert type="error" showIcon title={error} description="输入已保留。提交结果不明或版本冲突时，请先回读最新状态。" />}
    <PreferencePreview format={format} version={base.draft.version} csrf={csrf} disabled={dirty || busy} showSettings={errors.length > 0}>
    <div className="global-settings-layout">{children}<div className="global-settings-form" hidden={!active}><h2>{common ? '通用偏好' : formats[format] + ' · 落款'}</h2>
      <p>{common ? '署名和日期供五种格式继承；字体和主题色供 Office 格式沿用。格式页可单独设置。' : '独立落款包含署名和本次修订日期；日期由任务冻结，不手填具体日期。'}</p>
      <Form layout="vertical" disabled={busy}>
        {common && <CommonStyleFields document={document} format="common" onChange={update} disabled={busy} errors={errors} />}
        {['signer', 'dateFormat'].map(key => {
          const path = [...prefix, key], value = getPreferenceValue(document, path)
          const override = !common && ((document[format] as Doc).common as Doc)[key] != null
          const issue = errors.find(item => item.path === path.join('.'))
          return <Form.Item key={path.join('.')} label={key === 'signer' ? '署名' : '日期格式'} validateStatus={issue ? 'error' : undefined} help={issue?.message}>
            {key === 'signer' ? <Input id={'preference-' + path.join('.')} aria-label={common ? '通用署名' : '格式署名'} value={String(value ?? '')} maxLength={200} onChange={event => update(path, event.target.value)} /> :
              <Select aria-label={common ? '通用日期格式' : '格式日期格式'} value={String(value)} options={dates} onChange={value => update(path, value)} />}
            {!common && <div className="preference-inheritance"><span>{override ? '已单独设置' : '沿用通用偏好'}</span>
              {override && <Button type="link" size="small" onClick={() => update(path, null)}>恢复沿用</Button>}</div>}
          </Form.Item>
        })}
        {!common && <Form.Item className="preference-wide-field" label="附加说明" validateStatus={descriptionIssue ? 'error' : undefined} help={descriptionIssue?.message}><Input.TextArea id={'preference-' + format + '.signature.description'} aria-label="落款附加说明" maxLength={600} autoSize={{ minRows: 2, maxRows: 4 }} value={String((document[format] as Doc).signature && ((document[format] as Doc).signature as Doc).description || '')}
          onChange={event => update([format, 'signature', 'description'], event.target.value)} /></Form.Item>}
        {!common && <SignatureStyleFields document={document} format={format} onChange={update} disabled={busy} errors={errors} />}
      </Form>
    </div>{documentActive ? <div className="global-settings-form"><h2>{formats[format]} · {section === 'page' ? '页面' : '页眉页脚'}</h2>
      {section === 'page' && <><p>字体与主题色沿用通用偏好；正文、标题或单次任务的明确样式优先。</p><Form layout="vertical" disabled={busy}><CommonStyleFields document={document} format={format} onChange={update} disabled={busy} errors={errors} /></Form></>}
      {section === 'page' ? <PagePreferenceFields document={document} format={format} onChange={update} disabled={busy} errors={errors} /> : <HeaderFooterFields key={format} document={document} format={format} onChange={update} disabled={busy} errors={errors} />}
      {section === 'page' && format === 'xlsx' && <WorkbookLayoutFields document={document} onChange={update} disabled={busy} errors={errors} />}
      {section === 'page' && ['word', 'pdf', 'xlsx', 'pptx'].includes(format) && <details className="preference-typography-details" open={typographyOpen} onToggle={event => setTypographyOpen(event.currentTarget.open)}>
        <summary>文字排版</summary><TypographyFields document={document} format={format} onChange={update} disabled={busy} errors={errors} />
      </details>}
    </div> : tableActive ? <div className="global-settings-form"><h2>{formats[format]} · {format === 'md' ? '语法样式' : '表格'}</h2>
      <p>{format === 'md' ? '调整目录、语法与系统图片说明；手写说明、正文和来源保持不变。' : '仅调整显示和分页，保留业务数据与原生可编辑结构。'}</p>
      <TablePreferenceFields document={document} format={format} onChange={update} disabled={busy} errors={errors} />
    </div> : section === 'export' && format === 'xlsx' ? <div className="global-settings-form"><h2>{formats.xlsx} · 打印与导出</h2>
      <p>打印范围跟随实际数据；说明页落款一并打印。缩放只影响打印布局。</p>
      <WorkbookPrintFields document={document} onChange={update} disabled={busy} />
    </div> : section === 'export' && format === 'word' ? <div className="global-settings-form"><h2>{formats.word} · 输出选项</h2>
      <Form layout="vertical" disabled={busy}><DocumentStructureFields document={document} format="word" onChange={update} disabled={busy} /></Form>
    </div> : section === 'export' && format === 'pdf' ? <div className="global-settings-form"><h2>PDF · 输出选项</h2>
      <PdfOutputFields document={document} onChange={update} disabled={busy} errors={errors} includeStructure />
    </div> : !active && readonlyContent}</div>
    </PreferencePreview>
    <Modal rootClassName="management-overlay" open={confirm} title="确认保存偏好草稿" okText="保存草稿，暂不应用" cancelText="继续编辑" confirmLoading={busy} onCancel={() => setConfirm(false)} onOk={() => void save()}>
      <p>涉及：{[...new Set(changes.map(item => formats[item.path.split('.')[0]]))].join('、')}。本次只保存草稿。</p>
      <ul>{changes.map(item => <li key={item.path}>{formats[item.path.split('.')[0]]} · {item.path.endsWith('signer') ? '署名' : item.path.endsWith('dateFormat') ? (item.path.includes('.numbers.') ? '数据日期格式' : '日期格式') : item.path.startsWith('pptx.footerStyle.') ? '页脚 · ' + typographyLabels[item.path.split('.').at(-1)!] : item.path.includes('headerFooter') && headerFooterLayoutLabels[item.path.split('.').at(-1)!] ? headerFooterLayoutLabels[item.path.split('.').at(-1)!] : (item.path.includes('headerFooter') || item.path.includes('.footer.') ? (item.path.split('.').at(-2)?.toLowerCase().includes('footer') ? '页脚 · ' : '页眉 · ') : '') + ((item.path.includes('.margins.') ? marginSideLabels[item.path.split('.').at(-1)!] : undefined) || (item.path.includes('.typography.') ? (typographyRoles.find(role => role.value === item.path.split('.')[2])?.label || '') + ' · ' + typographyLabels[item.path.split('.').at(-1)!] : undefined) || (item.path.includes('.signature.') ? signatureStyleLabels[item.path.split('.').at(-1)!] : undefined) || (/^xlsx\.(body|header)\./.test(item.path) ? (item.path.split('.')[1] === 'body' ? '数据文字' : '表头文字') + ' · ' + typographyLabels[item.path.split('.').at(-1)!] : undefined) || workbookLayoutLabels[item.path.split('.').at(-1)!] || commonStyleLabels[item.path.split(".").at(-1)!] || documentFieldLabels[item.path.split('.').at(-1)!] || pdfOutputLabels[item.path.split('.').at(-1)!] || workbookPrintLabels[item.path.split('.').at(-1)!] || (item.path.includes('.tables.') && item.path.endsWith('.captionNumbering') ? '表格标题编号' : tableFieldLabels[item.path.split('.').at(-1)!]) || '附加说明')}：{item.path.startsWith('xlsx.') && item.before === null ? '自动/未设置' : valueLabel(item.before)} → {item.path.startsWith('xlsx.') && item.after === null ? '自动/未设置' : valueLabel(item.after)}</li>)}</ul>
    </Modal>
    <Drawer rootClassName="management-overlay" open={history} title="偏好版本历史" width={480} onClose={() => setHistory(false)}>
      {versions.isPending ? <p>正在读取…</p> : versions.error ? <Alert type="error" title={versions.error.message} /> : versions.data?.items.length ? versions.data.items.map(version => <div className="global-version" key={version.revision}><span>已发布 v{version.revision} · {new Date(version.publishedAt).toLocaleString()}</span><Button disabled={dirty || busy} onClick={() => void restore(version.revision)}>恢复到新草稿</Button></div>) : <p>尚无已发布偏好版本，草稿保存不等于发布。</p>}
    </Drawer>
  </>
}
