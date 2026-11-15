import { Form, InputNumber, Select, Switch } from 'antd'
import { getPreferenceValue } from './preference-draft'

type Doc = Record<string, unknown>
export const tableFieldLabels: Record<string, string> = { repeatHeader: '重复表头', captionNumbering: '图注编号', splitRows: '允许跨页断行', borders: '边框', striped: '交替条纹', freezeHeader: '冻结表头', autoFilter: '自动筛选', keepWithCaption: '图片与说明同页', sectionHeadingLevel: '章节起始级别', listMarker: '列表符号', codeFence: '代码块围栏', tableStyle: '表格写法', imageCaptions: '图片说明', references: '引用编号', toc: '生成目录', decimalPlaces: '小数位', thousandsSeparator: '千分位', negativeStyle: '负数样式', percentPlaces: '百分比小数位', dateFormat: '数据日期格式' }
export const borderOptions = [{ value: 'light', label: '浅边框' }, { value: 'all', label: '全部边框' }, { value: 'none', label: '无边框' }]

/** 只开放已有实际产物验证的设置，共用页面草稿与保存流程。 */
export function TablePreferenceFields({ document, format, onChange, disabled = false, errors = [] }: { document: Doc; format: string; onChange: (path: string[], value: unknown) => void; disabled?: boolean; errors?: { path: string; message: string }[] }) {
  const paged = format === 'word' || format === 'pdf'
  const slides = format === 'pptx'
  if (!paged && !slides && format !== 'xlsx') return null
  const prefix = paged || slides ? [format, 'tables'] : [format]
  const keys = slides ? ['repeatHeader', 'borders', 'striped', 'captionNumbering'] : paged ? ['repeatHeader', 'splitRows', 'borders', 'striped', 'captionNumbering'] : ['freezeHeader', 'autoFilter', 'borders', 'striped']
  return <Form layout="vertical" disabled={disabled}>
    {keys.map(key => {
      const path = [...prefix, key], value = getPreferenceValue(document, path)
      const label = key === 'captionNumbering' ? '表格标题编号' : tableFieldLabels[key]
      const issue = errors.find(error => error.path === path.join('.'))
      return <Form.Item key={path.join('.')} label={label} validateStatus={issue ? 'error' : undefined} help={issue?.message}
        extra={paged && key === 'captionNumbering' ? '仅对已登记的表格标题编号；普通正文不改写，模板沿用模板布局。' : undefined}>
        {key === 'borders' ? <Select aria-label={label} value={String(value)} options={borderOptions} onChange={next => onChange(path, next)} /> :
          <Switch id={'preference-' + path.join('.')} aria-label={label} checked={Boolean(value)} onChange={next => onChange(path, next)} />}
      </Form.Item>
    })}
    {paged && <Form.Item label="图片与说明同页" extra="仅控制图片和紧邻说明的分页，不改变图片、正文或数据。">
      <Switch aria-label="图片与说明同页" checked={Boolean(getPreferenceValue(document, [format, 'charts', 'keepWithCaption']) ?? true)}
        onChange={value => onChange([format, 'charts', 'keepWithCaption'], value)} />
    </Form.Item>}
    {format === 'xlsx' && <>
      <Form.Item label="小数位"><InputNumber aria-label="小数位" min={0} max={15} precision={0}
        value={Number(getPreferenceValue(document, ['xlsx', 'numbers', 'decimalPlaces']))}
        onChange={value => { if (value !== null) onChange(['xlsx', 'numbers', 'decimalPlaces'], value) }} /></Form.Item>
      <Form.Item label="千分位"><Switch aria-label="千分位"
        checked={Boolean(getPreferenceValue(document, ['xlsx', 'numbers', 'thousandsSeparator']))}
        onChange={value => onChange(['xlsx', 'numbers', 'thousandsSeparator'], value)} /></Form.Item>
      <Form.Item label="负数样式"><Select aria-label="负数样式"
        value={String(getPreferenceValue(document, ['xlsx', 'numbers', 'negativeStyle']))}
        options={[{ value: 'minus', label: '负号（-1234.56）' }, { value: 'parentheses', label: '括号（1234.56）' }, { value: 'red', label: '红色负号' }]}
        onChange={value => onChange(['xlsx', 'numbers', 'negativeStyle'], value)} /></Form.Item>
      <Form.Item label="百分比小数位" validateStatus={errors.some(error => error.path === 'xlsx.numbers.percentPlaces') ? 'error' : undefined} help={errors.find(error => error.path === 'xlsx.numbers.percentPlaces')?.message}><InputNumber id="preference-xlsx.numbers.percentPlaces" aria-label="百分比小数位" min={0} max={15} precision={0}
        value={Number(getPreferenceValue(document, ['xlsx', 'numbers', 'percentPlaces']))}
        onChange={value => { if (value !== null) onChange(['xlsx', 'numbers', 'percentPlaces'], value) }} /></Form.Item>
      <Form.Item label="数据日期格式"><Select aria-label="数据日期格式" value={String(getPreferenceValue(document, ['xlsx', 'numbers', 'dateFormat']))}
        options={[{ value: 'iso', label: 'YYYY-MM-DD' }, { value: 'slash', label: 'YYYY/MM/DD' }, { value: 'chinese', label: '中文日期' }]}
        onChange={value => onChange(['xlsx', 'numbers', 'dateFormat'], value)} /></Form.Item>
      <p className="preference-wide-field">仅作用于登记的百分数和日期；不按列名或文字外观猜测类型，不改变原值、公式或落款日期。</p>
    </>}
  </Form>
}
