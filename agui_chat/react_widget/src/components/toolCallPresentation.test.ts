import { describe, expect, it } from 'vitest'
import { getToolCallPresentation } from './toolCallPresentation'

describe('工具调用展示模型', () => {
  it('归一化已知工具名称、参数和默认状态', () => {
    const presentation = getToolCallPresentation({
      id: 'call-1',
      name: 'odoo.navigate_menu',
      args: { menuId: 42 }
    })

    expect(presentation.displayName).toBe('导航菜单')
    expect(presentation.status).toBe('pending')
    expect(presentation.call).toEqual({ id: 'call-1', args: { menuId: 42 } })
    expect(presentation.result).toEqual({})
  })

  it('未知工具名称保持原名称', () => {
    expect(getToolCallPresentation({ tool_name: 'custom.audit' }).displayName).toBe('custom.audit')
  })

  it('展示原生视图分组工具名称', () => {
    expect(getToolCallPresentation({ name: 'odoo.apply_group' }).displayName)
      .toBe('设置当前视图分组')
  })

  it('展示原生视图切换工具名称', () => {
    expect(getToolCallPresentation({ name: 'odoo.switch_view' }).displayName)
      .toBe('切换视图')
  })

  it('统计处理结果并提取撤销状态', () => {
    const presentation = getToolCallPresentation({
      name: 'odoo.patch_current_form',
      result: {
        applied: ['name', 'phone'],
        rejected: ['email'],
        receipt: { undo: { available: true, status: 'available' } }
      }
    })

    expect(presentation.applied).toBe(2)
    expect(presentation.rejected).toBe(1)
    expect(presentation.undo).toEqual({ available: true, status: 'available' })
  })

  it('优先展示工具错误并归一化确认状态', () => {
    const presentation = getToolCallPresentation({
      name: 'odoo.save_current_form',
      status: 'needs_confirmation',
      error: '调用失败',
      result: { error: '结果失败', receipt: { undo: 'invalid' } }
    })

    expect(presentation.error).toBe('调用失败')
    expect(presentation.needsConfirmation).toBe(true)
    expect(presentation.undo).toEqual({})
  })

  it('兼容工具标记的确认状态和非对象结果', () => {
    const presentation = getToolCallPresentation({
      name: 'odoo.open_record',
      needs_confirmation: true,
      result: '完成'
    })

    expect(presentation.needsConfirmation).toBe(true)
    expect(presentation.result).toEqual({})
  })
})
