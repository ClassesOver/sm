# 分类汇总 built smoke

仅在最终产品构建完成后运行 `node smoke/workbook-subtotal-built-smoke.mjs`。脚本只启动 Vite preview，使用正式静态资源；每个已加载 JS 都核对本地构建文件 SHA-256，不注入私有 editor/runtime。

三个独立来源修订：`sum` 在 Sum Data 的 A1:B5，`count` 在 Count 数据的 C5:D9，`average` 在 Average's Data 的 C5:D9。通过正式 Ribbon 与 Go To 操作，对话框取消零草稿、真实公式计算（原生剪贴板读取）、一次 Undo/Redo、草稿刷新、保存、下载、新修订显式重开分别验证。

保存端走真实 Python `native_office.patch_office`，下载文件使用独立 zipfile/lxml/openpyxl 检查公式、六格粗体、两级大纲、summaryBelow、尾行、跨表引用及 Body 名称。计算缓存单独报告，不以文件公式证明桌面已计算。

`SUBTOTAL_SMOKE_DIRECTORY` 可指定 checkpoint；默认 `/tmp/xlsx-subtotal-built-<timestamp>`。目录保留来源、保存回执、实际下载文件、独立回读、截图、资源身份和 summary。已有保存成功回执只重新下载和重开，不再次保存同一来源；存在产物而缺少回执时中止，避免重复签发。

首次真实构建执行：三聚合会话值 100、4、25，取消、Undo/Redo、草稿刷新、Python patch 保存、实际下载及新修订重开全部完成，但最终 pageerror 守卫拒绝通过：全局撤销历史拦截误拒文档 UI 内嵌编辑器历史。证据保存在 `/tmp/xlsx-subtotal-acceptance/built/`；保存前诊断 `/tmp/xlsx-subtotal-acceptance/diagnostic/page-error-*.json` 含 `docs-ui._pushHistory` 完整栈，无新增保存。

因此首次 run 不能宣称完整通过，等待修复及重新构建。重测使用 `SUBTOTAL_SMOKE_REVISION_OFFSET=30` 和新 checkpoint，保持旧保存回执不重存。`SUBTOTAL_SMOKE_AGG=sum` 可只诊断一种聚合；`SUBTOTAL_SMOKE_STOP_BEFORE_SAVE=1` 会在保存前明确停止，仅用于诊断。


修复后最终执行 **通过**：`SUBTOTAL_SMOKE_REVISION_OFFSET=30 SUBTOTAL_SMOKE_DIRECTORY=/tmp/xlsx-subtotal-acceptance/built-final node smoke/workbook-subtotal-built-smoke.mjs`，exit 0。Chromium 140.0.7339.16；`errors=[]`，`saveCount=3`，125 个 JS 的 HTTP 200 与 SHA-256 匹配。新来源 31、40、50 分别保存为 32、41、51，计算值 100、4、25，下载、独立回读及新修订重开均通过。`built-final/summary.json`、`assets.json`、`build-manifest.json`、实际下载、六份截图和三份保存回执完整保留；旧来源没有重存。
