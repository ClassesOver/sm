import type { ToolCall } from '../types'
import { toolArgs, toolCallId, toolName } from '../runtime/utils'

export const TOOL_DISPLAY_NAMES: Record<string, string> = {
  'odoo.navigate_menu': '导航菜单',
  'odoo.apply_filter': '筛选当前视图',
  'odoo.apply_group': '设置当前视图分组',
  'odoo.open_record': '打开记录',
  'odoo.open_create': '新建记录',
  'odoo.switch_view': '切换视图',
  'odoo.enter_edit_mode': '进入编辑模式',
  'odoo.activate_view_control': '激活页面控件',
  'odoo.search_relation': '查询关系记录',
  'odoo.stage_current_form': '暂存当前表单',
  'odoo.patch_current_form': '修改当前表单',
  'odoo.validate_current_form': '校验当前表单',
  'odoo.save_current_form': '保存当前表单',
  'odoo.open_x2many_record': '打开明细表单',
  'odoo.open_x2many_create': '新建明细表单',
  'odoo.prepare_x2many_import': '准备明细导入',
  'odoo.get_x2many_import_status': '查询导入状态',
  'odoo.reload_current_form': '重新载入表单',
  'odoo.discard_current_form': '放弃表单更改'
}

export function getToolCallPresentation(tool: ToolCall) {
  const name = toolName(tool)
  const result = tool.result && typeof tool.result === 'object'
    ? tool.result as Record<string, unknown>
    : {}
  const receipt = result.receipt && typeof result.receipt === 'object'
    ? result.receipt as Record<string, unknown>
    : {}
  const undo = receipt.undo && typeof receipt.undo === 'object'
    ? receipt.undo as Record<string, unknown>
    : {}
  const status = tool.status || 'pending'

  return {
    displayName: TOOL_DISPLAY_NAMES[name] || name,
    result,
    applied: Array.isArray(result.applied) ? result.applied.length : 0,
    rejected: Array.isArray(result.rejected) ? result.rejected.length : 0,
    status,
    error: tool.error || result.error,
    needsConfirmation: status === 'needs_confirmation' || !!tool.needs_confirmation,
    undo,
    call: { id: toolCallId(tool), args: toolArgs(tool) }
  }
}
