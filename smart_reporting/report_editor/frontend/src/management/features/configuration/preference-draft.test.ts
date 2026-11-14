import { expect, it } from 'vitest'
import { getPreferenceValue, setPreferenceValue, preferenceChanges, validateSignatureDraft } from './preference-draft'

const initial = { common: { signer: '通用署名', dateFormat: 'iso' },
  word: { common: { signer: null, dateFormat: null }, signature: { description: '' } },
  md: { common: { signer: '独立署名' }, signature: { description: '旧说明' } } }

it('章节起始级别只接受二至四级整数，旧快照缺省保持兼容', () => {
  expect(validateSignatureDraft(initial)).toEqual([])
  for (const value of [1, 5, 2.5, '3', null]) {
    expect(validateSignatureDraft(setPreferenceValue(initial, ['md', 'sectionHeadingLevel'], value)))
      .toContainEqual(expect.objectContaining({ path: 'md.sectionHeadingLevel' }))
  }
  for (const value of [2, 3, 4]) expect(validateSignatureDraft(setPreferenceValue(initial, ['md', 'sectionHeadingLevel'], value))).toEqual([])
})

it('PPTX正文与标题的已支持排版错误定位到具体角色', () => {
  for (const [role, key, value] of [['body', 'size', 73], ['h1', 'lineHeight', 0.5], ['h1', 'color', 'red']]) {
    expect(validateSignatureDraft(setPreferenceValue(initial, ['pptx', 'typography', String(role), String(key)], value)))
      .toEqual([expect.objectContaining({ path: 'pptx.typography.' + role + '.' + key })])
  }
})

it('主题色校验定位真实字段，恢复沿用不报错', () => {
  expect(validateSignatureDraft(setPreferenceValue(initial, ['common', 'accentColor'], 'red'))).toContainEqual({ path: 'common.accentColor', message: '请输入六位十六进制颜色，例如 #174a66。' })
  expect(validateSignatureDraft(setPreferenceValue(initial, ['word', 'common', 'accentColor'], '#123'))).toContainEqual({ path: 'word.common.accentColor', message: '请输入六位十六进制颜色，例如 #174a66。' })
  expect(validateSignatureDraft(setPreferenceValue(initial, ['word', 'common', 'accentColor'], null))).toEqual([])
})

it('排版数值和颜色校验定位角色，空覆盖保持继承', () => {
  for (const [key, value] of [['size', 5], ['lineHeight', 3.1], ['spaceBefore', -1], ['spaceAfter', 73], ['indent', 49], ['color', 'red']]) {
    expect(validateSignatureDraft(setPreferenceValue(initial, ['word', 'typography', 'h1', String(key)], value)))
      .toEqual([expect.objectContaining({ path: 'word.typography.h1.' + key })])
  }
  expect(validateSignatureDraft(setPreferenceValue(initial, ['pdf', 'typography', 'caption', 'color'], null))).toEqual([])
})

it('百分比小数位必须为0到15整数并定位数字分区', () => {
  for (const value of [-1, 16, 2.5, NaN]) expect(validateSignatureDraft(setPreferenceValue(initial, ['xlsx', 'numbers', 'percentPlaces'], value)))
    .toContainEqual({ path: 'xlsx.numbers.percentPlaces', message: '百分比小数位需为 0–15 的整数。' })
  expect(validateSignatureDraft(setPreferenceValue(initial, ['xlsx', 'numbers', 'percentPlaces'], 3))).toEqual([])
})

it('覆盖和恢复沿用均为独立字段，不改写其他格式和初始文档', () => {
  const next = setPreferenceValue(initial, ['word', 'common', 'signer'], 'Word署名')
  expect(getPreferenceValue(next, ['word', 'common', 'signer'])).toBe('Word署名')
  expect(initial.word.common.signer).toBeNull()
  expect(next.md).toEqual(initial.md)
  const restored = setPreferenceValue(next, ['word', 'common', 'signer'], null)
  expect(getPreferenceValue(restored, ['word', 'common', 'signer'])).toBe('通用署名')
})

it('差异定位到真实字段，署名错误能定位到对应格式', () => {
  const changed = setPreferenceValue(initial, ['word', 'common', 'signer'], ' ')
  expect(preferenceChanges(initial, changed)).toEqual([{ path: 'word.common.signer', before: null, after: ' ' }])
  expect(validateSignatureDraft(changed)).toEqual([{ path: 'word.common.signer', message: '请填写署名，或恢复沿用通用署名。' }])
})

it('说明校验定位到格式，保留合法多行并拒绝控制字符', () => {
  expect(validateSignatureDraft(setPreferenceValue(initial, ['word', 'signature', 'description'], '一行\n下一行'))).toEqual([])
  expect(validateSignatureDraft(setPreferenceValue(initial, ['word', 'signature', 'description'], '含\t控制字符'))).toEqual([
    { path: 'word.signature.description', message: '附加说明最多 600 字，可换行，不能包含控制字符。' },
  ])
})

