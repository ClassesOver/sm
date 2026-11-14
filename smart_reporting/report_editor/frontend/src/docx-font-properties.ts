import { Extension } from '@tiptap/core'
import { charScaleEm, wordKerns } from './vendor/genoffice-docs/apps/docs/src/renderer/line-metrics'
import { DOCX_FONT_PROPERTIES, docxFontProperties } from '../../../reporting/doc_engine/bridge/docx-font-properties'

export const NativeDocxFontDialog = Extension.create({ name: 'nativeDocxFontDialog', addGlobalAttributes: () => [{ types: ['docTextStyle'], attributes: { nativeFontDialog: { default: null, rendered: false } } }] })
/** 草稿恢复与对话框使用相同作者属性，派生显示值从实际文字及字号计算。 */
export function fontDialogMarkAttrs(prior: Record<string, unknown>, spec: Record<string, unknown>, text: string): Record<string, unknown> {
  const attrs = { ...prior, ...docxFontProperties(spec), nativeFontDialog: true } as Record<string, unknown>
  if ('fontAscii' in spec) attrs.fontAscii = spec.fontAscii
  if ('eastAsiaFont' in spec) { attrs.font = spec.eastAsiaFont; attrs.eastAsiaFont = spec.eastAsiaFont; attrs.eaSlotEmpty = spec.eastAsiaFont ? false : null }
  if ('charScalePct' in spec) { attrs.charScaleX = null; attrs.charScaleEm = attrs.charScalePct && attrs.charScalePct !== 100 ? charScaleEm(text, Number(attrs.charScalePct)) : null }
  if ('kernHalfPoints' in spec) attrs.kern = wordKerns(attrs.kernHalfPoints as number | undefined, Number(attrs.sizeHalfPoints) || 22) ?? null
  if ('vanishOwn' in spec) attrs.vanish = spec.vanishOwn
  return attrs
}
export { DOCX_FONT_PROPERTIES }
