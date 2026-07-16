import { afterEach, describe, expect, it } from 'vitest'
import { startSessionTracking, trackedSessionIds } from '../../integration-tests/session-tracker'


describe('E2E session tracker', () => {
  afterEach(() => {
    delete (globalThis as any).odoo
  })

  it('tracks only sessions created through the instrumented test page', async () => {
    let nextId = 1
    const bridge: any = {
      async createSession() {
        return {session: {id: nextId++}}
      }
    }
    ;(globalThis as any).odoo = {
      __DEBUG__: {
        services: {
          'web.web_client': {aguiChatSurfaceManager: {bridge}}
        }
      }
    }
    const page = {evaluate: async (callback: () => unknown) => callback()} as any

    await startSessionTracking(page)
    await bridge.createSession({})
    await bridge.__aguiE2eSessionTracker.createSession({})

    expect(await trackedSessionIds(page)).toEqual([1])

    await startSessionTracking(page)
    await bridge.createSession({})
    expect(await trackedSessionIds(page)).toEqual([3])
  })
})
