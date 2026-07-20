import type { SkillQuery } from './SkillPicker'
import type { MentionQuery } from './useMentionPickerState'

export type ComposerQueryState =
  | { mode: 'idle' }
  | { mode: 'menu'; query: MentionQuery }
  | {
    mode: 'skills'
    query: SkillQuery | null
    search: string
    returnQuery: MentionQuery | null
  }

export type ComposerQueryAction =
  | {
    type: 'value_changed'
    mentionQuery: MentionQuery | null
    skillQuery: SkillQuery | null
    hasSkills: boolean
    editingMentionSkill: boolean
  }
  | {
    type: 'cursor_changed'
    mentionQuery: MentionQuery | null
    skillQuery: SkillQuery | null
    hasSkills: boolean
  }
  | { type: 'open_skills_from_mention'; query: MentionQuery; inline: boolean }
  | { type: 'return_to_mentions' }
  | { type: 'consume_menu' }
  | { type: 'complete_skill' }
  | { type: 'close_menu' }
  | { type: 'close_skills' }
  | { type: 'toggle_skills' }
  | { type: 'dismiss' }
  | { type: 'skill_search_changed'; search: string }

export const INITIAL_COMPOSER_QUERY_STATE: ComposerQueryState = { mode: 'idle' }

function skillsState(
  query: SkillQuery | null,
  search: string,
  returnQuery: MentionQuery | null = null
): ComposerQueryState {
  return { mode: 'skills', query, search, returnQuery }
}

export function composerQueryReducer(
  state: ComposerQueryState,
  action: ComposerQueryAction
): ComposerQueryState {
  switch (action.type) {
    case 'value_changed': {
      if (action.editingMentionSkill) {
        if (action.mentionQuery?.query) {
          return skillsState(action.mentionQuery, action.mentionQuery.query, action.mentionQuery)
        }
        return action.mentionQuery
          ? { mode: 'menu', query: action.mentionQuery }
          : INITIAL_COMPOSER_QUERY_STATE
      }
      if (action.skillQuery && action.hasSkills) {
        return skillsState(action.skillQuery, action.skillQuery.query)
      }
      if (action.mentionQuery) return { mode: 'menu', query: action.mentionQuery }
      return state.mode === 'skills' ? { ...state, query: null } : INITIAL_COMPOSER_QUERY_STATE
    }
    case 'cursor_changed':
      if (action.skillQuery && action.hasSkills) {
        return skillsState(action.skillQuery, action.skillQuery.query)
      }
      if (action.mentionQuery) return { mode: 'menu', query: action.mentionQuery }
      return state.mode === 'menu' ? INITIAL_COMPOSER_QUERY_STATE : state
    case 'open_skills_from_mention':
      return action.inline
        ? skillsState(action.query, action.query.query, action.query)
        : skillsState(null, '', action.query)
    case 'return_to_mentions':
      return state.mode === 'skills' && state.returnQuery
        ? { mode: 'menu', query: state.returnQuery }
        : state
    case 'consume_menu':
      return state.mode === 'menu' ? INITIAL_COMPOSER_QUERY_STATE : state
    case 'complete_skill':
    case 'close_skills':
      return state.mode === 'skills' ? INITIAL_COMPOSER_QUERY_STATE : state
    case 'close_menu':
      if (state.mode === 'menu') return INITIAL_COMPOSER_QUERY_STATE
      return state.mode === 'skills' ? { ...state, returnQuery: null } : state
    case 'toggle_skills':
      return state.mode === 'skills'
        ? INITIAL_COMPOSER_QUERY_STATE
        : skillsState(null, '')
    case 'dismiss':
      return INITIAL_COMPOSER_QUERY_STATE
    case 'skill_search_changed':
      return state.mode === 'skills' ? { ...state, search: action.search } : state
  }
}
