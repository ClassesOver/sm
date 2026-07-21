import { AtSign, FileText, Folder, Sparkles } from 'lucide-react'
import type {
  MenuMention, SelectedAgentSkill, WorkspaceReference
} from '../types'
import { ContextChip } from './ContextChip'

interface MessageContextBarProps {
  workspaceReferences?: WorkspaceReference[]
  skills?: SelectedAgentSkill[]
  menuMention?: MenuMention
  onRemoveMenuMention?: () => void
}

export function MessageContextBar({
  workspaceReferences, skills, menuMention, onRemoveMenuMention
}: MessageContextBarProps) {
  return <>
    {workspaceReferences?.length ? <div className="mb-2 flex flex-wrap justify-end gap-1.5" aria-label="消息工作区引用">
      {workspaceReferences.map((reference) => <ContextChip
        key={reference.id}
        icon={reference.isDirectory ? <Folder className="size-3.5" /> : <FileText className="size-3.5" />}
        label={reference.name}
        title={reference.path}
      />)}
    </div> : null}
    {skills?.length ? <div className="mb-2 flex flex-wrap justify-end gap-1.5" aria-label="消息技能">
      {skills.map((skill) => <ContextChip
        key={skill.id}
        icon={<Sparkles className="size-3.5" />}
        label={skill.name}
        title={skill.description}
        tone={skill.valid ? 'positive' : 'warning'}
        trailing={!skill.valid ? <span className="shrink-0">（已失效）</span> : null}
      />)}
    </div> : null}
    {menuMention ? <div className="mb-2 flex justify-end">
      <ContextChip
        icon={<AtSign className="size-3.5" />}
        label={menuMention.fullPath}
        title={menuMention.fullPath}
        tone={menuMention.valid ? 'accent' : 'warning'}
        trailing={!menuMention.valid ? <span className="shrink-0">（已失效）</span> : null}
        onRemove={onRemoveMenuMention}
        removeLabel="移除菜单"
      />
    </div> : null}
  </>
}
