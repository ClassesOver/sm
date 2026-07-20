import { AtSign, FileText, Folder, Sparkles } from 'lucide-react'
import type { MenuMention, SelectedAgentSkill, WorkspaceReference } from '../types'
import { ContextChip } from './ContextChip'

interface ComposerContextBarProps {
  workspaceReferences: WorkspaceReference[]
  selectedSkills: SelectedAgentSkill[]
  menuMention?: MenuMention
  onRemoveWorkspaceReference?: (id: string) => void
  onRemoveSkill: (id: string) => void
  onRemoveMenuMention: () => void
}

export function ComposerContextBar({
  workspaceReferences, selectedSkills, menuMention,
  onRemoveWorkspaceReference, onRemoveSkill, onRemoveMenuMention
}: ComposerContextBarProps) {
  return <>
    {workspaceReferences.length ? <div className="mb-2 flex flex-wrap gap-1.5" aria-label="已选工作区引用">
      {workspaceReferences.map((reference) => <ContextChip
        key={reference.id}
        icon={reference.isDirectory ? <Folder className="size-3.5" /> : <FileText className="size-3.5" />}
        label={reference.name}
        title={reference.path}
        onRemove={() => onRemoveWorkspaceReference?.(reference.id)}
        removeLabel={`移除工作区引用 ${reference.name}`}
      />)}
    </div> : null}
    {selectedSkills.length ? <div className="mb-2 flex flex-wrap gap-1.5" aria-label="已选技能">
      {selectedSkills.map((skill) => <ContextChip
        key={skill.id}
        icon={<Sparkles className="size-3.5" />}
        label={skill.name}
        title={skill.valid ? skill.description : '技能已不可用，请移除后重试'}
        tone={skill.valid ? 'neutral' : 'warning'}
        trailing={!skill.valid ? <span className="shrink-0 text-destructive">（不可用）</span> : null}
        onRemove={() => onRemoveSkill(skill.id)}
        removeLabel={`移除技能 ${skill.name}`}
      />)}
    </div> : null}
    {menuMention ? <div className="mb-2 flex items-center">
      <ContextChip
        icon={<AtSign className="size-3.5" />}
        label={menuMention.fullPath}
        title={menuMention.fullPath}
        tone="accent"
        onRemove={onRemoveMenuMention}
        removeLabel="移除菜单"
      />
    </div> : null}
  </>
}
