export type MentionPickerView = 'home' | 'menus'
export type MentionPickerNavigationSource = 'explicit' | 'typed'

export interface MentionPickerState {
  view: MentionPickerView
  searchText: string
  navigationSource: MentionPickerNavigationSource
}

export type MentionPickerAction =
  | { type: 'query_synced'; query: string }
  | { type: 'typed_query_started'; query: string }
  | { type: 'typed_query_cleared' }
  | { type: 'menus_opened' }
  | { type: 'home_returned' }
  | { type: 'search_changed'; searchText: string }

export function createMentionPickerState(query: string): MentionPickerState {
  return { view: 'home', searchText: query, navigationSource: 'explicit' }
}

export function mentionPickerReducer(
  state: MentionPickerState,
  action: MentionPickerAction
): MentionPickerState {
  switch (action.type) {
    case 'query_synced':
      return state.searchText === action.query ? state : { ...state, searchText: action.query }
    case 'typed_query_started':
      return { view: 'menus', searchText: action.query, navigationSource: 'typed' }
    case 'typed_query_cleared':
      return state.view === 'menus' && state.navigationSource === 'typed'
        ? { ...state, view: 'home', searchText: '' }
        : state
    case 'menus_opened':
      return { ...state, view: 'menus', navigationSource: 'explicit' }
    case 'home_returned':
      return state.view === 'menus' ? { ...state, view: 'home' } : state
    case 'search_changed':
      return state.searchText === action.searchText ? state : { ...state, searchText: action.searchText }
  }
}
