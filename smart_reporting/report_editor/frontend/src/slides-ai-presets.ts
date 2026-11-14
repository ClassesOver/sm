/** 固定源 Slides Ribbon TRANSLATE_TARGETS 顺序及 ribbon/zh.ts 名称；不新增API。 */
export const SLIDES_AI_TRANSLATE_TARGETS = [
  { id: 'en', label: 'English', name: '英语' }, { id: 'zh-CN', label: 'Simplified Chinese', name: '简体中文' },
  { id: 'ja', label: 'Japanese', name: '日语' }, { id: 'ko', label: 'Korean', name: '韩语' },
  { id: 'fr', label: 'French', name: '法语' }, { id: 'de', label: 'German', name: '德语' },
  { id: 'es', label: 'Spanish', name: '西班牙语' }, { id: 'th', label: 'Thai', name: '泰文' },
  { id: 'id', label: 'Indonesian', name: '印尼文' }, { id: 'ru', label: 'Russian', name: '俄文' },
  { id: 'ar', label: 'Arabic', name: '阿拉伯文' }, { id: 'pt', label: 'Portuguese', name: '葡萄牙文' },
  { id: 'it', label: 'Italian', name: '意大利文' }, { id: 'pl', label: 'Polish', name: '波兰文' },
  { id: 'cs', label: 'Czech', name: '捷克文' }, { id: 'nl', label: 'Dutch', name: '荷兰文' },
  { id: 'ms', label: 'Malay', name: '马来文' }, { id: 'he', label: 'Hebrew', name: '希伯来文' },
  { id: 'hi', label: 'Hindi', name: '印地文' }, { id: 'zh-TW', label: 'Traditional Chinese', name: '繁体中文' },
  { id: 'vi', label: 'Vietnamese', name: '越南文' },
] as const
export type SlidesAIPreset = { kind: 'spelling' } | { kind: 'translate'; language: string }

/** 保留源任务范围：拼写逐页整稿、翻译当前页；通过既有候选而非直接写入。 */
export function slidesAIPreset(preset: SlidesAIPreset) {
  if (preset.kind === 'spelling') return { scope: 'deck' as const, title: '拼写检查', instruction: '逐页检查这份演示文稿已授权可编辑对象的错别字、语法和标点：提出修正候选，保持版式、原意、数字、字号和配色不变，不改页序、主题或备注；最后按页简要汇报修改点，没有问题的页跳过。等待用户明确采纳。' }
  const language = SLIDES_AI_TRANSLATE_TARGETS.find(item => item.id === preset.language)
  if (!language) throw new Error('请选择受支持的翻译语言')
  return { scope: 'slide' as const, title: '翻译 · ' + language.name, instruction: '把当前页已授权可编辑对象的所有文本翻译成' + language.name + '：提出替换候选，保持版式、数字、字号和配色不变，不改其它页面、页序、主题或备注。等待用户明确采纳。' }
}
