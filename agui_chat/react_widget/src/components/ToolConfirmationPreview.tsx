import { ChevronRight } from 'lucide-react'

interface ToolConfirmationPreviewProps {
  result: Record<string, unknown>
}

export function structuredPreview(result: Record<string, unknown>): Record<string, unknown> {
  const preview = result.preview && typeof result.preview === 'object'
    ? result.preview as Record<string, unknown> : {}
  if (preview.kind) return preview
  const nested = result.result && typeof result.result === 'object'
    ? result.result as Record<string, unknown> : {}
  return nested.preview && typeof nested.preview === 'object'
    ? nested.preview as Record<string, unknown> : preview
}

function displayDiffValue(value: unknown): string {
  if (value === false || value === null || value === undefined || value === '') return '空'
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

export function ToolConfirmationPreview({ result }: ToolConfirmationPreviewProps) {
  const preview = structuredPreview(result)
  const changes = Array.isArray(preview.changes)
    ? preview.changes as Array<Record<string, unknown>> : []
  const riskLabels: Record<string, string> = {
    multiple_fields: '多字段修改',
    relation_field: '关系字段',
    policy_high_risk_field: '管理员标记字段',
    field_type_unknown: '字段类型未确认',
    destructive_command: '写入操作',
    object_button: '对象按钮'
  }
  const reasons = Array.isArray(preview.riskReasons) ? preview.riskReasons : []
  const control = preview.control && typeof preview.control === 'object'
    ? preview.control as Record<string, unknown> : null

  if (control) {
    return <div className="mt-2 rounded border border-warning/25 bg-background p-2 text-xs text-primary">
      <div className="font-semibold">{String(control.label || '对象按钮')}</div>
      <div className="mt-1 text-muted">所属记录：{String(control.recordLabel || '当前记录')}</div>
    </div>
  }
  if (!changes.length) {
    return <pre className="mt-2 max-h-52 overflow-auto rounded bg-background p-2 text-[11px]">{JSON.stringify({ target: result.target || {}, patch: result.patch || {} }, null, 2)}</pre>
  }

  return <div className="mt-2 overflow-hidden rounded border border-warning/25 bg-background text-primary">
    {changes.map((change) => <div key={String(change.field)} className="grid gap-1 border-b border-border p-2 last:border-b-0">
      <div className="text-[11px] font-semibold">{String(change.label || change.field)}</div>
      <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-start gap-2 text-[11px]">
        <span className="break-words text-muted">{displayDiffValue(change.oldValue)}</span>
        <ChevronRight className="mt-0.5 size-3 text-muted" />
        <span className="break-words">{displayDiffValue(change.newValue)}</span>
      </div>
    </div>)}
    {reasons.length ? <div className="flex flex-wrap gap-1 border-t border-warning/20 p-2">{reasons.map((reason) => <span key={String(reason)} className="rounded border border-warning/25 px-1.5 py-0.5 text-[10px] text-warning">{riskLabels[String(reason)] || String(reason)}</span>)}</div> : null}
  </div>
}
