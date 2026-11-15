# Word 设计 ▸ 水印验收

2026-11-12。固定来源提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本次只验收文字水印这一项功能闭环，不代表 Word 功能区已全部对齐。

## 固定源行为

- `apps/docs/src/renderer/components/ribbon-design-tab.tsx`：水印下拉菜单包含：
  - 预设：中文界面为“机密 / 严禁复制 / 草稿 / 样本”，并追加 CONFIDENTIAL、DRAFT。
  - “自定义水印…”。
  - “删除水印”。
- `WatermarkDialog.tsx`（插入水印）分“无水印 / 图片 / 文字”三页。
  - 文字页的字段与默认值：文字（默认取第一个预设）、字体（Calibri）、字号（自动，或 36–144 共 14 档）、粗体、斜体、透明度（50%）、字体颜色（C0C0C0）、版式（斜式或水平）。
  - 指定字号时，形状框取浏览器测量的字形墨迹框（`inkBoxPt`）。
  - 重开文档时，用 `textFromDocImage` 从已保存的形状回读这些设置。
- 引擎 `saveDocx` 的 `watermark` 选项（`watermark.ts` 的 `watermarkParagraphXml`）：
  - 在每个生效节的页眉写入 Watermarks 构建块里的 VML 文字路径形状；需要时新建页眉部件。
  - `null` 表示删除水印。

## 原生实现

| 层 | 内容 |
| --- | --- |
| 操作 | 文档级 `{kind: 'setWatermark', expectedHeadersSha256, watermark: 文字规格 \| null}`。来源身份是主文档关系中全部页眉部件（路径加内容）的 SHA-256。 |
| 桥接 | `bridge/docx-watermark.ts`：<br>• inspect 下发当前文字水印、回读样式（经引擎 `readWatermarkShape`）、是否图片水印、各页眉是否不一致，以及只读原因。<br>• 整批先验：至多一条，摘要一致，取值限于固定源对话框能产生的值。<br>• 与页眉页脚、节设置、分节符同批时拒绝（`docx_watermark_header_batch_conflict`）。<br>• 交给未改动的引擎 `watermark` 选项写入。<br>• 写后独立回读：每个内容变化或新增的页眉部件都恰好带请求的水印，删除时不再带任何水印。<br>• 受保护文档只读。 |
| 前端 | 设计 ▸ 水印打开固定源菜单：预设、自定义水印…、删除水印。<br>• `docx-watermark-dialog.ts` 实现“无水印 / 文字”两页，默认值同固定源；指定字号时在浏览器测量墨迹框。<br>• 修改记入原生撤销/重做历史，草稿刷新后恢复。<br>• 选回与来源完全相同的水印（文字加样式）即撤回该修改。<br>• 纸面按生效水印预览（颜色、透明度、斜式或水平、字体、粗斜体），预览位于正文之下。 |
| Python | `delivery/docx_native.py` 的操作白名单加入 `setWatermark`。 |

## 证据

- `reporting/doc_engine/bridge/tests/docx-watermark.test.ts`（3 项）：
  - 校验覆盖批量冲突、摘要失效、未变化、文字为空 / 含换行 / 超长、颜色格式、透明度精度、字号与形状框需成对、非法字体名、图片规格。
  - 无页眉的来源：写入“机密”（引擎新建页眉，Watermarks 构建块、斜式 `rotation:315`），正文字节不变。
  - 自定义 Arial / C00000 / 0.3 / 水平 / 粗体 / 72 号，与正文改段同批写入；回读样式一致。
  - 删除水印。
  - 有页眉原文的来源：原文保留。
  - 拒绝情况：摘要失效、与 `setHeaderFooter` 或 `setSectionLayout` 同批、受保护文档；均不产生输出。
- `reporting/tests/test_docx_native_watermark.py`（7 项）：经 Python 入口写入，用 python-docx / ZIP 独立回读。
  - 设置“严禁复制”后页眉原文保留，正文段落不变；只改页眉部件与 core.xml（必要时连带节引用）。
  - 改样式（颜色、透明度、水平、斜体、字体）后回读一致。
  - 删除水印。
  - 6 种非法或过期请求均被拒绝。
- `frontend/src/docx-watermark.test.ts`（4 项）：
  - 模型解析与预设。
  - 草稿写入 / 撤回，以及带样式时“与来源相同”的判断。
  - 草稿恢复校验。
  - 对话框默认值、文字规格与“无水印”。
- `frontend/smoke/docx-watermark-gui-smoke.mjs`：在 Chromium 中跑真实 Python→DOCX 引擎链路，开发服务器模式，授权与修订路由用 fixture。
  1. 预设“机密”，撤销、重做。
  2. 删除水印即撤回。
  3. 自定义：内部资料 / Arial / 72 / 粗体 / 透明度 60% / #C00000 / 水平。
  4. 刷新后草稿恢复，保存为修订 2，下载字节与保存一致。
  5. ZIP / lxml 独立回读：
     - 唯一一个水印形状位于 Watermarks 构建块中，文字、颜色、透明度、Arial 粗体、无旋转、72 号墨迹框均与请求一致。
     - 正文 body 字节一致，页眉原文 “Untouched header” 保留。
     - 只改动 `word/header1.xml` 和 `docProps/core.xml`。
  6. 重开修订 2：纸面预览为 #C00000、水平、0.4、粗体；对话框默认值来自文件回读。
- LibreOffice 渲染下载文件：页面中央是红色水平的“内部资料”，页眉与正文保持原样。

## 已知且与本项无关

- Word 前端 `src/docx` 全量运行有 7 个失败。
  - 其中 6 个在未改动的基线 `d50b1369` 上同样失败：docx-ribbon 行距 1 个、docx-text-revisions-main-collector 4 个、docx-body-decorations 1 个。
  - 第 7 个是 docx-recovery 在全量并行时超时；单独运行两次均 62/62 通过。
- 类型检查只有上游已知的 `pdf-form-canvas.test.ts`、`slides-main.test.ts` 错误。

## 与固定源的差异 / 未完成

- 图片水印本轮未接入，对话框只有“无水印 / 文字”两页；来源为图片水印时，可以替换成文字水印或删除。
- 字体候选是固定的常用中西文字体列表；固定源读取系统字体。
- 重开文档时字号显示为“自动”。样式回读不包含字号档位（固定源会按墨迹框反推字号），再次确认时会改写为自动字号。
- 水印与页眉页脚、节设置不能同批保存，需要分开保存。
- 页面边框未实现：引擎只有逐节 `pgBorders` 的 section 设置，需另行接通节级写回与“应用于整篇文档”。
- 生产构建、真实授权与发布链路未验收；未在 Microsoft Word 中人工打开核对。
