/** Semantic document theme operations. Only fixed upstream presets cross the native boundary. */
import { createHash } from 'node:crypto'
import { readThemeFonts, readThemeColors } from '../packages/docx-engine/src/theme'
import type { ThemeFonts, ThemeColors } from '../packages/docx-engine/src/types'
import { THEME_PRESETS, THEME_FONT_PRESETS, THEME_COLOR_PRESETS } from './docx-theme-presets'
export interface DocxThemeModel { fonts: ThemeFonts | null; colors: ThemeColors | null; editable: boolean; readOnlyReason: string | null; expectedThemeSha256: string }
export interface DocxThemeSaveOptions { themeFonts?: ThemeFonts; themeColors?: ThemeColors }
export function inspectDocxTheme(xml: string | null, protectedSource: boolean): DocxThemeModel {
 const fonts=xml ? readThemeFonts(xml):null, colors=xml ? readThemeColors(xml):null
 const editable=!protectedSource && !!fonts?.major && !!fonts?.minor && !!colors && ['dk2','lt2','accent1','accent2','accent3','accent4','accent5','accent6'].every(k=>!!colors[k as keyof ThemeColors]) && ['majorFont','minorFont'].every(tag=>{const section=xml?.match(new RegExp(`<a:${tag}(?:\\s[^>]*)?>[\\s\\S]*?</a:${tag}>`))?.[0];return !!section && /<a:latin typeface="[^"]*"/.test(section) && /<a:ea typeface="[^"]*"/.test(section)})
 return {fonts,colors,editable,readOnlyReason:editable?null:protectedSource?'文档受保护，主题保持原样':'来源主题缺失或不支持安全修改，保持原样',expectedThemeSha256:createHash('sha256').update(xml??'').digest('hex')}
}
export function validateDocxThemeOperations(operations: Record<string,unknown>[], model: DocxThemeModel): DocxThemeSaveOptions | undefined {
 if(!operations.length)return undefined
 if(operations.length!==1)throw new Error('docx_theme_batch_conflict')
 const op=operations[0]!
 if(op.kind!=='setDocumentTheme'||Object.keys(op).some(k=>!['kind','expectedThemeSha256','themePreset','fontPreset','colorPreset'].includes(k))||!['themePreset','fontPreset','colorPreset'].some(k=>typeof op[k]==='string'))throw new Error('docx_theme_operation_invalid')
 if(!model.editable)throw new Error('docx_theme_source_unsupported')
 if(op.expectedThemeSha256!==model.expectedThemeSha256)throw new Error('docx_theme_anchor_invalid')
 const theme=THEME_PRESETS.find(p=>p.nameKey===op.themePreset), font=THEME_FONT_PRESETS.find(p=>p.nameKey===op.fontPreset),color=THEME_COLOR_PRESETS.find(p=>p.nameKey===op.colorPreset)
 if((op.themePreset!==undefined&&!theme)||(op.fontPreset!==undefined&&!font)||(op.colorPreset!==undefined&&!color))throw new Error('docx_theme_operation_invalid')
 return {...(theme||font?{themeFonts:{...(font?.fonts??theme!.fonts)}}:{}),...(theme||color?{themeColors:{...(color?.colors??theme!.colors)}}:{})}
}
export function assertDocxThemeWritten(xml:string, options:DocxThemeSaveOptions):void {
 const fonts=readThemeFonts(xml), colors=readThemeColors(xml)
 for(const [key,value] of Object.entries(options.themeFonts??{}))if(fonts?.[key as keyof ThemeFonts]!==value)throw new Error('docx_theme_write_not_applied')
 for(const [key,value] of Object.entries(options.themeColors??{}))if(colors?.[key as keyof ThemeColors]!==value)throw new Error('docx_theme_write_not_applied')
}
