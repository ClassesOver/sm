/**
 * 固定源 WatermarkDialog（插入水印）的文字页：无水印 / 文字（文字、字体、字号、粗体、斜体、透明度、字体颜色、版式）。
 * 取值与固定源一致：默认文字取第一个预设、Calibri、自动字号、50% 透明、银色 C0C0C0、斜式；
 * 指定字号时按固定源 inkBoxPt 在浏览器测量墨迹框。图片页本轮不接入。
 */
import { DOCX_WATERMARK_DEFAULT_COLOR, DOCX_WATERMARK_DEFAULT_FONT, DOCX_WATERMARK_FONTS, DOCX_WATERMARK_PRESETS, DOCX_WATERMARK_SIZES, docxWatermarkInkBoxPt, validDocxWatermarkSpec, type DocxWatermarkSpec } from './docx-watermark'

export function openDocxWatermarkDialog(host: HTMLElement, current: DocxWatermarkSpec | null, onApply: (spec: DocxWatermarkSpec | null) => void): HTMLDialogElement {
  const dialog = document.createElement('dialog')
  dialog.className = 'docx-watermark-dialog'; dialog.setAttribute('aria-label', '插入水印')
  const fonts = current?.fontFamily && !DOCX_WATERMARK_FONTS.includes(current.fontFamily) ? [current.fontFamily, ...DOCX_WATERMARK_FONTS] : DOCX_WATERMARK_FONTS
  dialog.innerHTML = '<h2>插入水印</h2>'
    + '<label class="docx-watermark-mode"><input type="radio" name="mode" value="none"> 无水印</label>'
    + '<label class="docx-watermark-mode"><input type="radio" name="mode" value="text"> 文字</label>'
    + '<fieldset class="docx-watermark-text"><legend class="sr-only">文字水印</legend>'
    + `<label>文字 <input name="text" list="docx-watermark-presets" maxlength="255" aria-label="水印文字"></label><datalist id="docx-watermark-presets">${DOCX_WATERMARK_PRESETS.map(text => `<option value="${text}"></option>`).join('')}</datalist>`
    + `<label>字体: <select name="font" aria-label="水印字体">${fonts.map(font => `<option value="${font}">${font}</option>`).join('')}</select></label>`
    + `<label>字号: <select name="size" aria-label="水印字号"><option value="auto">自动</option>${DOCX_WATERMARK_SIZES.map(size => `<option value="${size}">${size}</option>`).join('')}</select></label>`
    + '<label class="docx-watermark-check"><input type="checkbox" name="bold"> 粗体</label><label class="docx-watermark-check"><input type="checkbox" name="italic"> 斜体</label>'
    + '<label>透明度: <input name="transparency" type="number" min="0" max="100" step="1" aria-label="水印透明度"> %</label>'
    + '<label>字体颜色: <input name="color" type="color" aria-label="水印字体颜色"></label>'
    + '<span class="docx-watermark-layout">版式: <label><input type="radio" name="layout" value="diagonal"> 斜式</label><label><input type="radio" name="layout" value="horizontal"> 水平</label></span>'
    + '</fieldset><p role="alert"></p><div class="docx-watermark-actions"><button type="button" value="cancel">取消</button><button type="button" value="ok">确定</button></div>'
  const field = <T extends HTMLElement>(selector: string) => dialog.querySelector<T>(selector)!
  const radio = (name: string, value: string) => field<HTMLInputElement>(`input[name=${name}][value=${value}]`)
  radio('mode', current ? 'text' : 'none').checked = true
  field<HTMLInputElement>('input[name=text]').value = current?.text ?? DOCX_WATERMARK_PRESETS[0]!
  field<HTMLSelectElement>('select[name=font]').value = current?.fontFamily ?? DOCX_WATERMARK_DEFAULT_FONT
  field<HTMLSelectElement>('select[name=size]').value = current?.sizePt ? String(current.sizePt) : 'auto'
  field<HTMLInputElement>('input[name=bold]').checked = !!current?.bold
  field<HTMLInputElement>('input[name=italic]').checked = !!current?.italic
  field<HTMLInputElement>('input[name=transparency]').value = String(Math.round((1 - (current?.opacity ?? 0.5)) * 100))
  field<HTMLInputElement>('input[name=color]').value = `#${(current?.colorHex ?? DOCX_WATERMARK_DEFAULT_COLOR).toLowerCase()}`
  radio('layout', current?.diagonal === false ? 'horizontal' : 'diagonal').checked = true
  const sync = () => { field<HTMLFieldSetElement>('fieldset').disabled = !radio('mode', 'text').checked }
  for (const input of dialog.querySelectorAll<HTMLInputElement>('input[name=mode]')) input.addEventListener('change', sync)
  sync()
  const resolved = (): DocxWatermarkSpec | null => {
    if (radio('mode', 'none').checked) return null
    const text = field<HTMLInputElement>('input[name=text]').value.trim()
    const transparency = Number(field<HTMLInputElement>('input[name=transparency]').value)
    if (!text) throw new Error('请输入水印文字')
    if (!Number.isInteger(transparency) || transparency < 0 || transparency > 100) throw new Error('透明度须为 0–100 的整数')
    const spec: DocxWatermarkSpec = {
      text, fontFamily: field<HTMLSelectElement>('select[name=font]').value, colorHex: field<HTMLInputElement>('input[name=color]').value.replace(/^#/, '').toUpperCase(),
      opacity: Math.round((1 - transparency / 100) * 100) / 100, diagonal: radio('layout', 'diagonal').checked,
      ...(field<HTMLInputElement>('input[name=bold]').checked ? { bold: true } : {}), ...(field<HTMLInputElement>('input[name=italic]').checked ? { italic: true } : {}),
    }
    const size = field<HTMLSelectElement>('select[name=size]').value
    if (size !== 'auto') { spec.sizePt = Number(size); spec.boxPt = docxWatermarkInkBoxPt(spec, spec.sizePt) }
    if (!validDocxWatermarkSpec(spec)) throw new Error('水印文字须为 1–255 个字符，且不能包含换行或控制字符')
    return spec
  }
  host.append(dialog)
  dialog.addEventListener('close', () => dialog.remove())
  field<HTMLButtonElement>('button[value=cancel]').addEventListener('click', () => dialog.close())
  field<HTMLButtonElement>('button[value=ok]').addEventListener('click', () => {
    try { const spec = resolved(); dialog.close(); onApply(spec) } catch (error) { field('[role=alert]').textContent = error instanceof Error ? error.message : String(error) }
  })
  dialog.showModal()
  return dialog
}
