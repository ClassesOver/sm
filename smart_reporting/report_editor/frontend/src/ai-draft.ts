/** Applying AI changes requires an explicit save, including when autosave is in flight. */
export const AI_DRAFT_APPLY = 'report-ai-draft-apply'
export function markAIDraft() { document.dispatchEvent(new Event(AI_DRAFT_APPLY)) }
