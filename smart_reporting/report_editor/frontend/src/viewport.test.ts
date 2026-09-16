import { describe, expect, it } from 'vitest'

import { toolbarMode } from './viewport'

describe('toolbarMode', () => {
  it('uses compact controls on mobile and full controls on desktop', () => {
    expect(toolbarMode(390)).toBe('compact')
    expect(toolbarMode(768)).toBe('compact')
    expect(toolbarMode(769)).toBe('full')
    expect(toolbarMode(1440)).toBe('full')
  })
})
