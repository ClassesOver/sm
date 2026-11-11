import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { App, ConfigProvider } from 'antd'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { expect, it, vi } from 'vitest'
import { Release } from './release'
vi.mock('../../app/session', () => ({
  useSession: () => ({ state: { session: { csrfToken: 'test-csrf' } } }),
}))
const draft = {
  source_id: 'operations',
  version: 1,
  name: '数仓',
  source_type: 'starrocks',
  database: 'warehouse',
  metadata_version_id: 'operations:1',
  content_hash: 'hash1',
}
const published = {
  sourceId: 'operations',
  revision: 1,
  contentHash: 'hash1',
  publishedAt: '2026-11-09T00:00:00Z',
  name: '数仓',
  type: 'starrocks',
  database: 'warehouse',
  metadataVersionId: 'operations:1',
}
it('已核实丢失的发布响应后，新草稿重开发布不继承旧结果未知状态', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  vi.stubGlobal('matchMedia', () => ({
    matches: false,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
  }))
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options: RequestInit) => {
      if (url.includes('/release-check'))
        return new Response(
          JSON.stringify({
            expectedVersion: Number(
              new URL(url, 'http://test').searchParams.get('expectedVersion'),
            ),
            currentPublishedRevision: 1,
            changedFields: [],
            connectionChanged: false,
            hasUnpublishedChanges: true,
            canPublish: true,
            issues: [],
          }),
        )
      if (options?.method === 'POST') throw new TypeError('response lost')
      return new Response(
        JSON.stringify({
          draft,
          published,
          enabled: true,
          hasUnpublishedChanges: false,
        }),
      )
    }),
  )
  const node = document.createElement('div')
  document.body.append(node)
  const root = createRoot(node),
    client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    })
  const detail = {
    draft,
    published: null,
    enabled: true,
    hasUnpublishedChanges: true,
  }
  async function render(open: boolean, version = 1) {
    await act(async () => {
      root.render(
        <ConfigProvider button={{ autoInsertSpace: false }}>
          <App>
            <QueryClientProvider client={client}>
              <Release
                scope={{ database: 'warehouse', companyId: '100' }}
                id="operations"
                detail={{
                  ...detail,
                  draft: { ...draft, version, content_hash: 'hash' + version },
                }}
                open={open}
                onClose={() => {}}
              />
            </QueryClientProvider>
          </App>
        </ConfigProvider>,
      )
      await new Promise((resolve) => setTimeout(resolve, 80))
    })
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 80))
    })
  }
  const button = (name: string) =>
    [...document.querySelectorAll('button')].find(
      (b) => b.textContent === name,
    )!
  try {
    await render(true)
    await act(async () => {
      button('确认发布').click()
      await new Promise((resolve) => setTimeout(resolve, 50))
    })
    expect(button('确认发布').disabled).toBe(true)
    await render(false)
    await render(true)
    expect(button('确认发布').disabled).toBe(true)
    await act(async () => {
      button('读取最新状态').click()
      await new Promise((resolve) => setTimeout(resolve, 50))
    })
    await render(false)
    await render(true, 2)
    expect(button('确认发布').disabled).toBe(false)
  } finally {
    await act(async () => root.unmount())
    client.clear()
    node.remove()
    vi.unstubAllGlobals()
  }
})
