/**
 * Adapted from GenOffice apps/slides/src/renderer/insert-presets.ts (SMARTART_GALLERY) at
 * f8c17004fb730df11f0f743164ffd8b4281bb38c with the Simplified Chinese strings from
 * apps/slides/src/renderer/i18n/ribbon/zh.ts substituted for the i18n keys. Layout order and
 * default node items are unchanged.
 */
export type SmartArtGalleryLayout = 'list' | 'process' | 'cycle' | 'hierarchy' | 'pyramid' | 'matrix' | 'venn'
export const SMARTART_GALLERY: { layout: SmartArtGalleryLayout; label: string; defaultItems: string[] }[] = [
  { layout: 'list', label: '垂直列表', defaultItems: ['第一项', '第二项', '第三项'] },
  { layout: 'process', label: '基本流程', defaultItems: ['计划', '执行', '检查', '改进'] },
  { layout: 'cycle', label: '基本循环', defaultItems: ['分析', '设计', '实施', '评估'] },
  { layout: 'hierarchy', label: '组织结构', defaultItems: ['总经理', '研发', '市场', '运营'] },
  { layout: 'pyramid', label: '基本棱锥图', defaultItems: ['第一项', '第二项', '第三项'] },
  { layout: 'matrix', label: '基本矩阵', defaultItems: ['优势', '劣势', '机会', '威胁'] },
  { layout: 'venn', label: '基本维恩图', defaultItems: ['第一项', '第二项', '第三项'] },
]
/** NewSmartArtOptions.items: node count 1..8 */
export const SMARTART_MAX_ITEMS = 8
