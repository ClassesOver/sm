import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Select, Space } from 'antd'
import { z } from 'zod'
import { request } from '../../api/http'

const artifact = z.object({ filename: z.string(), mediaType: z.string(), size: z.number(), sha256: z.string(), base64: z.string() })
const schema = z.object({ format: z.string(), draftVersion: z.number(), contentHash: z.string(), generatedDate: z.string(),
  artifact, pdf: artifact.nullable(), pages: z.array(artifact), issues: z.array(z.object({
    code: z.string().optional(), page: z.number().optional(), message: z.string(),
  }).refine(issue => issue.code !== undefined || issue.page !== undefined)), scope: z.string() })
function save(value: z.infer<typeof artifact>) {
  const bytes = Uint8Array.from(atob(value.base64), char => char.charCodeAt(0))
  const url = URL.createObjectURL(new Blob([bytes], { type: value.mediaType }))
  const link = document.createElement('a'); link.href = url; link.download = value.filename; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
function displayIssue(issue: { code?: string; page?: number; message: string }) {
  return issue.code === undefined && issue.page !== undefined
    ? `第${issue.page}页存在版面提示，请查看实际样例。`
    : issue.message
}
export function PreferencePreview({ format, version, csrf, disabled, children, showSettings = false }: { format: string; version: number; csrf: string; disabled: boolean; children?: React.ReactNode; showSettings?: boolean }) {
  const [view, setView] = useState<'settings' | 'preview'>('settings'), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const [result, setResult] = useState<z.infer<typeof schema> | null>(null), [page, setPage] = useState(0)
  const generation = useRef(0)
  useEffect(() => { generation.current++; setResult(null); setError(''); setPage(0); setBusy(false); return () => { generation.current++ } }, [format, version])
  useEffect(() => { setView('settings') }, [format])
  useEffect(() => { if (showSettings) setView('settings') }, [showSettings])
  async function preview() {
    const current = ++generation.current
    setView('preview'); setBusy(true); setError(''); setResult(null)
    try {
      const next = await request('/configuration/preferences/preview/' + format, schema, { method: 'POST', csrf, body: { expectedVersion: version } })
      if (current === generation.current) { setResult(next); setPage(0) }
    } catch (reason) { if (current === generation.current) setError((reason as Error).message) }
    finally { if (current === generation.current) setBusy(false) }
  }
  return <section className="preference-workspace" data-preference-view={view}>
    <div className="preference-workspace-toolbar">
      <div className="preference-view-switch" role="group" aria-label="偏好工作区视图">
        <Button aria-label="设置" aria-pressed={view === 'settings'} onClick={() => setView('settings')}>设置</Button>
        <Button aria-label="预览" aria-pressed={view === 'preview'} onClick={() => setView('preview')}>预览</Button>
      </div>
      <Button aria-label="预览已保存草稿" disabled={disabled || busy} loading={busy} onClick={() => void preview()}>预览已保存草稿</Button>
    </div>
    <div className="preference-workspace-columns"><div className="preference-settings-pane">{children}</div>
    <section className="preference-preview-pane" aria-label="真实样例预览" aria-busy={busy}>
      <h2>真实样例预览</h2>
      {disabled && <p className="preference-preview-hint">预览对应已保存草稿，尚未包含当前修改。</p>}
      {!result && !busy && !error && <p className="preference-preview-hint">保存草稿后点击预览，查看当前格式的真实生成效果。</p>}
      {busy && <p role="status">正在生成真实文件并渲染页面，请稍候…</p>}
      {error && <Alert type="error" showIcon title={error} action={<Button disabled={disabled} onClick={() => void preview()}>重试</Button>} />}
      {result && <><p>草稿 v{result.draftVersion} · 日期 {result.generatedDate}</p><p>{result.scope}</p>
        {result.issues.map((issue, index) => <Alert key={index} type="warning" showIcon title={displayIssue(issue)} />)}
        <Space wrap className="preference-preview-actions"><Button onClick={() => save(result.artifact)}>读取原生样例</Button>
          {result.pdf && <Button onClick={() => save(result.pdf!)}>读取 PDF 样例</Button>}
          {!!result.pages.length && <Select aria-label="预览页码" value={page} options={result.pages.map((_, index) => ({ value: index, label: '第 ' + (index + 1) + ' 页 / 共 ' + result.pages.length + ' 页' }))} onChange={setPage} />}</Space>
        {result.format === 'md' ? <pre className="preference-markdown-preview">{new TextDecoder().decode(Uint8Array.from(atob(result.artifact.base64), char => char.charCodeAt(0)))}</pre> :
          result.pages[page] && <img className="preference-page-preview" alt={'实际样例第 ' + (page + 1) + ' 页'} src={'data:image/png;base64,' + result.pages[page].base64} />}
      </>}
    </section></div>
  </section>
}
