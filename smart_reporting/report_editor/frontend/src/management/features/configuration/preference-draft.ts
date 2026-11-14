type Document = Record<string, unknown>
export type PreferenceChange = { path: string; before: unknown; after: unknown }
export function getPreferenceValue(document: Document, path: string[]): unknown {
  let current: unknown = document
  for (const key of path) current = (current as Document | undefined)?.[key]
  if (current == null && path[1] === 'common') return (document.common as Document)?.[path[2]]
  return current
}
export function setPreferenceValue(document: Document, path: string[], value: unknown): Document {
  const [key, ...rest] = path
  return { ...document, [key]: rest.length ? setPreferenceValue((document[key] || {}) as Document, rest, value) : value }
}
export function preferenceChanges(before: Document, after: Document, prefix = ''): PreferenceChange[] {
  return [...new Set([...Object.keys(before), ...Object.keys(after)])].flatMap(key => {
    const path = prefix ? prefix + '.' + key : key
    const left = before[key], right = after[key]
    if (left && right && typeof left === 'object' && typeof right === 'object') return preferenceChanges(left as Document, right as Document, path)
    return left === right ? [] : [{ path, before: left, after: right }]
  })
}
export function validateSignatureDraft(document: Document) {
  const errors: { path: string; message: string }[] = []
  const headingLevel = getPreferenceValue(document, ['md', 'sectionHeadingLevel'])
  if (headingLevel !== undefined && (typeof headingLevel !== 'number' || !Number.isInteger(headingLevel) || headingLevel < 2 || headingLevel > 4))
    errors.push({ path: 'md.sectionHeadingLevel', message: '请选择二级、三级或四级章节起始级别。' })
  for (const format of ['word', 'pdf']) {
    const value = getPreferenceValue(document, [format, 'tables', 'captionNumbering'])
    if (value !== undefined && typeof value !== 'boolean')
      errors.push({ path: format + '.tables.captionNumbering', message: '请选择开启或关闭表格标题编号。' })
  }
  for (const format of ['word', 'pdf', 'xlsx', 'pptx']) for (const role of format === 'xlsx' ? ['body', 'header'] : format === 'pptx' ? ['body', 'h1', 'table', 'caption'] : ['body', 'h1', 'h2', 'h3', 'table', 'caption']) {
    const prefix = format === 'xlsx' ? [format, role] : [format, 'typography', role]
    const style = getPreferenceValue(document, prefix) as Document | undefined
    if (!style) continue
    for (const [key, min, max] of [['size', 6, 72], ['lineHeight', 1, 3], ['spaceBefore', 0, 72], ['spaceAfter', 0, 72], ['indent', 0, 48]] as const) {
      const value = style[key]
      if (value !== undefined && (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max))
        errors.push({ path: [...prefix, key].join('.'), message: '请输入 ' + min + '–' + max + ' 范围内的有效数值。' })
    }
    if (style.color != null && (typeof style.color !== 'string' || !/^#[0-9a-fA-F]{6}$/.test(style.color)))
      errors.push({ path: [...prefix, 'color'].join('.'), message: '请输入六位十六进制颜色，或清空以恢复默认。' })
  }
  for (const [key, min, max] of [['rowHeight', 8, 409], ['columnWidth', 2, 100]] as const) {
    const value = getPreferenceValue(document, ['xlsx', key])
    if (value != null && (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max))
      errors.push({ path: 'xlsx.' + key, message: '请输入 ' + min + '–' + max + ' 范围内的有效数值，或清空以使用默认。' })
  }
  for (const format of ['common', 'word', 'pdf', 'xlsx', 'pptx']) {
    const prefix = format === 'common' ? ['common'] : [format, 'common']
    const color = getPreferenceValue(document, [...prefix, 'accentColor'])
    if (color !== undefined && (typeof color !== 'string' || !/^#[0-9a-fA-F]{6}$/.test(color)))
      errors.push({ path: [...prefix, 'accentColor'].join('.'), message: '请输入六位十六进制颜色，例如 #174a66。' })
  }
  for (const format of ['common', 'md', 'xlsx', 'pptx', 'pdf', 'word']) {
    const path = format === 'common' ? ['common', 'signer'] : [format, 'common', 'signer']
    const section = format === 'common' ? document.common : (document[format] as Document)?.common
    const value = (section as Document | undefined)?.signer
    if (format !== 'common' && value == null) continue
    if (typeof value !== 'string' || !value.trim() || value.length > 200 || [...value].some(char => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127)) errors.push({ path: path.join('.'), message: '请填写署名，或恢复沿用通用署名。' })
  }
  for (const format of ['md', 'xlsx', 'pptx', 'pdf', 'word']) {
    const value = ((document[format] as Document)?.signature as Document)?.description
    if (value !== undefined && (typeof value !== 'string' || value.length > 600 || [...value].some(char => char.charCodeAt(0) < 32 && char !== '\n'))) {
      errors.push({ path: format + '.signature.description', message: '附加说明最多 600 字，可换行，不能包含控制字符。' })
    }
  }
  for (const format of ['word', 'pdf', 'xlsx', 'pptx']) {
    const prefix = format === 'xlsx' ? [format, 'print', 'headerFooter'] : format === 'pptx' ? [format] : [format, 'headerFooter']
    const value = getPreferenceValue(document, prefix) as Document | undefined
    if (format === 'word' || format === 'pdf') {
      for (const key of ['headerDistance', 'footerDistance']) {
        const distance = value?.[key]
        if (distance !== undefined && (typeof distance !== 'number' || !Number.isFinite(distance) || distance < 0 || distance > 50))
          errors.push({ path: [...prefix, key].join('.'), message: '距页面边缘需为 0–50 毫米的有效数值。' })
      }
      const start = value?.pageNumberStart
      if (start !== undefined && (typeof start !== 'number' || !Number.isInteger(start) || start < 1 || start > 9999))
        errors.push({ path: [...prefix, 'pageNumberStart'].join('.'), message: '正文页码起点需为 1–9999 的整数。' })
    }
    const stylePrefix = format === 'pptx' ? [...prefix, 'footerStyle'] : [...prefix, 'style']
    const style = getPreferenceValue(document, stylePrefix) as Document | undefined
    if (style?.size !== undefined && (typeof style.size !== 'number' || !Number.isFinite(style.size) || style.size < 6 || style.size > 72))
      errors.push({ path: [...stylePrefix, 'size'].join('.'), message: '页眉页脚字号需为 6–72 磅的有效数值。' })
    if (style?.color != null && (typeof style.color !== 'string' || !/^#[0-9a-fA-F]{6}$/.test(style.color)))
      errors.push({ path: [...stylePrefix, 'color'].join('.'), message: '请输入六位十六进制颜色，或清空以恢复默认。' })
    if (format === 'pptx' && style?.indent !== undefined && (typeof style.indent !== 'number' || !Number.isFinite(style.indent) || style.indent < 0 || style.indent > 48))
      errors.push({ path: 'pptx.footerStyle.indent', message: '首行缩进需为 0–48 磅的有效数值。' })
    const names = format === 'pptx' ? ['footer'] : ['header', 'footer', 'firstHeader', 'firstFooter', 'evenHeader', 'evenFooter']
    const allowed = new Set(['title', 'signer', 'period', 'date', 'filename', ...(format === 'pptx' ? ['slide', 'slides'] : ['page', 'pages'])])
    for (const name of names) for (const side of ['left', 'center', 'right']) {
      const text = (value?.[name] as Document | undefined)?.[side]
      if (text === undefined) continue
      const valid = typeof text === 'string' && text.length <= 200 && ![...text].some(char => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127) &&
        text.replace(/\{\{|\}\}|\{([^{}]+)\}/g, (token, field: string | undefined) => field && !allowed.has(field) ? token : '').search(/[{}]/) === -1
      if (!valid) errors.push({ path: [...prefix, name, side].join('.'), message: '请使用本格式支持的插入字段，文字最多 200 字且不能包含控制字符。' })
    }
  }
  for (const format of ['word', 'pdf', 'xlsx']) {
    const path = format === 'xlsx' ? [format, 'print', 'page'] : [format, 'page']
    const page = getPreferenceValue(document, path) as Document | undefined
    const margins = page?.margins as Record<string, number> | undefined
    if (!margins) continue
    let valid = true
    for (const side of ['top', 'bottom', 'left', 'right']) {
      if (typeof margins[side] !== 'number' || !Number.isFinite(margins[side]) || margins[side] < 0 || margins[side] > 100) {
        errors.push({ path: [...path, 'margins', side].join('.'), message: '边距需为 0–100 毫米的有效数值。' }); valid = false
      }
    }
    const size = ({ A4: [210, 297], A3: [297, 420], Letter: [215.9, 279.4] } as Record<string, number[]>)[String(page?.paper)]
    if (!valid || !size) continue
    const [width, height] = page?.orientation === 'landscape' ? [...size].reverse() : size
    if (width - margins.left - margins.right < 20) errors.push({ path: [...path, 'margins', 'left'].join('.'), message: '左右边距至少应保留 20 毫米的可打印宽度。' })
    if (height - margins.top - margins.bottom < 20) errors.push({ path: [...path, 'margins', 'top'].join('.'), message: '上下边距至少应保留 20 毫米的可打印高度。' })
  }
  for (const format of ['word', 'pdf', 'xlsx', 'pptx']) {
    const signature = getPreferenceValue(document, [format, 'signature']) as Document | undefined
    const size = signature?.size, color = signature?.color
    const spaceBefore = signature?.spaceBefore
    const indent = signature?.indent
    if (format === 'pptx' && indent !== undefined && (typeof indent !== 'number' || !Number.isFinite(indent) || indent < 0 || indent > 48))
      errors.push({ path: 'pptx.signature.indent', message: '首行缩进需为 0–48 磅的有效数值。' })
    if (format === 'pptx' && spaceBefore !== undefined && (typeof spaceBefore !== 'number' || !Number.isFinite(spaceBefore) || spaceBefore < 0 || spaceBefore > 144))
      errors.push({ path: 'pptx.signature.spaceBefore', message: '与落款页标题间距需为 0–144 磅的有效数值。' })
    if (size !== undefined && (typeof size !== 'number' || !Number.isFinite(size) || size < 6 || size > 72))
      errors.push({ path: format + '.signature.size', message: '落款字号需为 6–72 磅的有效数值。' })
    if (color != null && (typeof color !== 'string' || !/^#[0-9a-fA-F]{6}$/.test(color)))
      errors.push({ path: format + '.signature.color', message: '请输入六位十六进制颜色，例如 #172033，或恢复默认。' })
  }
  const quality = getPreferenceValue(document, ['pdf', 'imageQuality'])
  const percentPlaces = getPreferenceValue(document, ['xlsx', 'numbers', 'percentPlaces'])
  if (percentPlaces !== undefined && (typeof percentPlaces !== 'number' || !Number.isInteger(percentPlaces) || percentPlaces < 0 || percentPlaces > 15))
    errors.push({ path: 'xlsx.numbers.percentPlaces', message: '百分比小数位需为 0–15 的整数。' })
  if (quality !== undefined && (typeof quality !== 'number' || !Number.isInteger(quality) || quality < 50 || quality > 100))
    errors.push({ path: 'pdf.imageQuality', message: 'JPEG 图像质量需为 50–100 的整数。' })
  return errors
}
