import { Button, Collapse, Input, InputNumber, Select, Space } from 'antd'
import type { PolicyDefinition } from './editor-contracts'
import { MetricFieldPicker } from '../metrics/field-picker'

type Scalar = string | number | boolean | null
const operators = { eq: '等于', ne: '不等于', lt: '小于', le: '小于等于', gt: '大于', ge: '大于等于', in: '属于所列值', is_null: '为空' }
function ScalarField({ label, value, disabled, onChange }: { label: string; value: Scalar; disabled: boolean; onChange: (value: Scalar) => void }) {
 const type = value === null ? 'null' : typeof value
 return <Space wrap>
  <label>{label}类型<Select aria-label={label + '类型'} disabled={disabled} value={type} style={{ width: 110 }}
   options={[{ value: 'string', label: '文本' }, { value: 'number', label: '数字' }, { value: 'boolean', label: '布尔值' }, { value: 'null', label: '空值' }]}
   onChange={next => onChange(next === 'string' ? '' : next === 'number' ? 0 : next === 'boolean' ? false : null)} /></label>
  {typeof value === 'string' && <label>{label}<Input aria-label={label} disabled={disabled} value={value} onChange={e => onChange(e.target.value)} /></label>}
  {typeof value === 'number' && <label>{label}<InputNumber aria-label={label} disabled={disabled} value={value} onChange={next => onChange(next)} /></label>}
  {typeof value === 'boolean' && <label>{label}<Select aria-label={label} disabled={disabled} value={String(value)} options={[{ value: 'true', label: '真' }, { value: 'false', label: '假' }]} onChange={next => onChange(next === 'true')} /></label>}
  {value === null && <span>{label}：空值</span>}
 </Space>
}

