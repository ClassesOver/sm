import {
  defaultAIIcon,
  type AIProvider,
  type AISuggestionsBuilder,
} from '@milkdown/crepe/feature/ai'

import type { ReportEditorClient } from './api'
import { findProtocolMarkers, restoreProtocolMarkers } from './protocol'

export const selectionAIActions = ['polish', 'shorten', 'expand', 'professional'] as const
export type SelectionAIAction = (typeof selectionAIActions)[number]

const selectionAILabels: Record<SelectionAIAction, { label: string; streamingLabel: string }> = {
  polish: { label: '润色表达', streamingLabel: '正在润色' },
  shorten: { label: '精简内容', streamingLabel: '正在精简' },
  expand: { label: '扩写说明', streamingLabel: '正在扩写' },
  professional: { label: '专业报告语气', streamingLabel: '正在调整语气' },
}

export function configureSelectionAISuggestions(builder: AISuggestionsBuilder): void {
  builder.clear()
  for (const action of selectionAIActions) {
    builder.addItem(action, { icon: defaultAIIcon, ...selectionAILabels[action], prompt: action })
  }
}

/**
 * 指令框只要有输入就默认选中“自定义要求”一行：用户输入“润色”筛选后直接回车，提交的是原文而非预设动作。
 * 服务端只接受预设改写动作，因此把输入唯一对应到某个预设（名称包含输入，或输入包含名称）时按该预设执行；
 * 无法唯一对应时返回 null，由调用方拒绝，不把任意文本当作指令发送。
 */
export function resolveSelectionAIAction(instruction: string): SelectionAIAction | null {
  const text = instruction.trim()
  if (isSelectionAIAction(text)) return text
  if (!text) return null
  const matches = selectionAIActions.filter((action) => {
    const label = selectionAILabels[action].label
    return label.includes(text) || text.includes(label)
  })
  return matches.length === 1 ? matches[0] : null
}

interface SelectionAIClient {
  streamRewrite: ReportEditorClient['streamRewrite']
}

function isSelectionAIAction(value: string): value is SelectionAIAction {
  return selectionAIActions.includes(value as SelectionAIAction)
}

export function selectionAIProvider(client: SelectionAIClient): AIProvider {
  return async function* (context, signal) {
    const selection = context.selection.trim()
    if (!selection) throw new Error('report_editor_ai_selection_required')
    const action = resolveSelectionAIAction(context.instruction)
    if (!action) throw new Error('report_editor_ai_action_invalid')
    // Crepe 以 Markdown 序列化选区，协议标记会被转义为 \[\[...]]，需还原后再识别。
    const original = restoreProtocolMarkers(selection)
    const markers = findProtocolMarkers(original)
    if (markers.some(marker => ['section', 'table', 'table-close'].includes(marker.kind))) {
      throw new Error('请缩小选区，选择同一段正文；章节边界和整张表格暂不支持 AI 改写。')
    }
    // 完整接收后再提交给原生差异审阅。引用由编辑器拼回，既不传给模型，也不让
    // 流式片段暂时删掉引用；失败或取消时由原生 streaming 恢复原文。
    let cursor = 0
    let rewritten = ''
    for (const marker of [...markers, { start: original.length, end: original.length, raw: '' }]) {
      const text = original.slice(cursor, marker.start)
      if (text.trim()) {
        let output = ''
        for await (const chunk of client.streamRewrite(text, action, signal)) {
          if (signal.aborted) throw new DOMException('已取消', 'AbortError')
          output += chunk
        }
        if (!output.trim()) throw new Error('AI 未返回改写内容，已保留原文。')
        if (findProtocolMarkers(restoreProtocolMarkers(output)).length) throw new Error('AI 返回了无效引用，已保留原文。')
        rewritten += output
      } else rewritten += text
      rewritten += marker.raw
      cursor = marker.end
    }
    if (signal.aborted) throw new DOMException('已取消', 'AbortError')
    yield rewritten
  }
}
