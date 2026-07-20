import type { Suggestion } from '../types'

interface SuggestionItemProps {
  suggestion: Suggestion
  disabled: boolean
  onSelect: (suggestion: Suggestion) => void
}

interface SuggestionListProps {
  suggestions?: Suggestion[]
  disabled: boolean
  onSelect: (suggestion: Suggestion) => void
}

export function SuggestionItem({ suggestion, disabled, onSelect }: SuggestionItemProps) {
  return <button type="button" disabled={disabled} className="max-w-64 rounded-lg border border-solid border-border bg-background-secondary px-3 py-2 text-left hover:bg-accent disabled:opacity-40" onClick={() => onSelect(suggestion)}>
    <div className="text-xs font-medium text-primary">{suggestion.title}</div>
    <div className="mt-1 line-clamp-2 text-xs text-muted">{suggestion.message}</div>
  </button>
}

export function SuggestionList({ suggestions, disabled, onSelect }: SuggestionListProps) {
  if (!suggestions?.length) return null

  return <div className="flex flex-wrap justify-center gap-2">{suggestions.map((suggestion) => (
    <SuggestionItem
      key={`${suggestion.title}-${suggestion.message}`}
      suggestion={suggestion}
      disabled={disabled}
      onSelect={onSelect}
    />
  ))}</div>
}