export function PolicyRuleFields({ scope, value, disabled, onChange }: { scope: { database: string; companyId: string }; value: PolicyDefinition; disabled: boolean; onChange: (patch: Partial<PolicyDefinition>) => void }) {
 const field = (label: string, content: string, update: (next: string) => void, type = 'text') => <label style={{ display: 'grid', gap: 4 }}>{label}<Input aria-label={label} type={type} disabled={disabled} value={content} onChange={e => update(e.target.value)} /></label>
 const pick = (label: string, content: string | null, update: (next: string) => void) => <MetricFieldPicker scope={scope} label={label} value={content} disabled={disabled} onChange={update} />
 const filter = (index: number, patch: Partial<PolicyDefinition['filters'][number]>) => onChange({ filters: value.filters.map((item, i) => i === index ? { ...item, ...patch } : item) })
 const join = (index: number, patch: Partial<PolicyDefinition['joins'][number]>) => onChange({ joins: value.joins.map((item, i) => i === index ? { ...item, ...patch } : item) })
 const readiness = (patch: Partial<PolicyDefinition['readinessPolicy']>) => onChange({ readinessPolicy: { ...value.readinessPolicy, ...patch } })
 const period = (index: number, patch: Partial<PolicyDefinition['readinessPolicy']['expectedPeriods'][number]>) => readiness({ expectedPeriods: value.readinessPolicy.expectedPeriods.map((item, i) => i === index ? { ...item, ...patch } : item) })
 const group = (index: number, next: PolicyDefinition['readinessPolicy']['expectedGroups'][number]) => readiness({ expectedGroups: value.readinessPolicy.expectedGroups.map((item, i) => i === index ? next : item) })
 const stack = { display: 'grid', gap: 12 }
 return <Collapse defaultActiveKey={['filters', 'joins', 'readiness']} items={[
  { key: 'filters', label: `筛选条件（${value.filters.length}）`, children: <div style={stack}>
   <div>所有条件同时成立才纳入计算。比较值须明确文本、数字、布尔或空值，字段使用完整引用。</div>
   {value.filters.map((item, index) => <fieldset key={index} style={stack}><legend>筛选 {index + 1}</legend>
    {field(`筛选 ${index + 1} 字段`, item.fieldRef, fieldRef => filter(index, { fieldRef }))}
    {pick('筛选 ' + (index + 1) + ' 字段', item.fieldRef, fieldRef => filter(index, { fieldRef }))}
    <label>比较方式<Select aria-label={`筛选 ${index + 1} 比较方式`} disabled={disabled} value={item.operator} style={{ width: '100%' }}
     options={Object.entries(operators).map(([key, label]) => ({ value: key, label }))}
     onChange={operator => filter(index, { operator, values: operator === 'is_null' ? [] : operator === 'in' ? (item.values.length ? item.values : ['']) : [item.values[0] ?? ''] })} /></label>
    {item.values.map((v, i) => <Space key={i} wrap><ScalarField label={`筛选 ${index + 1} 值 ${i + 1}`} value={v} disabled={disabled} onChange={next => filter(index, { values: item.values.map((old, j) => j === i ? next : old) })} />
     {item.operator === 'in' && <Button disabled={disabled || item.values.length <= 1} onClick={() => filter(index, { values: item.values.filter((_, j) => j !== i) })}>移除筛选值 {index + 1}-{i + 1}</Button>}
    </Space>)}
    {item.operator === 'in' && <Button disabled={disabled || item.values.length >= 200} onClick={() => filter(index, { values: [...item.values, ''] })}>添加筛选值 {index + 1}</Button>}
    <Button disabled={disabled} onClick={() => onChange({ filters: value.filters.filter((_, i) => i !== index) })}>移除筛选 {index + 1}</Button>
   </fieldset>)}
   <Button disabled={disabled || value.filters.length >= 100} onClick={() => onChange({ filters: [...value.filters, { fieldRef: '', operator: 'eq', values: [''] }] })}>添加筛选</Button>
  </div> },
  { key: 'joins', label: `表关联（${value.joins.length}）`, children: <div style={stack}>
   <div>仅支持多对一关联；左右键一一配对。关联后的粒度应使用已登记维度标识。</div>
   {value.joins.map((item, index) => <fieldset key={index} style={stack}><legend>关联 {index + 1} · 多对一</legend>
    {item.leftKeys.map((left, i) => <div key={i} style={stack}>
     {field(`关联 ${index + 1} 左键 ${i + 1}`, left, next => join(index, { leftKeys: item.leftKeys.map((old, j) => j === i ? next : old) }))}
     {pick('关联 ' + (index + 1) + ' 左键 ' + (i + 1), left, next => join(index, { leftKeys: item.leftKeys.map((old, j) => j === i ? next : old) }))}
     {field(`关联 ${index + 1} 右键 ${i + 1}`, item.rightKeys[i] ?? '', next => join(index, { rightKeys: item.rightKeys.map((old, j) => j === i ? next : old) }))}
     {pick('关联 ' + (index + 1) + ' 右键 ' + (i + 1), item.rightKeys[i] ?? null, next => join(index, { rightKeys: item.rightKeys.map((old, j) => j === i ? next : old) }))}
     <Button disabled={disabled || item.leftKeys.length <= 1} onClick={() => join(index, { leftKeys: item.leftKeys.filter((_, j) => j !== i), rightKeys: item.rightKeys.filter((_, j) => j !== i) })}>移除关联键 {index + 1}-{i + 1}</Button>
    </div>)}
    <Button disabled={disabled || item.leftKeys.length >= 10} onClick={() => join(index, { leftKeys: [...item.leftKeys, ''], rightKeys: [...item.rightKeys, ''] })}>添加关联键 {index + 1}</Button>
    {field(`关联 ${index + 1} 输出粒度（逗号分隔）`, item.outputGrain.join(','), next => join(index, { outputGrain: next.split(',').map(id => id.trim()) }))}
    <Button disabled={disabled} onClick={() => onChange({ joins: value.joins.filter((_, i) => i !== index) })}>移除关联 {index + 1}</Button>
   </fieldset>)}
   <Button disabled={disabled || value.joins.length >= 20} onClick={() => onChange({ joins: [...value.joins, { leftKeys: [''], rightKeys: [''], outputGrain: [], cardinality: 'many_to_one' }] })}>添加关联</Button>
  </div> },
  { key: 'readiness', label: '数据充分性', children: <div style={stack}>
   <div>预期期间采用开始包含、结束不包含；未声明不代表数据完整。预期分组用于识别缺失对象。</div>
   {value.readinessPolicy.expectedPeriods.map((item, index) => <fieldset key={index} style={stack}><legend>预期期间 {index + 1}</legend>
    {field(`预期期间 ${index + 1} 开始`, item.start, start => period(index, { start }), 'date')}
    {field(`预期期间 ${index + 1} 结束`, item.end, end => period(index, { end }), 'date')}
    <Button disabled={disabled} onClick={() => readiness({ expectedPeriods: value.readinessPolicy.expectedPeriods.filter((_, i) => i !== index) })}>移除预期期间 {index + 1}</Button>
   </fieldset>)}
   <Button disabled={disabled} onClick={() => readiness({ expectedPeriods: [...value.readinessPolicy.expectedPeriods, { start: '', end: '' }] })}>添加预期期间</Button>
   {value.readinessPolicy.expectedGroups.map((items, index) => <fieldset key={index} style={stack}><legend>预期分组 {index + 1}</legend>
    {items.map((item, i) => <div key={i} style={stack}>
     {field(`预期分组 ${index + 1} 维度 ${i + 1}`, item.dimensionId, dimensionId => group(index, items.map((old, j) => j === i ? { ...old, dimensionId } : old)))}
     <ScalarField label={`预期分组 ${index + 1} 维度 ${i + 1} 值`} value={item.value} disabled={disabled} onChange={next => group(index, items.map((old, j) => j === i ? { ...old, value: next } : old))} />
     <Button disabled={disabled || items.length <= 1} onClick={() => group(index, items.filter((_, j) => j !== i))}>移除分组维度 {index + 1}-{i + 1}</Button>
    </div>)}
    <Button disabled={disabled} onClick={() => group(index, [...items, { dimensionId: '', value: '' }])}>添加分组维度 {index + 1}</Button>
    <Button disabled={disabled} onClick={() => readiness({ expectedGroups: value.readinessPolicy.expectedGroups.filter((_, i) => i !== index) })}>移除预期分组 {index + 1}</Button>
   </fieldset>)}
   <Button disabled={disabled} onClick={() => readiness({ expectedGroups: [...value.readinessPolicy.expectedGroups, [{ dimensionId: '', value: '' }]] })}>添加预期分组</Button>
   {field('源水位字段（可选）', value.readinessPolicy.watermarkField ?? '', watermarkField => readiness({ watermarkField: watermarkField || null }))}
   {pick('源水位字段', value.readinessPolicy.watermarkField, watermarkField => readiness({ watermarkField }))}
   <label>允许最大延迟（秒，可选）<InputNumber aria-label="允许最大延迟秒" disabled={disabled} min={0} precision={0} value={value.readinessPolicy.maximumDelaySeconds} onChange={maximumDelaySeconds => readiness({ maximumDelaySeconds })} /></label>
   <label>空数据如何处理<Select aria-label="空数据如何处理" disabled={disabled} value={value.readinessPolicy.emptyObservation} style={{ width: '100%' }}
    options={[{ value: 'unknown', label: '未知，不直接视为零' }, { value: 'zero_when_complete', label: '仅在数据完整时视为零' }]} onChange={emptyObservation => readiness({ emptyObservation })} /></label>
  </div> },
 ]} />
}
