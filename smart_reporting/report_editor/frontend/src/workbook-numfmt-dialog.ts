/**
 * Home ▸ Cells ▸ Format ▸ Format Cells ▸ Number (fixed source GenOffice
 * f8c17004 `numfmt-dialog.ts` — ported verbatim below the marker except the
 * short-date import — and the Number tab of `FormatCellsDialog.tsx`). The
 * chosen category + options build the pattern, which then goes through the
 * same validated number-format apply as the custom-format dialog: only the
 * display format changes, values and formulas stay.
 */
import { createModal } from './modal'

// ── fixed source numfmt-dialog.ts ────────────────────────────────────────
import { numfmt } from '@univerjs/core'

import { getSystemShortDate } from '@sheets-web/xlsx-engine'

/// Model behind the Format Cells → Number tab: category + sub-options ⇄
/// OOXML pattern. The ribbon's category dropdown (number-format.ts) derives
/// its representative patterns from the same builders.

export type NumfmtCategory =
  | 'general'
  | 'number'
  | 'currency'
  | 'accounting'
  | 'date'
  | 'time'
  | 'percentage'
  | 'fraction'
  | 'scientific'
  | 'text'
  | 'custom'

export type NegativeStyle = 'minus' | 'red' | 'parens' | 'red-parens'

export interface NumfmtOptions {
  readonly category: NumfmtCategory
  readonly decimals: number
  readonly thousands: boolean
  readonly negative: NegativeStyle
  /// Currency/accounting symbol; '' = none.
  readonly symbol: string
  readonly datePattern: string
  readonly timePattern: string
  readonly fractionPattern: string
  readonly custom: string
}

export const NUMFMT_CATEGORIES: readonly NumfmtCategory[] = [
  'general',
  'number',
  'currency',
  'accounting',
  'date',
  'time',
  'percentage',
  'fraction',
  'scientific',
  'text',
  'custom',
]

export const NEGATIVE_STYLES: readonly NegativeStyle[] = ['minus', 'red', 'parens', 'red-parens']

export const CURRENCY_SYMBOLS: readonly string[] = ['¥', '$', '€', '£', 'US$', 'HK$', '₩']

export const DATE_PATTERNS: readonly string[] = [
  'yyyy-mm-dd',
  'yyyy/m/d',
  'm/d/yyyy',
  'd-mmm-yy',
  'mmm-yy',
  'mmmm d, yyyy',
  'dddd, mmmm dd, yyyy',
  'yyyy"年"m"月"d"日"',
  'm"月"d"日"',
  'yyyy-mm-dd hh:mm',
]

/// The Date list with the workbook's system short date first, so a pattern
/// applied by the ribbon's Short Date category classifies as Date.
export function datePatterns(): readonly string[] {
  const system = getSystemShortDate()
  return DATE_PATTERNS.includes(system) ? DATE_PATTERNS : [system, ...DATE_PATTERNS]
}

export const TIME_PATTERNS: readonly string[] = [
  'h:mm',
  'h:mm:ss',
  'hh:mm:ss',
  'h:mm AM/PM',
  'h:mm:ss AM/PM',
  '[h]:mm:ss',
  'mm:ss',
]

export const FRACTION_PATTERNS: readonly string[] = [
  '# ?/?',
  '# ??/??',
  '# ???/???',
  '# ?/2',
  '# ?/4',
  '# ?/8',
  '# ??/16',
  '# ?/10',
]

export const DEFAULT_NUMFMT_OPTIONS: NumfmtOptions = {
  category: 'general',
  decimals: 2,
  thousands: false,
  negative: 'minus',
  symbol: '$',
  datePattern: 'yyyy-mm-dd',
  timePattern: 'h:mm:ss',
  fractionPattern: '# ?/?',
  custom: '',
}

export function clampDecimals(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.min(30, Math.max(0, Math.trunc(value)))
}

function digits(decimals: number): string {
  const count = clampDecimals(decimals)
  return count > 0 ? `.${'0'.repeat(count)}` : ''
}

/// Single-char symbols stay bare ($#,##0); multi-char ones need quoting.
function symbolToken(symbol: string): string {
  if (!symbol) return ''
  return symbol.length === 1 ? symbol : `"${symbol}"`
}

/// Excel's four negative-number styles around a positive-section base.
function withNegative(base: string, negative: NegativeStyle): string {
  switch (negative) {
    case 'minus':
      return base
    case 'red':
      return `${base};[Red]${base}`
    case 'parens':
      return `${base}_);(${base})`
    case 'red-parens':
      return `${base}_);[Red](${base})`
  }
}

