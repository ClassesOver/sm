import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Checkbox, Input, Select, Space } from 'antd'
import { useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { identity, request, scopeQuery } from '../../api/http'
import { MetricReleaseComparison } from './release-comparison'
import { MetricDependencyPicker } from './dependency-picker'
import { MetricFieldPicker } from './field-picker'
import { MetricConflictComparison, metricConflictGroups, type MetricConflictChoices } from './conflict-comparison'

const ref = z.object({ metricId: z.string(), revision: z.number().int().nonnegative() })
const definitionSchema = z.object({
  id: z.string(), name: z.string(), kind: z.enum(['sum', 'count', 'count_distinct', 'ratio']),
  fieldRef: z.string().nullable(), timeField: z.string().nullable(), unit: z.string(),
  numeratorVersion: ref.nullable(), denominatorVersion: ref.nullable(),
  grain: z.array(z.string()), dimensions: z.array(z.object({ id: z.string(), fieldRef: z.string() })),
  timeZone: z.string().nullable(), storageTimeZone: z.string().nullable(), aliases: z.array(z.string()),
  aggregationPolicy: z.object({ observationKind: z.enum(['flow', 'cumulative_snapshot']),
    timeAggregation: z.enum(['sum', 'difference', 'none']), reset: z.enum(['calendar_year_zero', 'none']).nullable() }),
})
export type Definition = z.infer<typeof definitionSchema>
const documentSchema = definitionSchema.extend({ scopeId: z.string(), revision: z.number().int().positive() })
const snapshotSchema = z.object({ version: z.number().int().positive(), document: documentSchema, contentHash: z.string() })
type Snapshot = z.infer<typeof snapshotSchema>
const publishedSchema = z.object({ revision: z.number().int().positive(), document: documentSchema, contentHash: z.string() })
const readSchema = z.object({ draft: snapshotSchema.nullable(), published: publishedSchema.nullable() })
const pendingSchema = z.object({ action: z.enum(['save', 'publish']), expectedVersion: z.number().int().nonnegative(),
  definition: definitionSchema, revision: z.number().int().positive().nullable(), contentHash: z.string().nullable() })
type Pending = z.infer<typeof pendingSchema>
const cacheSchema = z.object({ baseline: snapshotSchema.nullable(), value: definitionSchema, pending: pendingSchema.nullable() })
const same = (left: Definition, right: Definition) => JSON.stringify(definitionSchema.parse(left)) === JSON.stringify(definitionSchema.parse(right))
const fieldPattern = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.[A-Za-z_][A-Za-z0-9_$]{0,127}\.[A-Za-z_][A-Za-z0-9_$]{0,127}\.[A-Za-z_][A-Za-z0-9_$]{0,127}$/
const validId = (id: string) => /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(id)
function problem(value: Definition) {
  if (!validId(value.id) || !value.name.trim() || value.name.length > 200 || !value.unit.trim() || value.unit.length > 32) return '请填写有效的指标标识、名称和单位。'
  if (!value.dimensions.length || value.dimensions.length > 20 || value.dimensions.some(d => !validId(d.id) || !fieldPattern.test(d.fieldRef))
    || new Set(value.dimensions.map(d => d.id)).size !== value.dimensions.length || !value.grain.length
    || value.grain.some(id => !value.dimensions.some(d => d.id === id))) return '请登记不重复的维度字段，并明确选择至少一个计算粒度。'
  if (value.kind === 'ratio') {
    if (!value.numeratorVersion || !value.denominatorVersion || !validId(value.numeratorVersion.metricId) || !validId(value.denominatorVersion.metricId)
      || !value.numeratorVersion.revision || !value.denominatorVersion.revision
      || !['%', 'ratio'].includes(value.unit)) return '比率须明确分子、分母的已发布版本，单位为%或ratio。'
  } else if (!fieldPattern.test(value.fieldRef ?? '') || !fieldPattern.test(value.timeField ?? '')) return '取数字段与时间字段须使用 数据源.数据库.表.字段 的完整引用。'
  if (!!value.timeZone !== !!value.storageTimeZone) return '业务时区与存储时区须同时填写或同时留空。'
  try { for (const timeZone of [value.timeZone, value.storageTimeZone]) if (timeZone) new Intl.DateTimeFormat('zh-CN', { timeZone }) }
  catch { return '请填写有效的IANA时区名称。' }
  const aggregation = value.aggregationPolicy
  if ((aggregation.observationKind === 'flow' && (aggregation.timeAggregation === 'difference' || aggregation.reset !== null))
    || (aggregation.observationKind === 'cumulative_snapshot' && aggregation.timeAggregation === 'sum')) return '事件流不能差分或重置；累计快照不能按时间直接求和。'
  return ''
}

export function MetricEditor({ scope, metricId, username, csrf }: {
  scope: { database: string; companyId: string }; metricId: string; username: string; csrf: string
}) {
  const client = useQueryClient(), path = '/metrics/' + encodeURIComponent(metricId)
  const key = 'management-metric-editor:' + JSON.stringify([username, scope.database, scope.companyId, metricId])
  const [cache] = useState(() => { try {
    const raw = sessionStorage.getItem(key), value = raw ? cacheSchema.parse(JSON.parse(raw)) : null
    if (value && (value.value.id !== metricId || (value.baseline && value.baseline.document.id !== metricId)
      || (value.pending && value.pending.definition.id !== metricId))) throw Error('identity')
    return { value, invalid: false } }
    catch { return { value: null, invalid: true } } })
  const [value, setValue] = useState<Definition>(cache.value?.value ?? { id: metricId, name: '', kind: 'sum', fieldRef: null, timeField: null,
    unit: '', numeratorVersion: null, denominatorVersion: null, grain: [], dimensions: [], timeZone: null, storageTimeZone: null,
    aliases: [], aggregationPolicy: { observationKind: 'flow', timeAggregation: 'sum', reset: null } })
  const [baseline, setBaseline] = useState<Snapshot | null>(cache.value?.baseline ?? null)
  const [pending, setPending] = useState<Pending | null>(cache.value?.pending ?? null)
  const [published, setPublished] = useState<z.infer<typeof publishedSchema> | null>(null)
  const [loaded, setLoaded] = useState(false), [busy, setBusy] = useState(false), [ack, setAck] = useState(false)
  const [retryReady, setRetryReady] = useState(false)
  const [numeratorReady, setNumeratorReady] = useState(false), [denominatorReady, setDenominatorReady] = useState(false)
  const [conflict, setConflict] = useState<Snapshot | null>(null), [choices, setChoices] = useState<MetricConflictChoices>({}), [conflictAck, setConflictAck] = useState(false)
  const recovery = useRef<HTMLButtonElement>(null)
  const [notice, setNotice] = useState(cache.invalid ? '本地指标草稿无法读取，请保留缓存核对，禁止覆盖。' : '')
  useEffect(() => { if (pending && !busy) recovery.current?.focus() }, [pending, busy])
  useEffect(() => {
    const controller = new AbortController()
    request(path + '?' + scopeQuery(scope), readSchema, { signal: controller.signal }).then(data => {
      if ((data.draft && data.draft.document.id !== metricId) || (data.published && data.published.document.id !== metricId)) throw Error('identity')
      setPublished(data.published)
      if (!cache.value && !cache.invalid) {
        setBaseline(data.draft)
        if (data.draft || data.published) setValue(definitionSchema.parse((data.draft ?? data.published)!.document))
      }
      setLoaded(true)
    }).catch(error => {
      if (controller.signal.aborted) return
      if (error.status === 404 && !cache.value) setLoaded(true)
      else setNotice('指标读取失败，请重新进入核对；本地输入已保留。')
    })
    return () => controller.abort()
  }, [path, scope.database, scope.companyId, cache, metricId])
  const persist = (next: Definition, base: Snapshot | null, original: Pending | null) => {
    sessionStorage.setItem(key, JSON.stringify({ value: next, baseline: base, pending: original }))
  }
  const change = (patch: Partial<Definition>) => {
    const next = { ...value, ...patch }; setValue(next); setAck(false)
    try { persist(next, baseline, pending) } catch { setNotice('本地保存失败，请保留当前页面；提交前必须成功保存请求。') }
  }
  const invalidate = () => { void client.invalidateQueries({ queryKey: ['metrics', scope] }); void client.invalidateQueries({ queryKey: ['metric-version', scope] }) }
  const finish = (base: Snapshot | null, message: string) => {
    persist(value, base, null); setBaseline(base); setPending(null); setRetryReady(false); setAck(false); setNotice(message); invalidate()
  }
  const submit = async (original: Pending) => {
    try { persist(value, baseline, original) } catch { setNotice('无法保存原指标提交请求，未提交。'); return }
    setPending(original); setBusy(true); setRetryReady(false)
    try {
      if (original.action === 'save') {
        const result = await request(path + '/draft', snapshotSchema, { method: 'PUT', csrf,
          body: { ...identity(scope), expectedVersion: original.expectedVersion, definition: original.definition } })
        if (result.version !== original.expectedVersion + 1 || !same(result.document, original.definition)) throw Error('identity')
        finish(result, '草稿已保存，正式口径和报告尚未改变。')
      } else {
        const result = await request(path + '/publish', publishedSchema.extend({ issues: z.array(z.object({ message: z.string() }).passthrough()) }),
          { method: 'POST', csrf, body: { ...identity(scope), expectedVersion: original.expectedVersion } })
        if (result.revision !== original.revision || result.contentHash !== original.contentHash || !same(result.document, original.definition)) throw Error('identity')
        setPublished(result); finish(baseline, '指标版本已发布；不会自动替换口径或默认。' + result.issues.map(i => i.message).join('；'))
      }
    } catch { setNotice('提交结果待确认，请读取原提交结果；不会自动重发。') }
    finally { setBusy(false) }
  }
  const recover = async () => {
    if (!pending) return
    setBusy(true); setRetryReady(false); setAck(false); setConflict(null); setChoices({}); setConflictAck(false)
    try {
      let data: z.infer<typeof readSchema>
      try { data = await request(path + '?' + scopeQuery(scope) + (pending.action === 'publish' ? '&revision=' + pending.revision : ''), readSchema) }
      catch (error) {
        if (!(error instanceof Error) || !('status' in error) || error.status !== 404) throw error
        if (pending.action === 'save' && pending.expectedVersion === 0) data = { draft: null, published: null }
        else if (pending.action === 'publish') {
          data = await request(path + '?' + scopeQuery(scope), readSchema)
          if (data.published?.revision === pending.revision) throw Error('inconsistent exact read')
        } else throw error
      }
      if ((data.draft && (data.draft.document.id !== metricId || baseline && data.draft.document.scopeId !== baseline.document.scopeId))
        || data.published && data.published.document.id !== metricId) throw Error('identity')
      setPublished(data.published)
      if (pending.action === 'save' && data.draft?.version === pending.expectedVersion + 1 && same(data.draft.document, pending.definition)) {
        finish(data.draft, '当前草稿与原提交一致；此状态核对不代表独立请求回执。')
      } else if (pending.action === 'publish' && data.published?.revision === pending.revision && data.published.contentHash === pending.contentHash
        && same(data.published.document, pending.definition)) finish(baseline, '当前发布与原提交一致；不会自动替换口径或默认。')
      else if ((data.draft?.version ?? 0) === pending.expectedVersion && (pending.action === 'save' || data.draft?.contentHash === pending.contentHash)) {
        setRetryReady(true); setNotice('原请求尚未登记；已保留输入，须重新明确确认才能重提。')
      } else { setConflict(data.draft); setNotice('服务器版本与原请求冲突，已保留本地输入；请保留原请求核对，不能直接覆盖。') }
    } catch { setNotice('原提交结果仍无法确认，保留原请求，不会自动重发。') }
    finally { setBusy(false) }
  }
  const adoptConflict = async () => {
    if (!conflict || !pending || !conflictAck || busy || metricConflictGroups(value, conflict.document).some(g => !choices[g.key])) return
    setBusy(true); setAck(false); setConflictAck(false)
    try {
      const current = await request(path + '?' + scopeQuery(scope), readSchema)
      if (!current.draft || current.draft.document.id !== metricId || current.draft.document.scopeId !== conflict.document.scopeId
        || current.published && current.published.document.id !== metricId) throw Error('identity')
      if (current.draft.version !== conflict.version || current.draft.contentHash !== conflict.contentHash || !same(current.draft.document, conflict.document)) {
        setConflict(current.draft); setChoices({}); setNotice('服务器指标草稿再次变化，请重新核对；原请求和本地输入保留。'); return
      }
      const merged = definitionSchema.parse(current.draft.document)
      for (const group of metricConflictGroups(value, current.draft.document)) if (choices[group.key] === 'local') {
        for (const field of group.fields) Object.assign(merged, { [field]: value[field] })
      }
      const archiveKey = 'management-metric-conflict:' + JSON.stringify([username, scope.database, scope.companyId, metricId, pending.action, pending.expectedVersion, conflict.version, conflict.contentHash])
      sessionStorage.setItem(archiveKey, JSON.stringify({ value, baseline, pending, server: current.draft, choices }))
      persist(merged, current.draft, null)
      setValue(merged); setBaseline(current.draft); setPublished(current.published); setPending(null); setConflict(null); setChoices({}); setRetryReady(false); setNumeratorReady(false); setDenominatorReady(false)
      setNotice('已按服务器指标草稿版本 ' + current.draft.version + ' 准备本地修改；原提交与选择已保存到本次账号和组织的会话记录，请核对后明确保存，再重新确认发布。')
    } catch { setNotice('指标冲突核对未完成或无法保存记录，原请求和本地输入保留，未写入服务器。') }
    finally { setBusy(false) }
  }
  const dirty = !baseline || !same(value, baseline.document), blocked = !loaded || busy || cache.invalid || !!pending
  const input = (label: string, id: string, content: string | null, onChange: (text: string) => void) => <label style={{ display: 'grid', gap: 4 }}>
    {label}<Input id={id} value={content ?? ''} onChange={e => onChange(e.target.value)} disabled={blocked} /></label>
  return <Card title={'编辑指标 · ' + metricId} role="region" aria-label="指标定义编辑">
    <Space orientation="vertical" style={{ width: '100%', overflowWrap: 'anywhere' }} size="middle">
      {notice && <Alert type="info" title={notice} />}
      {conflict && pending && <>
        <MetricConflictComparison key={conflict.version + ':' + conflict.contentHash} local={value} server={conflict.document} version={conflict.version}
          choices={choices} onChoice={(group, choice) => { setChoices(previous => ({ ...previous, [group]: choice })); setConflictAck(false) }}
          acknowledged={conflictAck} onAcknowledge={setConflictAck} disabled={busy} />
        <Button disabled={busy || !conflictAck || metricConflictGroups(value, conflict.document).some(g => !choices[g.key])} onClick={() => void adoptConflict()}>采用指标核对结果继续编辑</Button>
      </>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(min(100%,260px),1fr))', gap: 12 }}>
        {input('指标名称', 'metric-name', value.name, name => change({ name }))}
        {input('显示单位', 'metric-unit', value.unit, unit => change({ unit }))}
        <label>计算方法<Select aria-label="指标计算方法" style={{ width: '100%' }} disabled={blocked} value={value.kind}
          options={[{ value: 'sum', label: '求和' }, { value: 'count', label: '非空计数' }, { value: 'count_distinct', label: '去重计数' }, { value: 'ratio', label: '比率（精确分子÷分母）' }]}
          onChange={kind => change({ kind, fieldRef: null, timeField: null, numeratorVersion: null, denominatorVersion: null })} /></label>
      </div>
      {value.kind !== 'ratio' ? <>
        {input('取数字段（数据源.数据库.表.字段）', 'metric-field', value.fieldRef, fieldRef => change({ fieldRef: fieldRef || null }))}
        <MetricFieldPicker scope={scope} label="取数字段" value={value.fieldRef} disabled={blocked} onChange={fieldRef => change({ fieldRef })} />
        {input('时间字段（完整引用）', 'metric-time', value.timeField, timeField => change({ timeField: timeField || null }))}
        <MetricFieldPicker scope={scope} label="时间字段" value={value.timeField} disabled={blocked} onChange={timeField => change({ timeField })} />
      </> : <>
        <Alert type="info" title="分子与分母须明确指定已发布版本；保存不检查依赖可用性，发布时由服务端核验完整依赖。" />
        {(['numeratorVersion', 'denominatorVersion'] as const).map((field, index) => <MetricDependencyPicker key={field}
          scope={scope} label={index ? '分母' : '分子'} value={value[field]} disabled={blocked}
          onChange={reference => change({ [field]: reference })}
          onAvailabilityChange={index ? setDenominatorReady : setNumeratorReady} />)}
        <div>计算说明：{value.numeratorVersion?.metricId || '未选分子'}（版本{value.numeratorVersion?.revision ?? '未选'}）÷ {value.denominatorVersion?.metricId || '未选分母'}（版本{value.denominatorVersion?.revision ?? '未选'}）{value.unit === '%' ? '，显示为百分比' : ''}</div>
      </>}
      <fieldset disabled={blocked}><legend>维度与计算粒度</legend>
        {value.dimensions.map((dimension, index) => <Space key={index} wrap style={{ marginBottom: 8 }}>
          {input('维度标识 ' + (index + 1), 'metric-dimension-' + index, dimension.id, id => change({
            dimensions: value.dimensions.map((d, i) => i === index ? { ...d, id } : d), grain: value.grain.map(v => v === dimension.id ? id : v) }))}
          {input('维度字段 ' + (index + 1), 'metric-dimension-field-' + index, dimension.fieldRef,
            fieldRef => change({ dimensions: value.dimensions.map((d, i) => i === index ? { ...d, fieldRef } : d) }))}
          <MetricFieldPicker scope={scope} label={'维度字段 ' + (index + 1)} value={dimension.fieldRef} disabled={blocked} onChange={fieldRef => change({ dimensions: value.dimensions.map((d, i) => i === index ? { ...d, fieldRef } : d) })} />
          <Checkbox disabled={blocked} checked={value.grain.includes(dimension.id)} onChange={e => change({ grain: e.target.checked ? [...value.grain, dimension.id] : value.grain.filter(id => id !== dimension.id) })}>作为计算粒度</Checkbox>
          <Button disabled={blocked} onClick={() => change({ dimensions: value.dimensions.filter((_, i) => i !== index), grain: value.grain.filter(id => id !== dimension.id) })}>移除维度 {index + 1}</Button>
        </Space>)}
        <Button disabled={blocked || value.dimensions.length >= 20} onClick={() => change({ dimensions: [...value.dimensions, { id: '', fieldRef: '' }] })}>添加维度</Button>
      </fieldset>
      <Space wrap>
        <label>观测类型<Select aria-label="观测类型" disabled={blocked} value={value.aggregationPolicy.observationKind} options={[{ value: 'flow', label: '事件流' }, { value: 'cumulative_snapshot', label: '累计快照' }]}
          onChange={observationKind => change({ aggregationPolicy: { observationKind, timeAggregation: observationKind === 'flow' ? 'sum' : 'difference', reset: null } })} /></label>
        <label>时间聚合<Select aria-label="时间聚合" disabled={blocked} value={value.aggregationPolicy.timeAggregation} options={(value.aggregationPolicy.observationKind === 'flow' ? ['sum', 'none'] : ['difference', 'none']).map(v => ({ value: v, label: ({ sum: '期间求和', difference: '期末减期初', none: '不聚合' } as Record<string, string>)[v] }))}
          onChange={timeAggregation => change({ aggregationPolicy: { ...value.aggregationPolicy, timeAggregation } })} /></label>
        {value.aggregationPolicy.observationKind === 'cumulative_snapshot' && <label>快照重置<Select<'' | 'none' | 'calendar_year_zero'> aria-label="快照重置" disabled={blocked} value={value.aggregationPolicy.reset ?? ''}
          options={[{ value: '', label: '未声明' }, { value: 'none', label: '不重置' }, { value: 'calendar_year_zero', label: '每年归零' }]}
          onChange={reset => change({ aggregationPolicy: { ...value.aggregationPolicy, reset: reset || null } })} /></label>}
      </Space>
      {input('业务时区（可选，如 Asia/Shanghai）', 'metric-zone', value.timeZone, timeZone => change({ timeZone: timeZone || null }))}
      {input('存储时区（与业务时区同时声明）', 'metric-storage-zone', value.storageTimeZone, storageTimeZone => change({ storageTimeZone: storageTimeZone || null }))}
      <label>别名（每行一个）<Input.TextArea aria-label="指标别名" disabled={blocked} value={value.aliases.join('\n')}
        onChange={e => change({ aliases: e.target.value.split('\n') })} /></label>
      <div>草稿版本：{baseline?.version ?? '尚未保存'}；目标发布版本：{baseline?.document.revision ?? '保存后由服务端确定'}；{dirty ? '有未保存修改' : '与已保存草稿一致'}。不会自动替换口径或默认。</div>
      <Button disabled={blocked || !dirty} loading={busy} onClick={() => { const issue = problem(value); if (issue) setNotice(issue); else void submit({ action: 'save', expectedVersion: baseline?.version ?? 0, definition: value, revision: null, contentHash: null }) }}>保存指标草稿</Button>
      {baseline && <MetricReleaseComparison current={published} target={baseline.document} dirty={dirty} />}
      <Checkbox aria-label="确认指标发布" checked={ack} disabled={busy || cache.invalid || (!retryReady && !!pending)} onChange={e => setAck(e.target.checked)}>已核对计算定义、精确依赖和粒度；发布不自动迁移使用方</Checkbox>
      {value.kind === 'ratio' && (!numeratorReady || !denominatorReady) && <Alert type="warning" title="分子和分母的精确版本尚未全部核验可用；可以保存草稿，暂不能发布。" />}
      <Button disabled={blocked || dirty || !ack || !baseline || (value.kind === 'ratio' && (!numeratorReady || !denominatorReady))
        || (published?.revision === baseline.document.revision && published.contentHash === baseline.contentHash)} onClick={() => {
        if (baseline) void submit({ action: 'publish', expectedVersion: baseline.version, definition: value, revision: baseline.document.revision, contentHash: baseline.contentHash })
      }}>发布指标版本</Button>
      {pending && <Button ref={recovery} disabled={busy} onClick={() => void recover()}>读取原提交结果</Button>}
      {pending && retryReady && <Button disabled={busy || !ack} onClick={() => void submit(pending)}>确认重提原请求</Button>}
    </Space>
  </Card>
}
