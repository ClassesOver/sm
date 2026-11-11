# PDF 原位改字快捷提交验收（2026-11-11）

## 固定源与本轮范围

对齐源 `/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。`apps/pdf/src/renderer/App.tsx:10304–10308` 的 textarea 对 `Enter && (metaKey || ctrlKey)` 阻止默认换行并调用 `commitTextDraft()`；对应 blob 为 `e87bc4f85aadc77bcc9cfb152619c17b8c70a30d`。

本地此前只有“加入文字修改”按钮路径。本轮 `frontend/src/pdf-text-edit-shortcuts.ts` 在替换文字 textarea 上绑定 Ctrl/Cmd+Enter，调用已有按钮的 `click()`，复用原对象身份、样式读取、忙碌状态和草稿操作校验。普通 Enter 仍用于换行，快捷键仅加入草稿，不自动预览或保存。

为避免输入法候选确认、长按、浏览器组合键和失活编辑器误提交，已处理 `isComposing`、IME keyCode 229、repeat、Alt、已阻止的事件、disabled/readOnly、隐藏祖先。监听沿用已有 AbortSignal 生命周期。未新增 document 级快捷键，未扩展 Escape、空文本 Delete、跨对象编辑或 OCR。

接线接口：`bindPdfTextEditShortcuts(replacement, stageText, abort.signal)`，位于既有按钮 click listener 注册后；现有 dispose 中的 `abort.abort()` 清理监听。

## 本地定向验证

- `frontend/src/pdf-text-edit-shortcuts.test.ts`：真实行为 RED 为 2 failed、12 passed（空实现不能快捷提交）；实现后 14/14 PASS。日志分别为 `/tmp/pdf-text-edit-shortcuts-behavior-red.log` 与 `/tmp/pdf-text-edit-shortcuts-green.log`。
- Ctrl 与 Meta 两条路径均确认已提交当前文字和真实选区样式读数，textarea 值、选区范围和方向保持；普通 Enter、其他快捷键、输入法、repeat、Alt、disabled/readOnly、隐藏、已阻止事件、abort、textarea 外事件均不触发提交。
- 专属 helper 的 strict TypeScript 编译 exit 0，日志 `/tmp/pdf-text-edit-shortcuts-types.log`。未据此声明整个工程全量类型检查通过。
- `frontend/smoke/pdf-text-edit-shortcuts-smoke.mjs` 已通过 `node --check`；独立 `pdf-text-edit-shortcuts-verify.py` 已通过语法编译。真实浏览器与实际 PDF 的 r1 证据见下文。

## 一次保存的真实浏览器方案

运行参数为 `PDF_TEXT_SHORTCUT_SMOKE_DIRECTORY`、`PDF_TEXT_SHORTCUT_SMOKE_PORT`（默认 4320）、`PDF_SMOKE_STATIC_DIRECTORY`，以及公共 fixture server 读取的 native runtime 环境变量。脚本校验 manifest 与每个 HTTP 加载 JS/MJS 的实际字节。

1. 真实 Enter 在 textarea 中插入换行，草稿仍为空；composition/repeat/Alt 合成事件不提交。
2. Ctrl+Enter 将 `AABBCD` 加入原对象替换，整对象 Courier12，`[2,4)` 为 Times18、粗斜体、红色。
3. 改值为 `AABBCC` 后使用 Meta+Enter，确认唯一 replaceText 操作的值实际变化，身份和选区样式保持。不能仅对未变化值按 Meta 后检查旧操作，否则漏接快捷键也可能假通过。
4. 仅一次真实 preview、确认、save 修订 4→5、下载 hash/size 核验及新 grant 重开，保留实际 validation 失败原因与告警，不把软告警标为通过。
5. 独立 pypdf 核验最终 AA/BB/CC、嵌入字体、字号、红色、基线和相邻 advance，另两页正文及页面 box 保持；不把文本提交宣称为完整版式或完整业务验收通过。

保存响应解析后立即把 staged、preview、payload、状态与请求落入 `shortcut-save.json`，下载校验后更新实际文件 hash/size，再执行重开；重开 context 也先落盘再校验。后续失败的 `failure.json` 保留 manifest SHA、已加载资产身份和所有修订记录，避免已提交修订的证据因浏览器后续失败丢失。

## 真实浏览器结果与构建身份

`/tmp/pdf-shortcuts-nudge-shading-text-browser/summary.json` 为 `ok=true`；已复读 `shortcut-checkpoints.json`、`shortcut-save.json` 与独立 pypdf 结果。root 已目视核验实际 PDF 渲染图 `actual-render.png`。

- Chromium `140.0.7339.16`；本次文字链使用 **r1** 构建，manifest SHA-256 为 `c22dc903c579bb21472d9d8eab2ad7c16f0af1cce99537ed4cdb2a591f74a370`。37 个实际加载的 JS/MJS 资源均与冻结磁盘字节匹配；pageErrors、consoleErrors、httpErrors、assetErrors 四类数组全部为空，来源保持未改写。
- 普通 Enter 的实际换行未提交草稿；composition/repeat/Alt 不拦截、不提交。Ctrl+Enter 产生唯一的 `AABBCD` replaceText；Meta+Enter 把同一来源/页面/对象操作更新为 `AABBCC`，未叠加第二条操作，`[2,4)` 字体、字号、粗斜与红色样式保持。
- preview 回执为 `appliedOperationIndices=[0]`、`skippedOperations=[]`、`reviewIssues=[]`。仅一次保存修订 4→5，HTTP 200、revisionRegistered=true；下载和重新签发 grant 打开后的来源均指向同一实际 PDF。
- 实际 `shortcut.pdf` 为 **12,030 字节**，SHA-256 `64fd35c8bf2d3d3ca81e0daa891bb1e17775c63d77537bfb8ae091e518992334`。来源 SHA-256 为 `bacea970895caa7c67bdacc064cea8f150eb048b62917c1e8a78ea860802f3eb`。已从磁盘重新读取大小与 hash 核对回执。
- 独立 pypdf 确认 AA、CC 为嵌入 LiberationMono/12，BB 为嵌入 LiberationSerif-BoldItalic/18；基线分别为 `(24,350)`、`(38.400002,350)`、`(62.375999,350)`，红色 `[1,0,0]`，其余两页正文和页面 box 保持。实际渲染图 SHA-256 为 `dddc33ff9578dba2f13edfa7045499699475b20ea036e190afcd39900514850b`。
- 保存仍返回 `validation.ok=false`、`native_source_review_pending`，说明业务事实与完整版式尚待核验；实际产物身份、下载链接和重开均保留，本记录不将该告警标为业务验收通过。

后续表单专项发现并发渲染可重复挂载 overlay，root 在共享入口增加 `!holder.contains(canvas)` 与 visible guard；又补充 `sync()` 返回 false、控件已断开 DOM 时 dispose 清理监听，形成后续最终构建。中间第二次构建尚未验收即被最终第三次构建替代。**文字链未在后续最终构建重跑**，上述浏览器证据仅属于 r1，不能用于宣称最终构建的文字完整链已验证。

r1 静态快照现已留存在 `/tmp/pdf-shortcuts-nudge-shading-static-r1`。已只读重新核对其 `.vite/manifest.json` SHA 与本次记录一致，37 个浏览器实际加载资产在快照中的字节 SHA 也逐一与 `summary.json.assets` 一致；此核对没有重复运行成功的测试或浏览器链路。