export function numfmtPattern(options: NumfmtOptions): string {
  switch (options.category) {
    case 'general':
      return 'General'
    case 'number':
      return withNegative(
        `${options.thousands ? '#,##0' : '0'}${digits(options.decimals)}`,
        options.negative,
      )
    case 'currency':
      return withNegative(
        `${symbolToken(options.symbol)}#,##0${digits(options.decimals)}`,
        options.negative,
      )
    case 'accounting': {
      const symbol = symbolToken(options.symbol)
      const base = `#,##0${digits(options.decimals)}`
      const zero = `"-"${'?'.repeat(clampDecimals(options.decimals))}`
      return `_(${symbol}* ${base}_);_(${symbol}* (${base});_(${symbol}* ${zero}_);_(@_)`
    }
    case 'date':
      return options.datePattern
    case 'time':
      return options.timePattern
    case 'percentage':
      return `0${digits(options.decimals)}%`
    case 'fraction':
      return options.fractionPattern
    case 'scientific':
      return `0${digits(options.decimals)}E+00`
    case 'text':
      return '@'
    case 'custom':
      return options.custom
  }
}

/// Leading `_(<symbol>* #,##0` section shared by Excel's Accounting and
/// (symbol-less) Comma styles.
const ACCOUNTING_SECTION = /^_\((?:"([^"]+)"|([^*\s]))?\* #,##0(?:\.(0+))?_\)/

export function isAccountingPattern(pattern: string): boolean {
  return ACCOUNTING_SECTION.test(pattern)
}

/// Best-effort reverse of numfmtPattern: extract candidate options, rebuild,
/// and only accept on an exact round-trip; anything else lands in Custom.
export function numfmtOptionsOf(pattern: string): NumfmtOptions {
  const defaults = DEFAULT_NUMFMT_OPTIONS
  if (!pattern || pattern === 'General') return { ...defaults, category: 'general' }
  if (pattern === '@') return { ...defaults, category: 'text' }
  if (datePatterns().includes(pattern))
    return { ...defaults, category: 'date', datePattern: pattern }
  if (TIME_PATTERNS.includes(pattern))
    return { ...defaults, category: 'time', timePattern: pattern }
  if (FRACTION_PATTERNS.includes(pattern)) {
    return { ...defaults, category: 'fraction', fractionPattern: pattern }
  }
  let match = /^0(?:\.(0+))?%$/.exec(pattern)
  if (match) return { ...defaults, category: 'percentage', decimals: match[1]?.length ?? 0 }
  match = /^0(?:\.(0+))?E\+00$/.exec(pattern)
  if (match) return { ...defaults, category: 'scientific', decimals: match[1]?.length ?? 0 }
  match = ACCOUNTING_SECTION.exec(pattern)
  if (match) {
    const candidate: NumfmtOptions = {
      ...defaults,
      category: 'accounting',
      symbol: match[1] ?? match[2] ?? '',
      decimals: match[3]?.length ?? 0,
    }
    // Excel's own accounting codes escape the parens and quote the symbol.
    const canonical = pattern.replace(/\\([()])/g, '$1').replace(/_\("([^"])"\* /g, '_($1* ')
    if (numfmtPattern(candidate) === canonical) return candidate
  }
  match = /^(?:"([^"]+)"|([^0#".,;[\]_]))?(#,##0|0)(?:\.(0+))?(?:[_;].*)?$/.exec(pattern)
  if (match) {
    const symbol = match[1] ?? match[2] ?? ''
    for (const negative of NEGATIVE_STYLES) {
      const candidate: NumfmtOptions = symbol
        ? { ...defaults, category: 'currency', symbol, decimals: match[4]?.length ?? 0, negative }
        : {
            ...defaults,
            category: 'number',
            thousands: match[3] === '#,##0',
            decimals: match[4]?.length ?? 0,
            negative,
          }
      if (numfmtPattern(candidate) === pattern) return candidate
    }
  }
  return { ...defaults, category: 'custom', custom: pattern }
}

export function numfmtPreview(pattern: string, value: number | string): string {
  try {
    return numfmt.format(pattern || 'General', value, { throws: false })
  } catch {
    return typeof value === 'string' ? value : String(value)
  }
}

