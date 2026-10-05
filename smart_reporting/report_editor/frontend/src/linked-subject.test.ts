import { describe, expect, it } from 'vitest'

import { linkedSubjectFromSearch } from './linked-subject'

describe('linkedSubjectFromSearch', () => {
  it('reads the subject id from an export link query string', () => {
    expect(linkedSubjectFromSearch('?subject=sub-cccccccccccccccc')).toBe(
      'sub-cccccccccccccccc',
    )
  })

  it('keeps other parameters intact and ignores empty values', () => {
    expect(linkedSubjectFromSearch('?foo=1&subject=sub-1&bar=2')).toBe('sub-1')
    expect(linkedSubjectFromSearch('?subject=')).toBeNull()
    expect(linkedSubjectFromSearch('')).toBeNull()
  })

  it('does not guess when the subject id exceeds the frozen contract limit', () => {
    expect(linkedSubjectFromSearch(`?subject=${'s'.repeat(129)}`)).toBeNull()
    expect(linkedSubjectFromSearch(`?subject=${'s'.repeat(128)}`)).toBe('s'.repeat(128))
  })
})
