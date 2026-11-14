import { showSlidesSettingsDialog } from './slides-settings-dialog'
import './slides-equation.css'

/** 固定源 insert-presets.ts 的 Unicode 模板；源功能也是数学字体文本框，不是 OMML。 */
const templates = [
  ['二次求根公式', 'x = (−b ± √(b² − 4ac)) / 2a'], ['勾股定理', 'a² + b² = c²'],
  ['欧拉恒等式', 'e^(iπ) + 1 = 0'], ['质能方程', 'E = mc²'], ['圆面积', 'A = πr²'],
  ['等差求和', '∑ₖ₌₁ⁿ k = n(n+1)/2'], ['高斯积分', '∫₋∞^∞ e^(−x²) dx = √π'],
  ['自然对数极限', 'lim(x→∞) (1 + 1/x)ˣ = e'], ['均值', 'x̄ = (1/n) ∑ᵢ xᵢ'],
  ['标准差', 'σ = √( ∑(xᵢ − μ)² / n )'], ['傅里叶变换', 'F(ω) = ∫₋∞^∞ f(t) e^(−iωt) dt'],
  ['正态分布', 'f(x) = (1/(σ√(2π))) e^(−(x−μ)²/2σ²)'],
] as const

/** 固定源 insert-defaults.ts：1 英寸方框居中，18pt Cambria Math 斜体。坐标使用现有96dpi桥协议。 */
export function equationTextBox(slideIndex: number, size: { cx: number; cy: number }, text: string) {
  return { slideIndex, text: text.trim(), fontSize: 18, fontFamily: 'Cambria Math', color: '#000000', italic: true, equation: true,
    geometry: { x: Math.round((size.cx / 9525 - 96) / 2), y: Math.round((size.cy / 9525 - 96) / 2), width: 96, height: 96 } }
}

export function openSlidesEquationDialog(host: HTMLElement, insert: (text: string) => void) {
  const dialog = document.createElement('dialog')
  dialog.className = 'slides-table-dialog slides-equation-dialog'
  dialog.setAttribute('aria-label', '插入公式')
  const heading = document.createElement('h2'); heading.textContent = '插入公式'
  const gallery = document.createElement('div'); gallery.className = 'slides-equation-gallery'
  const label = document.createElement('label'); label.textContent = '公式文本（Unicode 数学符号，插入为数学字体文本框）'
  const input = document.createElement('input'); input.type = 'text'; input.maxLength = 20000
  input.placeholder = '选择上方模板或直接输入，如 E = mc²'; input.setAttribute('aria-label', '公式文本')
  const confirm = document.createElement('button'); confirm.type = 'button'; confirm.textContent = '插入'; confirm.dataset.equationInsert = ''; confirm.disabled = true
  const update = () => { confirm.disabled = !input.value.trim() }
  for (const [name, text] of templates) {
    const button = document.createElement('button'); button.type = 'button'; button.dataset.equationTemplate = ''; button.title = name
    const preview = document.createElement('span'); preview.className = 'slides-equation-preview'; preview.textContent = text
    const caption = document.createElement('span'); caption.textContent = name
    button.append(preview, caption); button.addEventListener('click', () => { input.value = text; update(); input.focus() })
    gallery.append(button)
  }
  let submitted = false
  const apply = () => {
    const text = input.value.trim()
    if (submitted || !text || text.length > 20000 || !dialog.isConnected) return
    submitted = true; insert(text); dialog.close()
  }
  input.addEventListener('input', update)
  input.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.isComposing && event.keyCode !== 229) { event.preventDefault(); apply() } })
  confirm.addEventListener('click', apply)
  const cancel = document.createElement('button'); cancel.type = 'button'; cancel.textContent = '取消'; cancel.dataset.equationCancel = ''; cancel.addEventListener('click', () => dialog.close())
  const actions = document.createElement('div'); actions.className = 'dialog-actions'; actions.append(cancel, confirm)
  label.append(input); dialog.append(heading, gallery, label, actions); host.append(dialog); showSlidesSettingsDialog(dialog)
  return { dispose() { if (dialog.isConnected) dialog.close() } }
}
