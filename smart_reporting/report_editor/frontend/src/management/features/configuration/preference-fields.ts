type Fields = Record<string, unknown>
const pick = (value: Fields, keys: string[]) => Object.fromEntries(keys.filter(key => key in value && value[key] !== null && value[key] !== undefined && value[key] !== '').map(key => [key, value[key]]))
const textStyle = (value: unknown) => pick((value || {}) as Fields, ['font', 'size'])

/** 维护界面只保留独立决策，排版细节继续使用现有默认。 */
export function preferenceFields(section: string, value: Fields): Fields {
  if (section === 'signature') return pick(value, ['signer', 'dateFormat', 'description', 'font', 'size', 'align'])
  if (section === 'common') return pick(value, ['signer', 'dateFormat', 'font', 'accentColor'])
  if (section === 'page') {
    const fields = pick(value, ['page', 'aspectRatio', 'alignment', 'wrapText', 'density', 'layout'])
    if (value.page) fields.page = pick(value.page as Fields, ['paper', 'orientation'])
    const body = (value.typography as Fields | undefined)?.body || value.body
    if (body) fields.body = textStyle(body)
    return fields
  }
  if (section === 'export') {
    const fields = pick(value, ['cover', 'toc', 'sources', 'references'])
    if (value.print) fields.print = pick(value.print as Fields, ['fitToWidth', 'fitToHeight', 'scalePercent', 'repeatTitleRows'])
    return fields
  }
  if (section === 'headerFooter') {
    if (value.enabled === false) return { enabled: false }
    const fields = pick(value, ['enabled', 'header', 'footer', 'firstPageDifferent', 'oddEvenDifferent', 'pageNumbers', 'hideTitleSlideFooter'])
    if (value.firstPageDifferent) Object.assign(fields, pick(value, ['firstHeader', 'firstFooter']))
    if (value.oddEvenDifferent) Object.assign(fields, pick(value, ['evenHeader', 'evenFooter']))
    if (typeof value.pageNumberStart === 'number' && value.pageNumberStart !== 1) fields.pageNumberStart = value.pageNumberStart
    for (const key of ['header', 'footer', 'firstHeader', 'firstFooter', 'evenHeader', 'evenFooter']) {
      if (fields[key] && typeof fields[key] === 'object') fields[key] = Object.fromEntries(
        Object.entries(fields[key] as Fields).filter(([, text]) => text !== '' && text !== null))
    }
    return fields
  }
  if (section === 'tables') {
    const fields = pick(value, ['freezeHeader', 'autoFilter', 'borders', 'striped'])
    if (value.tables) fields.tables = pick(value.tables as Fields, ['repeatHeader', 'borders', 'striped', 'captionNumbering'])
    if (value.numbers) fields.numbers = pick(value.numbers as Fields, ['decimalPlaces', 'thousandsSeparator', 'percentPlaces', 'negativeStyle'])
    return fields
  }
  return { ...value }
}
