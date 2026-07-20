import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { AgentSkillOption, MenuMentionOption } from '../types'
import { useComposerSelectionState } from './useComposerSelectionState'

afterEach(cleanup)

const auditSkill: AgentSkillOption = {
  id: 'audit',
  name: '合同审计',
  description: '核对合同字段'
}

describe('消息输入选择状态', () => {
  it('选择菜单时克隆路径并标记有效', () => {
    const { result } = renderHook(() => useComposerSelectionState({ agentSkills: [] }))
    const option: MenuMentionOption = {
      menuId: 1,
      actionId: 2,
      name: '客户',
      path: ['销售', '客户'],
      fullPath: '销售 / 客户'
    }

    act(() => result.current.selectMenu(option))

    expect(result.current.menuMention).toEqual({ ...option, path: ['销售', '客户'], valid: true })
    expect(result.current.menuMention?.path).not.toBe(option.path)
  })

  it('切换技能时移除已选项或用新技能替换', () => {
    const reportSkill: AgentSkillOption = {
      id: 'report',
      name: '生成报告',
      description: '整理审计结果'
    }
    const { result } = renderHook(() => useComposerSelectionState({ agentSkills: [auditSkill, reportSkill] }))

    act(() => result.current.toggleSkill(auditSkill))
    expect(result.current.selectedSkills).toEqual([{ ...auditSkill, valid: true }])
    act(() => result.current.toggleSkill(auditSkill))
    expect(result.current.selectedSkills).toEqual([])
    act(() => result.current.toggleSkill(auditSkill))
    act(() => result.current.toggleSkill(reportSkill))
    expect(result.current.selectedSkills).toEqual([{ ...reportSkill, valid: true }])
  })

  it('技能列表变化时按 id 和名称同步有效性', () => {
    const { result, rerender } = renderHook(
      ({ skills }) => useComposerSelectionState({ agentSkills: skills }),
      { initialProps: { skills: [auditSkill] } }
    )

    act(() => result.current.toggleSkill(auditSkill))
    rerender({ skills: [{ ...auditSkill, name: '合同复核' }] })
    expect(result.current.selectedSkills[0].valid).toBe(false)
    rerender({ skills: [auditSkill] })
    expect(result.current.selectedSkills[0].valid).toBe(true)
  })

  it('支持独立移除和发送后的统一重置', () => {
    const { result } = renderHook(() => useComposerSelectionState({ agentSkills: [auditSkill] }))
    const option: MenuMentionOption = {
      menuId: 1,
      actionId: 2,
      name: '客户',
      path: ['销售', '客户'],
      fullPath: '销售 / 客户'
    }

    act(() => {
      result.current.selectMenu(option)
      result.current.toggleSkill(auditSkill)
    })
    act(() => result.current.removeSkill(auditSkill.id))
    expect(result.current.selectedSkills).toEqual([])
    act(() => result.current.toggleSkill(auditSkill))
    act(() => result.current.removeMenuMention())
    expect(result.current.menuMention).toBeUndefined()
    act(() => result.current.selectMenu(option))
    act(() => result.current.resetSelections())
    expect(result.current.menuMention).toBeUndefined()
    expect(result.current.selectedSkills).toEqual([])
  })
})
