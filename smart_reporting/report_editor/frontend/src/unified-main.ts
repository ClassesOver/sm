export {}

// 报告工作流与旧 Markdown/幻灯片/工作簿编辑器已退役，所有编辑入口统一进入 Office。
if (window.location.pathname.includes('/reports/v1/native/')) {
  await import('./style.css')
  const { startNativeEditor } = await import('./native-main')
  await startNativeEditor().catch(error => {
    const root = document.querySelector<HTMLElement>('#app')
    if (root) root.textContent = error instanceof Error ? error.message : '原生文档载入失败，请重新打开'
  })
} else {
  const root = document.querySelector<HTMLElement>('#app')
  if (root) root.textContent = '旧报告编辑入口已停用，请在 Office 中打开文件。'
}
