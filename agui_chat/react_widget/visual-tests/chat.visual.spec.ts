import { expect, test } from '@playwright/test'

const scenarios = ['empty', 'complete', 'streaming', 'markdown', 'tool', 'relation', 'attachments', 'error', 'panels'] as const

test('light scenarios', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })

  for (const scenario of scenarios) {
    errors.length = 0
    await page.goto(`/?scenario=${scenario}`)
    const root = page.locator('#root .agui-chat-react')
    await expect(root).toBeVisible()
    const main = root.locator('main')
    await expect(main).toBeVisible()
    await expect(page.getByRole('button', { name: '添加附件' })).toBeVisible()
    const [mainBox, formBox] = await Promise.all([main.boundingBox(), main.locator('form').boundingBox()])
    expect(Math.abs((mainBox!.y + mainBox!.height) - (formBox!.y + formBox!.height))).toBeLessThanOrEqual(1)
    if (scenario === 'streaming') {
      await expect(page.getByLabel('正在生成回复')).toBeVisible()
      await expect(page.getByRole('button', { name: '停止生成' })).toBeVisible()
    }
    if (scenario === 'attachments') {
      await expect(page.getByAltText('sales-dashboard.svg')).toBeVisible()
      expect(await page.getByAltText('sales-dashboard.svg').evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0)).toBe(true)
    }

    if (scenario === 'relation') {
      await expect(page.getByText('请选择关系记录')).toBeVisible()
      await expect(page.getByRole('button', { name: /上海星河科技有限公司/ })).toBeVisible()
      await expect(page.getByRole('button', { name: /上海远景贸易有限公司/ })).toBeVisible()
    }

    await page.addStyleTag({ content: '*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }' })
    await expect.poll(() => errors).toEqual([])
    const layout = await page.evaluate(() => {
      const documentOverflow = document.documentElement.scrollWidth - document.documentElement.clientWidth
      const rootElement = document.querySelector('#root .agui-chat-react') as HTMLElement | null
      const emptyRoot = !rootElement || rootElement.getBoundingClientRect().height === 0 || rootElement.childElementCount === 0
      const clipped = Array.from(document.querySelectorAll('#root button, #root textarea, #root input, #root select'))
        .filter((element) => {
          const html = element as HTMLElement
          const rect = html.getBoundingClientRect()
          return rect.width > 0 && rect.height > 0 && (html.scrollWidth > html.clientWidth + 1 || html.scrollHeight > html.clientHeight + 1)
        })
        .map((element) => (element.getAttribute('aria-label') || element.textContent || element.tagName).trim())
      return { documentOverflow, emptyRoot, clipped }
    })
    expect(layout.documentOverflow).toBeLessThanOrEqual(1)
    expect(layout.emptyRoot).toBe(false)
    expect(layout.clipped).toEqual([])
    await expect(page).toHaveScreenshot(`${scenario}.png`, { fullPage: true })
    if (scenario === 'attachments') {
      await page.getByRole('button', { name: '文件预览: sales-dashboard.svg' }).click()
      const preview = page.getByRole('complementary', { name: '文件预览' })
      await expect(preview).toBeVisible()
      await expect(preview.getByAltText('图片', { exact: true })).toBeVisible()
      if ((page.viewportSize()?.width || 0) >= 1024) {
        const resize = preview.getByRole('button', { name: '调整文件预览宽度' })
        const before = await preview.boundingBox()
        const handle = await resize.boundingBox()
        expect(before).not.toBeNull()
        expect(handle).not.toBeNull()
        await page.mouse.move(handle!.x + handle!.width / 2, handle!.y + handle!.height / 2)
        await page.mouse.down()
        await page.mouse.move(handle!.x - 100, handle!.y + handle!.height / 2)
        await page.mouse.up()
        const after = await preview.boundingBox()
        expect(after!.width).toBeGreaterThan(before!.width)
        expect((await root.locator('main').boundingBox())!.width).toBeGreaterThanOrEqual(420)
      }
      await expect(page).toHaveScreenshot('attachments-preview.png', { fullPage: true })
      await preview.getByRole('button', { name: '关闭文件预览' }).click()
      await expect(preview).toBeHidden()
    }
    if (scenario === 'empty') {
      const form = page.locator('form')
      await form.evaluate((element) => {
        const transfer = new DataTransfer()
        transfer.items.add(new File(['drop'], 'drop-check.txt', { type: 'text/plain' }))
        element.dispatchEvent(new DragEvent('dragenter', { bubbles: true, dataTransfer: transfer }))
      })
      await expect(page.getByLabel('拖放附件')).toBeVisible()
      const [mainBox, dropBox] = await Promise.all([
        root.locator('main').boundingBox(),
        page.getByLabel('拖放附件').boundingBox()
      ])
      expect(dropBox).toEqual(mainBox)
      await form.evaluate((element) => {
        element.dispatchEvent(new DragEvent('dragleave', { bubbles: true }))
      })
      await expect(page.getByLabel('拖放附件')).toBeHidden()

      await page.getByPlaceholder('输入消息，@ 选择记录、菜单或技能').evaluate((element) => {
        const transfer = new DataTransfer()
        transfer.items.add(new File(['paste'], 'paste-check.txt', { type: 'text/plain' }))
        transfer.items.add(new File(['region,amount'], 'sales-report.csv', { type: 'text/csv' }))
        element.dispatchEvent(new ClipboardEvent('paste', { bubbles: true, clipboardData: transfer }))
      })
      await expect(page.getByText('paste-check.txt')).toBeVisible()
      await expect(page.getByText('sales-report.csv')).toBeVisible()
      await expect(page.getByText('文本文件 · 1 KB')).toBeVisible()
      await expect(page).toHaveScreenshot('composer-attachments.png', { fullPage: true })
      await page.getByPlaceholder('输入消息，@ 选择记录、菜单或技能').fill('@')
      await expect(page.getByRole('dialog', { name: '添加到对话' })).toBeVisible()
      await expect(page).toHaveScreenshot('mention-picker.png', { fullPage: true })
      await page.getByRole('option', { name: /菜单/ }).click()
      await expect(page.getByLabel('搜索菜单')).toBeVisible()
      await expect(page).toHaveScreenshot('menu-picker.png', { fullPage: true })
      await page.getByRole('button', { name: '返回' }).click()
      await page.getByRole('option', { name: /业务记录/ }).click()
      await expect(page.getByLabel('搜索业务类型')).toBeVisible()
      await expect(page).toHaveScreenshot('record-types-picker.png', { fullPage: true })
      await page.getByRole('button', { name: '返回' }).click()
      await page.getByRole('option', { name: /技能/ }).click()
      await page.getByRole('option', { name: /合同审计/ }).click()
      await page.getByRole('button', { name: '选择技能' }).click()
      await expect(page.getByText('已选 1/1')).toBeVisible()
      await expect(page).toHaveScreenshot('skill-picker.png', { fullPage: true })
    }
  }
})
