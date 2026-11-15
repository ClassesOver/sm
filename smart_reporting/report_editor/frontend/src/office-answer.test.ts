import { expect, it, vi } from 'vitest'
import { renderOfficeAnswer, showOfficeAnswer } from './office-answer'

it('renders GenOffice chat Markdown and leaves raw HTML and unverified links inert', () => {
  const host = document.createElement('div')
  host.innerHTML = renderOfficeAnswer([
    '- **收入**', '- 支出', '',
    '| 指标 | 数值 |', '| --- | --- |', '| 收入 | 42 |', '',
    '\u0060\u0060\u0060text', '示例', '\u0060\u0060\u0060', '',
    '<img src=x onerror=alert(1)>',
    '[外部地址](https://example.com) [文件](file:///private.docx)',
  ].join('\n'))
  expect(host.querySelector('ul strong')?.textContent).toBe('收入')
  expect(host.querySelector('td:last-child')?.textContent).toBe('42')
  expect(host.querySelector('pre code')?.textContent).toContain('示例')
  expect(host.querySelector('img,a')).toBeNull()
  expect(host.textContent).toContain('<img src=x onerror=alert(1)>')
})



it('copies the original Markdown and gives feedback in the answer view', async () => {
  const descriptor = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', {configurable:true, value:{writeText}})
  try {
    const host = document.createElement('div')
    showOfficeAnswer(host, '**收入**', true)
    const copy = host.querySelector('button')!
    copy.click()
    await vi.waitFor(() => expect(copy.textContent).toBe('已复制'))
    expect(writeText).toHaveBeenCalledWith('**收入**')
    showOfficeAnswer(host, 'new answer')
    expect(host.querySelector('button')).toBeNull()
  } finally {
    if (descriptor) Object.defineProperty(navigator, 'clipboard', descriptor)
    else Reflect.deleteProperty(navigator, 'clipboard')
  }
})