it('页眉页脚仅接受对应格式动态字段，普通文字与转义花括号合法', () => {
  const valid = setPreferenceValue(initial, ['word', 'headerFooter'], { enabled: true, header: { left: '{{示例}} {title}', center: '', right: '{page}/{pages}' } })
  expect(validateSignatureDraft(valid)).toEqual([])
  const invalid = setPreferenceValue(valid, ['word', 'headerFooter', 'header', 'right'], '{slide}')
  expect(validateSignatureDraft(invalid)).toContainEqual({ path: 'word.headerFooter.header.right', message: '请使用本格式支持的插入字段，文字最多 200 字且不能包含控制字符。' })
  const slides = setPreferenceValue(initial, ['pptx', 'footer', 'left'], '{page}')
  expect(validateSignatureDraft(slides)).toContainEqual({ path: 'pptx.footer.left', message: '请使用本格式支持的插入字段，文字最多 200 字且不能包含控制字符。' })
})

it('页边距拒绝非有限数和不足20毫米的可打印空间，横向按交换后尺寸计算', () => {
  const page = { paper: 'A4', orientation: 'portrait', margins: { top: 25, right: 98, bottom: 24, left: 98 } }
  const invalid = setPreferenceValue(initial, ['xlsx', 'print', 'page'], page)
  expect(validateSignatureDraft(invalid)).toContainEqual({ path: 'xlsx.print.page.margins.left', message: '左右边距至少应保留 20 毫米的可打印宽度。' })
  expect(validateSignatureDraft(setPreferenceValue(invalid, ['xlsx', 'print', 'page', 'orientation'], 'landscape'))).toEqual([])
  expect(validateSignatureDraft(setPreferenceValue(initial, ['word', 'page'], { ...page, margins: { ...page.margins, left: NaN } })))
    .toContainEqual({ path: 'word.page.margins.left', message: '边距需为 0–100 毫米的有效数值。' })
})

it('落款字号与颜色本地校验，不允许无效样式保存', () => {
  expect(validateSignatureDraft(setPreferenceValue(initial, ['word', 'signature', 'size'], 90)))
    .toContainEqual({ path: 'word.signature.size', message: '落款字号需为 6–72 磅的有效数值。' })
  expect(validateSignatureDraft(setPreferenceValue(initial, ['word', 'signature', 'color'], '#bad')))
    .toContainEqual({ path: 'word.signature.color', message: '请输入六位十六进制颜色，例如 #172033，或恢复默认。' })
  expect(validateSignatureDraft(setPreferenceValue(initial, ['word', 'signature', 'color'], null))).toEqual([])
})

it('PDF图像质量只接受50至100的整数并定位输出区字段', () => {
  for (const quality of [49, 101, 75.5, NaN]) expect(validateSignatureDraft(setPreferenceValue(initial, ['pdf', 'imageQuality'], quality)))
    .toContainEqual({ path: 'pdf.imageQuality', message: 'JPEG 图像质量需为 50–100 的整数。' })
  expect(validateSignatureDraft(setPreferenceValue(initial, ['pdf', 'imageQuality'], 75))).toEqual([])
})

it('XLSX排版边界按原生模型校验，自动行列尺寸允许为空', () => {
  expect(validateSignatureDraft(setPreferenceValue(initial, ['xlsx', 'header', 'size'], 90))).toEqual(expect.arrayContaining([
    expect.objectContaining({ path: 'xlsx.header.size' }),
  ]))
  for (const [key, value] of [['rowHeight', 7], ['columnWidth', 101]] as const)
    expect(validateSignatureDraft(setPreferenceValue(initial, ['xlsx', key], value))).toEqual(expect.arrayContaining([expect.objectContaining({ path: 'xlsx.' + key })]))
  expect(validateSignatureDraft(setPreferenceValue(initial, ['xlsx', 'columnWidth'], null))).toEqual([])
})

it('演示文稿落款标题间距只接受0至144磅且错误定位到字段', () => {
  for (const space of [-1, 145, NaN, Infinity, '18'])
    expect(validateSignatureDraft(setPreferenceValue(initial, ['pptx', 'signature', 'spaceBefore'], space)))
      .toContainEqual({ path: 'pptx.signature.spaceBefore', message: '与落款页标题间距需为 0–144 磅的有效数值。' })
  for (const space of [0, 18.5, 144])
    expect(validateSignatureDraft(setPreferenceValue(initial, ['pptx', 'signature', 'spaceBefore'], space)))
      .not.toEqual(expect.arrayContaining([expect.objectContaining({ path: 'pptx.signature.spaceBefore' })]))
})
