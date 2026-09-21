import type { AIFeatureConfig } from '@milkdown/crepe/feature/ai'
import type { BlockEditFeatureConfig } from '@milkdown/crepe/feature/block-edit'
import type { LinkTooltipFeatureConfig } from '@milkdown/crepe/feature/link-tooltip'
import type { ToolbarFeatureConfig } from '@milkdown/crepe/feature/toolbar'

const blockEdit = {
  textGroup: {
    label: '文本',
    text: { label: '正文' },
    h1: { label: '一级标题' },
    h2: { label: '二级标题' },
    h3: { label: '三级标题' },
    h4: { label: '四级标题' },
    h5: { label: '五级标题' },
    h6: { label: '六级标题' },
    quote: { label: '引用' },
    divider: { label: '分隔线' },
  },
  listGroup: {
    label: '列表',
    bulletList: { label: '项目符号列表' },
    orderedList: { label: '编号列表' },
    taskList: { label: '任务列表' },
  },
  advancedGroup: {
    label: '插入',
    image: { label: '图片' },
    codeBlock: { label: '代码块' },
    table: { label: '表格' },
    math: { label: '数学公式' },
  },
} satisfies BlockEditFeatureConfig

const toolbar = {
  boldLabel: '加粗',
  italicLabel: '斜体',
  strikethroughLabel: '删除线',
  codeLabel: '行内代码',
  latexLabel: '行内公式',
  linkLabel: '链接',
  aiLabel: 'AI 改写',
} satisfies ToolbarFeatureConfig

const linkTooltip = {
  inputPlaceholder: '粘贴链接…',
} satisfies LinkTooltipFeatureConfig

const ai = {
  instructionPlaceholder: '请输入对选中内容的修改要求…',
  suggestionsHeaderLabel: '选择改写方式',
  sendAsPromptHeaderLabel: '自定义要求',
  sendAsPromptLabel: '询问 AI：',
  submitButtonLabel: '发送要求',
  listboxLabel: 'AI 改写方式',
  streamingIndicator: {
    fallbackLabel: '正在改写',
    cancelHint: '按 Esc 取消',
  },
  diff: {
    acceptLabel: '接受',
    rejectLabel: '拒绝',
  },
  diffActions: {
    retryLabel: '重试',
    rejectAllLabel: '全部拒绝',
    acceptAllLabel: '全部接受',
  },
} satisfies AIFeatureConfig

export const editorChineseLocale = {
  blockEdit,
  toolbar,
  linkTooltip,
  ai,
}

export function formatRevisionLabel(revision: string | number): string {
  return `版本 ${revision}`
}
