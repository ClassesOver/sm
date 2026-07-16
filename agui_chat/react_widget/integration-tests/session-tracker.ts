import type { Page } from '@playwright/test'


export async function startSessionTracking(page: Page) {
  await page.evaluate(() => {
    const manager = (globalThis as any).odoo.__DEBUG__.services['web.web_client'].aguiChatSurfaceManager
    const bridge = manager.bridge
    const existing = bridge.__aguiE2eSessionTracker
    if (existing) {
      existing.ids = []
      return
    }
    const tracker = {
      ids: [] as number[],
      createSession: bridge.createSession.bind(bridge)
    }
    bridge.__aguiE2eSessionTracker = tracker
    bridge.createSession = async (values: Record<string, unknown>) => {
      const result = await Promise.resolve(tracker.createSession(values))
      const session = result?.session || result
      const id = Number(session?.id)
      if (Number.isInteger(id) && id > 0) tracker.ids.push(id)
      return result
    }
  })
}

export async function trackedSessionIds(page: Page): Promise<number[]> {
  return page.evaluate(() => {
    const manager = (globalThis as any).odoo.__DEBUG__.services['web.web_client'].aguiChatSurfaceManager
    return [...(manager.bridge.__aguiE2eSessionTracker?.ids || [])]
  })
}
