import type { SheetPrintHeaderFooter } from './workbook-print'
import { createModal } from './modal'

// Fixed GenOffice f8c17004 HeaderFooterDialog.tsx / edit-journal.ts:
// six default-page sections; empty halves clear, first/even stay untouched.
interface HeaderFooterParts { readonly left?: string | undefined; readonly center?: string | undefined; readonly right?: string | undefined }
type Sections = { left: string; center: string; right: string }
export interface HeaderFooterEditorValues { header: Sections; footer: Sections }
export interface HeaderFooterEditorState { values: HeaderFooterEditorValues; hasFirstPage: boolean; hasEvenPages: boolean }
export interface HeaderFooterEditorPatch { header?: HeaderFooterParts | null; footer?: HeaderFooterParts | null }
export interface HeaderFooterEditorTarget { book: object; sheet: object; sheetId: string }
const keys = ['left', 'center', 'right'] as const
const halves = ['header', 'footer'] as const
const empty = (): Sections => ({ left: '', center: '', right: '' })

// Editing must retain field/format codes; the print decoder intentionally
// strips formatting and therefore cannot initialize an editable draft.
function sections(encoded: string): Sections {
  const result = empty()
  let current: keyof Sections = 'center', index = 0
  while (index < encoded.length) {
    if (encoded[index] !== '&') { result[current] += encoded[index++]; continue }
    const next = encoded[index + 1]
    if (next === '&') { result[current] += '&&'; index += 2; continue }
    if (next === '"') {
      const end = encoded.indexOf('"', index + 2)
      const stop = end < 0 ? encoded.length : end + 1
      result[current] += encoded.slice(index, stop); index = stop; continue
    }
    const marker = next?.toUpperCase()
    if (marker === 'L' || marker === 'C' || marker === 'R') {
      current = marker === 'L' ? 'left' : marker === 'R' ? 'right' : 'center'; index += 2; continue
    }
    result[current] += '&'; index++
  }
  return result
}
const fromParts = (parts: HeaderFooterParts | null): Sections => ({ left: parts?.left ?? '', center: parts?.center ?? '', right: parts?.right ?? '' })
export function headerFooterEditorState(file: SheetPrintHeaderFooter | undefined, patch?: HeaderFooterEditorPatch): HeaderFooterEditorState {
  return { values: {
    header: patch?.header !== undefined ? fromParts(patch.header) : sections(file?.oddHeader ?? ''),
    footer: patch?.footer !== undefined ? fromParts(patch.footer) : sections(file?.oddFooter ?? ''),
  }, hasFirstPage: file?.differentFirst === true, hasEvenPages: file?.differentOddEven === true }
}
export function headerFooterEditorPatch(state: HeaderFooterEditorState, values: HeaderFooterEditorValues): HeaderFooterEditorPatch | undefined {
  const patch: HeaderFooterEditorPatch = {}
  for (const half of halves) {
    if (keys.every(key => state.values[half][key] === values[half][key])) continue
    for (const key of keys) {
      const value = values[half][key], split = sections(value)
      for (let index = 0; index < value.length; index++) {
        if (value[index] !== '&') continue
        const next = value[++index]
        if (next === undefined) throw new Error('字段末尾的 & 必须配对；字面量请使用 &&。')
        if (next === '"') {
          const end = value.indexOf('"', index + 1)
          if (end < 0) throw new Error('字体声明必须使用闭合的双引号。')
          index = end
        }
      }
      // Prefixing a section marker must not move user text to another region.
      if (split.left !== '' || split.right !== '' || split.center !== value)
        throw new Error('区域文字中不能使用 &L、&C、&R；如需字面量请使用 &&L、&&C、&&R。')
    }
    patch[half] = keys.every(key => values[half][key] === '') ? null : { ...values[half] }
  }
  return Object.keys(patch).length ? patch : undefined
}

export function createHeaderFooterDialog(root: HTMLElement, apply: (patch: HeaderFooterEditorPatch, target: HeaderFooterEditorTarget) => void) {
  let state: HeaderFooterEditorState | undefined, target: HeaderFooterEditorTarget | undefined, disposed = false
  const labels = { header: '页眉', footer: '页脚', left: '左侧', center: '中间', right: '右侧' }
  const fields = halves.map(half => `<fieldset style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:12px 0;padding:12px"><legend>${labels[half]}</legend>${keys.map(key => `<label style="display:flex;flex-direction:column;gap:6px;min-width:0">${labels[key]}<textarea style="width:100%;min-width:0;box-sizing:border-box;resize:vertical" rows=3 data-header-footer-field="${half}-${key}" aria-label="${labels[half]}${labels[key]}"></textarea></label>`).join('')}</fieldset>`).join('')
  const modal = createModal({ root, label: '页眉页脚', overlayClass: 'workbook-header-footer-overlay', cardClass: 'workbook-ribbon-format-dialog workbook-header-footer-dialog', content: `<h2>页眉页脚</h2><form novalidate><p>编辑默认/奇数页文本。&P 页码，&N 总页数，&F 文件名，&A 工作表名；&& 表示 &。保留已有字段和格式代码。图片仅保留代码，打印暂不显示。</p><p data-header-footer-variants></p>${fields}<p class=workbook-ribbon-format-error role=alert></p><div class=workbook-ribbon-format-actions><button type=button data-header-footer-cancel>取消</button><button type=submit data-header-footer-apply>确定</button></div></form>` })
  const input = (half: typeof halves[number], key: typeof keys[number]) => modal.card.querySelector<HTMLTextAreaElement>(`[data-header-footer-field="${half}-${key}"]`)!
  const error = modal.card.querySelector<HTMLElement>('[role=alert]')!
  modal.card.querySelector('[data-header-footer-cancel]')!.addEventListener('click', modal.close)
  modal.card.querySelector('form')!.addEventListener('submit', event => {
    event.preventDefault()
    if (disposed || modal.overlay.hidden || !state || !target) return
    const values: HeaderFooterEditorValues = { header: empty(), footer: empty() }
    for (const half of halves) for (const key of keys) values[half][key] = input(half, key).value
    try { const patch = headerFooterEditorPatch(state, values); if (patch) apply(patch, target); modal.close() }
    catch (cause) { error.textContent = (cause as Error).message }
  })
  return {
    open(value: HeaderFooterEditorState, captured: HeaderFooterEditorTarget) {
      if (disposed) return
      state = structuredClone(value); target = captured; error.textContent = ''
      for (const half of halves) for (const key of keys) input(half, key).value = state.values[half][key]
      modal.card.querySelector('[data-header-footer-variants]')!.textContent = [state.hasFirstPage ? '文件已启用不同首页；此处不修改首页。' : '', state.hasEvenPages ? '文件已启用不同偶数页；此处不修改偶数页。' : ''].filter(Boolean).join(' ')
      modal.open(input('header', 'left'))
    },
    dispose() { disposed = true; state = undefined; target = undefined; modal.remove() },
  }
}
