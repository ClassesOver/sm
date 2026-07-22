import { Workflow } from 'lucide-react'
import type { ReasoningStep } from '../types'

interface MessageReasoningProps {
  steps: ReasoningStep[]
}

export function MessageReasoning({ steps }: MessageReasoningProps) {
  if (!steps.length) return null

  return <div className="flex items-start gap-3">
    <Workflow className="mt-0.5 size-5 shrink-0 text-muted" />
    <div className="flex flex-col gap-2">
      <div className="text-xs font-medium uppercase text-muted">执行状态</div>
      {steps.map((step, index) => (
        <details key={`${step.title}-${index}`} className="rounded-lg border border-border bg-accent px-3 py-2 text-sm">
          <summary className="cursor-pointer text-xs text-primary">步骤 {index + 1}：{step.title}</summary>
          {step.content ? <div className="mt-2 text-xs leading-5 text-muted">{step.content}</div> : null}
        </details>
      ))}
    </div>
  </div>
}
