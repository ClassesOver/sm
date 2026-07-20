import { useEffect, useState } from 'react'
import type { AgentSkillOption, MenuMention, MenuMentionOption, SelectedAgentSkill } from '../types'

interface UseComposerSelectionStateOptions {
  agentSkills: AgentSkillOption[]
}

export function useComposerSelectionState({ agentSkills }: UseComposerSelectionStateOptions) {
  const [menuMention, setMenuMention] = useState<MenuMention | undefined>()
  const [selectedSkills, setSelectedSkills] = useState<SelectedAgentSkill[]>([])

  useEffect(() => {
    setSelectedSkills((current) => {
      const next = current.map((skill) => ({
        ...skill,
        valid: agentSkills.some((option) => option.id === skill.id && option.name === skill.name)
      }))
      return next.every((skill, index) => skill.valid === current[index].valid) ? current : next
    })
  }, [agentSkills])

  const selectMenu = (option: MenuMentionOption) => {
    setMenuMention({ ...option, path: [...option.path], valid: true })
  }

  const toggleSkill = (skill: AgentSkillOption) => {
    setSelectedSkills((current) => {
      if (current.some((item) => item.id === skill.id)) {
        return current.filter((item) => item.id !== skill.id)
      }
      return [{ ...skill, valid: true }]
    })
  }

  const removeSkill = (id: string) => {
    setSelectedSkills((current) => current.filter((item) => item.id !== id))
  }

  const removeMenuMention = () => setMenuMention(undefined)

  const resetSelections = () => {
    setMenuMention(undefined)
    setSelectedSkills([])
  }

  return {
    menuMention,
    selectedSkills,
    selectMenu,
    toggleSkill,
    removeSkill,
    removeMenuMention,
    resetSelections
  }
}
