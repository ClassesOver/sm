import type { NativeOperation } from './native-draft'
import { THEME_PRESETS, THEME_FONT_PRESETS, THEME_COLOR_PRESETS, type ThemeFonts, type ThemeColors } from './docx-theme-presets'
export interface DocxThemeModel { fonts: ThemeFonts | null; colors: ThemeColors | null; editable: boolean; readOnlyReason: string | null; expectedThemeSha256: string }
export interface DocxThemeChoice { themePreset?: string; fontPreset?: string; colorPreset?: string }
export function docxThemeModel(value:unknown):DocxThemeModel|null {
 if(!value||typeof value!=='object')return null
 const m=value as DocxThemeModel
 if(typeof m.editable!=='boolean'||!/^[a-f0-9]{64}$/.test(m.expectedThemeSha256)||!(m.fonts===null||(typeof m.fonts?.major==='string'&&typeof m.fonts?.minor==='string'))||!(m.colors===null||typeof m.colors==='object'))return null
 return {...m,readOnlyReason:typeof m.readOnlyReason==='string'?m.readOnlyReason:null}
}
function validate(op:NativeOperation,model:DocxThemeModel|null):void {
 if(!model?.editable)throw new Error(model?.readOnlyReason??'当前文档主题不可修改')
 if(op.expectedThemeSha256!==model.expectedThemeSha256||Object.keys(op).some(k=>!['kind','expectedThemeSha256','themePreset','fontPreset','colorPreset'].includes(k))||!['themePreset','fontPreset','colorPreset'].some(k=>typeof op[k]==='string'))throw new Error('主题草稿与来源不一致；原草稿已保留')
 for(const [key,presets] of [['themePreset',THEME_PRESETS],['fontPreset',THEME_FONT_PRESETS],['colorPreset',THEME_COLOR_PRESETS]] as const)if(op[key]!==undefined&&!presets.some(p=>p.nameKey===op[key]))throw new Error('主题预设无效；原草稿已保留')
}
export function docxThemeOperations(operations:NativeOperation[], model:DocxThemeModel|null):NativeOperation[] {
 const found=operations.filter(op=>op.kind==='setDocumentTheme')
 if(found.length>1)throw new Error('主题草稿重复；原草稿已保留')
 found.forEach(op=>validate(op,model));return found.map(op=>({...op}))
}
/** Store this entire result through the existing native draft/history transaction; never mutate body marks. */
export function withDocxTheme(operations:NativeOperation[],model:DocxThemeModel|null,choice:DocxThemeChoice):NativeOperation[] {
 const previous=docxThemeOperations(operations,model)[0]
 const merged:DocxThemeChoice=choice.themePreset ? {...choice} : {...(previous?.themePreset?{themePreset:String(previous.themePreset)}:{}),...(previous?.fontPreset?{fontPreset:String(previous.fontPreset)}:{}),...(previous?.colorPreset?{colorPreset:String(previous.colorPreset)}:{}),...choice}
 const op:NativeOperation={kind:'setDocumentTheme',expectedThemeSha256:model?.expectedThemeSha256,...merged}
 validate(op,model)
 return [...operations.filter(op=>op.kind!=='setDocumentTheme'),op]
}
/** Live preset projection for docThemeCss; explicit formatting stays owned by parsed styles. */
export function effectiveDocxTheme(operations:NativeOperation[],model:DocxThemeModel|null):{fonts:ThemeFonts|null;colors:ThemeColors|null} {
 const op=docxThemeOperations(operations,model)[0]
 const theme=THEME_PRESETS.find(p=>p.nameKey===op?.themePreset)
 const font=THEME_FONT_PRESETS.find(p=>p.nameKey===op?.fontPreset)
 const color=THEME_COLOR_PRESETS.find(p=>p.nameKey===op?.colorPreset)
 return {fonts:font?.fonts??theme?.fonts??model?.fonts??null,colors:color?.colors??theme?.colors??model?.colors??null}
}
