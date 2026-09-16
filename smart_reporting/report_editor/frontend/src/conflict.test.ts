import { describe, expect, it } from 'vitest'

import { conflictLines } from './conflict'

describe('conflictLines', () => {
  it('keeps local and remote edits separately visible', () => {
    expect(conflictLines('标题\n原文', '标题\n本地', '标题\n远端')).toEqual([
      { kind: 'base', text: '标题' },
      { kind: 'base', text: '原文' },
      { kind: 'local', text: '本地' },
      { kind: 'base', text: '标题' },
      { kind: 'base', text: '原文' },
      { kind: 'remote', text: '远端' },
    ])
  })
})
