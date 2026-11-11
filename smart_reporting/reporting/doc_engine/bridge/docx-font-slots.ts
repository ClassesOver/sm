// 固定 GenOffice 字体槽语义，加上本地 OFL 中文字体名称；保持无依赖。
const EAST_ASIAN_FONT_RE =
  /[\u2E80-\u9FFF\uF900-\uFAFF\u3040-\u30FF\u31F0-\u31FF\uAC00-\uD7AF]|sim(sun|hei)|nsimsun|kaiti|fangsong|dengxian|yahei|songti|heiti|xingkai|lisu|youyuan|st(zhongsong|song|kai|fangsong|xihei|hupo|liti|caiyun)|pingfang|hiragino|meiryo|osaka|kozuka|yu (gothic|mincho)|yugoth|ms (ui )?p?(gothic|mincho)|biz ud|malgun|batang|gulim|dotum|gungsuh|m(ye|yu)ngjo|nanum|apple (sd )?gothic|applemyungjo|jhenghei|p?mingliu|biaukai|dfkai|kaiu|source han|noto (sans|serif)( mono)? (cjk|sc|tc|hk|jp|kr)|wenquanyi|^misans(?: (?:thin|extralight|light|normal|regular|medium|demibold|semibold|bold|heavy|black))?$|^ma shan zheng$|^zcool xiaowei$|^lxgw wenkai(?: |$)|^ar pl u(?:kai|ming)(?: |$)|^droid sans fallback(?: |$)/i

/**
 * Which rFonts slot a font-box pick should target: East Asian names go to
 * w:eastAsia, everything else to w:ascii/w:hAnsi — mirroring Word, where
 * picking a Latin font never clobbers the Chinese font and vice versa.
 */
export function isEastAsianFontName(name: string): boolean {
  return EAST_ASIAN_FONT_RE.test(name.normalize('NFKC'))
}

export function docxFontPickAttrs(font: string | null): Record<string, unknown> {
  if (font === null) return { font: null, fontAscii: null, eastAsiaFont: null, fontCs: null, csFont: null, themeRFonts: null }
  return isEastAsianFontName(font) ? { font, eastAsiaFont: font } : { fontAscii: font }
}
