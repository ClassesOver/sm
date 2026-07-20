import {
  AtSign, Database, FileText, Filter as FilterIcon, Folder, Menu, SlidersHorizontal, Sparkles
} from 'lucide-react'
import type {
  MenuMention, MentionReference, SelectedAgentSkill, WorkspaceReference
} from '../types'
import { ContextChip } from './ContextChip'

interface MessageContextBarProps {
  mentions?: MentionReference[]
  workspaceReferences?: WorkspaceReference[]
  skills?: SelectedAgentSkill[]
  menuMention?: MenuMention
  onRemoveMention?: (referenceId: string) => void
  onRemoveMenuMention?: () => void
}

const actionLabels = {
  read: '引用数据', open: '打开', create: '新建', view: '查看', edit: '编辑', apply: '应用'
}

function mentionIcon(kind: MentionReference['kind']) {
  if (kind === 'menu') return <Menu className="size-3.5 shrink-0" />
  if (kind === 'record') return <Database className="size-3.5 shrink-0" />
  if (kind === 'saved_filter') return <FilterIcon className="size-3.5 shrink-0" />
  return <SlidersHorizontal className="size-3.5 shrink-0" />
}

export function MessageContextBar({
  mentions, workspaceReferences, skills, menuMention,
  onRemoveMention, onRemoveMenuMention
}: MessageContextBarProps) {
  return <>
    {mentions?.length ? <div className="mb-2 flex flex-wrap justify-end gap-1.5">
      {mentions.map((reference) => <ContextChip
        key={reference.id}
        icon={mentionIcon(reference.kind)}
        label={reference.label}
        title={reference.detail}
        tone={reference.valid ? 'accent' : 'warning'}
        trailing={<>
          <span className="shrink-0 opacity-70">{actionLabels[reference.action]}</span>
          {!reference.valid ? <span className="shrink-0">（已失效）</span> : null}
        </>}
        onRemove={onRemoveMention ? () => onRemoveMention(reference.id) : undefined}
        removeLabel={`移除引用 ${reference.label}`}
        removeTitle="移除引用"
      />)}
    </div> : null}
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
