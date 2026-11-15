import { THEME_PRESETS, THEME_FONT_PRESETS, THEME_COLOR_PRESETS } from './docx-theme-presets'
import type { DocxThemeChoice, DocxThemeModel } from './docx-theme'
/** Design tab adapter; the owner commits onChange through native document history. */
export function DocxThemeControls({ model, value, onChange }: { model: DocxThemeModel | null; value?: DocxThemeChoice; onChange: (choice: DocxThemeChoice) => void }) {
 return <>{([
 ['主题', 'themePreset', THEME_PRESETS], ['主题字体', 'fontPreset', THEME_FONT_PRESETS], ['主题颜色', 'colorPreset', THEME_COLOR_PRESETS],
 ] as const).map(([label,key,presets])=><label key={key}>{label}<select aria-label={label} disabled={!model?.editable} title={model?.readOnlyReason??undefined} value={value?.[key]??''} onChange={e=>{if(e.target.value)onChange({[key]:e.target.value})}}><option value="">当前文档{label}</option>{presets.map(p=><option key={p.nameKey} value={p.nameKey}>{labels[p.nameKey]??p.nameKey}</option>)}</select></label>)}</>
}
const labels:Record<string,string>={ribbonThemeOffice:'Office',ribbonThemeFacet:'Facet',ribbonThemeIon:'Ion',ribbonThemeRetrospect:'Retrospect',ribbonThemeFontOffice:'Office',ribbonThemeFontSongti:'黑体 / 宋体',ribbonThemeFontYahei:'微软雅黑',ribbonThemeFontKaiti:'楷体',ribbonThemeFontTimes:'Times New Roman / 宋体',ribbonThemeFontArial:'Arial / 黑体',ribbonPaletteGrayscale:'灰度',ribbonColorBlue:'蓝色',ribbonColorGreen:'绿色',ribbonPaletteRedViolet:'红紫色',ribbonColorOrange:'橙色'}
