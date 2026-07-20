import { useState } from 'react'
import { Download, FileSpreadsheet, FlaskConical, RefreshCw } from 'lucide-react'
import type {
  X2ManyImportPreviewRequest,
  X2ManyImportPreviewResponse
} from '../types'
import { Button } from './Button'
import { InlineNotice } from './InlineNotice'

interface X2ManyImportPreviewProps {
  preview: Record<string, unknown>
  running?: boolean
  onSubmit?: (
    request: X2ManyImportPreviewRequest
  ) => Promise<X2ManyImportPreviewResponse>
}

interface ImportColumn {
  index: number
  header: string
  mappedField: string | false
  mappable: boolean
}

interface ImportField {
  name: string
  label: string
  type: string | false
  required: boolean
}

interface ImportParseOptions {
  encoding: string | false
  separator: string | false
  quoting: string
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : {}
}

function importData(preview: Record<string, unknown>): Record<string, unknown> {
  return asRecord(preview.import)
}

function columnsFrom(value: unknown): ImportColumn[] {
  if (!Array.isArray(value)) return []
  return value.map((raw, index) => {
    const column = asRecord(raw)
    return {
      index: Number.isInteger(column.index) ? Number(column.index) : index,
      header: String(column.header || ''),
      mappedField: typeof column.mappedField === 'string' ? column.mappedField : false,
      mappable: column.mappable !== false
    }
  })
}

function fieldsFrom(value: unknown): ImportField[] {
  if (!Array.isArray(value)) return []
  return value.map((raw) => {
    const field = asRecord(raw)
    const type: string | false = typeof field.type === 'string' ? field.type : false
    return {
      name: String(field.name || ''),
      label: String(field.label || field.name || ''),
      type,
      required: field.required === true
    }
  }).filter((field) => field.name)
}

function parseOptionsFrom(value: unknown): ImportParseOptions {
  const options = asRecord(value)
  const encoding: string | false = typeof options.encoding === 'string'
    ? options.encoding : false
  const separator: string | false = typeof options.separator === 'string'
    ? options.separator : false
  return {
    encoding,
    separator,
    quoting: typeof options.quoting === 'string' ? options.quoting : '"'
  }
}

function rowsFrom(value: unknown): string[][] {
  if (!Array.isArray(value)) return []
  return value.map((row) => Array.isArray(row) ? row.map((cell) => String(cell ?? '')) : [])
}

function errorText(value: unknown): string {
  const error = asRecord(value)
  const messages = Array.isArray(error.errors) ? error.errors.map(String) : []
  const prefix = Number.isInteger(error.row) && Number(error.row) > 0
    ? `第 ${error.row} 行` : '文件'
  return `${prefix}：${messages.join('；') || String(error.code || '导入数据无效')}`
}