/// Excel 1900-system serial for "now", so date/time previews show today.
export function todaySerial(now = new Date()): number {
  const utc = Date.UTC(
    now.getFullYear(),
    now.getMonth(),
    now.getDate(),
    now.getHours(),
    now.getMinutes(),
    now.getSeconds(),
  )
  return utc / 86400000 + 25569
}

/// Preview value: the anchor cell's number when there is one, else a
/// category-appropriate stand-in.
export function sampleValue(
  category: NumfmtCategory,
  anchor: number | string | null,
  serial: number,
): number | string {
  if (typeof anchor === 'number') return anchor
  if (category === 'date' || category === 'time') return serial
  if (typeof anchor === 'string' && anchor !== '') return anchor
  return 1234.56
}

// ── fixed source FormatCellsDialog.tsx Number tab (DOM) ──────────────────
const CATEGORY_LABELS: Record<NumfmtCategory, string> = {
  general: '常规', number: '数值', currency: '货币', accounting: '会计专用', date: '日期', time: '时间',
  percentage: '百分比', fraction: '分数', scientific: '科学记数', text: '文本', custom: '自定义',
}
const NEGATIVE_LABELS: Record<NegativeStyle, string> = { minus: '-1234.10', red: '红色 1234.10', parens: '(1234.10)', 'red-parens': '红色 (1234.10)' }
const DECIMAL_CATEGORIES: readonly NumfmtCategory[] = ['number', 'currency', 'accounting', 'percentage', 'scientific']

export interface FormatCellsDialogOptions {
  /** Current pattern of the selection (undefined when mixed/unavailable) and the anchor value for the preview. */
  current(): { pattern: string | undefined; anchor: number | string | null }
  /** Validates and applies the pattern to the captured target; throws a user-facing error. */
  apply(pattern: string): void
}

