import {
  defaultAIIcon,
  type AIProvider,
  type AISuggestionsBuilder,
} from '@milkdown/crepe/feature/ai'

import type { ReportEditorClient } from './api'
import { findProtocolMarkers } from './protocol'

export const selectionAIActions = ['polish', 'shorten', 'expand', 'professional'] as const
export type SelectionAIAction = (typeof selectionAIActions)[number]

export function configureSelectionAISuggestions(builder: AISuggestionsBuilder): void {
  builder
    .clear()
    .addItem('polish', {
      icon: defaultAIIcon,
      label: '润色表达',
      streamingLabel: '正在润色',
      prompt: 'polish',
    })
    .addItem('shorten', {
      icon: defaultAIIcon,
      label: '精简内容',
      streamingLabel: '正在精简',
      prompt: 'shorten',
    })
    .addItem('expand', {
      icon: defaultAIIcon,
      label: '扩写说明',
      streamingLabel: '正在扩写',
      prompt: 'expand',
    })
    .addItem('professional', {
      icon: defaultAIIcon,
      label: '专业报告语气',
      streamingLabel: '正在调整语气',
      prompt: 'professional',
    })
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
    if (!isSelectionAIAction(context.instruction)) {
      throw new Error('report_editor_ai_action_invalid')
    }
    if (findProtocolMarkers(selection).length > 0) {
      throw new Error('report_editor_ai_protocol_marker')
    }
    yield* client.streamRewrite(selection, context.instruction, signal)
  }
}
