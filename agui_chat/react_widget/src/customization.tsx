import { Check, Copy, Paperclip, RefreshCcw, Send, Square, User } from 'lucide-react'
import type { ChatIcons, ChatLabels } from './types'

export const defaultLabels: ChatLabels = {
  inputPlaceholder: '输入消息，开始提问',
  emptyTitle: '智能助手',
  emptyDescription: '询问当前 Odoo 记录、选中内容或操作。',
  newSession: '新建对话',
  copyResponse: '复制回复',
  copied: '已复制',
  regenerateResponse: '重新生成',
  approve: '批准',
  reject: '拒绝',
  attachments: '附件',
  uploadedAttachments: '已添加 {count} 个附件',
  clearAttachments: '清空',
  addAttachments: '添加附件',
  removeAttachment: '移除',
  sendMessage: '发送消息',
  stopGenerating: '停止生成',
  generatingResponse: '正在生成回复',
  positiveFeedback: '有帮助',
  negativeFeedback: '没有帮助',
  filePreview: '文件预览',
  closeFilePreview: '关闭文件预览',
  openFile: '打开文件',
  previewUnavailable: '此文件类型暂不支持预览。',
  relationCandidates: '请选择关系记录',
  relationNoResults: '没有找到匹配的记录',
  relationSelectionExpired: '当前表单已变化，请重新查询候选记录',
  confirmRelationSelection: '确认选择',
  selectedRelationCount: '已选择 {count} 项'
}

export const defaultIcons: ChatIcons = {
  assistant: <span className="text-[10px] font-semibold leading-none">AI</span>,
  user: <User className="size-4" />,
  send: <Send className="size-4" />,
  stop: <Square className="size-4 fill-current" />,
  upload: <Paperclip className="size-4" />,
  copy: <Copy className="size-3.5" />,
  complete: <Check className="size-3.5" />,
  regenerate: <RefreshCcw className="size-3.5" />,
  activity: <span className="agui-activity-dot" />
}

export function mergeLabels(labels?: Partial<ChatLabels>): ChatLabels {
  return { ...defaultLabels, ...labels }
}

export function mergeIcons(icons?: Partial<ChatIcons>): ChatIcons {
  return { ...defaultIcons, ...icons }
}

export function observeInteraction(callback: (() => void) | undefined): void {
  if (!callback) return
  try {
    callback()
  } catch (error) {
    console.error('AG-UI interaction observer failed', error)
  }
}