export function createFormatCellsDialog(root: HTMLElement, options: FormatCellsDialogOptions) {
  const modal = createModal({ root, label: '设置单元格格式', overlayClass: 'workbook-ribbon-format-overlay', cardClass: 'workbook-ribbon-format-dialog workbook-ribbon-numfmt-dialog', closeLabel: '关闭', content: `
    <h2>设置单元格格式：数字</h2><form class="workbook-ribbon-format-form">
      <div class="workbook-ribbon-numfmt-cats" role="listbox" aria-label="分类">${NUMFMT_CATEGORIES.map(category =>
        `<button type="button" role="option" data-numfmt-category="${category}">${CATEGORY_LABELS[category]}</button>`).join('')}</div>
      <p class="workbook-ribbon-numfmt-preview">示例：<output data-numfmt-preview></output></p>
      <label data-numfmt-field="decimals">小数位数<input type="number" min="0" max="30" data-numfmt-decimals></label>
      <label data-numfmt-field="symbol">货币符号<select data-numfmt-symbol>${['', ...CURRENCY_SYMBOLS].map(symbol => `<option value="${symbol}">${symbol || '无'}</option>`).join('')}</select></label>
      <label data-numfmt-field="thousands"><input type="checkbox" data-numfmt-thousands>使用千位分隔符</label>
      <label data-numfmt-field="negative">负数<select data-numfmt-negative>${NEGATIVE_STYLES.map(style => `<option value="${style}">${NEGATIVE_LABELS[style]}</option>`).join('')}</select></label>
      <label data-numfmt-field="date">类型<select data-numfmt-date></select></label>
      <label data-numfmt-field="time">类型<select data-numfmt-time>${TIME_PATTERNS.map(pattern => `<option value="${pattern}">${pattern}</option>`).join('')}</select></label>
      <label data-numfmt-field="fraction">类型<select data-numfmt-fraction>${FRACTION_PATTERNS.map(pattern => `<option value="${pattern}">${pattern}</option>`).join('')}</select></label>
      <label data-numfmt-field="custom">类型<input type="text" maxlength="255" autocomplete="off" spellcheck="false" data-numfmt-custom></label>
      <p class="workbook-ribbon-axis-help" data-numfmt-note></p>
      <p class="workbook-ribbon-format-error" role="alert"></p>
      <div class="workbook-ribbon-format-actions"><button type="button" class="workbook-ribbon-format-cancel">取消</button><button type="submit" class="workbook-ribbon-format-apply">确定</button></div>
    </form>` })
  const card = modal.card
  const $ = <T extends HTMLElement>(selector: string) => card.querySelector<T>(selector)!
  const error = $<HTMLElement>('[role="alert"]')
  let state: NumfmtOptions = DEFAULT_NUMFMT_OPTIONS
  let anchor: number | string | null = null
  const render = () => {
    for (const button of card.querySelectorAll<HTMLButtonElement>('[data-numfmt-category]')) {
      const selected = button.dataset.numfmtCategory === state.category
      button.setAttribute('aria-selected', String(selected)); button.classList.toggle('active', selected)
    }
    const show = (field: string, visible: boolean) => { $<HTMLElement>(`[data-numfmt-field="${field}"]`).hidden = !visible }
    show('decimals', DECIMAL_CATEGORIES.includes(state.category))
    show('symbol', state.category === 'currency' || state.category === 'accounting')
    show('thousands', state.category === 'number')
    show('negative', state.category === 'number' || state.category === 'currency')
    show('date', state.category === 'date'); show('time', state.category === 'time')
    show('fraction', state.category === 'fraction'); show('custom', state.category === 'custom')
    $<HTMLInputElement>('[data-numfmt-decimals]').value = String(state.decimals)
    $<HTMLSelectElement>('[data-numfmt-symbol]').value = state.symbol
    $<HTMLInputElement>('[data-numfmt-thousands]').checked = state.thousands
    $<HTMLSelectElement>('[data-numfmt-negative]').value = state.negative
    $<HTMLSelectElement>('[data-numfmt-date]').value = state.datePattern
    $<HTMLSelectElement>('[data-numfmt-time]').value = state.timePattern
    $<HTMLSelectElement>('[data-numfmt-fraction]').value = state.fractionPattern
    const custom = $<HTMLInputElement>('[data-numfmt-custom]')
    if (document.activeElement !== custom) custom.value = state.category === 'custom' ? state.custom : numfmtPattern(state)
    const pattern = numfmtPattern(state)
    $<HTMLOutputElement>('[data-numfmt-preview]').textContent = numfmtPreview(pattern, sampleValue(state.category, anchor, todaySerial()))
    $<HTMLElement>('[data-numfmt-note]').textContent = state.category === 'general' ? '常规单元格格式不包含任何特定的数字格式。'
      : state.category === 'text' ? '文本格式中，数字作为文本处理，显示内容与输入内容一致。' : `格式代码：${pattern}`
  }
  card.querySelector('.workbook-ribbon-numfmt-cats')!.addEventListener('click', event => {
    const category = (event.target as HTMLElement).closest<HTMLButtonElement>('[data-numfmt-category]')?.dataset.numfmtCategory as NumfmtCategory | undefined
    if (!category) return
    state = { ...state, category, ...(category === 'custom' ? { custom: numfmtPattern(state) } : {}) }
    error.textContent = ''; render()
  })
  card.addEventListener('input', event => {
    const target = event.target as HTMLElement
    if (target.matches('[data-numfmt-decimals]')) state = { ...state, decimals: clampDecimals(Number((target as HTMLInputElement).value)) }
    else if (target.matches('[data-numfmt-custom]')) state = { ...state, custom: (target as HTMLInputElement).value }
    else return
    render()
  })
  card.addEventListener('change', event => {
    const target = event.target as HTMLInputElement
    if (target.matches('[data-numfmt-symbol]')) state = { ...state, symbol: target.value }
    else if (target.matches('[data-numfmt-thousands]')) state = { ...state, thousands: target.checked }
    else if (target.matches('[data-numfmt-negative]')) state = { ...state, negative: target.value as NegativeStyle }
    else if (target.matches('[data-numfmt-date]')) state = { ...state, datePattern: target.value }
    else if (target.matches('[data-numfmt-time]')) state = { ...state, timePattern: target.value }
    else if (target.matches('[data-numfmt-fraction]')) state = { ...state, fractionPattern: target.value }
    else return
    render()
  })
  $<HTMLButtonElement>('.workbook-ribbon-format-cancel').addEventListener('click', modal.close)
  card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    try { options.apply(numfmtPattern(state)); modal.close() } catch (cause) { error.textContent = (cause as Error).message }
  })
  return {
    open() {
      const current = options.current()
      anchor = current.anchor
      state = current.pattern === undefined ? DEFAULT_NUMFMT_OPTIONS : numfmtOptionsOf(current.pattern)
      $<HTMLSelectElement>('[data-numfmt-date]').replaceChildren(...datePatterns().map(pattern => { const option = document.createElement('option'); option.value = pattern; option.textContent = pattern; return option }))
      error.textContent = ''; render()
      modal.open(card.querySelector<HTMLButtonElement>(`[data-numfmt-category="${state.category}"]`)!)
    },
    dispose: modal.remove,
  }
}