export function X2ManyImportPreview({
  preview, running = false, onSubmit
}: X2ManyImportPreviewProps) {
  const initial = importData(preview)
  const [data, setData] = useState(initial)
  const [mapping, setMapping] = useState<Record<string, string | false>>(() =>
    Object.fromEntries(columnsFrom(initial.columns).map((column) => [
      column.header, column.mappedField
    ]))
  )
  const [parseOptions, setParseOptions] = useState<ImportParseOptions>(() =>
    parseOptionsFrom(initial.parseOptions)
  )
  const [submitting, setSubmitting] = useState(false)
  const [requestError, setRequestError] = useState('')

  const appliedParseOptions = parseOptionsFrom(data.parseOptions)
  const parseOptionsChanged = parseOptions.encoding !== appliedParseOptions.encoding ||
    parseOptions.separator !== appliedParseOptions.separator ||
    parseOptions.quoting !== appliedParseOptions.quoting
  const columns = columnsFrom(data.columns)
  const schema = asRecord(data.schema)
  const fields = fieldsFrom(schema.fields)
  const rows = rowsFrom(data.rows)
  const errors = Array.isArray(data.errors) ? data.errors : []
  const errorCount = Number(data.errorCount || errors.length)
  const errorReport = typeof data.errorReport === 'string' &&
    data.errorReport.startsWith('/agui_chat_import/error/') ? data.errorReport : ''
  const selectedFields = Object.values(mapping).filter(Boolean) as string[]
  const duplicateFields = new Set(selectedFields.filter(
    (field, index) => selectedFields.indexOf(field) !== index
  ))
  const missingRequired = fields.filter(
    (field) => field.required && !selectedFields.includes(field.name)
  )
  const state = String(data.state || 'preview')
  const locked = state !== 'preview'
  const result = asRecord(data.result)

  const submit = async (finalize: boolean) => {
    if (!onSubmit || locked || submitting) return
    setSubmitting(true)
    setRequestError('')
    try {
      const response = await onSubmit({
        jobToken: String(data.jobToken || ''),
        expectedRevision: Number(data.revision || 0),
        parseOptions,
        mapping: parseOptionsChanged ? {} : mapping,
        finalize
      })
      if (!response.ok) {
        setRequestError(response.error || response.code || '导入预览更新失败。')
        return
      }
      const next = importData(asRecord(response.preview))
      if (Object.keys(next).length) {
        setData(next)
        setMapping(Object.fromEntries(columnsFrom(next.columns).map((column) => [
          column.header, column.mappedField
        ])))
        setParseOptions(parseOptionsFrom(next.parseOptions))
      }
    } catch (reason) {
      setRequestError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSubmitting(false)
    }
  }

  return <section className="mt-2 min-w-0 border-t border-border pt-2 text-xs text-primary">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex min-w-0 items-center gap-2">
        <FileSpreadsheet className="size-4 shrink-0 text-positive" />
        <div className="min-w-0">
          <div className="truncate font-semibold">{String(data.fileName || '导入文件')}</div>
          <div className="text-[11px] text-muted">
            {Number(data.rowCount || 0).toLocaleString()} 行 · {Number(data.fileSize || 0).toLocaleString()} B
          </div>
        </div>
      </div>
      <span className="text-[11px] text-muted">
        {state === 'ready' ? '已通过测试' : state === 'done' ? '已完成' : state === 'failed' ? '执行失败' : '预览'}
      </span>
    </div>

    {!locked ? <details className="mt-2 border-y border-border py-2">
      <summary className="cursor-pointer text-[11px] font-medium text-muted">格式选项</summary>
      <div className="mt-2 grid gap-2 sm:grid-cols-3">
        <label className="grid gap-1 text-[11px] text-muted">
          编码
          <select aria-label="编码" className="h-8 min-w-0 border border-border bg-background px-2 text-primary" value={parseOptions.encoding || ''} disabled={submitting || running} onChange={(event) => setParseOptions((current) => ({ ...current, encoding: event.target.value || false }))}>
            <option value="">自动检测</option>
            <option value="ascii">ASCII</option>
            <option value="utf-8">UTF-8</option>
            <option value="utf-8-sig">UTF-8 BOM</option>
            <option value="gb18030">GB18030</option>
            <option value="gbk">GBK</option>
            <option value="big5">Big5</option>
            <option value="iso-8859-1">ISO-8859-1</option>
            <option value="windows-1252">Windows-1252</option>
          </select>
        </label>
        <label className="grid gap-1 text-[11px] text-muted">
          分隔符
          <select aria-label="分隔符" className="h-8 min-w-0 border border-border bg-background px-2 text-primary" value={parseOptions.separator || ''} disabled={submitting || running} onChange={(event) => setParseOptions((current) => ({ ...current, separator: event.target.value || false }))}>
            <option value="">自动检测</option>
            <option value=",">逗号</option>
            <option value=";">分号</option>
            <option value={'\t'}>制表符</option>
            <option value="|">竖线</option>
          </select>
        </label>
        <label className="grid gap-1 text-[11px] text-muted">
          文本限定符
          <select aria-label="文本限定符" className="h-8 min-w-0 border border-border bg-background px-2 text-primary" value={parseOptions.quoting} disabled={submitting || running} onChange={(event) => setParseOptions((current) => ({ ...current, quoting: event.target.value }))}>
            <option value={'"'}>双引号</option>
            <option value={"'"}>单引号</option>
          </select>
        </label>
      </div>
    </details> : null}

    <div className="mt-2 max-w-full overflow-x-auto border border-border">
      <table className="min-w-max border-collapse text-left text-[11px]">
        <thead className="bg-background-secondary">
          <tr>{columns.map((column) => <th key={column.header} className="min-w-40 border-r border-border p-2 last:border-r-0">
            <div className="mb-1 max-w-48 truncate font-medium" title={column.header}>{column.header}</div>
            <select aria-label={`映射 ${column.header}`} className="h-8 w-full border border-border bg-background px-2 font-normal text-primary" value={mapping[column.header] || ''} disabled={locked || submitting || running || !column.mappable} onChange={(event) => setMapping((current) => ({ ...current, [column.header]: event.target.value || false }))}>
              <option value="">不导入</option>
              {fields.map((field) => <option key={field.name} value={field.name} disabled={selectedFields.includes(field.name) && mapping[column.header] !== field.name}>
                {field.label}{field.required ? ' *' : ''}
              </option>)}
            </select>
          </th>)}</tr>
        </thead>
        <tbody>{rows.length ? rows.map((row, rowIndex) => <tr key={rowIndex} className="border-t border-border">
          {columns.map((column) => <td key={column.header} className="max-w-64 border-r border-border p-2 align-top last:border-r-0">
            <span className="block max-w-60 truncate" title={row[column.index] || ''}>{row[column.index] || ''}</span>
          </td>)}
        </tr>) : <tr><td colSpan={Math.max(columns.length, 1)} className="p-4 text-center text-muted">没有可预览的数据</td></tr>}</tbody>
      </table>
    </div>

    {missingRequired.length || duplicateFields.size ? <InlineNotice className="mt-2" tone="warning">
      {missingRequired.length ? `请映射必填字段：${missingRequired.map((field) => field.label).join('、')}` : '同一目标字段不能重复映射。'}
    </InlineNotice> : null}
    {errors.length ? <div className="mt-2 border-l-2 border-destructive pl-2 text-destructive">
      {errors.map((error, index) => <div key={index}>{errorText(error)}</div>)}
      {errorReport ? <a className="mt-1 inline-flex items-center gap-1 font-medium underline" href={errorReport}>
        <Download className="size-3.5" />下载完整错误报告{errorCount > errors.length ? `（共 ${errorCount} 项）` : ''}
      </a> : null}
    </div> : null}
    {requestError ? <InlineNotice className="mt-2" tone="error">{requestError}</InlineNotice> : null}
    {state === 'done' ? <div className="mt-2 text-positive">已创建 {Number(result.created || 0)} 条明细。</div> : null}

    {!locked && onSubmit ? <div className="mt-2 flex flex-wrap justify-end gap-2">
      <Button size="sm" className="h-8 rounded-md bg-background" disabled={submitting || running} onClick={() => void submit(false)}>
        <RefreshCw className={submitting ? 'size-3.5 animate-spin' : 'size-3.5'} />更新预览
      </Button>
      <Button size="sm" variant="primary" className="h-8 rounded-md" disabled={submitting || running || Boolean(missingRequired.length || duplicateFields.size)} onClick={() => void submit(true)}>
        <FlaskConical className="size-3.5" />测试导入
      </Button>
    </div> : null}
  </section>
}
