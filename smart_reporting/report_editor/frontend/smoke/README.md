# Report Editor 生产冒烟

以下检查必须使用真实 reporting 后端和有效编辑会话。Vite API fixture 只能验证前端渲染，不能替代权限、会话和 renderer 链路。

## 自动化检查

在已安装 Playwright 的环境中，将浏览器已有的有效会话地址传入脚本；脚本只读页面，不会触发保存或导出：

```bash
REPORT_EDITOR_URL='https://reporting.example/reports/v1/editor/<report>/<revision>' \
REPORT_EDITOR_BROWSER=chromium \
npm run smoke
```

将 `REPORT_EDITOR_BROWSER` 改为 `firefox` 可执行 Firefox 检查；`HEADLESS=0` 可显示浏览器窗口。

默认脚本严格只读。仅可废弃的测试报告允许执行完整链路：

```bash
REPORT_EDITOR_URL='https://reporting.example/reports/v1/editor/<report>/<revision>' \
REPORT_EDITOR_ALLOW_MUTATION=1 \
REPORT_EDITOR_BROWSER=chromium \
npm run smoke
```

写入模式依次执行：保存唯一探针、使用旧 SHA 验证 409、恢复原 Markdown、导出一个新 revision，并下载检查 PDF `%PDF-` 与 Word `PK` 文件头及文件大小。即使正文恢复，导出仍会创建新 revision；禁止用于用户正式报告。

## 桌面端

1. 从报告列表打开编辑器，确认 Markdown 正文、目录和保存时间正常显示。
2. 修改一段正文，确认状态依次为“有未保存更改”“保存中”“已保存”。刷新页面后内容仍存在。
3. 在两个窗口编辑同一 revision，确认后保存的窗口收到 409，并可选择本地、远端或合并后重试。
4. 使用过期会话打开页面，确认显示 410 会话过期面板，不出现空白编辑区。
5. 分别导出 PDF 和 Word，确认状态显示准备、生成、完成，下载链接可访问，失败时可以重试。
6. 抽查封面、目录、页眉页脚、页码、中文字体、宽表格和跨页图片。
7. 导出失败时记录页面显示的请求编号，并确认服务端 `report_editor_export_failed` 日志包含相同 `request_id`、report、revision、耗时和错误码。

## 移动端

1. 在 375px 和 768px 视口确认底部 6 个主操作保持单行，更多菜单不会超出屏幕。
2. 唤起软键盘后编辑当前段落，确认光标和底部工具栏可见，页面没有横向整体滚动。
3. 打开目录、历史、导出设置和冲突弹窗，验证 Tab/Shift+Tab、Esc 和关闭后的焦点回收。

## 浏览器矩阵

- Chromium：当前稳定版。
- Firefox：当前稳定版，重点检查 sticky 目录、fixed 移动工具栏、宽表格滚动和 Milkdown 浮动工具栏。
- Safari/iOS：发布前使用真机验证 safe-area 与软键盘；桌面模拟不计为真机证据。
