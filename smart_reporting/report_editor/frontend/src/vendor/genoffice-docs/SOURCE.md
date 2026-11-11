# GenOffice Docs 浏览器接入源码

- 上游：https://github.com/genspark-ai/genoffice
- 固定版本：`f8c17004fb730df11f0f743164ffd8b4281bb38c`
- 完整源码核对位置：`/home/junge/pros/genoffice-source-full`（仅开发环境路径）
- 许可证：见同目录 `LICENSE`、`NOTICE`。
- `SOURCE-SHA256.json` 记录原始上游文件的 SHA-256；`LOCAL-SHA256.json` 记录当前本地文件身份。原始清单并非修改后文件哈希。

本目录保留上游相对目录结构，提取真实 Docs Tiptap 扩展、OOXML → ProseMirror 转换、Worker 解析、文档样式、字体解析、分页测量与 PaginationPreview 的依赖闭包；DOCX引擎与共享 redact/zip 包通过项目 Vite/TypeScript 别名复用 `reporting/slides_engine/packages` 的同版本源码。未引入 Electron 桌面启动、IPC 注册或上游 AI 调用链。

浏览器适配：

1. `editor/extensions.ts` 的图片复制委托 ProseMirror 标准 HTML 剪贴板，删除桌面 `copyImageToClipboard` 分支。浏览器没有伪造成功的桌面桥。
2. `font-resolve.ts` 的指标 provider 默认为空，使用文档嵌入字体和上游静态字体指标/替代链，不访问系统字体 IPC。
3. `i18n/locale.tsx` 保留 React locale context，去掉桌面语言广播订阅。
4. `ai/style-ops.ts` 的 `AgentToolDef` 类型直接取自纯 `agent-core/types`，避免引入桌面 IPC 类型图。此处仅为编辑器扩展依赖，不开放上游 AI 执行。
5. `packages/font-metrics/src/browser.ts` 仅提取上游 `FaceVerticalMetrics` 接口；`packages/ui/src/browser.ts` 仅导出所需纯函数与字体/WordArt常量。未引入 Node 字体扫描器。
6. `scoped.css` 用 PostCSS 将原 `styles.css` 选择器加 `.docx-native` 前缀（`:root` 替换成该根节点，保留关键帧规则），防止上游桌面样式覆盖报告外壳。

2026-11-05 Word Ribbon 首批裁剪：`docx-home-source.tsx` 对应固定上游 `apps/docs/src/renderer/components/Ribbon.tsx` 的 Home 分支，保留原控件组顺序；控件回调由本地 Native DOCX 操作适配。图标复用上游 `components/icons.tsx`，中文 Home 标签只提取 `i18n/ribbon/zh.ts` 中实际使用的词条到 `home-zh.ts`。完整 Ribbon 依赖 Docs App closures、编辑服务和 `@genoffice/ui`，没有将这些桌面/宿主依赖带入；文件及图标 SHA 在 `SOURCE-SHA256.json`，本地裁剪词条和源文件身份在 `LOCAL-SHA256.json` 与 Task 2 brief 登记。

接入层 `docx-main.tsx` 保留真实 GenOffice 编辑器与分页预览；源文件及对象锚点均与服务端逐一核验，只有服务端支持的段落文字、整段基础样式、简单表格文字和段落插删映射为保存操作，其余修改显示原因并拒绝本次事务。原生草稿保存、发布、下载由本项目服务负责。分页预览是浏览器快照，完整桌面 Word 的版式一致性仍需独立验收。

2026-11-05 Word Insert 追加迁移：`docx-insert-source.tsx` 从同版本 `ribbon-insert-tab.tsx` 的 InsertTab JSX 提取页面、表格、插图、文本、链接、批注、页眉页脚和符号八组；保留原 SVG 图标与中文标签。Symbols 保留原 50 个符号、原面板结构和 Tiptap 文字插入回调，经现有 Native 文字操作保存；其他结构命令禁用并说明写回协议缺口，不导入尚不可持久化的弹窗/调色板。`insert-zh.ts` 仅提取对应实际使用词条。真实 Playwright smoke 已验证 Home 格式、段落增删、Insert 符号写入、浏览器下载、独立 DOCX 回读及修订 2 重开，原修订字节不变；授权与修订登记仍由 smoke mock，不代表真实 HTTP 发布验收。

2026-11-05 追加同步：上游今天新增六提交；本闭包交集仅 `editor/hf-dom.ts`，同步原生 PAGE 字段 helper `hfPageNumberOnly`。未导入桌面 ribbon/App。七个共享服务端包在上一基线至当前提交之间无变更。

2026-11-05 增量核对上游最新 `f8c17004fb730df11f0f743164ffd8b4281bb38c`：该增量中与 Docs 相关的三个文件为 `App.tsx`、`ribbon-insert-tab.tsx`、`editor/hf-dom.ts`，本依赖闭包仅包含最后一个；已升级该文件（新增 PAGE 单段页码 helper），其余两个由本系统宿主替代，未复制。未变更文件保留原版本SHA；单文件版本在原始清单明确标记。

2026-11-05 Ribbon increment: Home paragraph alignment maps the source `setSelectionAlign` behavior into an anchored `setParagraphAlignment` operation. The DOCX bridge changes only `w:jc`, preserves other paragraph properties, and rejects alignment edits on new unsaved paragraphs until a stable source anchor exists. Left/center/right/justify plus RTL, combined style edits, save/download/reopen and source preservation are covered by the DOCX brief and smoke.

2026-11-06 Word Home 行距菜单补齐关闭行为：原样迁入固定版本 `packages/ui/src/popover-dismiss.ts`，仅依赖 React；接入其 `useDismissablePopover`，由本菜单容器 ref 提供 inside guard，并启用 Escape。外部 capture-phase pointerdown、窗口 blur 和已有可选 shell 通知均复用上游实现，不新增事件系统或桌面依赖。原始与本地文件哈希均已登记，独立 Home 测试覆盖外点关闭、Escape、失焦、菜单内部点击和触发器切换。

## PDF text exports (2026-11-11)

The browser PDF export adapter uses the existing Docs parse/render pipeline and
these fixed-ref upstream serializers: renderer/export-markdown.ts and
renderer/html-export.ts. Ten previously absent relative-import source modules
were added without replacing existing local adaptations. SOURCE-SHA256.json
records their original source hashes. shared/ipc.ts is a local narrow extract
of the unchanged upstream MarkdownImage and MARKDOWN_MEDIA_DIR_TOKEN definitions,
plus a type-only AgentToolDef re-export from the existing shared source package;
it excludes unrelated desktop/AI protocol declarations. LOCAL-SHA256.json
records the resulting local files. Markdown images are replaced with their
verified parser-provided data URLs by the local browser adapter; no temporary
media folder is exposed. HTML is attachment-only. OCR is not enabled, and
content/layout/font fidelity remains pending manual review.
