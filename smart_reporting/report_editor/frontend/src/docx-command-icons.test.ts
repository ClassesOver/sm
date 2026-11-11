import { expect, it } from 'vitest'
import { fillDocxCommandIcons } from './docx-command-icons'
it('fills GenOffice icons for view, review, drawing and table commands without duplicating them', () => {
  const root = document.createElement('div')
  for (const label of ['保存','拼写检查','缩放','100%','页宽','插入脚注','上方插入','形状填充','笔','查找收件人']) {
    const button = document.createElement('button'); button.className='docx-ribbon-command'; button.textContent=label; button.setAttribute('aria-label',label); button.disabled=true;root.append(button)
  }
  fillDocxCommandIcons(root);fillDocxCommandIcons(root)
  for(const button of root.querySelectorAll('button')) {
    expect(button.querySelectorAll('svg')).toHaveLength(1)
    expect(button.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true')
    expect(button.disabled).toBe(true);expect(button.getAttribute('aria-label')).toBeTruthy()
  }
})
