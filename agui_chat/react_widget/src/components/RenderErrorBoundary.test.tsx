import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RenderErrorBoundary } from './RenderErrorBoundary'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

function MaybeBroken({ broken }: { broken: boolean }) {
  if (broken) throw new Error('渲染失败')
  return <div>正常内容</div>
}

describe('渲染错误边界', () => {
  it('仅在 resetKeys 变化后重新尝试渲染', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const { rerender } = render(
      <RenderErrorBoundary fallback={<div>回退内容</div>} resetKeys={['first']}>
        <MaybeBroken broken />
      </RenderErrorBoundary>
    )
    expect(screen.getByText('回退内容')).toBeTruthy()

    rerender(
      <RenderErrorBoundary fallback={<div>回退内容</div>} resetKeys={['first']}>
        <MaybeBroken broken={false} />
      </RenderErrorBoundary>
    )
    expect(screen.getByText('回退内容')).toBeTruthy()

    rerender(
      <RenderErrorBoundary fallback={<div>回退内容</div>} resetKeys={['second']}>
        <MaybeBroken broken={false} />
      </RenderErrorBoundary>
    )
    expect(screen.getByText('正常内容')).toBeTruthy()
  })
})
