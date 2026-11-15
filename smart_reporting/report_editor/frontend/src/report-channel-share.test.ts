import { expect, it, vi } from 'vitest'
import { mountReportChannelShare } from './report-channel-share'

it('发布邀请、接收连接器回复并安全重试同一条消息', async () => {
  const panel = document.createElement('section')
  const invitation = 'https://reports.test/reports/join#synthetic'
  const api = {
    inviteReportConnector: vi.fn().mockResolvedValue({url: invitation}),
    revokeReportConnector: vi.fn().mockResolvedValue(undefined),
    readReportChannel: vi.fn().mockResolvedValueOnce([{sequence: 1, sender: 'connector', text: '<b>合成回复</b>'}])
      .mockResolvedValue([{sequence: 2, sender: 'editor', text: '请编辑选区'}]),
    postReportChannel: vi.fn().mockRejectedValueOnce(new Error('连接中断')).mockResolvedValueOnce(undefined),
  }
  const follow = vi.fn().mockResolvedValue(undefined)
  const dispose = mountReportChannelShare(panel, api as never, follow)
  try {
    const details = panel.querySelector('details')!
    details.open = true
    details.dispatchEvent(new Event('toggle'))
    await vi.waitFor(() => expect(panel.querySelector('li')?.textContent).toContain('<b>合成回复</b>'))
    expect(panel.querySelector('li b')).toBeNull()
    panel.querySelector('label input')!.value = 'synthetic-subject'
    const [invite, revoke, send] = panel.querySelectorAll('button')
    invite.click()
    const link = panel.querySelector<HTMLInputElement>('input[readonly]')!
    await vi.waitFor(() => expect(link.value).toBe(invitation))
    expect(api.inviteReportConnector).toHaveBeenCalledWith('synthetic-subject')
    const message = panel.querySelector('textarea')!
    message.value = '请编辑选区'
    send.click()
    await vi.waitFor(() => expect(panel.textContent).toContain('连接中断'))
    send.click()
    await vi.waitFor(() => expect(panel.querySelectorAll('li')).toHaveLength(2))
    expect(api.postReportChannel.mock.calls[0][0]).toBe(api.postReportChannel.mock.calls[1][0])
    expect(api.readReportChannel).toHaveBeenCalledWith(1, expect.any(AbortSignal))
    revoke.click()
    await vi.waitFor(() => expect(panel.textContent).toContain('已撤销频道授权'))
    expect(link.value).toBe('')
  } finally {
    dispose()
  }
})

it('通过频道事件打开已有 Word 任务', async () => {
  const panel = document.createElement('section')
  const follow = vi.fn().mockResolvedValue(undefined)
  const api = {readReportChannel:vi.fn().mockResolvedValue([{sequence:1, sender:'word-task', text:'word-task-1'}])}
  const dispose = mountReportChannelShare(panel, api as never, follow)
  try {
    const details = panel.querySelector('details')!
    details.open = true
    details.dispatchEvent(new Event('toggle'))
    await vi.waitFor(() => expect(panel.querySelector('li button')).not.toBeNull())
    panel.querySelector<HTMLButtonElement>('li button')!.click()
    expect(follow).toHaveBeenCalledWith('word-task-1')
  } finally { dispose() }
})
